import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from core import database

logger = logging.getLogger(__name__)


class AnalyticsEngine:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self._cache: Dict[str, tuple] = {}
        self._cache_ttl = timedelta(hours=1)
        self._lock = threading.Lock()

    def _cached(self, key: str, fn, *args, **kwargs):
        now = datetime.now()
        with self._lock:
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
        except Exception:
            # Force a new connection if the current one is broken
            database._local.conn = None
            return database._get_conn()

    def _fetchall(self, sql: str, params: tuple = ()) -> List[dict]:
        try:
            cursor = self._conn().cursor()
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("Analytics query failed for user %s: %s", self.user_id, e)
            return []

    def _fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
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

    def latest_executions(self, limit: int = 10) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM execution_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (self.user_id, limit),
        )

    def execution_count_by_day(self, days: int = 30) -> List[dict]:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return self._fetchall(
            """SELECT DATE(timestamp) AS day, COUNT(*) AS count
               FROM execution_log
               WHERE user_id = ? AND timestamp > ?
               GROUP BY day ORDER BY day""",
            (self.user_id, cutoff),
        )

    # ── Reporting ───────────────────────────────────────────────────

    def generate_monthly_report(self, year: Optional[int] = None,
                                 month: Optional[int] = None) -> Dict[str, Any]:
        from datetime import timezone as dt_timezone
        now = datetime.now(dt_timezone.utc)
        year = year or now.year
        month = month or now.month

        def _h(s):
            if s is None:
                return ""
            return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        start = f"{year}-{month:02d}-01"
        if month == 12:
            end = f"{year + 1}-01-01"
        else:
            end = f"{year}-{month + 1:02d}-01"

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

        # Business info
        biz = conn.execute(
            "SELECT business_name FROM client_details WHERE user_id = ? LIMIT 1",
            (self.user_id,),
        ).fetchone()
        business_name = _h(biz["business_name"] if biz else "")

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
