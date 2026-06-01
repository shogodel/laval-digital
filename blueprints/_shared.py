import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core import database
from core.app_state import (
    get_executioner,
)

logger = logging.getLogger(__name__)

AGENT_PERSONALITIES = {
    "local_seo": {"emoji": "\U0001f4cd", "color": "#10b981", "short": "Local SEO", "short_fr": "SEO Local"},
    "social_media": {"emoji": "\U0001f4f1", "color": "#3b82f6", "short": "Social", "short_fr": "Sociaux"},
    "lead_conversion": {"emoji": "\U0001f3af", "color": "#f59e0b", "short": "Leads", "short_fr": "Prospects"},
    "paid_ads": {"emoji": "\U0001f4e2", "color": "#ef4444", "short": "Ads", "short_fr": "Annonces"},
    "growth_hacker": {"emoji": "\U0001f680", "color": "#8b5cf6", "short": "Growth", "short_fr": "Croissance"},
    "reputation": {"emoji": "\u2b50", "color": "#06b6d4", "short": "Reputation", "short_fr": "R\u00e9putation"},
    "email_marketing": {"emoji": "\u2709\ufe0f", "color": "#ec4899", "short": "Email", "short_fr": "Courriel"},
    "tiktok": {"emoji": "\U0001f3ac", "color": "#14b8a6", "short": "TikTok", "short_fr": "TikTok"},
    "outreach": {"emoji": "\U0001f91d", "color": "#f97316", "short": "Outreach", "short_fr": "Prospection"},
    "backlinks": {"emoji": "\U0001f517", "color": "#6366f1", "short": "Backlinks", "short_fr": "Liens"},
    "content_strategy": {"emoji": "\U0001f4dd", "color": "#84cc16", "short": "Content", "short_fr": "Contenu"},
    "technical_seo": {"emoji": "\u2699\ufe0f", "color": "#06b6d4", "short": "Tech SEO", "short_fr": "SEO Tech"},
    "reporting": {"emoji": "\U0001f4ca", "color": "#a855f7", "short": "Reports", "short_fr": "Rapports"},
    "cro": {"emoji": "\U0001f4d0", "color": "#f43f5e", "short": "CRO", "short_fr": "CRO"},
    "video": {"emoji": "\U0001f3a5", "color": "#eab308", "short": "Video", "short_fr": "Vid\u00e9o"},
    "sms_marketing": {"emoji": "\U0001f4ac", "color": "#06b6d4", "short": "SMS", "short_fr": "SMS"},
    "executioner": {"emoji": "\u26a1", "color": "#64748b", "short": "Execute", "short_fr": "Ex\u00e9cution"},
}

MANAGED_MONTHLY_FEE = int(os.getenv("MANAGED_MONTHLY_FEE", "499"))

_sms_lock = threading.Lock()
_email_bridge_instance = None
_email_bridge_lock = threading.RLock()


def _decrypt_credential(ciphertext: str) -> str:
    from core.app_state import get_credential_cipher
    return get_credential_cipher().decrypt(ciphertext.encode()).decode()


def _safe_tenant_id(tenant_id: str) -> Optional[int]:
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
        from agents.executioner_agent import ExecutionerError
        try:
            exec_result = get_executioner().execute(row["agent_name"], row["content"], tool_name=row["tool_name"])
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
                logger.error("Silent exception in email_bridge_handler: %s", e)


def _get_email_bridge():
    from core.email_bridge import EmailBridge
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
