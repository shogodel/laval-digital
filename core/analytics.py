import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from core import database

logger = logging.getLogger(__name__)


class AnalyticsEngine:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self._cache: dict[str, tuple] = {}
        self._cache_ttl = timedelta(hours=1)
        self._lock = threading.Lock()

    def _cached(self, key: str, fn, *args, **kwargs):
        now = datetime.now(UTC)
        with self._lock:
            # Prune expired entries
            stale = [k for k, (_, ts) in self._cache.items() if now - ts >= self._cache_ttl]
            for k in stale:
                del self._cache[k]
            if key in self._cache:
                val, ts = self._cache[key]
                if now - ts < self._cache_ttl:
                    return val
        result = fn(*args, **kwargs)
        with self._lock:
            self._cache[key] = (result, now)
        return result

    def invalidate_cache(self):
        with self._lock:
            self._cache.clear()

    def _conn(self):
        """Return a fresh connection for each query to avoid thread-safety issues."""
        try:
            conn = database._get_conn()
            # Verify connection is usable
            conn.execute("SELECT 1")
            return conn
        except Exception as e:
            logger.debug("Analytics connection retry: %s", e)
            # Force a new connection if the current one is broken
            database.reset_conn()
            return database._get_conn()

    def _fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        try:
            cursor = self._conn().cursor()
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("Analytics query failed for user %s: %s", self.user_id, e)
            return []

    def _fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        try:
            cursor = self._conn().cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error("Analytics query failed for user %s: %s", self.user_id, e)
            return None

    # ── Metrics ─────────────────────────────────────────────────────

    def total_executions(self) -> int:
        row = self._fetchone(
            "SELECT COUNT(*) AS c FROM execution_log WHERE user_id = ?",
            (self.user_id,),
        )
        return row["c"] if row else 0

    def successful_executions(self) -> int:
        row = self._fetchone(
            "SELECT COUNT(*) AS c FROM execution_log WHERE user_id = ? AND success = 1",
            (self.user_id,),
        )
        return row["c"] if row else 0

    def failed_executions(self) -> int:
        row = self._fetchone(
            "SELECT COUNT(*) AS c FROM execution_log WHERE user_id = ? AND success = 0",
            (self.user_id,),
        )
        return row["c"] if row else 0

    def execution_success_rate(self) -> float:
        total = self.total_executions()
        if total == 0:
            return 0.0
        return round(self.successful_executions() / total * 100, 1)

    def total_leads(self) -> int:
        row = self._fetchone(
            "SELECT COUNT(*) AS c FROM leads WHERE user_id = ?",
            (self.user_id,),
        )
        return row["c"] if row else 0

    def get_performance_summary(self) -> dict[str, Any]:
        total = self.total_executions()
        success = self.successful_executions()
        failed = self.failed_executions()
        leads = self.total_leads()
        rate = self.execution_success_rate()
        return {
            "leads_this_month": leads,
            "tasks_this_month": total,
            "success_count": success,
            "fail_count": failed,
            "success_rate": rate,
            "active_agents": 0,
            "total_agents": 0,
        }

    def get_lead_metrics(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        total = self._fetchone(
            "SELECT COUNT(*) AS c FROM leads WHERE user_id = ? AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at <= ?)",
            (self.user_id, start_date, start_date, end_date, end_date),
        )
        by_status = self._fetchall(
            "SELECT status, COUNT(*) AS count FROM leads WHERE user_id = ? AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at <= ?) GROUP BY status",
            (self.user_id, start_date, start_date, end_date, end_date),
        )
        by_service = self._fetchall(
            "SELECT service, COUNT(*) AS count FROM leads WHERE user_id = ? AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at <= ?) AND service IS NOT NULL AND service != '' GROUP BY service",
            (self.user_id, start_date, start_date, end_date, end_date),
        )
        converted = self._fetchone(
            "SELECT COUNT(*) AS c FROM leads WHERE user_id = ? AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at <= ?) AND status IN ('converted', 'closed')",
            (self.user_id, start_date, start_date, end_date, end_date),
        )
        total_count = total["c"] if total else 0
        converted_count = converted["c"] if converted else 0
        conversion_rate = round(converted_count / total_count * 100, 1) if total_count else 0.0

        return {
            "total": total_count,
            "by_status": {r["status"]: r["count"] for r in by_status},
            "by_service": {r["service"]: r["count"] for r in by_service},
            "conversion_rate": conversion_rate,
            "converted": converted_count,
        }

    def get_agent_metrics(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        tasks_per_agent = self._fetchall(
            "SELECT agent_name, COUNT(*) AS total, SUM(success) AS success FROM execution_log WHERE user_id = ? AND (? IS NULL OR timestamp >= ?) AND (? IS NULL OR timestamp <= ?) GROUP BY agent_name ORDER BY total DESC",
            (self.user_id, start_date, start_date, end_date, end_date),
        )
        return {
            "tasks_per_agent": [
                {
                    "agent": r["agent_name"],
                    "total": r["total"],
                    "success": r["success"] or 0,
                    "fail": r["total"] - (r["success"] or 0),
                    "success_rate": round((r["success"] or 0) / r["total"] * 100, 1) if r["total"] else 0,
                }
                for r in tasks_per_agent
            ],
            "avg_response_time": 0,
        }

    def get_execution_metrics(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        stats = self._fetchone(
            "SELECT COUNT(*) AS total, SUM(success) AS success FROM execution_log WHERE user_id = ? AND (? IS NULL OR timestamp >= ?) AND (? IS NULL OR timestamp <= ?)",
            (self.user_id, start_date, start_date, end_date, end_date),
        )
        failures_by_tool = self._fetchall(
            "SELECT tool_name, COUNT(*) AS count FROM execution_log WHERE user_id = ? AND (? IS NULL OR timestamp >= ?) AND (? IS NULL OR timestamp <= ?) AND success = 0 AND tool_name IS NOT NULL AND tool_name != '' GROUP BY tool_name ORDER BY count DESC",
            (self.user_id, start_date, start_date, end_date, end_date),
        )
        total_count = stats["total"] if stats else 0
        success_count = stats["success"] if stats and stats["success"] else 0
        fail_count = total_count - success_count

        return {
            "total": total_count,
            "success_count": success_count,
            "fail_count": fail_count,
            "success_rate": round(success_count / total_count * 100, 1) if total_count else 0,
            "failures_by_tool": {r["tool_name"]: r["count"] for r in failures_by_tool},
        }

    def latest_executions(self, limit: int = 10) -> list[dict]:
        return self._fetchall(
            "SELECT * FROM execution_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (self.user_id, limit),
        )

    def execution_count_by_day(self, days: int = 30) -> list[dict]:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        return self._fetchall(
            """SELECT DATE(timestamp) AS day, COUNT(*) AS count
               FROM execution_log
               WHERE user_id = ? AND timestamp > ?
               GROUP BY day ORDER BY day""",
            (self.user_id, cutoff),
        )

    # ── Reporting ───────────────────────────────────────────────────

    def generate_monthly_report(self, year: int | None = None,
                                 month: int | None = None) -> dict[str, Any]:
        now = datetime.now(UTC)
        year = year or now.year
        month = month or now.month

        def _h(s):
            if s is None:
                return ""
            return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#x27;")

        start = f"{year}-{month:02d}-01"
        end = f"{year + 1}-01-01" if month == 12 else f"{year}-{month + 1:02d}-01"

        conn = self._conn()

        # Leads
        leads = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE user_id = ? AND created_at >= ? AND created_at < ?",
            (self.user_id, start, end),
        ).fetchone()
        lead_count = leads["c"] if leads else 0

        # Executions
        execs = conn.execute(
            "SELECT COUNT(*) AS c, SUM(success) AS s FROM execution_log WHERE user_id = ? AND timestamp >= ? AND timestamp < ?",
            (self.user_id, start, end),
        ).fetchone()
        exec_count = execs["c"] if execs else 0
        success_count = execs["s"] if execs and execs["s"] else 0

        # Agent breakdown
        agents = conn.execute(
            "SELECT agent_name, COUNT(*) AS c, SUM(success) AS s FROM execution_log WHERE user_id = ? AND timestamp >= ? AND timestamp < ? GROUP BY agent_name ORDER BY c DESC",
            (self.user_id, start, end),
        ).fetchall()

        business_name = ""
        agent_lines = "".join(
            f"<tr><td>{_h(a['agent_name'])}</td><td>{a['c']}</td><td>{a['s'] or 0}</td></tr>"
            for a in agents
        )

        html = f"""<html><body>
<h2>Monthly Report — {business_name or f'User {self.user_id}'}</h2>
<p>Period: {year}-{month:02d}</p>
<table border=1 cellpadding=4>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Total Leads</td><td>{lead_count}</td></tr>
<tr><td>Total Executions</td><td>{exec_count}</td></tr>
<tr><td>Successful</td><td>{success_count}</td></tr>
</table>
<h3>Agent Breakdown</h3>
<table border=1 cellpadding=4>
<tr><th>Agent</th><th>Executions</th><th>Success</th></tr>
{agent_lines}
</table></body></html>"""
        return {"html": html, "lead_count": lead_count,
                "exec_count": exec_count, "success_count": success_count}
