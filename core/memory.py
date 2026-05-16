"""Agent memory and feedback system.

Stores user preferences, feedback from approvals (rejected/approved drafts),
and cross-agent findings so agents can learn from past interactions and
coordinate with each other.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentMemory:
    """Persistent memory for agent preferences, feedback, and findings.

    Uses the tenant's own database for storage.  Each tenant has its own
    feedback, preferences, and findings tables.
    """

    def __init__(self, tenant_manager) -> None:
        self._tm = tenant_manager
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create memory tables in the platform DB."""
        try:
            self._tm.create_tenant_database("_memory", "direct")
        except Exception:
            pass
        conn = self._tm.get_connection("_memory")
        cursor = conn.cursor()
        for ddl in [
            """CREATE TABLE IF NOT EXISTS agent_feedback (
                id TEXT PRIMARY KEY, tenant_id TEXT, agent_id TEXT,
                feedback_type TEXT, content TEXT, approved INTEGER,
                created_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS agent_preferences (
                id TEXT PRIMARY KEY, tenant_id TEXT, agent_id TEXT,
                pref_key TEXT, pref_value TEXT, updated_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS agent_findings (
                id TEXT PRIMARY KEY, tenant_id TEXT, source_agent TEXT,
                finding_type TEXT, summary TEXT, detail TEXT,
                created_at TEXT, expires_at TEXT
            )""",
        ]:
            cursor.execute(ddl)
        conn.commit()

    def _conn(self):
        return self._tm.get_connection("_memory")

    # ── Feedback ────────────────────────────────────────────────────

    def record_feedback(
        self, tenant_id: str, agent_id: str,
        feedback_type: str, content: str, approved: bool,
    ) -> None:
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO agent_feedback (id, tenant_id, agent_id, feedback_type, content, approved, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex[:12], tenant_id, agent_id, feedback_type, content[:500],
                 int(approved), datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except Exception as e:
            logger.warning("Failed to record feedback: %s", e)

    def get_feedback(self, tenant_id: str, agent_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT feedback_type, content, approved, created_at FROM agent_feedback "
                "WHERE tenant_id = ? AND agent_id = ? ORDER BY created_at DESC LIMIT ?",
                (tenant_id, agent_id, limit),
            )
            return [dict(r) for r in cursor.fetchall()]
        except Exception:
            return []

    def get_feedback_summary(self, tenant_id: str, agent_id: str) -> str:
        feedback = self.get_feedback(tenant_id, agent_id, 10)
        if not feedback:
            return ""
        parts = []
        for f in feedback:
            label = "approved" if f["approved"] else "rejected"
            parts.append(f"[{label}] {f['content'][:100]}")
        return "\n".join(parts)

    # ── Preferences ─────────────────────────────────────────────────

    def set_preference(self, tenant_id: str, agent_id: str, key: str, value: str) -> None:
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO agent_preferences (id, tenant_id, agent_id, pref_key, pref_value, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f"{tenant_id}:{agent_id}:{key}", tenant_id, agent_id, key, value,
                 datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except Exception as e:
            logger.warning("Failed to set preference: %s", e)

    def get_preferences(self, tenant_id: str, agent_id: str) -> Dict[str, str]:
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT pref_key, pref_value FROM agent_preferences WHERE tenant_id = ? AND agent_id = ?",
                (tenant_id, agent_id),
            )
            return {r["pref_key"]: r["pref_value"] for r in cursor.fetchall()}
        except Exception:
            return {}

    def get_preferences_prompt(self, tenant_id: str, agent_id: str) -> str:
        prefs = self.get_preferences(tenant_id, agent_id)
        if not prefs:
            return ""
        lines = [f"- {k}: {v}" for k, v in prefs.items()]
        return "User preferences for this agent:\n" + "\n".join(lines)

    # ── Cross-agent findings ────────────────────────────────────────

    def publish_finding(
        self, tenant_id: str, source_agent: str,
        finding_type: str, summary: str, detail: str = "",
    ) -> None:
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO agent_findings (id, tenant_id, source_agent, finding_type, summary, detail, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex[:12], tenant_id, source_agent, finding_type,
                 summary[:200], detail[:2000], datetime.now(timezone.utc).isoformat(),
                 (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()),
            )
            conn.commit()
        except Exception as e:
            logger.warning("Failed to publish finding: %s", e)

    def get_findings(self, tenant_id: str, finding_type: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            conn = self._conn()
            cursor = conn.cursor()
            if finding_type:
                cursor.execute(
                    "SELECT source_agent, finding_type, summary, detail, created_at FROM agent_findings "
                    "WHERE tenant_id = ? AND finding_type = ? ORDER BY created_at DESC LIMIT 20",
                    (tenant_id, finding_type),
                )
            else:
                cursor.execute(
                    "SELECT source_agent, finding_type, summary, detail, created_at FROM agent_findings "
                    "WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 20",
                    (tenant_id,),
                )
            return [dict(r) for r in cursor.fetchall()]
        except Exception:
            return []

    def get_findings_prompt(self, tenant_id: str) -> str:
        findings = self.get_findings(tenant_id)
        if not findings:
            return ""
        lines = ["Recent findings from other agents:"]
        for f in findings:
            lines.append(f"- [{f['source_agent']}] {f['summary']}")
        return "\n".join(lines)

    # ── Cleanup old findings ────────────────────────────────────────

    def cleanup_expired(self) -> None:
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM agent_findings WHERE expires_at < ?",
                           (datetime.now(timezone.utc).isoformat(),))
            conn.commit()
        except Exception:
            pass
