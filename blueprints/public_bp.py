"""Blueprint for public / unauthenticated API routes."""
import logging
import re
import smtplib
import uuid
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from flask import Blueprint, jsonify, redirect, request, session, url_for
from flask_login import current_user
from werkzeug.security import generate_password_hash

from blueprints._shared import AGENT_PERSONALITIES
from core import database
from core.api_helpers import api_error, api_success
from core.app_state import (
    get_current_user_id,
    get_executioner,
    get_llm_adapter,
    get_orchestrator,
    get_push_manager,
    safe_int,
    safe_url,
)
from core.auth import (
    User,
    _record_attempt,
    validate_password,
)
from core.rate_limiter import RateLimitExceededError, check_ip_rate_limit, ip_rate_limit

logger = logging.getLogger(__name__)
public_bp = Blueprint("public", __name__)


@public_bp.route("/api/health")
def api_health():
    try:
        conn = database._get_conn()
        conn.execute("SELECT 1")
        return jsonify({"status": "healthy", "database": "ok"})
    except Exception as e:
        logger.error("Health check failed: %s", e)
        return jsonify({"status": "unhealthy", "database": "error"}), 503


@public_bp.route("/health")
def health():
    status = {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}
    try:
        conn = database._get_conn()
        conn.execute("SELECT 1")
        status["database"] = "ok"
    except Exception:
        status["database"] = "error"
        status["status"] = "degraded"
    try:
        models = get_llm_adapter().get_available_models()
        status["llm"] = "ok" if models else "no_models"
    except Exception as e:
        status["llm"] = "unhealthy"
        logger.error("Health check LLM error: %s", e)
        status["status"] = "degraded"
    try:
        from core.settings import credential_health
        from core.shopify_auth import shopify_credential_health
        status["encryption"] = credential_health()
        status["encryption"]["shopify"] = shopify_credential_health()
        if status["encryption"]["status"] != "ok" or status["encryption"]["shopify"]["status"] != "ok":
            status["status"] = "degraded"
    except Exception as e:
        status["encryption"] = {"status": "error", "detail": str(e)}
        status["status"] = "degraded"
    try:
        from core.ads_auth import ads_credential_health
        status["google_ads"] = ads_credential_health()
        if status["google_ads"]["status"] not in ("ok", "no_accounts"):
            status["status"] = "degraded"
    except Exception as e:
        status["google_ads"] = {"status": "error", "detail": str(e)}
        status["status"] = "degraded"
    http_code = 200 if status["status"] == "ok" else 503
    return jsonify(status), http_code


@public_bp.route("/api/contact", methods=["POST"])
@ip_rate_limit(max_request=5, window_seconds=60)
def api_contact():
    data = request.json or {}
    if not data:
        return api_error("No data provided", 400)

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password", "")

    if not name or not email or not password:
        return api_error("Name, email, and password are required.", 400)

    is_valid, err_msg = validate_password(password)
    if not is_valid:
        return api_error(err_msg, 400)

    try:
        now = datetime.now(UTC)
        trial_ends = (now + timedelta(days=7)).isoformat()
        uid = database.create_user(
            email=email,
            password_hash=generate_password_hash(password),
            role="user",
            display_name=name,
        )
        conn = database._get_conn()
        conn.execute(
            "UPDATE users SET status = 'trial', trial_ends_at = ? WHERE id = ?",
            (trial_ends, uid),
        )
        conn.commit()

        user_row = database.get_user_by_id(uid)
        temp_user = User(
            row_id=user_row["id"], email=user_row["email"],
            password_hash=user_row["password_hash"], role=user_row["role"],
            display_name=user_row["display_name"],
            status="trial", trial_ends_at=trial_ends,
        )
        session["last_active"] = datetime.now(UTC).isoformat()

        logger.info("New trial user created: %s (id=%s)", email, uid)
        _record_attempt(True, "signup")
        return api_success({"redirect": url_for("shopify.admin_embedded")}, status_code=201)

    except ValueError as e:
        _record_attempt(False, "signup")
        logger.warning("Signup validation failed: %s", e)
        return api_error("Invalid signup data. Please check your information.", 400)
    except RuntimeError as e:
        _record_attempt(False, "signup")
        logger.error("Signup failed: %s", e, exc_info=True)
        return api_error("Account creation failed. Please try again later.", 500)


@public_bp.route("/login")
def login_redirect():
    return redirect(url_for("admin.login"))


@public_bp.route("/api/leads", methods=["GET", "POST"])
def handle_leads():
    conn = database._get_conn()
    if request.method == "POST":
        try:
            check_ip_rate_limit(10, 60)
        except RateLimitExceededError as e:
            return api_error(str(e), 429)
        data = request.json or {}
        name = data.get("name", "")
        phone = data.get("phone", "")
        if not name or not phone:
            return api_error("Name and phone are required", 400)
        lead_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        user_id = None
        if not current_user.is_anonymous and current_user.role != "admin":
            user_id = int(current_user.id)
        conn.execute(
            "INSERT INTO leads (id, user_id, name, phone, service, urgency, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (lead_id, user_id, name, phone, data.get("service", ""), data.get("urgency", ""), now),
        )
        conn.commit()
        return api_success({"lead": {"id": lead_id, "name": name, "phone": phone}}, status_code=201)
    if current_user.is_anonymous:
        return api_error("Authentication required", 401)
    if current_user.is_authenticated and current_user.role == "admin":
        tenant_id = session.get("active_user_id")
        if tenant_id:
            rows = conn.execute("SELECT * FROM leads WHERE user_id = ? ORDER BY created_at DESC LIMIT 100", (safe_int(tenant_id),)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM leads ORDER BY created_at DESC LIMIT 100").fetchall()
    else:
        user_id = int(current_user.id)
        rows = conn.execute("SELECT * FROM leads WHERE user_id = ? ORDER BY created_at DESC LIMIT 100", (user_id,)).fetchall()
    return api_success({"leads": [dict(r) for r in rows]})


@public_bp.route("/api/personalities", methods=["GET"])
def api_personalities():
    lang = request.args.get("lang", "en")
    data = {}
    for aid, p in AGENT_PERSONALITIES.items():
        entry = dict(p)
        entry["short"] = p.get("short_fr", p["short"]) if lang == "fr" else p["short"]
        data[aid] = entry
    return api_success({"personalities": data})


@public_bp.route("/api/onboarding/status", methods=["GET"])
def api_onboarding_status():
    user_id = get_current_user_id()
    if not user_id:
        return api_error("No user", 400, data={"onboarded": False})
    return api_success({"onboarded": True, "steps": {"welcome": True, "agents": True, "autonomy": True, "done": True}})


@public_bp.route("/api/push/vapid-key", methods=["GET"])
def api_push_vapid_key():
    pm = get_push_manager()
    return api_success({"public_key": pm.public_key, "enabled": pm.enabled})


@public_bp.route("/api/push/subscribe", methods=["POST"])
def api_push_subscribe():
    data = request.json or {}
    if not data:
        return api_error("No subscription data", 400)
    ok = get_push_manager().subscribe(data)
    return api_success({"success": ok})


@public_bp.route("/api/push/unsubscribe", methods=["POST"])
def api_push_unsubscribe():
    data = request.json
    endpoint = (data or {}).get("endpoint", "")
    if not endpoint:
        return api_error("No endpoint", 400)
    ok = get_push_manager().unsubscribe(endpoint)
    return api_success({"success": ok})


@public_bp.route("/api/orchestrator/welcome", methods=["POST"])
@ip_rate_limit(max_request=10, window_seconds=60)
def api_orchestrator_welcome():
    data = request.json or {}
    language = data.get("language", "en")
    orch = get_orchestrator()
    return api_success(orch.get_welcome(language))


@public_bp.route("/api/orchestrator/suggestions", methods=["POST"])
@ip_rate_limit(max_request=10, window_seconds=60)
def api_orchestrator_suggestions():
    data = request.json or {}
    language = data.get("language", "en")
    orch = get_orchestrator()
    return api_success(orch.get_suggestions(language))


@public_bp.route("/api/site/inspect", methods=["GET"])
def api_site_inspect():
    user_id = get_current_user_id()
    if not user_id:
        return api_success({"suggestions": [], "error": "No user"})
    return api_success({"suggestions": [], "site": None})
    niche = row.get("niche", "")

    suggestions = []
    try:
        resp = safe_url(site_url)
        html = resp.text.lower()
        title = ""
        meta_desc = ""
        m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m: title = m.group(1).strip()
        m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE | re.DOTALL)
        if m: meta_desc = m.group(1).strip()
        has_h1 = bool(re.search(r"<h1[^>]*>", html))
        h1_count = len(re.findall(r"<h1[^>]*>", html))
        has_schema = "schema.org" in html or "application/ld+json" in html
        has_og = "og:title" in html
        has_whatsapp = "whatsapp" in html
        has_phone = bool(re.search(r"tel:|\(\d{3}\)\s*\d{3}-\d{4}|\d{3}-\d{3}-\d{4}", html))
        word_count = len(html.split())

        if not title:
            suggestions.append("Your homepage is missing a <title> tag. Add one with your business name and city.")
        else:
            suggestions.append(f"Your site title is: \"{title[:80]}\" \u2014 keep it under 60 chars for Google.")

        if not meta_desc:
            suggestions.append("No meta description found. Add one summarizing your services for better click-through rates.")

        if h1_count > 1:
            suggestions.append(f"You have {h1_count} H1 tags. Use only one H1 per page for SEO best practices.")
        elif not has_h1:
            suggestions.append("No H1 heading found. Add one that includes your main service keyword.")

        if not has_schema:
            suggestions.append("No schema.org markup detected. LocalBusiness schema helps you show up in rich results.")

        if not has_og:
            suggestions.append("No Open Graph tags found. These control how your site looks when shared on Facebook and LinkedIn.")

        if not has_phone:
            suggestions.append("No click-to-call phone number detected. Add your phone number prominently for mobile users.")

        if word_count < 100:
            suggestions.append(f"Your homepage only has about {word_count} words. Add more content describing your services for better SEO.")

        if not has_whatsapp:
            pass

        return api_success({
            "site": {"url": site_url, "title": title[:80], "meta_desc": meta_desc[:120], "business": business, "city": city, "niche": niche},
            "suggestions": suggestions[:5],
        })
    except Exception:
        return api_success({"suggestions": [f"Could not reach {site_url}. Make sure the site is live."], "site": None})



