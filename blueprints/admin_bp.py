"""Admin blueprint — login, logout, panel, dashboard, connector, analytics, reports, managed."""
import os
import hmac
import uuid
from functools import wraps
from pathlib import Path
from flask import Blueprint, render_template, redirect, url_for, session, request, flash, current_app
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timezone

from core import database
from core.auth import admin_required, admin_page_required, _check_rate_limit, _record_attempt

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
admin_fr_bp = Blueprint("admin_fr", __name__, url_prefix="/fr/admin")

_admin_password_hash = ""


def _get_admin_password_hash() -> str:
    """Load the hashed admin password from environment."""
    global _admin_password_hash
    if not _admin_password_hash:
        from werkzeug.security import generate_password_hash
        _admin_password_hash = os.getenv("ADMIN_PASSWORD_HASH", generate_password_hash(os.getenv("ADMIN_PASSWORD", "")))
    return _admin_password_hash


def admin_page_required_fr(f):
    """Decorator that requires admin session authentication (redirects to French login)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_fr.login_fr"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Admin auth routes
# ---------------------------------------------------------------------------

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    """Serve the admin login page and handle authentication."""
    if request.method == "POST":
        if not _check_rate_limit("admin"):
            return render_template(
                "login.html", error="Too many attempts. Please try again later.", now=datetime.now()
            )
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        expected_user = os.getenv("ADMIN_USERNAME")
        if hmac.compare_digest(username, expected_user) and check_password_hash(_get_admin_password_hash(), password):
            _record_attempt(True, "admin")
            session["admin_logged_in"] = True
            return redirect(url_for("admin.panel"))
        _record_attempt(False, "admin")
        return render_template(
            "login.html", error="Invalid username or password.", now=datetime.now()
        )
    return render_template("login.html", now=datetime.now())


@admin_bp.route("/logout")
def logout():
    """Log out and redirect to login."""
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin.login"))


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------

@admin_bp.route("")
def panel():
    """Serve the admin panel with session-based auth."""
    auth_check = admin_page_required()
    if auth_check:
        return auth_check
    logo_status = request.args.get("logo_uploaded", "")
    tenants = {
        "direct_clients": database.list_users(role='user'),
    }
    active_tenant = session.get("active_user_id")
    return render_template(
        "admin.html",
        logo_uploaded=logo_status,
        tenants=tenants,
        active_tenant=active_tenant,
    )


@admin_bp.route("/agent/<agent_id>/chat")
def agent_chat(agent_id):
    """Serve the admin agent chat interface."""
    auth_check = admin_page_required()
    if auth_check:
        return auth_check
    from core.app_state import get_agent_registry, get_agent_meta
    agent_registry = get_agent_registry()
    AGENT_META = get_agent_meta()
    if agent_id not in agent_registry:
        return "Agent not found", 404
    return render_template(
        "admin/agent_chat.html",
        agent_id=agent_id,
        agent=agent_registry[agent_id],
        agent_name=AGENT_META.get(agent_id, {}).get("name", agent_id),
    )


@admin_bp.route("/dashboard")
def dashboard():
    """Serve the real-time agent dashboard."""
    auth_check = admin_page_required()
    if auth_check:
        return auth_check
    from core.app_state import get_agent_meta
    return render_template(
        "admin/dashboard.html",
        agents=get_agent_meta(),
    )


@admin_bp.route("/connector")
def connector():
    """Serve the connector setup page (bookmarklet + email bridge)."""
    auth_check = admin_page_required()
    if auth_check:
        return auth_check
    tenant_id = session.get("active_user_id")
    if not tenant_id:
        return render_template("admin/connector.html", error="Select a client first to configure the connector.")
    base_url = request.host_url.rstrip("/")
    bookmarklet_code = (
        'javascript:(function(){var s=document.createElement("script");'
        f's.src="{base_url}/static/bookmarklet.js";'
        "document.body.appendChild(s);})()"
    )
    return render_template("admin/connector.html", bookmarklet_code=bookmarklet_code, tenant_id=tenant_id)


@admin_bp.route("/analytics")
def analytics():
    """Serve the admin analytics dashboard page."""
    auth_check = admin_page_required()
    if auth_check:
        return auth_check
    tenants = {
        "direct_clients": database.list_users(role='user'),
    }
    active_tenant = session.get("active_user_id")
    return render_template("admin.html", tenants=tenants, active_tenant=active_tenant)


@admin_bp.route("/reports")
def reports():
    """Serve the report generation page."""
    auth_check = admin_page_required()
    if auth_check:
        return auth_check
    tenants = {
        "direct_clients": database.list_users(role='user'),
    }
    active_tenant = session.get("active_user_id")
    return render_template("admin.html", tenants=tenants, active_tenant=active_tenant)


@admin_bp.route("/managed")
def managed():
    """Serve the managed clients admin page."""
    auth_check = admin_page_required()
    if auth_check:
        return auth_check
    tenants = {
        "direct_clients": database.list_users(role='user'),
    }
    active_tenant = session.get("active_user_id")
    return render_template("admin.html", tenants=tenants, active_tenant=active_tenant)


# ---------------------------------------------------------------------------
# French admin routes (admin_fr_bp)
# ---------------------------------------------------------------------------


@admin_fr_bp.route("/login", methods=["GET", "POST"])
def login_fr():
    """Serve the French admin login page."""
    if request.method == "POST":
        if not _check_rate_limit("admin"):
            return render_template(
                "login_fr.html", error="Trop de tentatives. Veuillez réessayer plus tard.", now=datetime.now()
            )
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        expected_user = os.getenv("ADMIN_USERNAME")
        if hmac.compare_digest(username, expected_user) and check_password_hash(_get_admin_password_hash(), password):
            _record_attempt(True, "admin")
            session["admin_logged_in"] = True
            return redirect(url_for("admin_fr.panel_redirect_fr"))
        _record_attempt(False, "admin")
        return render_template(
            "login_fr.html",
            error="Nom d'utilisateur ou mot de passe invalide.",
            now=datetime.now(),
        )
    return render_template("login_fr.html", now=datetime.now())


@admin_fr_bp.route("/logout")
def logout_fr():
    """Log out from French admin and redirect to login."""
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_fr.login_fr"))


@admin_fr_bp.route("")
@admin_page_required_fr
def panel_redirect_fr():
    """Serve the French admin panel with session-based auth."""
    logo_status = request.args.get("logo_uploaded", "")
    tenants = {
        "direct_clients": database.list_users(role='user'),
    }
    active_tenant = session.get("active_user_id")
    return render_template(
        "admin_fr.html",
        logo_uploaded=logo_status,
        tenants=tenants,
        active_tenant=active_tenant,
    )


@admin_fr_bp.route("/agent/<agent_id>/chat")
@admin_page_required_fr
def agent_chat_fr(agent_id):
    """Serve the French admin agent chat interface."""
    from core.app_state import get_agent_registry, get_agent_meta
    agent_registry = get_agent_registry()
    AGENT_META = get_agent_meta()
    if agent_id not in agent_registry:
        return "Agent introuvable", 404
    return render_template(
        "admin/agent_chat_fr.html",
        agent_id=agent_id,
        agent=agent_registry[agent_id],
        agent_name=AGENT_META.get(agent_id, {}).get("name", agent_id),
    )


@admin_bp.route("/logo", methods=["POST"])
def logo():
    """Upload a logo file (PNG or SVG) to static/."""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin.login"))
    if "logo" not in request.files:
        return redirect(url_for("admin_fr.panel_redirect_fr", logo_uploaded="invalid"))
    file = request.files["logo"]
    if file.filename == "":
        return redirect(url_for("admin_fr.panel_redirect_fr", logo_uploaded="invalid"))
    ext = Path(file.filename).suffix.lower() if file.filename else ""
    if ext not in (".png", ".svg"):
        return redirect(url_for("admin_fr.panel_redirect_fr", logo_uploaded="invalid"))
    filename = secure_filename(f"logo{ext}")
    static_dir = Path(current_app.root_path) / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    file.save(str(static_dir / filename))
    return redirect(url_for("admin_fr.panel_redirect_fr", logo_uploaded="success"))
