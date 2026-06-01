import logging
import uuid
from datetime import datetime, timedelta, UTC
from typing import Any, Optional

from core import database

logger = logging.getLogger(__name__)


class AgentMemory:
    def __init__(self):
        pass

    def _conn(self):
        return database._get_conn()

    # ── Feedback ────────────────────────────────────────────────────

    def record_feedback(self, user_id: int, agent_id: str, feedback_type: str,
                        content: str, approved: Optional[bool] = None) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT INTO agent_feedback (id, user_id, agent_id, feedback_type, content, approved, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (uuid.uuid4().hex, user_id, agent_id, feedback_type, content,
             int(approved) if approved is not None else None,
             datetime.now(UTC).isoformat()),
        )
        conn.commit()

    def get_feedback(self, user_id: int, agent_id: str,
                     limit: int = 20) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM agent_feedback WHERE user_id = ? AND agent_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, agent_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_feedback_summary(self, user_id: int, agent_id: str) -> str:
        feedback = self.get_feedback(user_id, agent_id, 10)
        if not feedback:
            return "No feedback available."
        parts = []
        for f in feedback:
            status = "approved" if f.get("approved") else "rejected" if f.get("approved") == 0 else "info"
            parts.append(f"[{f['created_at'][:10]}] ({status}) {f.get('content', '')[:200]}")
        return "\n".join(parts)

    # ── Preferences ─────────────────────────────────────────────────

    def set_preference(self, user_id: int, agent_id: str, key: str, value: str) -> None:
        conn = self._conn()
        now = datetime.now(UTC).isoformat()
        pref_id = f"{user_id}|{agent_id}|{key}"
        conn.execute(
            """INSERT INTO agent_preferences (id, user_id, agent_id, pref_key, pref_value, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET pref_value = ?, updated_at = ?""",
            (pref_id, user_id, agent_id, key, value, now, value, now),
        )
        conn.commit()

    def get_preferences(self, user_id: int, agent_id: str) -> dict[str, str]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT pref_key, pref_value FROM agent_preferences WHERE user_id = ? AND agent_id = ?",
            (user_id, agent_id),
        ).fetchall()
        return {r["pref_key"]: r["pref_value"] for r in rows}

    def get_preferences_prompt(self, user_id: int, agent_id: str) -> str:
        prefs = self.get_preferences(user_id, agent_id)
        if not prefs:
            return ""
        lines = [f"- {k}: {v}" for k, v in prefs.items()]
        return "User preferences:\n" + "\n".join(lines)

    # ── Findings ────────────────────────────────────────────────────

    def publish_finding(self, user_id: int, source_agent: str, finding_type: str,
                        summary: str, detail: str = "") -> None:
        now = datetime.now(UTC).isoformat()
        expires = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        conn = self._conn()
        conn.execute(
            """INSERT INTO agent_findings (id, user_id, source_agent, finding_type, summary, detail, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (uuid.uuid4().hex, user_id, source_agent, finding_type, summary, detail, now, expires),
        )
        conn.commit()

    def get_findings(self, user_id: int,
                     finding_type: Optional[str] = None) -> list[dict[str, Any]]:
        conn = self._conn()
        now = datetime.now(UTC).isoformat()
        if finding_type:
            rows = conn.execute(
                "SELECT * FROM agent_findings WHERE user_id = ? AND finding_type = ? AND expires_at > ? ORDER BY created_at DESC",
                (user_id, finding_type, now),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_findings WHERE user_id = ? AND expires_at > ? ORDER BY created_at DESC",
                (user_id, now),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_findings_prompt(self, user_id: int) -> str:
        findings = self.get_findings(user_id)
        if not findings:
            return ""
        parts = ["Cross-agent findings:"]
        for f in findings:
            parts.append(f"- [{f['finding_type']}] {f['summary']}")
        return "\n".join(parts)
