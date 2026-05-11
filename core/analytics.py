import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class AnalyticsEngine:
    """Per-tenant analytics engine with caching.

    Reads from the tenant database (leads, execution_log, threads, agents
    tables) and computes key performance metrics.

    Results are cached in-memory with a 1-hour TTL.
    """

    def __init__(self, tenant_id: str, tenant_manager, tenant_type: str = "direct",
                 reseller_id: Optional[str] = None):
        self.tenant_id = tenant_id
        self.tm = tenant_manager
        self.tenant_type = tenant_type
        self.reseller_id = reseller_id
        self._cache: Dict[str, tuple] = {}
        self._cache_ttl = timedelta(hours=1)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cached(self, key: str, fn, *args, **kwargs):
        """Return cached value or compute and cache."""
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
        """Clear all cached analytics for this tenant."""
        with self._lock:
            self._cache.clear()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _conn(self):
        """Get the tenant database connection."""
        return self.tm.get_connection(
            self.tenant_id, self.tenant_type, self.reseller_id
        )

    def _fetchall(self, sql: str, params: tuple = ()) -> List[dict]:
        try:
            cursor = self._conn().cursor()
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("Analytics query failed for %s: %s", self.tenant_id, e)
            return []

    def _fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        try:
            cursor = self._conn().cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error("Analytics query failed for %s: %s", self.tenant_id, e)
            return None

    # ------------------------------------------------------------------
    # Lead metrics
    # ------------------------------------------------------------------

    def get_lead_metrics(self, start_date: Optional[str] = None,
                         end_date: Optional[str] = None) -> dict:
        """Return lead capture and conversion metrics.

        Args:
            start_date: ISO date string (default: first of current month).
            end_date: ISO date string (default: today).

        Returns:
            Dict with total_leads, leads_by_source, leads_by_urgency,
            conversion_rate.
        """
        return self._cached("lead_metrics", self._compute_lead_metrics,
                            start_date, end_date)

    def _compute_lead_metrics(self, start_date, end_date) -> dict:
        if not start_date:
            start_date = datetime.now().replace(day=1).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        rows = self._fetchall(
            """SELECT id, name, service, urgency, status, created_at
               FROM leads WHERE DATE(created_at) >= ? AND DATE(created_at) <= ?
               ORDER BY created_at DESC""",
            (start_date, end_date),
        )

        total = len(rows)
        by_service: Dict[str, int] = {}
        by_urgency: Dict[str, int] = {}
        converted = 0

        for r in rows:
            svc = (r.get("service") or "Unknown").strip()
            by_service[svc] = by_service.get(svc, 0) + 1

            urg = (r.get("urgency") or "Unknown").strip()
            by_urgency[urg] = by_urgency.get(urg, 0) + 1

            if r.get("status") in ("converted", "client", "won"):
                converted += 1

        # Also count contract submissions as leads
        contracts = self._fetchall(
            """SELECT id, created_at FROM client_details
               WHERE DATE(created_at) >= ? AND DATE(created_at) <= ?""",
            (start_date, end_date),
        )

        return {
            "total_leads": total + len(contracts),
            "leads_by_source": by_service,
            "leads_by_urgency": by_urgency,
            "conversion_rate": round((converted / total * 100) if total else 0, 1),
            "period": {"start": start_date, "end": end_date},
        }

    # ------------------------------------------------------------------
    # Agent metrics
    # ------------------------------------------------------------------

    def get_agent_metrics(self, start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> dict:
        """Return per-agent performance metrics.

        Returns:
            Dict with tasks_per_agent (list), success_rate_per_agent,
            avg_response_time, most_active_agent.
        """
        return self._cached("agent_metrics", self._compute_agent_metrics,
                            start_date, end_date)

    def _compute_agent_metrics(self, start_date, end_date) -> dict:
        if not start_date:
            start_date = datetime.now().replace(day=1).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        rows = self._fetchall(
            """SELECT agent_name, success, COUNT(*) as count
               FROM execution_log
               WHERE DATE(timestamp) >= ? AND DATE(timestamp) <= ?
               GROUP BY agent_name, success
               ORDER BY agent_name""",
            (start_date, end_date),
        )

        agent_stats: Dict[str, dict] = {}
        for r in rows:
            agent = r["agent_name"] or "unknown"
            if agent not in agent_stats:
                agent_stats[agent] = {"total": 0, "success": 0, "fail": 0}
            agent_stats[agent]["total"] += r["count"]
            if r["success"]:
                agent_stats[agent]["success"] += r["count"]
            else:
                agent_stats[agent]["fail"] += r["count"]

        tasks_per_agent = []
        most_active = ("", 0)
        for agent, stats in agent_stats.items():
            sr = round((stats["success"] / stats["total"] * 100) if stats["total"] else 0, 1)
            tasks_per_agent.append({
                "agent": agent,
                "total": stats["total"],
                "success": stats["success"],
                "fail": stats["fail"],
                "success_rate": sr,
            })
            if stats["total"] > most_active[1]:
                most_active = (agent, stats["total"])

        # Agent status from agents table
        agent_rows = self._fetchall(
            "SELECT agent_id, status, task_count FROM agents"
        )

        return {
            "tasks_per_agent": tasks_per_agent,
            "success_rate_per_agent": {a["agent"]: a["success_rate"]
                                       for a in tasks_per_agent},
            "avg_response_time": self._estimate_response_time(agent_rows),
            "most_active_agent": most_active[0],
            "agent_statuses": {r["agent_id"]: r["status"] for r in agent_rows},
        }

    def _estimate_response_time(self, agent_rows: list) -> float:
        """Estimate average response time from task_count distribution."""
        active = [r for r in agent_rows if r.get("status") in ("processing", "idle")]
        total_tasks = sum(r.get("task_count", 0) for r in active)
        if not total_tasks:
            return 0
        return round(total_tasks / len(active), 1) if active else 0

    # ------------------------------------------------------------------
    # Execution metrics
    # ------------------------------------------------------------------

    def get_execution_metrics(self, start_date: Optional[str] = None,
                              end_date: Optional[str] = None) -> dict:
        """Return execution tracking metrics.

        Returns:
            Dict with total_executions, success_rate, failures_by_tool,
            avg_retries.
        """
        return self._cached("execution_metrics", self._compute_execution_metrics,
                            start_date, end_date)

    def _compute_execution_metrics(self, start_date, end_date) -> dict:
        if not start_date:
            start_date = datetime.now().replace(day=1).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        rows = self._fetchall(
            """SELECT id, agent_name, tool_name, success, error, timestamp
               FROM execution_log
               WHERE DATE(timestamp) >= ? AND DATE(timestamp) <= ?
               ORDER BY timestamp DESC""",
            (start_date, end_date),
        )

        total = len(rows)
        success_count = sum(1 for r in rows if r["success"])
        fail_count = total - success_count

        failures_by_tool: Dict[str, int] = {}
        for r in rows:
            if not r["success"]:
                tool = r.get("tool_name") or "unknown"
                failures_by_tool[tool] = failures_by_tool.get(tool, 0) + 1

        return {
            "total_executions": total,
            "success_count": success_count,
            "fail_count": fail_count,
            "success_rate": round((success_count / total * 100) if total else 0, 1),
            "failures_by_tool": failures_by_tool,
            "avg_retries": round(fail_count / total * 100, 1) if total else 0,
            "recent": rows[:20],
        }

    # ------------------------------------------------------------------
    # Performance summary
    # ------------------------------------------------------------------

    def get_performance_summary(self) -> dict:
        """Return a high-level performance snapshot for a dashboard card.

        Returns:
            Dict with leads_this_month, tasks_this_month, active_agents,
            uptime_percentage.
        """
        now = datetime.now()
        start = now.replace(day=1).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")

        lead_metrics = self.get_lead_metrics(start, end)
        agent_metrics = self.get_agent_metrics(start, end)
        exec_metrics = self.get_execution_metrics(start, end)

        active_count = sum(
            1 for s in agent_metrics.get("agent_statuses", {}).values()
            if s in ("idle", "processing")
        )

        # Count threads as tasks this month
        thread_rows = self._fetchall(
            """SELECT COUNT(*) as cnt FROM threads
               WHERE DATE(created_at) >= ? AND DATE(created_at) <= ?""",
            (start, end),
        )
        thread_count = thread_rows[0]["cnt"] if thread_rows else 0

        tasks_total = thread_count + exec_metrics.get("total_executions", 0)

        return {
            "leads_this_month": lead_metrics.get("total_leads", 0),
            "conversion_rate": lead_metrics.get("conversion_rate", 0),
            "tasks_this_month": tasks_total,
            "executions_this_month": exec_metrics.get("total_executions", 0),
            "active_agents": active_count,
            "total_agents": len(agent_metrics.get("agent_statuses", {})),
            "success_rate": exec_metrics.get("success_rate", 0),
            "most_active_agent": agent_metrics.get("most_active_agent", ""),
        }

    # ------------------------------------------------------------------
    # Cross-tenant admin metrics
    # ------------------------------------------------------------------

    def get_admin_summary(self, all_tenants: list) -> dict:
        """Aggregate metrics across multiple tenants for admin dashboard.

        Args:
            all_tenants: List of tenant_id strings (direct clients).

        Returns:
            Dict with total_clients, total_leads, total_tasks,
            avg_success_rate, per_client breakdown.
        """
        total_leads = 0
        total_tasks = 0
        total_executions = 0
        total_success_rate = 0
        client_count = len(all_tenants)
        per_client = []

        for tid in all_tenants:
            engine = AnalyticsEngine(tid, self.tm)
            summary = engine.get_performance_summary()
            total_leads += summary.get("leads_this_month", 0)
            total_tasks += summary.get("tasks_this_month", 0)
            total_executions += summary.get("executions_this_month", 0)
            total_success_rate += summary.get("success_rate", 0)
            per_client.append({
                "tenant_id": tid,
                "leads": summary.get("leads_this_month", 0),
                "tasks": summary.get("tasks_this_month", 0),
                "success_rate": summary.get("success_rate", 0),
                "active_agents": summary.get("active_agents", 0),
            })

        return {
            "total_clients": client_count,
            "total_leads": total_leads,
            "total_tasks": total_tasks,
            "avg_success_rate": round(total_success_rate / client_count, 1)
                                 if client_count else 0,
            "per_client": per_client,
        }

    # ------------------------------------------------------------------
    # Monthly report
    # ------------------------------------------------------------------

    def generate_monthly_report(self, year: Optional[int] = None,
                                month: Optional[int] = None) -> str:
        """Generate an HTML monthly report string.

        Args:
            year: 4-digit year (default: current year).
            month: 1-12 (default: previous month).

        Returns:
            HTML string suitable for printing or emailing.
        """
        now = datetime.now()
        if year is None:
            year = now.year
        if month is None:
            month = now.month - 1 if now.month > 1 else 12
            if month == 12:
                year -= 1

        start_date = f"{year}-{month:02d}-01"
        if month == 12:
            end_date = f"{year}-12-31"
        else:
            end_date = f"{year}-{month + 1:02d}-01"
            from datetime import date as dt_date
            import calendar
            last_day = calendar.monthrange(year, month)[1]
            end_date = f"{year}-{month:02d}-{last_day}"

        lead_m = self.get_lead_metrics(start_date, end_date)
        agent_m = self.get_agent_metrics(start_date, end_date)
        exec_m = self.get_execution_metrics(start_date, end_date)
        summary = self.get_performance_summary()

        # Get business name
        biz_row = self._fetchone(
            "SELECT business_name FROM client_details LIMIT 1"
        )
        business_name = biz_row["business_name"] if biz_row else self.tenant_id

        month_name = datetime(year, month, 1).strftime("%B %Y")

        # Build agent activity rows
        agent_rows_html = ""
        for a in agent_m.get("tasks_per_agent", []):
            agent_rows_html += f"""
            <tr>
                <td style="padding:6px 10px;border-bottom:1px solid #e5e7eb;">{a['agent']}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #e5e7eb;text-align:center;">{a['total']}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #e5e7eb;text-align:center;color:#059669;">{a['success']}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #e5e7eb;text-align:center;color:#dc2626;">{a['fail']}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #e5e7eb;text-align:center;font-weight:600;">{a['success_rate']}%</td>
            </tr>"""

        # Lead source rows
        source_rows = ""
        for src, cnt in sorted(lead_m.get("leads_by_source", {}).items(),
                                key=lambda x: x[1], reverse=True):
            source_rows += f"""
            <tr>
                <td style="padding:6px 10px;border-bottom:1px solid #e5e7eb;">{src}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #e5e7eb;text-align:center;">{cnt}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8">
<style>
  body {{ font-family: 'Inter', Arial, sans-serif; color: #111827; margin: 0; padding: 32px; }}
  h1 {{ font-size: 1.5rem; font-weight: 800; color: #0f2b45; margin-bottom: 4px; }}
  h2 {{ font-size: 1.15rem; font-weight: 700; color: #0f2b45; margin: 24px 0 12px; border-bottom: 2px solid #D42B2B; padding-bottom: 6px; }}
  .subtitle {{ color: #6b7280; font-size: 0.85rem; margin-bottom: 20px; }}
  .summary {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }}
  .stat {{ background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px 20px; text-align: center; flex: 1; min-width: 120px; }}
  .stat .val {{ font-size: 1.4rem; font-weight: 800; color: #D42B2B; }}
  .stat .lbl {{ font-size: 0.72rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.04em; margin-top: 2px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-bottom: 16px; }}
  th {{ text-align: left; font-weight: 600; color: #6b7280; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; padding: 8px 10px; border-bottom: 2px solid #e5e7eb; }}
  p {{ font-size: 0.88rem; color: #4b5563; line-height: 1.6; }}
  .footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 0.78rem; color: #9ca3af; text-align: center; }}
</style>
</head>
<body>
  <h1>Monthly Performance Report</h1>
  <p class="subtitle">{business_name} &mdash; {month_name}</p>

  <div class="summary">
    <div class="stat"><div class="val">{summary.get('leads_this_month', 0)}</div><div class="lbl">Leads</div></div>
    <div class="stat"><div class="val">{summary.get('tasks_this_month', 0)}</div><div class="lbl">Tasks</div></div>
    <div class="stat"><div class="val">{summary.get('executions_this_month', 0)}</div><div class="lbl">Executions</div></div>
    <div class="stat"><div class="val">{summary.get('success_rate', 0)}%</div><div class="lbl">Success Rate</div></div>
    <div class="stat"><div class="val">{summary.get('active_agents', 0)}/{summary.get('total_agents', 0)}</div><div class="lbl">Agents Active</div></div>
  </div>

  <h2>Executive Summary</h2>
  <p>During {month_name}, {business_name} generated {summary.get('leads_this_month', 0)} leads with a {lead_m.get('conversion_rate', 0)}% conversion rate. The AI agents completed {summary.get('tasks_this_month', 0)} tasks with a {summary.get('success_rate', 0)}% execution success rate. {summary.get('active_agents', 0)} of {summary.get('total_agents', 0)} agents were active throughout the period.</p>

  <h2>Lead Generation</h2>
  <table>
    <thead><tr><th>Service</th><th style="text-align:center;">Leads</th></tr></thead>
    <tbody>{source_rows or '<tr><td colspan="2" style="text-align:center;color:#9ca3af;padding:16px;">No lead data for this period.</td></tr>'}</tbody>
  </table>
  <p><strong>Conversion Rate:</strong> {lead_m.get('conversion_rate', 0)}%</p>

  <h2>AI Agent Activity</h2>
  <table>
    <thead><tr><th>Agent</th><th style="text-align:center;">Total</th><th style="text-align:center;">Success</th><th style="text-align:center;">Fail</th><th style="text-align:center;">Rate</th></tr></thead>
    <tbody>{agent_rows_html or '<tr><td colspan="5" style="text-align:center;color:#9ca3af;padding:16px;">No agent activity data for this period.</td></tr>'}</tbody>
  </table>

  <h2>Recommendations</h2>
  <p>Based on this month's performance, we recommend focusing on the following areas for next month:</p>
  <ul style="font-size:0.88rem;color:#4b5563;line-height:1.7;">
    <li><strong>Top Agent:</strong> {agent_m.get('most_active_agent', 'N/A')} was the most active agent. Consider leveraging its strengths further.</li>
    <li><strong>Lead Sources:</strong> Focus additional attention on the highest-performing lead sources to maximize ROI.</li>
    <li><strong>Execution Quality:</strong> With a {summary.get('success_rate', 0)}% success rate, review any tools with recurring failures to improve reliability.</li>
    <li><strong>Consistency:</strong> Maintain the current content cadence to build momentum in search rankings and social reach.</li>
  </ul>

  <div class="footer">
    <p>Report generated by Laval Digital AI Marketing Platform &mdash; {datetime.now().strftime('%B %d, %Y')}</p>
  </div>
</body>
</html>"""
        return html
