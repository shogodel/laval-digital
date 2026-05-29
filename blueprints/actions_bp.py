"""Blueprint for pending actions, SMS actions, and email bridge configuration."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, request, session
from flask_login import current_user

from core import database
from core.api_helpers import api_error, api_success
from core.app_state import (
    safe_error, safe_int,
)
from core.app_state import encrypt_credential
from core.auth import admin_required
from blueprints._shared import (
    _confirm_pending_action, _decrypt_credential, _email_bridge_handler,
    _email_bridge_lock, _get_email_bridge, _get_pending_actions,
    _safe_tenant_id, _set_email_bridge, _sms_lock,
)

logger = logging.getLogger(__name__)
actions_bp = Blueprint("actions", __name__)


@actions_bp.route("/api/actions/pending", methods=["GET"])
def api_pending_actions():
    tenant_id = session.get("active_user_id") or getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return api_success({"actions": []})
    actions = _get_pending_actions(tenant_id)
    return api_success({"actions": actions})


@actions_bp.route("/api/actions/sms-pending", methods=["GET"])
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


@actions_bp.route("/api/actions/<action_id>/confirm", methods=["POST"])
def api_confirm_action(action_id):
    tenant_id = session.get("active_user_id") or getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return api_error("No tenant context", 400)
    result = _confirm_pending_action(tenant_id, action_id)
    return api_success(result)


@actions_bp.route("/api/actions/sms-sent", methods=["POST"])
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
            logger.error("Silent exception in api_sms_mark_sent: %s", e)
    return api_success({"success": True})


@actions_bp.route("/api/actions/<action_id>/skip", methods=["POST"])
def api_skip_action(action_id):
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
        return safe_error(e, 500)


@actions_bp.route("/api/actions/bridge/email", methods=["POST"])
def api_set_email_bridge():
    from core.email_bridge import EmailBridge
    if not current_user.is_authenticated:
        return api_error("Unauthorized", 401)
    data = request.json
    if not data:
        return api_error("No data provided", 400)
    tenant_id = current_user.tenant_id
    settings = {
        "imap_host": data.get("imap_host", "imap.gmail.com"),
        "imap_port": int(data.get("imap_port", 993)),
        "username": data.get("email", ""),
        "password": encrypt_credential(data.get("password", "")),
    }
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE client_details SET email = ?, services = ? WHERE user_id = ?",
            (settings["username"], json.dumps({"email_bridge": settings}), safe_int(tenant_id)),
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
        return safe_error(e, 500)
