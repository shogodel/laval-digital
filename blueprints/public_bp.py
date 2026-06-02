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
from flask_login import current_user, login_user
from werkzeug.security import generate_password_hash

from blueprints._shared import AGENT_PERSONALITIES
from core import database
from core.rate_limiter import ip_rate_limit
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
    _check_rate_limit,
    _record_attempt,
    validate_password,
)

logger = logging.getLogger(__name__)
public_bp = Blueprint("public", __name__)


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
    http_code = 200 if status["status"] == "ok" else 503
    return jsonify(status), http_code


@public_bp.route("/api/contact", methods=["POST"])
def api_contact():
    if not _check_rate_limit("contact"):
        return api_error("Too many submissions. Please try again later.", 429)
    _record_attempt(False, "contact")
    data = request.json
    if not data:
        return api_error("No data provided", 400)

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    service = (data.get("service") or "").strip()
    message = (data.get("message") or "").strip()

    if not name or not email or not phone:
        return api_error("Name, email, and phone are required", 400)

    service_labels = {
        "managed": "Managed For You ($897.99/mo)",
        "website": "Custom Website (From $999)",
        "both": "Both Services",
        "other": "Other / General Inquiry",
    }
    service_label = service_labels.get(service, service)

    try:
        settings = get_executioner().get_smtp_config()
        smtp_host = settings.get("smtp_host", "smtp.gmail.com")
        smtp_port = int(settings.get("smtp_port", 587))
        smtp_user = settings.get("smtp_username", "")
        smtp_pass = settings.get("smtp_password", "")
        smtp_from = settings.get("smtp_from_email", smtp_user)
        use_tls = settings.get("smtp_use_tls", True)

        if not smtp_user or not smtp_pass:
            logger.warning("Contact form: SMTP credentials not configured, storing as lead")
            conn = database._get_conn()
            lead_id = str(uuid.uuid4())
            now = datetime.now(UTC).isoformat()
            conn.execute(
                "INSERT INTO leads (id, user_id, name, phone, service, urgency, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (lead_id, None, name, phone, service, "", now),
            )
            conn.commit()
            return api_success({"status": "ok", "message": "Message received (email not configured)"}, status_code=201)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Contact Form: {service_label} \u2014 {name}"
        msg["From"] = smtp_from
        msg["To"] = "lavaldigital@gmail.com"
        msg["Reply-To"] = email

        text_body = f"""New contact form submission

Name: {name}
Email: {email}
Phone: {phone}
Service: {service_label}

Message:
{message if message else "(none)"}
"""
        html_body = f"""\
<html>
<body style="font-family: Arial, sans-serif; color: #1f2937;">
<h2 style="color: #0f2b45;">New Contact Form Submission</h2>
<table style="border-collapse: collapse; margin: 16px 0;">
<tr><td style="padding: 6px 12px; font-weight: bold; background: #f3f4f6;">Name</td><td style="padding: 6px 12px;">{escape(name)}</td></tr>
<tr><td style="padding: 6px 12px; font-weight: bold; background: #f3f4f6;">Email</td><td style="padding: 6px 12px;"><a href="mailto:{escape(email)}">{escape(email)}</a></td></tr>
<tr><td style="padding: 6px 12px; font-weight: bold; background: #f3f4f6;">Phone</td><td style="padding: 6px 12px;">{escape(phone)}</td></tr>
<tr><td style="padding: 6px 12px; font-weight: bold; background: #f3f4f6;">Service</td><td style="padding: 6px 12px;">{escape(service_label)}</td></tr>
</table>
<h3 style="color: #0f2b45;">Message</h3>
<p style="background: #f9fafb; padding: 12px; border-radius: 6px;">{escape(message) if message else "<em>(none)</em>"}</p>
</body>
</html>
"""
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            if use_tls:
                server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        conn = database._get_conn()
        lead_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO leads (id, user_id, name, phone, service, urgency, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (lead_id, None, name, phone, service, "", now),
        )
        conn.commit()

        logger.info("Contact form email sent to lavaldigital@gmail.com from %s (%s)", email, name)
        return api_success({"status": "ok", "message": "Message sent successfully"}, status_code=201)

    except Exception as e:
        logger.error("Contact form email failed: %s", e)
        return api_error("Failed to send message. Please try again later.", 500)


@public_bp.route("/api/signup", methods=["POST"])
def api_signup():
    if not _check_rate_limit():
        return api_error("Too many attempts. Please try again later.", 429)

    data = request.json
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
        login_user(temp_user)
        session["last_active"] = datetime.now(UTC).isoformat()

        logger.info("New trial user created: %s (id=%s)", email, uid)
        _record_attempt(True)
        return api_success({"redirect": url_for("client.client_dashboard")}, status_code=201)

    except ValueError as e:
        _record_attempt(False)
        logger.warning("Signup validation failed: %s", e)
        return api_error("Invalid signup data. Please check your information.", 400)
    except RuntimeError as e:
        _record_attempt(False)
        logger.error("Signup failed: %s", e, exc_info=True)
        return api_error("Account creation failed. Please try again later.", 500)


@public_bp.route("/login")
def login_redirect():
    return redirect(url_for("client.client_login"))


@public_bp.route("/api/leads", methods=["GET", "POST"])
def handle_leads():
    conn = database._get_conn()
    if request.method == "POST":
        if not _check_rate_limit():
            return api_error("Too many attempts. Please try again later.", 429)
        data = request.json
        name = data.get("name", "")
        phone = data.get("phone", "")
        if not name or not phone:
            return api_error("Name and phone are required", 400)
        lead_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        user_id = None
        if not current_user.is_anonymous:
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
    data = request.json
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


@public_bp.route("/api/frankie/inspect", methods=["GET"])
def api_frankie_inspect():
    user_id = get_current_user_id()
    if not user_id:
        return api_success({"suggestions": [], "error": "No user"})
    try:
        conn = database._get_conn()
        row = conn.execute("SELECT site_url, business_name, city, niche FROM client_details WHERE user_id = ? LIMIT 1", (safe_int(user_id),)).fetchone()
    except Exception:
        logger.warning("Failed to query client_details for suggestions", exc_info=True)
        row = None
    if not row or not row.get("site_url"):
        return api_success({"suggestions": [], "site": None})

    site_url = row["site_url"]
    business = row.get("business_name", "")
    city = row.get("city", "")
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
