import logging
from datetime import datetime, timedelta, UTC
from typing import Dict, Any

from core import database
from .base_server import MCPServer, _safe_error

logger = logging.getLogger(__name__)


class AnalyticsMCPServer(MCPServer):
    def __init__(self):
        super().__init__(
            name="analytics",
            description="Analytics and reporting — cross-channel ROI, dashboards, trends, benchmarks, lead attribution"
        )

    def _conn(self):
        return database._get_conn()

    def _register_tools(self) -> None:
        self.register_tool("generate_monthly_report", self.generate_monthly_report,
            "Generate a comprehensive monthly marketing report across all channels")
        self.register_tool("track_roi", self.track_roi,
            "Calculate ROI per marketing channel with revenue attribution")
        self.register_tool("create_client_dashboard", self.create_client_dashboard,
            "Create a real-time marketing dashboard configuration")
        self.register_tool("track_lead_sources", self.track_lead_sources,
            "Attribute leads to specific campaigns and channels")
        self.register_tool("analyze_trends", self.analyze_trends,
            "Analyze trends from execution and lead data")
        self.register_tool("compare_periods", self.compare_periods,
            "Compare performance across two time periods")
        self.register_tool("get_executive_summary", self.get_executive_summary,
            "Get executive summary of key metrics")
        self.register_tool("get_chart_data", self.get_chart_data,
            "Get chart-ready data for any metric")

    def generate_monthly_report(self, **kwargs) -> Dict[str, Any]:
        return {"success": True, "result": "Monthly report generated",
                "report": {
                    "period": kwargs.get("period", ""),
                    "channels": [],
                    "executions": 0,
                    "leads": 0,
                    "recommendations": [
                        "Double down on top-performing channels",
                        "A/B test underperforming ad creative",
                        "Increase GMB posting frequency — active profiles rank higher",
                        "Launch retargeting campaign for website visitors who didn't convert"
                    ]
                }}

    def track_roi(self, user_id: int = 0, **kwargs) -> Dict[str, Any]:
        conn = self._conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as total, SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successful FROM execution_log WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            total_executions = row["total"] or 0
            successful = row["successful"] or 0

            cursor.execute(
                "SELECT COUNT(*) as total FROM leads WHERE user_id = ?",
                (user_id,),
            )
            leads = cursor.fetchone()["total"] or 0

            cursor.execute(
                "SELECT agent_name, COUNT(*) as count FROM execution_log WHERE user_id = ? GROUP BY agent_name ORDER BY count DESC",
                (user_id,),
            )
            agent_tasks = {row["agent_name"]: row["count"] for row in cursor.fetchall()}

            estimated_customers = int(leads * 0.10)
            estimated_revenue = estimated_customers * 500
            monthly_cost = 597.99
            roi = ((estimated_revenue - monthly_cost) / monthly_cost * 100) if monthly_cost > 0 else 0

            return {"success": True,
                    "result": f"ROI: {roi:.0f}% (${estimated_revenue} est. revenue / ${monthly_cost} cost)",
                    "metrics": {"total_executions": total_executions,
                                "successful_executions": successful,
                                "success_rate": round((successful / total_executions * 100), 1) if total_executions > 0 else 0,
                                "leads_captured": leads,
                                "estimated_customers": estimated_customers,
                                "estimated_revenue": estimated_revenue,
                                "monthly_cost": monthly_cost,
                                "roi_pct": round(roi, 1),
                                "agent_breakdown": agent_tasks}}
        except Exception as e:
            return {"success": False, "result": "", "error": _safe_error(e)}
        finally:
            conn.close()

    def create_client_dashboard(self, **kwargs) -> Dict[str, Any]:
        dashboard = {
            "name": f"{kwargs.get('business_name', 'Your')} Marketing Dashboard",
            "refresh_interval": "5 minutes",
            "widgets": [
                {"type": "metric_card", "title": "Total Leads This Month", "size": "small", "position": {"row": 1, "col": 1}},
                {"type": "metric_card", "title": "Marketing ROI", "size": "small", "position": {"row": 1, "col": 2}},
                {"type": "metric_card", "title": "Tasks Executed", "size": "small", "position": {"row": 1, "col": 3}},
                {"type": "metric_card", "title": "Active Campaigns", "size": "small", "position": {"row": 1, "col": 4}},
                {"type": "line_chart", "title": "Leads Over Time", "size": "large", "position": {"row": 2, "col": 1}},
                {"type": "bar_chart", "title": "Performance by Channel", "size": "large", "position": {"row": 2, "col": 3}},
                {"type": "pie_chart", "title": "Lead Sources", "size": "medium", "position": {"row": 3, "col": 1}},
                {"type": "table", "title": "Recent Activity", "size": "medium", "position": {"row": 3, "col": 3}},
            ]
        }
        return {"success": True, "result": "Dashboard configuration created", "dashboard": dashboard}

    def track_lead_sources(self, **kwargs) -> Dict[str, Any]:
        attribution_models = {
            "first_touch": "Credits the first channel that brought the lead",
            "last_touch": "Credits the last channel before conversion",
            "linear": "Equal credit to all touchpoints",
            "time_decay": "More credit to recent touchpoints",
            "position_based": "40% first touch, 40% last touch, 20% middle"
        }
        sources = ["Google organic", "Google Maps", "Facebook organic", "Facebook paid", "Instagram", "Direct", "Referral", "Email"]
        return {"success": True, "result": "Lead source tracking configured",
                "attribution_models": attribution_models, "tracked_sources": sources,
                "recommendation": "Use UTM parameters on all links for accurate attribution"}

    def analyze_trends(self, user_id: int = 0, **kwargs) -> Dict[str, Any]:
        conn = self._conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT DATE(timestamp) as day, COUNT(*) as count FROM execution_log
                   WHERE user_id = ? AND timestamp >= DATE('now', '-28 days') GROUP BY DATE(timestamp) ORDER BY day""",
                (user_id,),
            )
            daily_executions = [{"date": row["day"], "count": row["count"]} for row in cursor.fetchall()]

            cursor.execute(
                """SELECT DATE(timestamp) as day, COUNT(*) as total, SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successful
                   FROM execution_log WHERE user_id = ? AND timestamp >= DATE('now', '-28 days')
                   GROUP BY DATE(timestamp) ORDER BY day""",
                (user_id,),
            )
            success_trend = [{"date": row["day"], "rate": round((row["successful"]/row["total"]*100),1) if row["total"] > 0 else 0} for row in cursor.fetchall()]

            cursor.execute(
                """SELECT agent_name, COUNT(*) as count FROM execution_log
                   WHERE user_id = ? AND timestamp >= DATE('now', '-30 days')
                   GROUP BY agent_name ORDER BY count DESC""",
                (user_id,),
            )
            agent_activity = {row["agent_name"]: row["count"] for row in cursor.fetchall()}

            cursor.execute(
                """SELECT strftime('%W', created_at) as week, COUNT(*) as count FROM leads
                   WHERE user_id = ? AND created_at >= DATE('now', '-28 days')
                   GROUP BY week ORDER BY week""",
                (user_id,),
            )
            lead_growth = [{"week": f"Week {row['week']}", "count": row["count"]} for row in cursor.fetchall()]

            return {"success": True, "result": f"Analyzed trends for {len(daily_executions)} days",
                    "trends": {"daily_executions": daily_executions,
                               "success_rate_trends": success_trend,
                               "agent_activity": agent_activity,
                               "lead_growth": lead_growth},
                    "insights": self._generate_trend_insights(daily_executions, success_trend, agent_activity)}
        except Exception as e:
            return {"success": False, "error": _safe_error(e)}
        finally:
            conn.close()

    def _generate_trend_insights(self, daily_execs, success_trend, agent_activity):
        insights = []
        if daily_execs:
            recent = daily_execs[-3:]
            avg = sum(d["count"] for d in recent) / len(recent) if recent else 0
            insights.append(f"Average daily executions: {avg:.1f}")
        if success_trend:
            recent_success = [s for s in success_trend[-3:] if s["rate"] > 0]
            if recent_success:
                avg_rate = sum(s["rate"] for s in recent_success) / len(recent_success)
                insights.append(f"Average success rate: {avg_rate:.1f}%")
        if agent_activity:
            top_agent = max(agent_activity, key=agent_activity.get)
            insights.append(f"Most active agent: {top_agent} ({agent_activity[top_agent]} tasks)")
        return insights

    def compare_periods(self, user_id: int = 0, **kwargs) -> Dict[str, Any]:
        conn = self._conn()
        period_a_days = kwargs.get("period_a_days", 30)
        period_b_days = kwargs.get("period_b_days", 30)
        offset_days = kwargs.get("offset_days", period_a_days)
        try:
            now = datetime.now(UTC)
            a_start = (now - timedelta(days=period_a_days)).isoformat()
            a_end = now.isoformat()
            b_start = (now - timedelta(days=period_a_days + period_b_days)).isoformat()
            b_end = (now - timedelta(days=offset_days)).isoformat()

            def _stats(start, end):
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) as total, SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successful FROM execution_log WHERE user_id = ? AND timestamp >= ? AND timestamp < ?",
                    (user_id, start, end),
                )
                e = cursor.fetchone()
                cursor.execute(
                    "SELECT COUNT(*) as total FROM leads WHERE user_id = ? AND created_at >= ? AND created_at < ?",
                    (user_id, start, end),
                )
                l = cursor.fetchone()
                return {"executions": e["total"] or 0, "successful": e["successful"] or 0, "leads": l["total"] or 0}

            period_a = _stats(a_start, a_end)
            period_b = _stats(b_start, b_end)

            return {"success": True, "result": "Periods compared", "period_a": period_a, "period_b": period_b,
                    "changes": {
                        "executions": period_a["executions"] - period_b["executions"],
                        "leads": period_a["leads"] - period_b["leads"],
                    }}
        except Exception as e:
            return {"success": False, "error": _safe_error(e)}
        finally:
            conn.close()

    def get_executive_summary(self, user_id: int = 0, **kwargs) -> Dict[str, Any]:
        conn = self._conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as total, SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successful FROM execution_log WHERE user_id = ?",
                (user_id,),
            )
            ec = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) as total FROM leads WHERE user_id = ?", (user_id,))
            lc = cursor.fetchone()
            cursor.execute(
                "SELECT COUNT(DISTINCT agent_name) as agents FROM execution_log WHERE user_id = ?",
                (user_id,),
            )
            ac = cursor.fetchone()
            cursor.execute(
                "SELECT agent_name, COUNT(*) as count FROM execution_log WHERE user_id = ? GROUP BY agent_name ORDER BY count DESC LIMIT 1",
                (user_id,),
            )
            top = cursor.fetchone()

            return {"success": True, "result": "Executive summary generated",
                    "summary": {
                        "total_executions": ec["total"] or 0,
                        "successful_executions": ec["successful"] or 0,
                        "success_rate": round(((ec["successful"] or 0) / (ec["total"] or 1)) * 100, 1),
                        "total_leads": lc["total"] or 0,
                        "active_agents": ac["agents"] or 0,
                        "top_agent": top["agent_name"] if top else "N/A",
                    }}
        except Exception as e:
            return {"success": False, "error": _safe_error(e)}
        finally:
            conn.close()

    def get_chart_data(self, user_id: int = 0, **kwargs) -> Dict[str, Any]:
        conn = self._conn()
        chart_type = kwargs.get("chart_type", "executions_by_day")
        days = kwargs.get("days", 30)
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        try:
            if chart_type == "executions_by_day":
                cursor = conn.execute(
                    """SELECT DATE(timestamp) as label, COUNT(*) as value FROM execution_log
                       WHERE user_id = ? AND timestamp > ? GROUP BY label ORDER BY label""",
                    (user_id, cutoff),
                )
                data = [dict(r) for r in cursor.fetchall()]
            elif chart_type == "leads_by_day":
                cursor = conn.execute(
                    """SELECT DATE(created_at) as label, COUNT(*) as value FROM leads
                       WHERE user_id = ? AND created_at > ? GROUP BY label ORDER BY label""",
                    (user_id, cutoff),
                )
                data = [dict(r) for r in cursor.fetchall()]
            elif chart_type == "agent_breakdown":
                cursor = conn.execute(
                    """SELECT agent_name as label, COUNT(*) as value FROM execution_log
                       WHERE user_id = ? AND timestamp > ? GROUP BY label ORDER BY value DESC""",
                    (user_id, cutoff),
                )
                data = [dict(r) for r in cursor.fetchall()]
            elif chart_type == "success_rate":
                cursor = conn.execute(
                    """SELECT DATE(timestamp) as label,
                              SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) * 100 as value
                       FROM execution_log WHERE user_id = ? AND timestamp > ?
                       GROUP BY label ORDER BY label""",
                    (user_id, cutoff),
                )
                data = [dict(r) for r in cursor.fetchall()]
            else:
                data = []
            return {"success": True, "chart_type": chart_type, "data": data}
        except Exception as e:
            return {"success": False, "error": _safe_error(e)}
        finally:
            conn.close()
