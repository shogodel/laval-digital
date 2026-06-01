"""Admin blueprint — login, logout, panel, dashboard, connector, analytics, reports, managed."""
import hmac
import logging
import os
from datetime import datetime
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user
from werkzeug.security import check_password_hash

from core import database
from core.auth import AdminUser, _check_rate_limit, _record_attempt, admin_page_required

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
logger = logging.getLogger(__name__)
admin_fr_bp = Blueprint("admin_fr", __name__, url_prefix="/fr/admin")


@admin_bp.context_processor
def inject_logo():
    return {"logo_file": "logo.svg"}


@admin_fr_bp.context_processor
def inject_logo_fr():
    return {"logo_file": "logo.svg"}

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
        if not (current_user.is_authenticated and current_user.role == "admin"):
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
            login_user(AdminUser("admin"))
            return redirect(url_for("admin.panel"))
        _record_attempt(False, "admin")
        return render_template(
            "login.html", error="Invalid username or password.", now=datetime.now()
        )
    return render_template("login.html", now=datetime.now())


@admin_bp.route("/logout")
def logout():
    """Log out and redirect to login."""
    logout_user()
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
    tenants = {
        "direct_clients": database.list_users(role='user'),
    }
    active_tenant = session.get("active_user_id")
    return render_template(
        "admin.html",
        tenants=tenants,
        active_tenant=active_tenant,
        locale="en",
    )


@admin_bp.route("/agent/<agent_id>/chat")
def agent_chat(agent_id):
    """Serve the admin agent chat interface."""
    auth_check = admin_page_required()
    if auth_check:
        return auth_check
    from core.app_state import get_agent_meta, get_agent_registry
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
        flash("Select a client first to configure the connector.", "warning")
        return redirect(url_for("admin.panel"))
    _allowed_hosts = {"lavaldigital.ca", "www.lavaldigital.ca", "127.0.0.1:5000", "localhost:5000"}
    if request.host not in _allowed_hosts:
        logger.warning("Blocked connector page access from untrusted host: %s", request.host)
        flash("Cannot generate bookmarklet from this host.", "error")
        return redirect(url_for("admin.panel"))
    base_url = f"{request.scheme}://{request.host}"
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
    return render_template("admin.html", tenants=tenants, active_tenant=active_tenant, default_tab="analytics", locale="en")


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
    return render_template("admin.html", tenants=tenants, active_tenant=active_tenant, default_tab="reports", locale="en")


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
    return render_template("admin.html", tenants=tenants, active_tenant=active_tenant, default_tab="managed", locale="en")


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
            login_user(AdminUser("admin"))
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
    logout_user()
    return redirect(url_for("admin_fr.login_fr"))


@admin_fr_bp.route("")
@admin_page_required_fr
def panel_redirect_fr():
    """Serve the French admin panel with session-based auth."""
    tenants = {
        "direct_clients": database.list_users(role='user'),
    }
    active_tenant = session.get("active_user_id")
    return render_template(
        "admin.html",
        tenants=tenants,
        active_tenant=active_tenant,
        locale="fr",
    )


@admin_fr_bp.route("/agent/<agent_id>/chat")
@admin_page_required_fr
def agent_chat_fr(agent_id):
    """Serve the French admin agent chat interface."""
    from core.app_state import get_agent_meta, get_agent_registry
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


@admin_fr_bp.route("/dashboard")
@admin_page_required_fr
def dashboard_fr():
    """Serve the real-time agent dashboard (French)."""
    from core.app_state import get_agent_meta
    return render_template("admin/dashboard.html", agents=get_agent_meta())


@admin_fr_bp.route("/connector")
@admin_page_required_fr
def connector_fr():
    """Serve the connector setup page (French)."""
    tenant_id = session.get("active_user_id")
    if not tenant_id:
        flash("Sélectionnez d'abord un client pour configurer le connecteur.", "warning")
        return redirect(url_for("admin_fr.panel_redirect_fr"))
    _allowed_hosts = {"lavaldigital.ca", "www.lavaldigital.ca", "127.0.0.1:5000", "localhost:5000"}
    if request.host not in _allowed_hosts:
        logger.warning("Blocked FR connector page access from untrusted host: %s", request.host)
        flash("Impossible de générer le bookmarklet depuis cet hôte.", "error")
        return redirect(url_for("admin_fr.panel_redirect_fr"))
    base_url = f"{request.scheme}://{request.host}"
    bookmarklet_code = (
        'javascript:(function(){var s=document.createElement("script");'
        f's.src="{base_url}/static/bookmarklet.js";'
        "document.body.appendChild(s);})()"
    )
    return render_template("admin/connector.html", bookmarklet_code=bookmarklet_code, tenant_id=tenant_id)


@admin_fr_bp.route("/analytics")
@admin_page_required_fr
def analytics_fr():
    """Serve the analytics dashboard (French SPA)."""
    tenants = {"direct_clients": database.list_users(role='user')}
    active_tenant = session.get("active_user_id")
    return render_template("admin.html", tenants=tenants, active_tenant=active_tenant, default_tab="analytics", locale="fr")


@admin_fr_bp.route("/reports")
@admin_page_required_fr
def reports_fr():
    """Serve the reports page (French SPA)."""
    tenants = {"direct_clients": database.list_users(role='user')}
    active_tenant = session.get("active_user_id")
    return render_template("admin.html", tenants=tenants, active_tenant=active_tenant, default_tab="reports", locale="fr")


@admin_fr_bp.route("/managed")
@admin_page_required_fr
def managed_fr():
    """Serve the managed clients page (French SPA)."""
    tenants = {"direct_clients": database.list_users(role='user')}
    active_tenant = session.get("active_user_id")
    return render_template("admin.html", tenants=tenants, active_tenant=active_tenant, default_tab="managed", locale="fr")



