"""Main blueprint — all routes extracted from app.py."""

# ── stdlib ────────────────────────────────────────────────
import calendar
import html
import json
import logging
import os
import re
import secrets
import smtplib
import socket
import ssl
import threading
import uuid
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps
from pathlib import Path
from queue import Empty
from typing import Any, Dict, Optional

# ── Flask ─────────────────────────────────────────────────
from flask import (
    Blueprint, Response, current_app, flash, g,
    jsonify, redirect, render_template, request,
    session, stream_with_context, url_for,
)
from flask_login import current_user, login_user, logout_user
from werkzeug.security import generate_password_hash

# ── App modules ───────────────────────────────────────────
from core import database
from core.api_helpers import api_error, api_success
from core.app_state import (
    get_agent_configs, get_agent_meta,
    get_agent_personalities, get_agent_registry,
    get_credential_cipher, get_current_user_id,
    get_email_bridge, get_executioner, get_llm_adapter,
    get_orchestrator, get_push_manager, get_scheduler_manager,
    get_speech_engine, safe_error, safe_int,
    update_agent_activity,
)
from core.auth import (
    admin_required, admin_page_required, client_required,
    _check_rate_limit, _record_attempt, validate_password,
    add_user_to_tenant,
)
from core.events import get_event_bus
from core.llm_adapter import LLMAdapter
from core.orchestrator import Orchestrator
from mcp import AGENT_MCP_ROUTING

logger = logging.getLogger(__name__)

main_bp = Blueprint("main", __name__)


# ── Lazy fallback for app.py globals ──
# Route functions reference globals like llm_adapter, executioner,
# agent_registry, orchestrator etc. defined in app.py.  This hook
# resolves them at runtime, avoiding circular imports.
def __getattr__(name):
    import importlib
    return getattr(importlib.import_module("app"), name)


# ── Globals moved from app.py ──
_sms_lock = threading.Lock()
_email_bridge_instance = None
_email_bridge_lock = threading.RLock()
_report_history = []
_report_history_lock = threading.Lock()
MANAGED_MONTHLY_FEE = int(os.getenv("MANAGED_MONTHLY_FEE", "499"))

AGENT_PERSONALITIES = {
    "local_seo": {"emoji": "📍", "color": "#10b981", "short": "Local SEO", "short_fr": "SEO Local"},
    "social_media": {"emoji": "📱", "color": "#3b82f6", "short": "Social", "short_fr": "Sociaux"},
    "lead_conversion": {"emoji": "🎯", "color": "#f59e0b", "short": "Leads", "short_fr": "Prospects"},
    "paid_ads": {"emoji": "📢", "color": "#ef4444", "short": "Ads", "short_fr": "Annonces"},
    "growth_hacker": {"emoji": "🚀", "color": "#8b5cf6", "short": "Growth", "short_fr": "Croissance"},
    "reputation": {"emoji": "⭐", "color": "#06b6d4", "short": "Reputation", "short_fr": "Réputation"},
    "email_marketing": {"emoji": "✉️", "color": "#ec4899", "short": "Email", "short_fr": "Courriel"},
    "tiktok": {"emoji": "🎬", "color": "#14b8a6", "short": "TikTok", "short_fr": "TikTok"},
    "outreach": {"emoji": "🤝", "color": "#f97316", "short": "Outreach", "short_fr": "Prospection"},
    "backlinks": {"emoji": "🔗", "color": "#6366f1", "short": "Backlinks", "short_fr": "Liens"},
    "content_strategy": {"emoji": "📝", "color": "#84cc16", "short": "Content", "short_fr": "Contenu"},
    "technical_seo": {"emoji": "⚙️", "color": "#06b6d4", "short": "Tech SEO", "short_fr": "SEO Tech"},
    "reporting": {"emoji": "📊", "color": "#a855f7", "short": "Reports", "short_fr": "Rapports"},
    "cro": {"emoji": "📐", "color": "#f43f5e", "short": "CRO", "short_fr": "CRO"},
    "video": {"emoji": "🎥", "color": "#eab308", "short": "Video", "short_fr": "Vidéo"},
    "sms_marketing": {"emoji": "💬", "color": "#06b6d4", "short": "SMS", "short_fr": "SMS"},
    "executioner": {"emoji": "⚡", "color": "#64748b", "short": "Execute", "short_fr": "Exécution"},
}


@main_bp.route("/health")
def health():
    """Health check endpoint for Docker/K8s probes."""
    status = {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
    # Check DB connectivity
    try:
        conn = database._get_conn()
        conn.execute("SELECT 1")
        status["database"] = "ok"
    except Exception as e:
        status["database"] = "error"
        status["status"] = "degraded"
    # Check LLM adapter (lightweight model list call)
    try:
        models = llm_adapter.get_available_models()
        status["llm"] = "ok" if models else "no_models"
    except Exception as e:
        status["llm"] = "unhealthy"
        logger.error("Health check LLM error: %s", e)
        status["status"] = "degraded"
    http_code = 200 if status["status"] == "ok" else 503
    return jsonify(status), http_code

@main_bp.route("/api/contact", methods=["POST"])
def api_contact():
    """Handle contact form submissions and email to lavaldigital@gmail.com."""
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from html import escape

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
        settings = executioner.get_settings()
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
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO leads (id, user_id, name, phone, service, urgency, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (lead_id, None, name, phone, service, "", now),
            )
            conn.commit()
            return api_success({"status": "ok", "message": "Message received (email not configured)"}, status_code=201)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Contact Form: {service_label} — {name}"
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
        now = datetime.now(timezone.utc).isoformat()
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

@main_bp.route("/api/signup", methods=["POST"])
def api_signup():
    """Create a new trial user account and log them in."""
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
        now = datetime.now(timezone.utc)
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
        session["last_active"] = datetime.now(timezone.utc).isoformat()

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

@main_bp.route("/login")
def login_redirect():
    """Redirect to the client login page."""
    return redirect(url_for("client.client_login"))

@main_bp.route("/api/users", methods=["GET"])
@admin_required
def api_list_users():

    tenant_id = session.get("active_user_id")
    role_filter = request.args.get("role", "").strip().lower()

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        if tenant_id:
            if role_filter in ("user", "affiliate"):
                cursor.execute(
                    "SELECT id, email, display_name, role, created_at, last_login "
                    "FROM users WHERE (id = ? OR tenant_id = ?) AND role = ? ORDER BY created_at DESC",
                    (_safe_int(tenant_id), _safe_int(tenant_id), role_filter),
                )
            else:
                cursor.execute(
                    "SELECT id, email, display_name, role, created_at, last_login "
                    "FROM users WHERE id = ? OR tenant_id = ? ORDER BY created_at DESC",
                    (_safe_int(tenant_id), _safe_int(tenant_id)),
                )
        else:
            if role_filter in ("user", "affiliate"):
                cursor.execute(
                    "SELECT id, email, display_name, role, created_at, last_login "
                    "FROM users WHERE role = ? ORDER BY created_at DESC",
                    (role_filter,),
                )
            else:
                cursor.execute(
                    "SELECT id, email, display_name, role, created_at, last_login "
                    "FROM users ORDER BY created_at DESC",
                )
        users = [dict(row) for row in cursor.fetchall()]
        return api_success({"users": users})
    except Exception as e:
        return _safe_error(e, 500)

@main_bp.route("/api/users", methods=["POST"])
@admin_required
def api_add_user():

    data = request.json
    email = (data.get("email") or "").strip()
    password = data.get("password", "")
    role = data.get("role", "user")
    display_name = (data.get("display_name") or "").strip()

    if role not in ("user", "affiliate"):
        return api_error("Invalid role. Must be 'user' or 'affiliate'.", 400)

    if not email or not password:
        return api_error("Email and password are required", 400)

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return api_error("Invalid email format.", 400)

    is_valid, err_msg = validate_password(password)
    if not is_valid:
        return api_error(err_msg, 400)

    # Allow creating first user without active_user_id (tenant_id = NULL)
    tenant_id = session.get("active_user_id")

    try:
        result = add_user_to_tenant(email, password, role, display_name, tenant_id or "")
        return api_success(result, status_code=201)
    except ValueError as e:
        return _safe_error(e, 400)
    except RuntimeError as e:
        return _safe_error(e, 500)

@main_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@admin_required
def api_delete_user(user_id):

    tenant_id = session.get("active_user_id")
    if tenant_id and str(user_id) == str(tenant_id):
        return api_error("Cannot delete the currently selected client", 400)

    try:
        user = database.get_user_by_id(user_id)
        if not user:
            return api_error("User not found", 404)
        if tenant_id and user.get("tenant_id") is not None and str(user["tenant_id"]) != str(tenant_id):
            return api_error("User does not belong to the selected client", 403)
        database.delete_user(user_id)
        return api_success({"message": "User deleted"})
    except Exception as e:
        return _safe_error(e, 500)

@main_bp.route("/api/leads", methods=["GET", "POST"])
def handle_leads():
    """Capture and list lead form submissions."""
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
        now = datetime.now(timezone.utc).isoformat()
        user_id = None
        if not current_user.is_anonymous:
            user_id = int(current_user.id)
        conn.execute(
            "INSERT INTO leads (id, user_id, name, phone, service, urgency, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (lead_id, user_id, name, phone, data.get("service", ""), data.get("urgency", ""), now),
        )
        conn.commit()
        return api_success({"lead": {"id": lead_id, "name": name, "phone": phone}}, status_code=201)
    if current_user.is_anonymous and not session.get("admin_logged_in"):
        return api_error("Authentication required", 401)
    if session.get("admin_logged_in"):
        tenant_id = session.get("active_user_id")
        if tenant_id:
            rows = conn.execute("SELECT * FROM leads WHERE user_id = ? ORDER BY created_at DESC LIMIT 100", (_safe_int(tenant_id),)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM leads ORDER BY created_at DESC LIMIT 100").fetchall()
    else:
        user_id = int(current_user.id)
        rows = conn.execute("SELECT * FROM leads WHERE user_id = ? ORDER BY created_at DESC LIMIT 100", (user_id,)).fetchall()
    return api_success({"leads": [dict(r) for r in rows]})

@main_bp.route("/api/agents", methods=["GET"])
def get_agents():
    """Get status and activity telemetry of all agents."""
    tenant_id = str(current_user.id) if not current_user.is_anonymous else None

    agents_status = []

    if tenant_id:
        activity = get_tenant_agent_activity(tenant_id)
        for agent_id, agent in agent_registry.items():
            act = activity.get(agent_id, {})
            agents_status.append({
                "agent_id": agent_id,
                "enabled": agent.enabled,
                "model": agent.model,
                "api_key": "",
                "status": act.get("status", "idle"),
                "last_invoked": act.get("last_invoked"),
                "task_count": act.get("task_count", 0),
                "success_count": act.get("success_count", 0),
                "failure_count": act.get("failure_count", 0),
                "last_draft_preview": act.get("last_draft_preview"),
            })
    else:
        for agent_id, agent in agent_registry.items():
            agents_status.append({
                "agent_id": agent_id,
                "enabled": agent.enabled,
                "model": agent.model,
                "api_key": "",
                "status": "idle",
                "last_invoked": None,
                "task_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "last_draft_preview": None,
            })

    return api_success({"agents": agents_status})

@main_bp.route("/api/agents/<agent_id>", methods=["GET"])
def get_agent_stats(agent_id):
    """Get stats for a specific agent (for the agent chat panel)."""
    if agent_id not in agent_registry:
        return api_error("Agent not found", 404)
    tenant_id = str(current_user.id) if not current_user.is_anonymous else None
    stats = {"agent_id": agent_id, "task_count": 0, "success_count": 0, "failure_count": 0, "enabled": agent_registry[agent_id].enabled, "model": agent_registry[agent_id].model}
    if tenant_id:
        try:
            conn = database._get_conn()
            row = conn.execute(
                "SELECT task_count, success_count, failure_count FROM agent_configs WHERE agent_id = ? AND user_id = ?",
                (agent_id, _safe_int(tenant_id)),
            ).fetchone()
            if row:
                stats.update(dict(row))
        except Exception as e:
            logger.debug("Silent exception in %s: %s", __name__, e)
    return api_success(stats)

@main_bp.route("/api/agents/<agent_id>/toggle", methods=["POST"])
@admin_required
def toggle_agent(agent_id):
    if agent_id not in agent_registry:
        return api_error("Agent not found", 404)

    agent = agent_registry[agent_id]
    agent.enabled = not agent.enabled

    # Persist toggle to tenant database only if a tenant is selected
    tenant_id = str(current_user.id) if not current_user.is_anonymous else None
    if tenant_id:
        try:
            conn = database._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE agent_configs SET enabled = ? WHERE agent_id = ? AND user_id = ?",
                (int(agent.enabled), agent_id, _safe_int(tenant_id)),
            )
            conn.commit()
        except Exception as e:
            logger.debug("Silent exception in %s: %s", __name__, e)

    return api_success({"agent_id": agent_id, "enabled": agent.enabled})

@main_bp.route("/api/agents/<agent_id>/config", methods=["GET"])
@admin_required
def get_agent_config(agent_id):
    if agent_id not in AGENT_CONFIGS:
        return api_error("Agent not found", 404)
    config = AGENT_CONFIGS[agent_id]
    api_key = config.get("credentials", {}).get("api_key", "")
    masked_key = ("****" + api_key[-4:]) if api_key and len(api_key) > 4 else ""
    return api_success({
        "agent_id": agent_id,
        "model": config.get("model", "deepseek-chat"),
        "api_key": masked_key,
        "api_base": config.get("credentials", {}).get("api_base", ""),
    })

@main_bp.route("/api/models", methods=["GET"])
def get_available_models():
    """Return list of all available LLM models via litellm."""
    try:
        models = LLMAdapter.get_available_models()
        return api_success({"models": models})
    except Exception:
        return api_success({
            "models": ["deepseek-chat", "gpt-4o", "claude-3.5-sonnet"]
        })

@main_bp.route("/api/models/detect", methods=["POST"])
def detect_models():
    """Detect provider from API key and return available models."""
    data = request.json
    api_key = data.get("api_key", "")
    if not api_key:
        return api_error("API key is required", 400)
    try:
        result = LLMAdapter.detect_models(api_key)
        return api_success(result)
    except Exception as e:
        logger.error("Model detection failed: %s", type(e).__name__)
        return api_error("Model detection failed.", 500, data={"provider": "unknown", "models": []})

@main_bp.route("/api/executions", methods=["GET"])
@admin_required
def get_executions():
    limit = request.args.get("limit", 50, type=int)
    history = executioner.get_execution_history(limit)
    return api_success({"executions": history})

@main_bp.route("/api/speech/settings", methods=["GET"])
@admin_required
def get_speech_settings():
    return api_success(speech_engine.get_public_settings())

@main_bp.route("/api/speech/settings", methods=["PUT"])
@admin_required
def update_speech_settings():
    data = request.json
    if not data:
        return api_error("No data provided", 400)
    speech_engine.update_settings(data)
    return api_success(speech_engine.get_public_settings())

@main_bp.route("/api/speech/stt", methods=["POST"])
@admin_required
def speech_to_text():
    if "audio" not in request.files:
        return api_error("No audio file provided", 400)

    audio_file = request.files["audio"]
    language = request.form.get("language", "en")

    try:
        text = speech_engine.transcribe(audio_file.read(), language)
        return api_success({"text": text, "language": language})
    except Exception as e:
        logger.error("Speech-to-text failed: %s", e)
        return _safe_error(e, 500)

@main_bp.route("/api/speech/tts", methods=["POST"])
@admin_required
def text_to_speech():
    data = request.json
    if not data or not data.get("text"):
        return api_error("No text provided", 400)

    text = data["text"]
    language = data.get("language", "en")

    try:
        audio_bytes = speech_engine.synthesize(text, language)
        return (audio_bytes, 200, {"Content-Type": "audio/mpeg"})
    except Exception as e:
        logger.error("Text-to-speech failed: %s", e)
        return _safe_error(e, 500)

@main_bp.route("/api/speech/voices", methods=["GET"])
@admin_required
def get_speech_voices():
    provider = speech_engine.get_settings().get("tts_provider", "browser")
    if provider == "openai":
        return api_success({"voices": ["alloy", "echo", "fable", "nova", "shimmer"]})
    elif provider == "elevenlabs":
        api_key = speech_engine.get_settings().get("elevenlabs_api_key", "")
        if not api_key:
            return api_success({"voices": []})
        try:
            resp = requests.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            voices = [{"id": v["voice_id"], "name": v["name"]} for v in resp.json().get("voices", [])]
            return api_success({"voices": voices})
        except Exception:
            return api_success({"voices": []})
    return api_success({"voices": []})

@main_bp.route("/api/tasks", methods=["POST"])
@admin_required
def submit_task():
    data = request.json
    user_request = data.get("request", "").strip()

    if not user_request:
        return api_error("No request provided", 400)

    thread_id = data.get("thread_id", str(uuid.uuid4()))
    language = data.get("language", "")

    try:
        orch = get_orchestrator()

        user_id = get_current_user_id()
        autonomy_config = None
        if user_id:
            conn = database._get_conn()
            rows = conn.execute(
                "SELECT agent_id, autonomy, confidence_threshold FROM agent_configs WHERE user_id = ?",
                (_safe_int(user_id),),
            ).fetchall()
            autonomy_config = {
                r["agent_id"]: {"autonomy": r["autonomy"], "confidence_threshold": r["confidence_threshold"]}
                for r in rows
            }

        # Load conversation history for multi-turn context
        conversation_history: list = []
        if user_id:
            cursor = conn.execute(
                "SELECT agent_task, agent_draft FROM threads WHERE thread_id = ? AND user_id = ? AND status = 'chat' ORDER BY created_at ASC",
                (thread_id, _safe_int(user_id)),
            )
            for row in cursor.fetchall():
                if row["agent_task"]:
                    conversation_history.append({"role": "user", "content": row["agent_task"]})
                if row["agent_draft"]:
                    conversation_history.append({"role": "assistant", "content": row["agent_draft"]})

        result = orch.process_message(
            user_request, thread_id,
            language=language or None,
            autonomy_config=autonomy_config,
            user_id=_safe_int(user_id) if user_id else 0,
            conversation_history=conversation_history[-20:],
        )

        return api_success(result)
    except Exception as e:
        logger.error("Task failed: %s", e, exc_info=True)
        return api_error("I had trouble processing that request. Please try again.", 500, data={
            "response": "I had trouble processing that request. Please try again.",
            "agent": "error",
            "status": "error",
            "thread_id": thread_id,
            "pending_approval": False
        })

@main_bp.route("/api/approvals", methods=["GET"])
@admin_required
def get_approvals():
    orch = get_orchestrator()
    user_id = get_current_user_id()
    approvals = []
    for thread_id, draft_info in orch.get_pending_drafts(user_id).items():
        approvals.append({
            "thread_id": thread_id,
            "agent": draft_info.get("agent", "unknown"),
            "draft": draft_info.get("draft", ""),
            "task": draft_info.get("task", "")
        })
    logger.info("Returning %d pending approvals", len(approvals))
    return api_success({"approvals": approvals})

@main_bp.route("/api/orchestrator/welcome", methods=["POST"])
def api_orchestrator_welcome():
    """Get a welcome message from the orchestrator."""
    data = request.json or {}
    language = data.get("language", "en")
    orch = get_orchestrator()
    return api_success(orch.get_welcome(language))

@main_bp.route("/api/orchestrator/suggestions", methods=["POST"])
def api_orchestrator_suggestions():
    """Get proactive suggestions from the orchestrator."""
    data = request.json or {}
    language = data.get("language", "en")
    orch = get_orchestrator()
    return api_success(orch.get_suggestions(language))

@main_bp.route("/api/orchestrator/panic", methods=["POST"])
@admin_required
def api_panic():
    orch = get_orchestrator()
    orch.panic()
    return api_success({"status": "panicked", "message": "All agents stopped."})

@main_bp.route("/api/orchestrator/resume", methods=["POST"])
@admin_required
def api_resume():
    orch = get_orchestrator()
    orch.clear_panic()
    return api_success({"status": "active", "message": "Agents resumed."})

@main_bp.route("/api/orchestrator/status", methods=["GET"])
@admin_required
def api_orchestrator_status():
    orch = get_orchestrator()
    user_id = get_current_user_id()
    return api_success({
        "panicked": orch.is_panicked,
        "pending_drafts": len(orch.get_pending_drafts(user_id)),
        "activity_count": len(orch.get_activity_feed(200)),
    })

@main_bp.route("/api/orchestrator/activity", methods=["GET"])
@admin_required
def api_activity():
    limit = request.args.get("limit", 50, type=int)
    orch = get_orchestrator()
    return api_success({"activities": orch.get_activity_feed(limit)})

@main_bp.route("/api/events/stream")
@admin_required
def api_events_stream():
    event_bus = get_event_bus()
    q = event_bus.subscribe()

    def generate():
        from queue import Empty as _QueueEmpty
        try:
            while True:
                try:
                    event = q.get(timeout=10)
                    yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                except _QueueEmpty:
                    yield f"event: heartbeat\ndata: {{\"ts\": \"{datetime.now(timezone.utc).isoformat()}\"}}\n\n"
        except GeneratorExit:
            event_bus.unsubscribe(q)

    return app.response_class(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@main_bp.route("/api/events/history", methods=["GET"])
@admin_required
def api_events_history():
    limit = request.args.get("limit", 100, type=int)
    event_type = request.args.get("type", "").strip() or None
    agent = request.args.get("agent", "").strip() or None
    events = get_event_bus().get_history(limit=limit, event_type=event_type, agent=agent)
    return api_success({"events": events})

@main_bp.route("/api/events/stats", methods=["GET"])
@admin_required
def api_events_stats():
    return api_success(get_event_bus().get_stats())

@main_bp.route("/api/push/vapid-key", methods=["GET"])
def api_push_vapid_key():
    """Return the VAPID public key for push subscription."""
    return api_success({"public_key": push_manager.public_key, "enabled": push_manager.enabled})

@main_bp.route("/api/push/subscribe", methods=["POST"])
def api_push_subscribe():
    """Store a push subscription from the browser."""
    data = request.json
    if not data:
        return api_error("No subscription data", 400)
    ok = push_manager.subscribe(data)
    return api_success({"success": ok})

@main_bp.route("/api/push/unsubscribe", methods=["POST"])
def api_push_unsubscribe():
    """Remove a push subscription."""
    data = request.json
    endpoint = (data or {}).get("endpoint", "")
    if not endpoint:
        return api_error("No endpoint", 400)
    ok = push_manager.unsubscribe(endpoint)
    return api_success({"success": ok})

@main_bp.route("/api/inbox", methods=["GET"])
@admin_required
def api_inbox():
    limit = request.args.get("limit", 50, type=int)
    orch = get_orchestrator()
    user_id = session.get("active_user_id")
    uid = _safe_tenant_id(user_id) if user_id else None
    items = []

    # Pending approvals
    for tid, info in orch.get_pending_drafts(uid).items():
        items.append({
            "type": "approval",
            "agent": info.get("agent", "?"),
            "summary": (info.get("draft", "") or "")[:120],
            "thread_id": tid,
            "created_at": info.get("created_at", ""),
            "icon": "🤔",
        })

    # Activity feed
    for a in orch.get_activity_feed(limit):
        items.append({
            "type": "activity",
            "agent": a.get("agent", "?"),
            "summary": a.get("draft_preview", "")[:120],
            "action": a.get("action", ""),
            "created_at": a.get("timestamp", ""),
            "icon": "✅" if a.get("success") else "❌",
        })

    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return api_success({"items": items[:limit]})

@main_bp.route("/api/orchestrator/undo", methods=["POST"])
@admin_required
def api_undo():
    orch = get_orchestrator()
    result = orch.undo_last()
    return api_success(result) if result else api_success({"action": "nothing_to_undo"})

@main_bp.route("/api/frankie/inspect", methods=["GET"])
def api_frankie_inspect():
    """Frankie inspects the client's live website and returns actionable suggestions."""
    user_id = get_current_user_id()
    if not user_id:
        return api_success({"suggestions": [], "error": "No user"})
    try:
        conn = database._get_conn()
        row = conn.execute("SELECT site_url, business_name, city, niche FROM client_details WHERE user_id = ? LIMIT 1", (_safe_int(user_id),)).fetchone()
    except Exception:
        row = None
    if not row or not row.get("site_url"):
        return api_success({"suggestions": [], "site": None})

    site_url = row["site_url"]
    business = row.get("business_name", "")
    city = row.get("city", "")
    niche = row.get("niche", "")

    suggestions = []
    try:
        resp = _safe_url(site_url)
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
            suggestions.append(f"Your site title is: \"{title[:80]}\" — keep it under 60 chars for Google.")

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
            pass  # optional

        return api_success({
            "site": {"url": site_url, "title": title[:80], "meta_desc": meta_desc[:120], "business": business, "city": city, "niche": niche},
            "suggestions": suggestions[:5],
        })
    except Exception as e:
        return api_success({"suggestions": [f"Could not reach {site_url}. Make sure the site is live."], "site": None})

@main_bp.route("/api/dashboard/ask", methods=["POST"])
@admin_required
def api_dashboard_ask():
    data = request.json
    query = (data or {}).get("query", "").strip()
    if not query:
        return api_error("No query provided", 400)
    lang = "fr" if (session.get("lang") == "fr" or (request.accept_languages and request.accept_languages.best and request.accept_languages.best.startswith("fr"))) else "en"
    try:
        orch = get_orchestrator()
        user_id = get_current_user_id()
        autonomy_config = None
        if user_id:
            conn = database._get_conn()
            rows = conn.execute(
                "SELECT agent_id, autonomy, confidence_threshold FROM agent_configs WHERE user_id = ?",
                (_safe_int(user_id),),
            ).fetchall()
            autonomy_config = {
                r["agent_id"]: {"autonomy": r["autonomy"], "confidence_threshold": r["confidence_threshold"]}
                for r in rows
            }

        result = orch.process_message(
            user_message=query,
            thread_id="frankie-" + uuid.uuid4().hex[:8],
            language=lang if lang else None,
            autonomy_config=autonomy_config,
            user_id=_safe_int(user_id) if user_id else 0,
            source="frankie",
        )

        status = result.get("status", "error")
        response = result.get("response", "")

        # Format Frankie's response based on what happened
        if status == "pending_approval":
            agent = result.get("agent", "agent")
            p = AGENT_PERSONALITIES.get(agent, {})
            emoji = p.get("emoji", "🤖")
            color = p.get("color", "#6b7280")
            draft_preview = (response or "")[:200]
            en = f"{emoji} I asked **{p.get('short', agent)}** to handle this. Here's the draft:\n\n{draft_preview}\n\n---\n\nYou can **approve** or **reject** it in the Tasks tab."
            fr = f"{emoji} J'ai demandé à **{p.get('short_fr', agent)}** de s'en occuper. Voici le projet :\n\n{draft_preview}\n\n---\n\nVous pouvez **approuver** ou **rejeter** dans l'onglet Tâches."
            return api_success({"response": fr if lang == "fr" else en, "pending_approval": True, "agent": agent, "thread_id": result.get("thread_id")})
        elif status == "auto_executed":
            agent = result.get("agent", "agent")
            p = AGENT_PERSONALITIES.get(agent, {})
            emoji = p.get("emoji", "✅")
            en = f"{emoji} Done! **{p.get('short', agent)}** handled it automatically."
            fr = f"{emoji} Terminé ! **{p.get('short_fr', agent)}** s'en est occupé automatiquement."
            return api_success({"response": fr if lang == "fr" else en})
        elif status == "executed_silent":
            return api_success({"response": "✅ Done."})
        elif status == "error":
            return api_success({"response": response or "I couldn't process that."})
        else:
            return api_success({"response": response or "Done."})
    except Exception as e:
        logger.error("Frankie query failed: %s", e, exc_info=True)
        fallback = "Je n'ai pas pu traiter ça. Essayez de me parler des agents, des approbations ou de l'activité récente." if lang == "fr" else "I couldn't process that. Try asking about agents, approvals, or recent activity."
        return api_success({"response": fallback})

@main_bp.route("/api/personalities", methods=["GET"])
def api_personalities():
    """Return agent personalities (emoji, color, short name).
    Supports ``?lang=fr`` for French names."""
    lang = request.args.get("lang", "en")
    data = {}
    for aid, p in AGENT_PERSONALITIES.items():
        entry = dict(p)
        entry["short"] = p.get("short_fr", p["short"]) if lang == "fr" else p["short"]
        data[aid] = entry
    return api_success({"personalities": data})

@main_bp.route("/api/onboarding/status", methods=["GET"])
def api_onboarding_status():
    """Return onboarding completion status for the current user."""
    user_id = get_current_user_id()
    if not user_id:
        return api_error("No user", 400, data={"onboarded": False})
    return api_success({"onboarded": True, "steps": {"welcome": True, "agents": True, "autonomy": True, "done": True}})

@main_bp.route("/api/schedules", methods=["GET"])
@admin_required
def api_list_schedules():
    tenant_id = request.args.get("tenant_id", "")
    schedules = scheduler_manager.get_schedules(user_id=_safe_int(tenant_id) if tenant_id else None)
    return api_success({"schedules": schedules, "enabled": scheduler_manager.enabled})

@main_bp.route("/api/schedules", methods=["POST"])
@admin_required
def api_create_schedule():
    data = request.json
    if not data:
        return api_error("No data", 400)
    tenant_id = data.get("tenant_id", "")
    agent_id = data.get("agent_id", "")
    task = data.get("task", "")
    cron = data.get("cron", "")
    lang = data.get("language", "en")
    if not all([tenant_id, agent_id, task, cron]):
        return api_error("tenant_id, agent_id, task, and cron are required", 400)
    sid = scheduler_manager.create_schedule(_safe_int(tenant_id), agent_id, task, cron, lang)
    return api_success({"id": sid}, status_code=201)

@main_bp.route("/api/schedules/<schedule_id>", methods=["DELETE"])
@admin_required
def api_delete_schedule(schedule_id):
    ok = scheduler_manager.delete_schedule(schedule_id)
    return api_success({"success": ok})

@main_bp.route("/api/schedules/<schedule_id>/toggle", methods=["POST"])
@admin_required
def api_toggle_schedule(schedule_id):
    data = request.json
    enabled = (data or {}).get("enabled", True)
    ok = scheduler_manager.toggle_schedule(schedule_id, enabled)
    return api_success({"success": ok})

@main_bp.route("/api/actions/pending", methods=["GET"])
def api_pending_actions():
    """Return pending actions for the current tenant (used by bookmarklet)."""
    tenant_id = session.get("active_user_id") or getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return api_success({"actions": []})
    actions = _get_pending_actions(tenant_id)
    return api_success({"actions": actions})

@main_bp.route("/api/actions/sms-pending", methods=["GET"])
@admin_required
def api_sms_pending():
    sms_file = Path(__file__).parent / "content" / "sms" / "sms.jsonl"
    if not sms_file.exists():
        return api_success({"messages": []})
    messages = []
    for line in sms_file.read_text().strip().split("\n"):
        if line.strip():
            try:
                msg = json.loads(line)
                if msg.get("status") == "queued":
                    messages.append(msg)
            except json.JSONDecodeError:
                continue
    return api_success({"messages": messages[::-1]})

@main_bp.route("/api/actions/<action_id>/confirm", methods=["POST"])
def api_confirm_action(action_id):
    """Confirm and execute a pending action (called by bookmarklet or email bridge)."""
    tenant_id = session.get("active_user_id") or getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return api_error("No tenant context", 400)
    result = _confirm_pending_action(tenant_id, action_id)
    return api_success(result)

@main_bp.route("/api/actions/sms-sent", methods=["POST"])
@admin_required
def api_sms_mark_sent():
    data = request.json
    timestamp = (data or {}).get("timestamp", "")
    if not timestamp:
        return api_error("timestamp required", 400)
    sms_file = Path(__file__).parent / "content" / "sms" / "sms.jsonl"
    if not sms_file.exists():
        return api_success({"success": True})
    with _sms_lock:
        try:
            lines = sms_file.read_text().strip().split("\n")
            new_lines = []
            for line in lines:
                if line.strip():
                    try:
                        msg = json.loads(line)
                        if msg.get("timestamp") == timestamp:
                            msg["status"] = "sent"
                        new_lines.append(json.dumps(msg))
                    except json.JSONDecodeError:
                        new_lines.append(line)
            sms_file.write_text("\n".join(new_lines) + "\n")
        except Exception as e:
            logger.debug("Silent exception in %s: %s", __name__, e)
    return api_success({"success": True})

@main_bp.route("/api/actions/<action_id>/skip", methods=["POST"])
def api_skip_action(action_id):
    """Skip/discard a pending action without executing."""
    tenant_id = session.get("active_user_id") or getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return api_error("No tenant context", 400)
    uid = _safe_tenant_id(tenant_id)
    if uid is None:
        return api_error("Invalid tenant", 400)
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE pending_actions SET status = 'skipped', completed_at = ? WHERE id = ? AND user_id = ? AND status = 'pending'",
            (datetime.now(timezone.utc).isoformat(), action_id, uid),
        )
        conn.commit()
        return api_success({"action_id": action_id})
    except Exception as e:
        return _safe_error(e, 500)

@main_bp.route("/api/actions/bridge/email", methods=["POST"])
def api_set_email_bridge():
    """Configure the email bridge for the current user."""
    if not current_user.is_authenticated and not session.get("admin_logged_in"):
        return api_error("Unauthorized", 401)
    data = request.json
    if not data:
        return api_error("No data provided", 400)
    tenant_id = current_user.tenant_id
    settings = {
        "imap_host": data.get("imap_host", "imap.gmail.com"),
        "imap_port": int(data.get("imap_port", 993)),
        "username": data.get("email", ""),
        "password": _encrypt_credential(data.get("password", "")),
    }
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE client_details SET email = ?, services = ? WHERE user_id = ?",
            (settings["username"], json.dumps({"email_bridge": settings}), _safe_int(tenant_id)),
        )
        conn.commit()
        decrypted_pw = _decrypt_credential(settings["password"])
        with _email_bridge_lock:
            bridge = _get_email_bridge()
            bridge.stop()
            bridge2 = EmailBridge(
                imap_host=settings["imap_host"],
                imap_port=settings["imap_port"],
                username=settings["username"],
                password=decrypted_pw,
            )
            bridge2.set_handler(lambda action, subj, body: _email_bridge_handler(action, subj, body, tenant_id))
            bridge2.start()
            _set_email_bridge(bridge2)
        return api_success({"message": "Email bridge configured"})
    except Exception as e:
        return _safe_error(e, 500)

@main_bp.route("/api/agents/<agent_id>/autonomy", methods=["GET", "PUT"])
@admin_required
def api_agent_autonomy(agent_id):
    user_id = get_current_user_id()
    if not user_id:
        return api_error("No user selected", 400)

    conn = database._get_conn()
    uid = _safe_int(user_id)

    if request.method == "PUT":
        data = request.json
        if not data:
            return api_error("No data provided", 400)

        autonomy = data.get("autonomy", "manual")
        threshold = float(data.get("confidence_threshold", 0.7))

        if autonomy not in ("manual", "suggest", "auto", "silent"):
            return api_error(f"Invalid autonomy '{autonomy}'. Must be one of: manual, suggest, auto, silent", 400)

        conn.execute(
            "UPDATE agent_configs SET autonomy = ?, confidence_threshold = ? WHERE user_id = ? AND agent_id = ?",
            (autonomy, threshold, uid, agent_id),
        )
        conn.commit()
        return api_success({"agent_id": agent_id, "autonomy": autonomy, "confidence_threshold": threshold})

    rows = conn.execute(
        "SELECT agent_id, autonomy, confidence_threshold FROM agent_configs WHERE user_id = ?",
        (uid,),
    ).fetchall()
    configs = {r["agent_id"]: {"autonomy": r["autonomy"], "confidence_threshold": r["confidence_threshold"]} for r in rows}
    cfg = configs.get(agent_id, {"autonomy": "manual", "confidence_threshold": 0.7})
    return api_success({"agent_id": agent_id, **cfg})

@main_bp.route("/api/agents/autonomy/bulk", methods=["GET"])
@admin_required
def api_all_agent_autonomy():
    user_id = get_current_user_id()
    if not user_id:
        return api_error("No user selected", 400)
    conn = database._get_conn()
    rows = conn.execute(
        "SELECT agent_id, autonomy, confidence_threshold FROM agent_configs WHERE user_id = ?",
        (_safe_int(user_id),),
    ).fetchall()
    configs = {r["agent_id"]: {"autonomy": r["autonomy"], "confidence_threshold": r["confidence_threshold"]} for r in rows}
    return api_success({"autonomy": configs})

@main_bp.route("/api/approvals/<thread_id>/respond", methods=["POST"])
def respond_approval(thread_id):
    """Respond to an approval request using the chat orchestrator."""
    tenant_id = get_current_user_id()
    if not tenant_id:
        return api_error("Authentication required", 401)
    data = request.json
    approved = data.get("approved", False)
    now_iso = datetime.now(timezone.utc).isoformat()

    orch = get_orchestrator()

    # Delegate to orchestrator which now handles execution internally
    drafts = orch.get_pending_drafts(tenant_id)
    if thread_id in drafts:
        result = orch.handle_approval(thread_id, approved=approved)
        return api_success({
            "thread_id": thread_id,
            "status": "completed" if approved else "rejected",
            "execution": result.get("execution"),
            "response": result.get("response"),
        })

    # Fallback: check tenant database if no in-memory draft found
    uid = _safe_tenant_id(tenant_id)
    if uid is None:
        return api_error("Invalid tenant", 400)
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT routed_agent, agent_draft FROM threads WHERE thread_id = ? AND user_id = ?",
            (thread_id, uid),
        )
        row = cursor.fetchone()
        if not row:
            return api_error("Thread not found", 404)

        agent_name = row["routed_agent"]
        draft = row["agent_draft"]
        execution_result = None

        cursor.execute(
            """
            UPDATE threads
            SET approved = ?, status = 'completed', updated_at = ?
            WHERE thread_id = ? AND user_id = ?
            """,
            (int(approved), now_iso, thread_id, uid),
        )
        conn.commit()

        if approved and agent_name and agent_name in agent_registry:
            # Try MCP execution first, fall back to Executioner
            exec_result = None
            mcp_mapping = AGENT_MCP_ROUTING

            mapping = mcp_mapping.get(agent_name)
            if mapping:
                server_name, tool_name = mapping
                mcp_server = get_mcp_server(server_name)
                if mcp_server:
                    try:
                        mcp_result = mcp_server.call_tool(tool_name, content=draft)
                        exec_result = {
                            "success": mcp_result.get("success", False),
                            "result": mcp_result.get("result", ""),
                            "error": mcp_result.get("error"),
                            "execution_id": f"mcp-{server_name}-{tool_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                        }
                        logger.info("MCP execution: %s/%s → success=%s", server_name, tool_name, exec_result['success'])
                    except Exception as e:
                        logger.warning("MCP execution failed, falling back to Executioner: %s", e)

            # Fall back to old Executioner if MCP failed or no mapping
            if not exec_result:
                try:
                    exec_result = executioner.execute(agent_name, draft)
                except Exception as exec_err:
                    exec_result = {"success": False, "error": str(exec_err)}

            execution_result = {
                "success": exec_result.get("success", False),
                "result": exec_result.get("result", "")
            }

        return api_success({
            "thread_id": thread_id,
            "status": "completed",
            "execution": execution_result
        })
    except Exception as e:
        return _safe_error(e, 500)

@main_bp.route("/api/agents/<agent_id>/invoke", methods=["POST"])
@admin_required
def invoke_agent(agent_id):
    if agent_id not in agent_registry:
        return api_error("Agent not found", 404)

    agent = agent_registry[agent_id]

    if not agent.enabled:
        return api_error("Agent is disabled", 403)

    data = request.json
    task = data.get("task")

    if not task:
        return api_error("No task provided", 400)

    tenant_id = get_current_user_id()
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        if tenant_id:
            try:
                update_tenant_agent_activity(
                    tenant_id, agent_id, status="processing"
                )
            except Exception as e:
                logger.debug("Silent exception in %s: %s", __name__, e)

        result = agent._invoke_llm(task)

        draft = result.get("draft_output", "")
        draft_preview = (draft[:120] + "...") if len(draft) > 120 else draft

        if tenant_id:
            try:
                update_tenant_agent_activity(
                    tenant_id,
                    agent_id,
                    status="idle",
                    last_invoked=now_iso,
                    last_draft_preview=draft_preview,
                )
            except Exception as e:
                logger.debug("Silent exception in %s: %s", __name__, e)

        return api_success({"agent_id": agent_id, "result": result})
    except Exception as e:
        if tenant_id:
            try:
                update_tenant_agent_activity(
                    tenant_id, agent_id, status="idle"
                )
            except Exception as e:
                logger.debug("Silent exception in %s: %s", __name__, e)
        return _safe_error(e, 500)

@main_bp.route("/api/agents/<agent_id>/chat", methods=["POST"])
@admin_required
def agent_chat(agent_id):
    if agent_id not in agent_registry:
        return api_error(f"Agent '{agent_id}' not found", 404)

    agent = agent_registry[agent_id]
    if not agent.enabled:
        return api_error("Agent is disabled", 403)

    data = request.json
    if not data:
        return api_error("No data provided", 400)

    message = data.get("message", "").strip()
    thread_id = data.get("thread_id", str(uuid.uuid4()))
    language = data.get("language", "")

    if not message:
        return api_error("No message provided", 400)

    if not language:
        from core.base_agent import BaseAgent
        language = BaseAgent._detect_language(message)

    tenant_id = str(current_user.id) if not current_user.is_anonymous else None
    now_iso = datetime.now(timezone.utc).isoformat()

    # Build conversation context from previous messages in this thread
    conversation_context = ""
    if tenant_id:
        try:
            uid = _safe_int(tenant_id)
            conn = database._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT agent_task, agent_draft FROM threads WHERE thread_id = ? AND user_id = ? ORDER BY created_at ASC LIMIT 20",
                (thread_id, uid)
            )
            history = cursor.fetchall()
            if history:
                conversation_context = "\n\n--- Previous conversation in this thread ---\n"
                for row in history:
                    conversation_context += f"User: {row['agent_task']}\nAgent: {row['agent_draft'][:300]}...\n"
                conversation_context += "--- End of history ---\n\n"
        except Exception as e:
            logger.debug("Silent exception in %s: %s", __name__, e)

    # Build the full task with context
    full_task = f"{conversation_context}Current request: {message}" if conversation_context else message
    stream = data.get("stream", False)

    def _store_draft(draft_text: str) -> None:
        if tenant_id:
            try:
                uid = _safe_int(tenant_id)
                conn = database._get_conn()
                conn.execute(
                    """INSERT INTO threads
                       (thread_id, routed_agent, agent_task, agent_draft, status, created_at, updated_at, user_id)
                       VALUES (?, ?, ?, ?, 'chat', ?, ?, ?)""",
                    (thread_id, agent_id, message, draft_text, now_iso, now_iso, uid),
                )
                conn.commit()
                update_tenant_agent_activity(
                    tenant_id, agent_id,
                    status="idle", last_invoked=now_iso,
                    last_draft_preview=(draft_text[:120] + "...") if len(draft_text) > 120 else draft_text,
                )
            except Exception as e:
                logger.debug("Silent exception in %s: %s", __name__, e)

    try:
        if stream:
            def generate():
                collected: list[str] = []
                for item in agent._stream_llm(full_task):
                    if isinstance(item, str):
                        collected.append(item)
                        yield f"data: {json.dumps({'type': 'token', 'content': item})}\n\n"
                    else:
                        draft = item.get("draft_output", "")
                        thinking = f"Agent '{agent_id}' processed your request using model '{agent.model}'."
                        _store_draft(draft)
                        yield f"data: {json.dumps({'type': 'done', 'response': draft, 'thread_id': thread_id, 'language': language, 'thinking': thinking, 'model': agent.model})}\n\n"
            return Response(stream_with_context(generate()), mimetype='text/event-stream')
        else:
            result = agent._invoke_llm(full_task)
            draft = result.get("draft_output", "")
            _store_draft(draft)
            return api_success({
                "agent_id": agent_id,
                "response": draft,
                "thread_id": thread_id,
                "language": language,
                "thinking": f"Agent '{agent_id}' processed your request using model '{agent.model}'. The agent applied its specialized system prompt to generate this response.",
                "model": agent.model,
            })
    except Exception as e:
        logger.error("Agent chat failed for %s: %s", agent_id, e)
        return _safe_error(e, 500)

@main_bp.route("/api/agents/<agent_id>/threads", methods=["GET"])
def get_agent_threads(agent_id):
    """
    Get all chat threads for a specific agent in the current tenant.
    Returns list of thread IDs with preview of the first message.
    """
    if agent_id not in agent_registry:
        return api_error(f"Agent '{agent_id}' not found", 404)

    tenant_id = get_current_user_id()
    if not tenant_id:
        return api_success({"threads": []})

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT DISTINCT thread_id,
                      MIN(created_at) as started_at,
                      (SELECT agent_task FROM threads t2 WHERE t2.thread_id = threads.thread_id ORDER BY created_at ASC LIMIT 1) as first_message
               FROM threads
               WHERE routed_agent = ? AND user_id = ? AND status = 'chat'
               GROUP BY thread_id
               ORDER BY started_at DESC LIMIT 30""",
            (agent_id, _safe_int(tenant_id))
        )
        threads = []
        for row in cursor.fetchall():
            threads.append({
                "thread_id": row["thread_id"],
                "started_at": row["started_at"],
                "first_message": (row["first_message"] or "")[:80] + "..." if row["first_message"] and len(row["first_message"]) > 80 else (row["first_message"] or "New conversation"),
            })
        return api_success({"threads": threads})
    except Exception as e:
        return _safe_error(e, 500)

@main_bp.route("/api/agents/<agent_id>/threads/<thread_id>", methods=["GET"])
def get_agent_thread_history(agent_id, thread_id):
    """
    Get the full conversation history for a specific thread.
    Returns all messages in chronological order.
    """
    if agent_id not in agent_registry:
        return api_error(f"Agent '{agent_id}' not found", 404)

    tenant_id = get_current_user_id()
    if not tenant_id:
        return api_success({"messages": []})

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT agent_task, agent_draft, created_at
               FROM threads
               WHERE thread_id = ? AND user_id = ? AND routed_agent = ?
               ORDER BY created_at ASC""",
            (thread_id, _safe_int(tenant_id), agent_id)
        )
        messages = []
        for row in cursor.fetchall():
            messages.append({
                "role": "user",
                "content": row["agent_task"],
                "timestamp": row["created_at"],
            })
            messages.append({
                "role": "agent",
                "content": row["agent_draft"],
                "timestamp": row["created_at"],
            })
        return api_success({"messages": messages, "thread_id": thread_id, "agent_id": agent_id})
    except Exception as e:
        return _safe_error(e, 500)

@main_bp.route("/api/threads")
def api_list_threads():
    """List chat threads for the current tenant, optionally filtered by agent."""
    if session.get("admin_logged_in"):
        tenant_id = session.get("active_user_id")
    else:
        tenant_id = getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return api_success({"threads": []})

    agent_filter = request.args.get("agent", "")
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        if agent_filter:
            cursor.execute(
                ("SELECT thread_id, agent_task, created_at FROM threads "
                 "WHERE status = 'chat' AND routed_agent = ? AND user_id = ? "
                 "ORDER BY created_at DESC LIMIT 50"),
                (agent_filter, _safe_int(tenant_id)),
            )
        else:
            cursor.execute(
                "SELECT thread_id, agent_task, created_at FROM threads WHERE status = 'chat' AND user_id = ? ORDER BY created_at DESC LIMIT 50",
                (_safe_int(tenant_id),)
            )
        rows = cursor.fetchall()
        return api_success({
            "threads": [
                {"thread_id": r["thread_id"], "agent_task": r["agent_task"], "created_at": r["created_at"]}
                for r in rows
            ]
        })
    except Exception as e:
        return _safe_error(e, 500)

@main_bp.route("/api/threads/<thread_id>/messages")
def api_get_thread_messages(thread_id):
    """Get all messages in a chat thread."""
    if session.get("admin_logged_in"):
        tenant_id = session.get("active_user_id")
    else:
        tenant_id = getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return api_success({"messages": []})

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT agent_task, agent_draft, result FROM threads WHERE thread_id = ? AND user_id = ? AND status = 'chat' ORDER BY created_at ASC",
            (thread_id, _safe_int(tenant_id)),
        )
        rows = cursor.fetchall()
        messages = []
        for r in rows:
            messages.append({"role": "user", "content": r["agent_task"]})
            messages.append({"role": "agent", "content": r["agent_draft"], "thinking": None})
        return api_success({"messages": messages})
    except Exception as e:
        return _safe_error(e, 500)

@main_bp.route("/api/tenants", methods=["GET"])
@admin_required
def list_tenants():

    direct = [str(u["id"]) for u in database.list_users(role='user')]

    return api_success({
        "direct_clients": direct,
        "active_tenant": session.get("active_user_id"),
    })

@main_bp.route("/api/tenants/switch", methods=["POST"])
@admin_required
def switch_tenant():

    data = request.json
    tenant_id = data.get("tenant_id")

    if tenant_id:
        session["active_user_id"] = tenant_id
        return api_success({
            "active_tenant": tenant_id,
            "message": f"Switched to {tenant_id}",
        })
    else:
        session.pop("active_user_id", None)
        return api_success({
            "active_tenant": None,
            "message": "Client cleared",
        })

@main_bp.route("/api/analytics/summary")
def api_analytics_summary():
    """Return summary analytics for a user or all users (admin)."""
    if not session.get("admin_logged_in"):
        return api_error("Unauthorized", 401)

    user_id = request.args.get("client", "").strip()
    days = int(request.args.get("days", 30))
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    is_admin = session.get("admin_logged_in", False)
    session_user = session.get("active_user_id") or getattr(current_user, "id", None)

    if user_id and is_admin:
        engine = AnalyticsEngine(_safe_int(user_id))
        perf = engine.get_performance_summary()
        leads = engine.get_lead_metrics(start_date, end_date)
        agents = engine.get_agent_metrics(start_date, end_date)
        execs = engine.get_execution_metrics(start_date, end_date)
        return api_success({
            "total_clients": 1,
            "total_leads": perf.get("leads_this_month", 0),
            "total_tasks": perf.get("tasks_this_month", 0),
            "success_rate": perf.get("success_rate", 0),
            "success_count": execs.get("success_count", 0),
            "fail_count": execs.get("fail_count", 0),
            "avg_success_rate": perf.get("success_rate", 0),
            "leads_this_month": perf.get("leads_this_month", 0),
            "tasks_this_month": perf.get("tasks_this_month", 0),
            "active_agents": perf.get("active_agents", 0),
            "total_agents": perf.get("total_agents", 0),
            "avg_response_time": agents.get("avg_response_time", 0),
            "leads_by_month": _leads_by_month(engine),
            "tasks_per_agent": agents.get("tasks_per_agent", []),
            "failures_by_tool": execs.get("failures_by_tool", {}),
            "recent_leads": engine._fetchall(
                "SELECT name, service, urgency, status FROM leads ORDER BY created_at DESC LIMIT 50"
            ),
            "recent_executions": engine._fetchall(
                "SELECT agent_name, tool_name, success, timestamp FROM execution_log ORDER BY timestamp DESC LIMIT 50"
            ),
            "per_client": [{
                "user_id": user_id,
                "leads": perf.get("leads_this_month", 0),
                "tasks": perf.get("tasks_this_month", 0),
                "success_rate": perf.get("success_rate", 0),
                "active_agents": perf.get("active_agents", 0),
            }],
        })

    if is_admin:
        all_users = database.list_users(role='user')
        all_user_ids = [str(u["id"]) for u in all_users]
        total_leads = 0
        total_tasks = 0
        total_success = 0
        total_fail = 0
        all_tasks_per_agent = {}
        all_failures_by_tool = {}
        all_leads_by_month = {}
        all_recent_leads = []
        all_recent_execs = []
        for uid in all_user_ids:
            e = AnalyticsEngine(int(uid))
            perf = e.get_performance_summary()
            leads_m = e.get_lead_metrics(start_date, end_date)
            agents_m = e.get_agent_metrics(start_date, end_date)
            execs_m = e.get_execution_metrics(start_date, end_date)
            total_leads += perf.get("leads_this_month", 0)
            total_tasks += perf.get("tasks_this_month", 0)
            total_success += execs_m.get("success_count", 0)
            total_fail += execs_m.get("fail_count", 0)
            for a in agents_m.get("tasks_per_agent", []):
                name = a["agent"]
                if name not in all_tasks_per_agent:
                    all_tasks_per_agent[name] = {"agent": name, "total": 0, "success": 0, "fail": 0, "success_rate": 0}
                all_tasks_per_agent[name]["total"] += a["total"]
                all_tasks_per_agent[name]["success"] += a["success"]
                all_tasks_per_agent[name]["fail"] += a["fail"]
            for tool, cnt in execs_m.get("failures_by_tool", {}).items():
                all_failures_by_tool[tool] = all_failures_by_tool.get(tool, 0) + cnt
            for m in _leads_by_month(e):
                lbl = m["label"]
                all_leads_by_month[lbl] = all_leads_by_month.get(lbl, 0) + m["count"]
            all_recent_leads.extend(
                e._fetchall("SELECT name, service, urgency, status FROM leads ORDER BY created_at DESC LIMIT 20")
            )
            all_recent_execs.extend(
                e._fetchall("SELECT agent_name, tool_name, success, timestamp FROM execution_log ORDER BY timestamp DESC LIMIT 20")
            )
        for a in all_tasks_per_agent.values():
            a["success_rate"] = round((a["success"] / a["total"] * 100) if a["total"] else 0, 1)
        leads_by_month = [{"label": k, "count": v} for k, v in sorted(all_leads_by_month.items())]
        total_clients = len(all_user_ids)
        avg_sr = round((total_success / (total_success + total_fail) * 100) if (total_success + total_fail) else 0, 1)
        return api_success({
            "total_clients": total_clients,
            "total_leads": total_leads,
            "total_tasks": total_tasks,
            "success_count": total_success,
            "fail_count": total_fail,
            "avg_success_rate": avg_sr,
            "active_agents": len(all_tasks_per_agent),
            "total_agents": len(database.DEFAULT_AGENTS),
            "leads_this_month": total_leads,
            "tasks_this_month": total_tasks,
            "leads_by_month": leads_by_month,
            "tasks_per_agent": list(all_tasks_per_agent.values()),
            "failures_by_tool": all_failures_by_tool,
            "recent_leads": sorted(all_recent_leads, key=lambda x: x.get("name", ""))[:20],
            "recent_executions": sorted(all_recent_execs, key=lambda x: x.get("timestamp", ""), reverse=True)[:20],
        })

    if not is_admin and session_user:
        engine = AnalyticsEngine(int(session_user))
        perf = engine.get_performance_summary()
        leads = engine.get_lead_metrics(start_date, end_date)
        agents = engine.get_agent_metrics(start_date, end_date)
        execs = engine.get_execution_metrics(start_date, end_date)
        return api_success({
            "leads_this_month": perf.get("leads_this_month", 0),
            "tasks_this_month": perf.get("tasks_this_month", 0),
            "success_rate": perf.get("success_rate", 0),
            "active_agents": perf.get("active_agents", 0),
            "total_agents": perf.get("total_agents", 0),
            "avg_response_time": agents.get("avg_response_time", 0),
            "conversion_rate": leads.get("conversion_rate", 0),
            "leads_by_month": _leads_by_month(engine),
            "tasks_per_agent": agents.get("tasks_per_agent", []),
            "failures_by_tool": execs.get("failures_by_tool", {}),
            "recent_leads": engine._fetchall(
                "SELECT name, service, urgency, status FROM leads ORDER BY created_at DESC LIMIT 20"
            ),
            "recent_executions": engine._fetchall(
                "SELECT agent_name, tool_name, success, timestamp FROM execution_log ORDER BY timestamp DESC LIMIT 20"
            ),
        })

    return api_error("Unauthorized", 401)

@main_bp.route("/api/analytics/leads")
@admin_required
def api_analytics_leads():
    user_id = request.args.get("client", "").strip() or session.get("active_user_id") or getattr(current_user, "id", None)
    start = request.args.get("start")
    end = request.args.get("end")
    if not user_id:
        return api_error("No user context", 400)
    engine = AnalyticsEngine(_safe_int(user_id))
    return api_success(engine.get_lead_metrics(start, end))

@main_bp.route("/api/analytics/agents")
@admin_required
def api_analytics_agents():
    user_id = request.args.get("client", "").strip() or session.get("active_user_id") or getattr(current_user, "id", None)
    start = request.args.get("start")
    end = request.args.get("end")
    if not user_id:
        return api_error("No user context", 400)
    engine = AnalyticsEngine(_safe_int(user_id))
    return api_success(engine.get_agent_metrics(start, end))

@main_bp.route("/api/analytics/executions")
@admin_required
def api_analytics_executions():
    user_id = request.args.get("client", "").strip() or session.get("active_user_id") or getattr(current_user, "id", None)
    start = request.args.get("start")
    end = request.args.get("end")
    if not user_id:
        return api_error("No user context", 400)
    engine = AnalyticsEngine(_safe_int(user_id))
    return api_success(engine.get_execution_metrics(start, end))

@main_bp.route("/api/analytics/report/generate", methods=["POST"])
@admin_required
def api_analytics_generate_report():
    data = request.json
    user_id = data.get("user_id") or session.get("active_user_id")
    month = data.get("month")
    year = data.get("year")
    if not user_id:
        return api_error("user_id required", 400)
    engine = AnalyticsEngine(_safe_int(user_id))
    html = engine.generate_monthly_report(year, month)
    return api_success({"html": html})

@main_bp.route("/api/analytics/report/save", methods=["POST"])
@admin_required
def api_analytics_save_report():
    data = request.json
    report_id = uuid.uuid4().hex[:12]
    entry = {
        "id": report_id,
        "user_id": data.get("user_id", ""),
        "month": data.get("month"),
        "year": data.get("year"),
        "html": data.get("html", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _report_history_lock:
        _report_history.insert(0, entry)
        _report_history[:] = _report_history[:100]
    return api_success({"id": report_id})

@main_bp.route("/api/analytics/reports/history", methods=["GET"])
@admin_required
def api_analytics_report_history():
    user_id = request.args.get("user_id", "")
    with _report_history_lock:
        reports = [r for r in _report_history if not user_id or r.get("user_id") == user_id]
    safe = [{"id": r["id"], "month": r["month"], "year": r["year"], "created_at": r["created_at"]} for r in reports]
    return api_success({"reports": safe})

@main_bp.route("/api/analytics/report/<report_id>", methods=["GET"])
@admin_required
def api_analytics_get_report(report_id):
    with _report_history_lock:
        for r in _report_history:
            if r["id"] == report_id:
                return api_success({"html": r["html"]})
    return api_error("Report not found", 404)

@main_bp.route("/api/analytics/report/<report_id>/email", methods=["POST"])
@admin_required
def api_analytics_email_saved_report(report_id):
    with _report_history_lock:
        report = None
        for r in _report_history:
            if r["id"] == report_id:
                report = r
                break
    if not report:
        return api_error("Report not found", 404)
    return _send_report_email(report["html"], report["user_id"])

@main_bp.route("/api/analytics/report/email", methods=["POST"])
@admin_required
def api_analytics_email_report():
    data = request.json
    user_id = data.get("user_id")
    html = data.get("html")
    if not user_id or not html:
        return api_error("user_id and html are required", 400)
    return _send_report_email(html, user_id)

@main_bp.route("/api/managed/upgrade", methods=["POST"])
@client_required
def api_managed_upgrade():
    """Upgrade the current client to managed services."""
    tenant_id = current_user.tenant_id
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE client_details SET managed_service = 1, managed_since = ? WHERE user_id = ?",
            (now_iso, _safe_int(tenant_id)),
        )
        conn.commit()

        # Log to execution_log
        try:
            cursor.execute(
                "INSERT INTO execution_log (user_id, execution_id, agent_name, tool_name, success, draft_preview, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_safe_int(tenant_id), str(uuid.uuid4()), "system", "managed_services", 1,
                 f"Client upgraded to Managed Services (${MANAGED_MONTHLY_FEE}/mo)", now_iso),
            )
            conn.commit()
        except Exception as e:
            logger.debug("Silent exception in %s: %s", __name__, e)

        logger.info("Client %s upgraded to Managed Services", tenant_id)
        return api_success({"message": "Upgraded to Managed Services"})
    except Exception as e:
        logger.error("Failed to upgrade %s: %s", tenant_id, e)
        logger.error("Internal error: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 500)

@main_bp.route("/api/managed/cancel", methods=["POST"])
@client_required
def api_managed_cancel():
    """Request cancellation of managed services (30-day notice)."""
    tenant_id = current_user.tenant_id
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE client_details SET managed_service = 0 WHERE user_id = ? AND managed_service = 1",
            (_safe_int(tenant_id),)
        )
        conn.commit()
        logger.info("Client %s cancelled Managed Services", tenant_id)
        # Log cancellation
        try:
            cursor.execute(
                "INSERT INTO execution_log (user_id, execution_id, agent_name, tool_name, success, draft_preview, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_safe_int(tenant_id), str(uuid.uuid4()), "system", "managed_services", 1,
                 "Client cancelled Managed Services (30-day notice)", now_iso),
            )
            conn.commit()
        except Exception as e:
            logger.debug("Silent exception in %s: %s", __name__, e)
        return api_success({"message": "Cancellation requested"})
    except Exception as e:
        logger.error("Failed to cancel managed for %s: %s", tenant_id, e)
        logger.error("Internal error: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 500)

@main_bp.route("/api/managed/clients")
@admin_required
def api_managed_clients():

    filter_mode = request.args.get("filter", "active")
    all_tenants = [str(u["id"]) for u in database.list_users(role='user')]
    clients = []
    total_mrr = 0
    total_pending = 0
    past_due_count = 0

    for tid in all_tenants:
        try:
            conn = database._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT managed_service, managed_since, package FROM client_details WHERE user_id = ?",
                (int(tid),)
            )
            row = cursor.fetchone()
            if not row or not row.get("managed_service"):
                continue

            managed_since = row.get("managed_since")
            managed_since_str = managed_since[:10] if managed_since else None
            pkg = row.get("package", "")

            # Calculate billing date (30 days from managed_since)
            next_billing = None
            if managed_since:
                try:
                    from datetime import date as dt_date
                    ms_date = dt_date.fromisoformat(managed_since[:10])
                    from datetime import timedelta as td
                    next_date = ms_date + td(days=30)
                    while next_date < dt_date.today():
                        next_date += td(days=30)
                    next_billing = next_date.isoformat()
                except Exception as e:
                    logger.debug("Silent exception in %s: %s", __name__, e)

            # Determine status
            status = "active"
            if next_billing:
                try:
                    from datetime import date as dt_date
                    billing_dt = dt_date.fromisoformat(next_billing)
                    if billing_dt < dt_date.today():
                        status = "past_due"
                        past_due_count += 1
                except Exception as e:
                    logger.debug("Silent exception in %s: %s", __name__, e)

            if filter_mode != "all" and status != filter_mode:
                continue

            total_mrr += MANAGED_MONTHLY_FEE

            # Count pending approvals
            try:
                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM threads WHERE user_id = ? AND status = 'pending_approval'",
                    (int(tid),)
                )
                pending_row = cursor.fetchone()
                pending_count = pending_row["cnt"] if pending_row else 0
                total_pending += pending_count
            except Exception:
                pending_count = 0

            clients.append({
                "tenant_id": tid,
                "package": pkg,
                "managed_since": managed_since_str,
                "monthly_fee": MANAGED_MONTHLY_FEE,
                "next_billing": next_billing[:10] if next_billing else None,
                "status": status,
                "pending_approvals": pending_count,
            })
        except Exception:
            continue

    return api_success({
        "clients": clients,
        "total_mrr": total_mrr,
        "total_pending_approvals": total_pending,
        "past_due_count": past_due_count,
    })

@main_bp.route("/api/managed/pause", methods=["POST"])
@admin_required
def api_managed_pause():
    data = request.json
    tenant_id = data.get("tenant_id")
    if not tenant_id:
        return api_error("tenant_id required", 400)
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE client_details SET managed_service = 0 WHERE user_id = ? AND managed_service = 1",
            (_safe_int(tenant_id),)
        )
        conn.commit()
        logger.info("Admin paused Managed Services for %s", tenant_id)
        return api_success({"message": "Managed services paused"})
    except Exception as e:
        logger.error("Internal error: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 500)

@main_bp.route("/api/managed/resume", methods=["POST"])
@admin_required
def api_managed_resume():
    data = request.json
    tenant_id = data.get("tenant_id")
    if not tenant_id:
        return api_error("tenant_id required", 400)
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE client_details SET managed_service = 1, managed_since = ? WHERE user_id = ?",
            (now_iso, _safe_int(tenant_id)),
        )
        conn.commit()
        logger.info("Admin resumed Managed Services for %s", tenant_id)
        return api_success({"message": "Managed services resumed"})
    except Exception as e:
        logger.error("Internal error: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 500)

@main_bp.route("/api/managed/bulk-approve", methods=["POST"])
@admin_required
def api_managed_bulk_approve():
    data = request.json
    tenant_id = data.get("tenant_id")
    if not tenant_id:
        return api_error("tenant_id required", 400)
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT thread_id, routed_agent, agent_draft FROM threads WHERE user_id = ? AND status = 'pending_approval'",
            (_safe_int(tenant_id),)
        )
        pending = cursor.fetchall()
        approved_count = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        for row in pending:
            thread_id = row["thread_id"]
            agent_name = row["routed_agent"]
            draft = row["agent_draft"] or ""

            # Approve the thread
            cursor.execute(
                "UPDATE threads SET approved = 1, status = 'completed', updated_at = ? WHERE thread_id = ? AND user_id = ?",
                (now_iso, thread_id, _safe_int(tenant_id)),
            )

            # Execute via executioner if agent exists and draft is not empty
            if agent_name and draft and agent_name in agent_registry:
                try:
                    exec_result = executioner.execute(agent_name, draft)
                    # Log execution
                    cursor.execute(
                        "INSERT INTO execution_log (user_id, execution_id, agent_name, tool_name, success, draft_preview, timestamp) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (_safe_int(tenant_id), str(uuid.uuid4()), agent_name, "managed_bulk_approve",
                         int(exec_result.get("success", False)),
                         (draft[:120] + "...") if len(draft) > 120 else draft, now_iso),
                    )
                except Exception as e:
                    logger.debug("Silent exception in %s: %s", __name__, e)

            approved_count += 1

        conn.commit()
        logger.info("Bulk approved %d items for %s", approved_count, tenant_id)
        return api_success({
            "approved_count": approved_count,
            "message": f"Approved {approved_count} pending item(s)",
        })
    except Exception as e:
        logger.error("Bulk approve failed for %s: %s", tenant_id, e)
        logger.error("Internal error: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 500)

@main_bp.route("/api/managed/mrr")
@admin_required
def api_managed_mrr():
    all_tenants = [str(u["id"]) for u in database.list_users(role='user')]
    active_count = 0
    for tid in all_tenants:
        try:
            conn = database._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT managed_service FROM client_details WHERE user_id = ?", (int(tid),))
            row = cursor.fetchone()
            if row and row.get("managed_service"):
                active_count += 1
        except Exception:
            continue
    total_mrr = active_count * MANAGED_MONTHLY_FEE
    return api_success({
        "active_managed_clients": active_count,
        "monthly_fee": MANAGED_MONTHLY_FEE,
        "total_mrr": total_mrr,
    })

def _reinitialize_agent(agent_id: str, config: dict) -> None:
    cls = AGENT_CLASSES.get(agent_id)
    if cls:
        agent_registry[agent_id] = cls(agent_id, config)

def _safe_tenant_id(tenant_id: str) -> Optional[int]:
    """Safely convert tenant_id to int, returning None if invalid."""
    if not tenant_id or not str(tenant_id).strip().isdigit():
        return None
    return int(tenant_id)

def _get_pending_actions(tenant_id: str, status: str = "pending") -> list:
    uid = _safe_tenant_id(tenant_id)
    if uid is None:
        return []
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, agent_name, tool_name, provider, content, subject, status, created_at "
            "FROM pending_actions WHERE status = ? AND user_id = ? ORDER BY created_at DESC LIMIT 50",
            (status, uid),
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error("Failed to get pending actions for %s: %s", tenant_id, e)
        return []

def _add_pending_action(
    tenant_id: str, agent_name: str, tool_name: str,
    content: str, provider: str = "web", subject: str = "",
) -> str:
    uid = _safe_tenant_id(tenant_id)
    if uid is None:
        return ""
    action_id = uuid.uuid4().hex[:12]
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO pending_actions (id, user_id, agent_name, tool_name, provider, content, subject, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (action_id, uid, agent_name, tool_name, provider, content, subject, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return action_id
    except Exception as e:
        logger.error("Failed to add pending action: %s", e)
        return ""

def _confirm_pending_action(tenant_id: str, action_id: str) -> Dict[str, Any]:
    uid = _safe_tenant_id(tenant_id)
    if uid is None:
        return {"success": False, "error": "Invalid tenant"}
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, agent_name, tool_name, content FROM pending_actions WHERE id = ? AND user_id = ? AND status = 'pending'",
            (action_id, uid),
        )
        row = cursor.fetchone()
        if not row:
            return {"success": False, "error": "Action not found or already completed"}
        # Execute via executioner
        from agents.executioner_agent import ExecutionerError
        try:
            exec_result = executioner.execute(row["agent_name"], row["content"], tool_name=row["tool_name"])
            cursor.execute(
                "UPDATE pending_actions SET status = 'completed', completed_at = ? WHERE id = ? AND user_id = ?",
                (datetime.now(timezone.utc).isoformat(), action_id, uid),
            )
            conn.commit()
            return {"success": True, "result": exec_result.get("result", "Done"), "action_id": action_id}
        except ExecutionerError as ee:
            return {"success": False, "error": str(ee)}
    except Exception as e:
        logger.error("Failed to confirm action %s: %s", action_id, e)
        return {"success": False, "error": "Internal error"}

def _email_bridge_handler(action: str, subject: str, body: str, tenant_id: str) -> None:
    if action == "approve":
        actions = _get_pending_actions(tenant_id)
        if actions:
            _confirm_pending_action(tenant_id, actions[0]["id"])
            logger.info("Email bridge approved action %s for %s", actions[0]["id"], tenant_id)
    elif action == "reject":
        actions = _get_pending_actions(tenant_id)
        if actions:
            try:
                conn = database._get_conn()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE pending_actions SET status = 'skipped', completed_at = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), actions[0]["id"]),
                )
                conn.commit()
            except Exception as e:
                logger.debug("Silent exception in %s: %s", __name__, e)

def _get_email_bridge():
    global _email_bridge_instance
    with _email_bridge_lock:
        if _email_bridge_instance is None:
            _email_bridge_instance = EmailBridge()
            _email_bridge_instance.set_handler(lambda a, s, b: logger.warning("Email bridge: no tenant configured, ignoring action '%s'", a))
        return _email_bridge_instance

def _set_email_bridge(bridge):
    global _email_bridge_instance
    with _email_bridge_lock:
        _email_bridge_instance = bridge

def _leads_by_month(engine, months: int = 6) -> list:
    """Return lead counts grouped by month for chart display."""
    from datetime import date as dt_date
    import calendar
    result = []
    today = dt_date.today()
    for i in range(months - 1, -1, -1):
        m = today.month - i
        y = today.year
        while m < 1:
            m += 12
            y -= 1
        start = f"{y}-{m:02d}-01"
        last_day = calendar.monthrange(y, m)[1]
        end = f"{y}-{m:02d}-{last_day}"
        rows = engine._fetchall(
            "SELECT COUNT(*) as cnt FROM leads WHERE DATE(created_at) >= ? AND DATE(created_at) <= ?",
            (start, end),
        )
        cnt = rows[0]["cnt"] if rows else 0
        result.append({"label": f"{calendar.month_abbr[m]}", "count": cnt})
    return result

def _send_report_email(html: str, user_id: str):
    """Shared helper to email a report HTML to a client."""
    try:
        engine = AnalyticsEngine(_safe_int(user_id))
        biz_row = engine._fetchone("SELECT business_name, email FROM client_details WHERE user_id = ?", (_safe_int(user_id),))
        business_name = biz_row["business_name"] if biz_row else user_id
        client_email = biz_row["email"] if biz_row else None
        if not client_email:
            return api_error("No client email found", 400)
        settings = executioner.get_settings()
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Monthly Performance Report — {business_name}"
        msg["From"] = settings.get("smtp_from_email", "reports@lavaldigital.ca")
        msg["To"] = client_email
        part = MIMEText(html, "html")
        msg.attach(part)
        ssl_context = ssl.create_default_context()
        with smtplib.SMTP(settings.get("smtp_host", "smtp.gmail.com"), settings.get("smtp_port", 587)) as server:
            if settings.get("smtp_use_tls", True):
                server.starttls(context=ssl_context)
            if settings.get("smtp_username"):
                server.login(settings["smtp_username"], settings.get("smtp_password", ""))
            server.send_message(msg)
        return api_success({"message": f"Report emailed to {client_email}"})
    except Exception as e:
        logger.error("Failed to email report: %s", e)
        return api_error("An internal error occurred.", 500)
