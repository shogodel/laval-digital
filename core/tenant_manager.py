"""Compatibility shim — delegates all calls to the single database.

This file is a temporary wrapper so app.py and other modules don't
need to be rewritten all at once.  All methods now operate on the
single data/frankie.db instead of per-tenant database files.
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from core import database

logger = logging.getLogger(__name__)

DEFAULT_AGENTS = [
    "local_seo", "social_media", "lead_conversion", "paid_ads",
    "growth_hacker", "reputation", "email_marketing", "tiktok",
    "outreach", "backlinks", "executioner",
    "content_strategy", "technical_seo", "reporting",
    "cro", "video", "sms_marketing",
]


class TenantManager:
    def __init__(self, base_path: str = "tenants") -> None:
        pass

    def _conn(self) -> sqlite3.Connection:
        return database._get_conn()

    def _get_db_path(self, tenant_id: str, tenant_type: str = "direct") -> Path:
        return Path("data") / "frankie.db"

    def create_tenant_database(self, tenant_id: str,
                               tenant_type: str = "direct") -> str:
        return str(Path("data") / "frankie.db")

    def get_connection(self, tenant_id: str,
                       tenant_type: str = "direct") -> sqlite3.Connection:
        return self._conn()

    def close_connection(self, tenant_id: str,
                         tenant_type: str = "direct") -> None:
        pass

    def list_tenants(self, tenant_type: str = "direct") -> List[str]:
        if tenant_type == "direct":
            rows = self._conn().execute(
                "SELECT id FROM users WHERE role IN ('user', 'admin')"
            ).fetchall()
            return [str(r["id"]) for r in rows]
        return []

    def delete_tenant(self, tenant_id: str,
                      tenant_type: str = "direct") -> bool:
        return False

    def cleanup_stale_connections(self, max_idle_minutes: int = 30) -> int:
        return 0

    def _get_user_id(self, tenant_id: str) -> int:
        try:
            return int(tenant_id)
        except (ValueError, TypeError):
            return 0

    # ── Agent autonomy methods ────────────────────────────────────────

    def get_agent_autonomy(self, tenant_id: str) -> Dict[str, Dict[str, Any]]:
        """Return autonomy settings for all agents belonging to a user."""
        uid = self._get_user_id(tenant_id)
        rows = self._conn().execute(
            "SELECT agent_id, autonomy, confidence_threshold FROM agent_configs WHERE user_id = ?",
            (uid,),
        ).fetchall()
        return {
            r["agent_id"]: {
                "autonomy": r["autonomy"],
                "confidence_threshold": r["confidence_threshold"],
            }
            for r in rows
        }

    def set_agent_autonomy(self, tenant_id: str, agent_id: str,
                           autonomy: str, threshold: float) -> None:
        """Set autonomy and confidence threshold for a user's agent."""
        uid = self._get_user_id(tenant_id)
        self._conn().execute(
            "UPDATE agent_configs SET autonomy = ?, confidence_threshold = ? WHERE user_id = ? AND agent_id = ?",
            (autonomy, threshold, uid, agent_id),
        )
        self._conn().commit()
