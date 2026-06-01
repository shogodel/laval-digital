"""Client blueprint — login, logout, dashboard, chat, analytics, managed services, API."""
import logging
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from core import database
from core.analytics import AnalyticsEngine
from core.api_helpers import api_success
from core.auth import User, _check_rate_limit, _record_attempt, client_required, find_user_by_email

logger = logging.getLogger(__name__)

client_bp = Blueprint("client", __name__, url_prefix="")


# ---------------------------------------------------------------------------
# Client auth routes
# ---------------------------------------------------------------------------


@client_bp.route("/client/login", methods=["GET", "POST"])
def client_login():
    """Serve client login page and authenticate."""
    if current_user.is_authenticated and current_user.role in ("client", "user"):
        return redirect(url_for("client.client_dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not _check_rate_limit("client"):
            flash("Too many login attempts. Try again later.", "error")
            return render_template("client/login.html")

        user_row = find_user_by_email(email)
        if not user_row or user_row["role"] != "user":
            _record_attempt(False, "client")
            flash("Invalid email or password.", "error")
            return render_template("client/login.html")

        temp_user = User(
            row_id=user_row["id"], email=user_row["email"],
            password_hash=user_row["password_hash"], role=user_row["role"],
            display_name=user_row["display_name"],
        )
        if not temp_user.check_password(password):
            _record_attempt(False, "client")
            flash("Invalid email or password.", "error")
            return render_template("client/login.html")

        login_user(temp_user)
        _record_attempt(True, "client")
        session["tenant_id"] = str(user_row["id"])
        session["user_role"] = "client"
        session["last_active"] = datetime.now().isoformat()

        try:
            conn = database._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.now().isoformat(), user_row["id"]),
            )
            conn.commit()
        except Exception:
            logger.warning("Failed to update login timestamp for client", exc_info=True)

        return redirect(url_for("client.client_dashboard"))

    return render_template("client/login.html")


@client_bp.route("/client/logout")
def client_logout():
    """Log out client and redirect to login."""
    logout_user()
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("client.client_login"))


# ---------------------------------------------------------------------------
# Client agent chat routes
# ---------------------------------------------------------------------------


@client_bp.route("/client/agent/<agent_id>/chat")
@client_required
def client_agent_chat(agent_id):
    """Serve the client agent chat interface."""
    from core.app_state import get_agent_meta, get_agent_registry
    agent_registry = get_agent_registry()
    agent_meta = get_agent_meta()
    if agent_id not in agent_registry:
        return "Agent not found", 404
    return render_template(
        "client/agent_chat.html",
        agent_id=agent_id,
        agent=agent_registry[agent_id],
        agent_name=agent_meta.get(agent_id, {}).get("name", agent_id),
    )


@client_bp.route("/fr/client/agent/<agent_id>/chat")
@client_required
def client_agent_chat_fr(agent_id):
    """Serve the French client agent chat interface."""
    from core.app_state import get_agent_meta, get_agent_registry
    agent_registry = get_agent_registry()
    agent_meta = get_agent_meta()
    if agent_id not in agent_registry:
        return "Agent introuvable", 404
    return render_template(
        "client/agent_chat_fr.html",
        agent_id=agent_id,
        agent=agent_registry[agent_id],
        agent_name=agent_meta.get(agent_id, {}).get("name", agent_id),
    )


# ---------------------------------------------------------------------------
# Client dashboard
# ---------------------------------------------------------------------------


@client_bp.route("/client/dashboard")
@client_required
def client_dashboard():
    """Serve the client project dashboard."""
    tenant_id = current_user.id

    payments = []
    total_paid = 0
    total_owed = 0
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM payments WHERE user_id = ? ORDER BY installment_number", (int(tenant_id),))
        for row in cursor.fetchall():
            p = dict(row)
            payments.append(p)
            if p.get("paid"):
                total_paid += p["amount"]
            else:
                total_owed += p["amount"]
    except Exception:
        logger.warning("Failed to load payment data for client dashboard", exc_info=True)

    site_url = None
    managed = False
    managed_since = None
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT site_url, managed_service, managed_since FROM client_details WHERE user_id = ?",
            (int(tenant_id),)
        )
        row = cursor.fetchone()
        if row:
            site_url = row["site_url"]
            managed = bool(row.get("managed_service", False))
            ms = row.get("managed_since")
            managed_since = ms[:10] if ms else None
    except Exception as e:
        logger.error("Silent exception in %s: %s", __name__, e)

    return render_template(
        "client/dashboard.html",
        payments=payments,
        total_paid=total_paid,
        total_owed=total_owed,
        site_url=site_url,
        project_status="Live" if site_url else "In Progress",
        active_agents=11,
        tasks_this_month=0,
        managed=managed,
        managed_since=managed_since,
    )


# ---------------------------------------------------------------------------
# Client analytics routes
# ---------------------------------------------------------------------------


@client_bp.route("/client/analytics")
@client_required
def client_analytics_page():
    """Serve the client analytics view."""
    return redirect(url_for("client.client_dashboard"))


@client_bp.route("/client/analytics/report")
@client_required
def client_analytics_report():
    """Generate and serve a printable monthly report for the client."""
    user_id = current_user.id
    engine = AnalyticsEngine(user_id)
    html = engine.generate_monthly_report()
    return html, 200, {"Content-Type": "text/html"}


# ---------------------------------------------------------------------------
# Managed Services routes
# ---------------------------------------------------------------------------


@client_bp.route("/client/managed-services")
@client_required
def client_managed_services():
    """Serve the managed services opt-in page."""
    tenant_id = current_user.tenant_id
    managed = False
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT managed_service FROM client_details WHERE user_id = ?",
            (int(tenant_id),)
        )
        row = cursor.fetchone()
        if row:
            managed = bool(row.get("managed_service", False))
    except Exception as e:
        logger.error("Silent exception in %s: %s", __name__, e)
    return render_template("client/managed_services.html", managed=managed)


# ---------------------------------------------------------------------------
# Client API routes
# ---------------------------------------------------------------------------


@client_bp.route("/api/client/threads")
@client_required
def api_client_list_threads():
    """List chat threads for the current client, optionally filtered by agent."""
    tenant_id = current_user.tenant_id
    agent_filter = request.args.get("agent", "")
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        if agent_filter:
            cursor.execute(
                ("SELECT thread_id, agent_task, created_at FROM threads "
                 "WHERE status = 'chat' AND routed_agent = ? AND user_id = ? "
                 "ORDER BY created_at DESC LIMIT 50"),
                (agent_filter, int(tenant_id)),
            )
        else:
            cursor.execute(
                "SELECT thread_id, agent_task, created_at FROM threads WHERE status = 'chat' AND user_id = ? ORDER BY created_at DESC LIMIT 50",
                (int(tenant_id),)
            )
        rows = cursor.fetchall()
        return api_success({
            "threads": [
                {"thread_id": r["thread_id"], "agent_task": r["agent_task"], "created_at": r["created_at"]}
                for r in rows
            ]
        })
    except Exception:
        logger.error("Failed to load client threads", exc_info=True)
        return api_success({"threads": []})


@client_bp.route("/api/client/threads/<thread_id>/messages")
@client_required
def api_client_get_thread_messages(thread_id):
    """Get all messages in a chat thread for the current client."""
    tenant_id = current_user.tenant_id
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT agent_task, agent_draft FROM threads WHERE thread_id = ? AND user_id = ? AND status = 'chat' ORDER BY created_at ASC",
            (thread_id, int(tenant_id)),
        )
        rows = cursor.fetchall()
        messages = []
        for r in rows:
            messages.append({"role": "user", "content": r["agent_task"]})
            messages.append({"role": "agent", "content": r["agent_draft"]})
        return api_success({"messages": messages})
    except Exception:
        logger.error("Failed to load client thread messages", exc_info=True)
        return api_success({"messages": []})
