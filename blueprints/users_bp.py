"""Blueprint for user and tenant management (admin-only)."""
import logging
import re
from datetime import UTC, datetime

from flask import Blueprint, request, session
from flask_login import current_user

from core import database
from core.api_helpers import api_error, api_success
from core.database import export_user_data
from core.app_state import get_current_user_id, safe_error, safe_int
from core.auth import add_user_to_tenant, validate_password

logger = logging.getLogger(__name__)
users_bp = Blueprint("users", __name__)


@users_bp.route("/api/users", methods=["GET"])
def api_list_users():
    tenant_id = session.get("active_user_id")
    role_filter = request.args.get("role", "").strip().lower()
    limit = min(safe_int(request.args.get("limit", "100"), 100), 500)
    offset = max(safe_int(request.args.get("offset", "0"), 0), 0)

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        if tenant_id:
            if role_filter == "user":
                cursor.execute(
                    "SELECT id, email, display_name, role, created_at, last_login "
                    "FROM users WHERE (id = ? OR tenant_id = ?) AND role = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (safe_int(tenant_id), safe_int(tenant_id), role_filter, limit, offset),
                )
            else:
                cursor.execute(
                    "SELECT id, email, display_name, role, created_at, last_login "
                    "FROM users WHERE id = ? OR tenant_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (safe_int(tenant_id), safe_int(tenant_id), limit, offset),
                )
        else:
            if role_filter == "user":
                cursor.execute(
                    "SELECT id, email, display_name, role, created_at, last_login "
                    "FROM users WHERE role = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (role_filter, limit, offset),
                )
            else:
                cursor.execute(
                    "SELECT id, email, display_name, role, created_at, last_login "
                    "FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
        users = [dict(row) for row in cursor.fetchall()]
        return api_success({"users": users, "limit": limit, "offset": offset})
    except Exception as e:
        return safe_error(e, 500)


@users_bp.route("/api/users", methods=["POST"])
def api_add_user():
    data = request.json or {}
    email = (data.get("email") or "").strip()
    password = data.get("password", "")
    role = data.get("role", "user")
    display_name = (data.get("display_name") or "").strip()

    if role != "user":
        return api_error("Invalid role. Must be 'user'.", 400)

    if not email or not password:
        return api_error("Email and password are required", 400)

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return api_error("Invalid email format.", 400)

    is_valid, err_msg = validate_password(password)
    if not is_valid:
        return api_error(err_msg, 400)

    tenant_id = session.get("active_user_id")

    try:
        result = add_user_to_tenant(email, password, role, display_name, tenant_id or "")
        return api_success(result, status_code=201)
    except ValueError as e:
        return safe_error(e, 400)
    except RuntimeError as e:
        return safe_error(e, 500)


@users_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
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
        return safe_error(e, 500)


@users_bp.route("/api/tenants", methods=["GET"])
def list_tenants():
    direct = [str(u["id"]) for u in database.list_users(role='user')]
    return api_success({
        "direct_clients": direct,
        "active_tenant": session.get("active_user_id"),
    })


@users_bp.route("/api/user/export", methods=["GET"])
def api_export_user_data():
    """Return all personal data for the current user (GDPR/CCPA data portability)."""
    uid = get_current_user_id()
    if not uid:
        return api_error("Not authenticated", 401)
    try:
        data = export_user_data(int(uid))
        return api_success({"exported_at": datetime.now(UTC).isoformat(), "data": data})
    except Exception as e:
        return safe_error(e, 500)


@users_bp.route("/api/user/export", methods=["DELETE"])
def api_delete_user_data():
    """Delete all personal data for the current user (GDPR right to erasure)."""
    uid = get_current_user_id()
    if not uid:
        return api_error("Not authenticated", 401)
    try:
        database.delete_user(int(uid))
        return api_success({"message": "All personal data has been deleted"})
    except Exception as e:
        return safe_error(e, 500)


@users_bp.route("/api/tenants/switch", methods=["POST"])
def switch_tenant():
    data = request.json or {}
    tenant_id = data.get("tenant_id")

    if tenant_id:
        session["active_user_id"] = tenant_id
        logger.info("Admin '%s' switched to tenant %s", current_user.id, tenant_id)
        return api_success({
            "active_tenant": tenant_id,
            "message": f"Switched to {tenant_id}",
        })
    else:
        cleared = session.pop("active_user_id", None)
        if cleared:
            logger.info("Admin '%s' cleared tenant %s", current_user.id, cleared)
        return api_success({
            "active_tenant": None,
            "message": "Client cleared",
        })
