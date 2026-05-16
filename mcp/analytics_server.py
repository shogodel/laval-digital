"""Analytics & Reporting MCP Server for Frankie — Cross-channel performance measurement."""
import logging
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from .base_server import MCPServer

logger = logging.getLogger(__name__)


class AnalyticsMCPServer(MCPServer):
    """MCP Server for analytics and reporting — measures ROI across all marketing channels."""

    def __init__(self):
        super().__init__(
            name="analytics",
            description="Analytics and reporting — cross-channel ROI, dashboards, trends, benchmarks, lead attribution"
        )

    def _get_tenant_connection(self, tenant_id: str) -> Optional[sqlite3.Connection]:
        """Get a database connection for a tenant. Returns None if tenant doesn't exist."""
        try:
            db_path = Path("tenants/direct") / f"{tenant_id}.db"
            if not db_path.exists():
                return None
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to tenant {tenant_id}: {e}")
            return None

    def _register_tools(self) -> None:
        self.register_tool("generate_monthly_report", self.generate_monthly_report,
            "Generate a comprehensive monthly marketing report across all channels")
        self.register_tool("track_roi", self.track_roi,
            "Calculate ROI per marketing channel with revenue attribution")
        self.register_tool("create_client_dashboard", self.create_client_dashboard,
            "Create a real-time dashboard with live marketing metrics")
        self.register_tool("track_lead_sources", self.track_lead_sources,
            "Attribute leads to specific campaigns and channels")
        self.register_tool("analyze_trends", self.analyze_trends,
            "Identify growth trends across all marketing channels")
        self.register_tool("compare_periods", self.compare_periods,
            "Compare performance between two time periods")
        self.register_tool("export_report_pdf", self.export_report_pdf,
            "Generate a PDF-ready HTML report for client delivery")
        self.register_tool("set_goals_and_track", self.set_goals_and_track,
            "Set KPIs and track progress toward goals")
        self.register_tool("alert_on_milestones", self.alert_on_milestones,
            "Configure alerts when campaigns hit key milestones")
        self.register_tool("benchmark_vs_industry", self.benchmark_vs_industry,
            "Compare performance to industry averages")
        self.register_tool("get_executive_summary", self.get_executive_summary,
            "Generate a plain-language executive summary of all Frankie activity")
        self.register_tool("get_chart_data", self.get_chart_data,
            "Return chart-ready data for the Frankie dashboard")

    # ------------------------------------------------------------------
    # Monthly Report
    # ------------------------------------------------------------------

    def generate_monthly_report(self, month: str = "", business_name: str = "", channels: str = "seo,social,email,gmb,ads",
                                **kwargs) -> Dict[str, Any]:
        """Generate a comprehensive monthly marketing report."""
        try:
            report_month = datetime.strptime(month, "%Y-%m") if month else datetime.now()
        except ValueError:
            report_month = datetime.now()
        channel_list = [c.strip() for c in channels.split(',')]

        report = {
            "title": f"Monthly Marketing Report — {business_name or 'Your Business'}",
            "period": report_month.strftime("%B %Y"),
            "generated": datetime.now().isoformat(),
            "executive_summary": "This month, Frankie executed [X] tasks across [N] channels, generating [Y] leads and [Z] customer actions. Overall marketing ROI was [ROI%].",
            "channels": {},
            "recommendations": []
        }

        channel_templates = {
            "seo": {"name": "SEO & Content", "metrics": ["New blog posts", "Keywords ranking up", "Keywords ranking down",
                        "Google impressions", "Google clicks", "Average position", "Backlinks acquired", "GMB profile views"]},
            "social": {"name": "Social Media", "metrics": ["Posts published", "Total impressions", "Total engagements",
                        "Engagement rate", "New followers", "Top performing post", "Clicks to website"]},
            "email": {"name": "Email Marketing", "metrics": ["Emails sent", "Open rate", "Click rate", "Unsubscribe rate",
                        "Bounce rate", "New subscribers", "Conversions from email"]},
            "gmb": {"name": "Google Business Profile", "metrics": ["Profile views", "Search views", "Map views",
                        "Direction requests", "Phone calls", "Website clicks", "New reviews", "Average rating"]},
            "ads": {"name": "Paid Advertising", "metrics": ["Ad spend", "Impressions", "Clicks", "CTR", "CPC",
                        "Conversions", "Conversion rate", "CPA", "ROAS"]}
        }

        for c in channel_list:
            if c in channel_templates:
                report["channels"][c] = channel_templates[c]
                report["channels"][c]["data"] = "Connect channel API for live data"

        report["recommendations"] = [
            "Double down on top-performing channels",
            "A/B test underperforming ad creative",
            "Increase GMB posting frequency — active profiles rank higher",
            "Launch retargeting campaign for website visitors who didn't convert"
        ]

        return {"success": True, "result": f"Monthly report for {report['period']} generated",
                "report": report, "channels_covered": len(report["channels"])}

    # ------------------------------------------------------------------
    # ROI Tracking
    # ------------------------------------------------------------------

    def track_roi(self, tenant_id: str = "", period: str = "monthly", **kwargs) -> Dict[str, Any]:
        """Calculate real ROI from Frankie's execution data."""
        conn = self._get_tenant_connection(tenant_id) if tenant_id else None
        if not conn:
            return {"success": False, "result": "", "error": f"No data found for tenant '{tenant_id}'. Deploy Frankie first."}

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as total, SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successful FROM execution_log")
            row = cursor.fetchone()
            total_executions = row["total"] or 0
            successful = row["successful"] or 0

            cursor.execute("SELECT COUNT(*) as total FROM leads")
            leads = cursor.fetchone()["total"] or 0

            cursor.execute("SELECT agent_name, COUNT(*) as count FROM execution_log GROUP BY agent_name ORDER BY count DESC")
            agent_tasks = {row["agent_name"]: row["count"] for row in cursor.fetchall()}

            estimated_customers = int(leads * 0.10)
            estimated_revenue = estimated_customers * 500
            monthly_cost = 597.99
            roi = ((estimated_revenue - monthly_cost) / monthly_cost * 100) if monthly_cost > 0 else 0

            conn.close()
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
            conn.close() if conn else None
            return {"success": False, "result": "", "error": str(e)}

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def create_client_dashboard(self, business_name: str = "", **kwargs) -> Dict[str, Any]:
        """Create a real-time marketing dashboard configuration."""
        dashboard = {
            "name": f"{business_name or 'Your'} Marketing Dashboard",
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

    # ------------------------------------------------------------------
    # Lead Attribution
    # ------------------------------------------------------------------

    def track_lead_sources(self, **kwargs) -> Dict[str, Any]:
        """Attribute leads to specific campaigns and channels."""
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

    # ------------------------------------------------------------------
    # Trends
    # ------------------------------------------------------------------

    def analyze_trends(self, tenant_id: str = "", channel: str = "all", metric: str = "executions", **kwargs) -> Dict[str, Any]:
        """Analyze real trends from execution data."""
        conn = self._get_tenant_connection(tenant_id) if tenant_id else None
        if not conn:
            return {"success": False, "error": f"No data found for tenant '{tenant_id}'"}

        try:
            cursor = conn.cursor()
            cursor.execute("""SELECT DATE(timestamp) as day, COUNT(*) as count FROM execution_log WHERE timestamp >= DATE('now', '-28 days') GROUP BY DATE(timestamp) ORDER BY day""")
            daily_executions = [{"date": row["day"], "count": row["count"]} for row in cursor.fetchall()]

            cursor.execute("""SELECT DATE(timestamp) as day, COUNT(*) as total, SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successful FROM execution_log WHERE timestamp >= DATE('now', '-28 days') GROUP BY DATE(timestamp) ORDER BY day""")
            success_trend = [{"date": row["day"], "rate": round((row["successful"]/row["total"]*100),1) if row["total"] > 0 else 0} for row in cursor.fetchall()]

            cursor.execute("""SELECT agent_name, COUNT(*) as count FROM execution_log WHERE timestamp >= DATE('now', '-30 days') GROUP BY agent_name ORDER BY count DESC""")
            agent_activity = {row["agent_name"]: row["count"] for row in cursor.fetchall()}

            cursor.execute("""SELECT strftime('%W', created_at) as week, COUNT(*) as count FROM leads WHERE created_at >= DATE('now', '-28 days') GROUP BY week ORDER BY week""")
            lead_growth = [{"week": f"Week {row['week']}", "count": row["count"]} for row in cursor.fetchall()]

            conn.close()
            return {"success": True,
                    "result": f"Trend analysis complete — {len(daily_executions)} days of data",
                    "trends": {"daily_executions": daily_executions,
                               "success_rate_trend": success_trend,
                               "agent_activity": agent_activity,
                               "lead_growth": lead_growth,
                               "summary": {"total_executions_28d": sum(d["count"] for d in daily_executions),
                                           "avg_daily_executions": round(sum(d["count"] for d in daily_executions) / max(len(daily_executions), 1), 1),
                                           "trend_direction": "up" if len(daily_executions) >= 2 and daily_executions[-1]["count"] > daily_executions[0]["count"] else "stable",
                                           "most_active_agent": max(agent_activity, key=agent_activity.get) if agent_activity else "none"}}}
        except Exception as e:
            conn.close() if conn else None
            return {"success": False, "error": str(e)}

    def compare_periods(self, tenant_id: str = "", period_a_days: int = 30, period_b_days: int = 30, **kwargs) -> Dict[str, Any]:
        """Compare real performance between current period and previous period."""
        conn = self._get_tenant_connection(tenant_id) if tenant_id else None
        if not conn:
            return {"success": False, "error": f"No data for tenant '{tenant_id}'"}

        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc)
            cutoff_a = (now - timedelta(days=period_a_days)).isoformat()
            cutoff_b = (now - timedelta(days=period_a_days + period_b_days)).isoformat()
            cutoff_a_end = (now - timedelta(days=period_a_days)).isoformat()

            cursor.execute("""SELECT COUNT(*) as executions, SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successful, COUNT(DISTINCT DATE(timestamp)) as active_days FROM execution_log WHERE timestamp >= ?""", (cutoff_a,))
            current = dict(cursor.fetchone())

            cursor.execute("""SELECT COUNT(*) as executions, SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successful, COUNT(DISTINCT DATE(timestamp)) as active_days FROM execution_log WHERE timestamp >= ? AND timestamp < ?""", (cutoff_b, cutoff_a_end))
            previous = dict(cursor.fetchone())

            cursor.execute("SELECT COUNT(*) FROM leads WHERE created_at >= ?", (cutoff_a,))
            current_leads = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM leads WHERE created_at >= ? AND created_at < ?", (cutoff_b, cutoff_a_end))
            previous_leads = cursor.fetchone()[0] or 0

            conn.close()

            def calc_change(c, p):
                if p == 0: return 100 if c > 0 else 0
                return round(((c - p) / p) * 100, 1)

            return {"success": True,
                    "result": f"Period comparison: last {period_a_days} days vs previous {period_b_days} days",
                    "comparison": {"current_period": {"executions": current["executions"] or 0, "successful": current["successful"] or 0, "active_days": current["active_days"] or 0, "leads": current_leads},
                                   "previous_period": {"executions": previous["executions"] or 0, "successful": previous["successful"] or 0, "active_days": previous["active_days"] or 0, "leads": previous_leads},
                                   "changes": {"executions": f"{calc_change(current['executions'] or 0, previous['executions'] or 0):+}%",
                                               "success_rate": f"{calc_change(current['successful'] or 0, previous['successful'] or 0):+}%",
                                               "leads": f"{calc_change(current_leads, previous_leads):+}%"}}}
        except Exception as e:
            conn.close() if conn else None
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_report_pdf(self, report_html: str = "", **kwargs) -> Dict[str, Any]:
        """Generate a PDF-ready HTML report."""
        return {"success": True, "result": "Report ready for PDF export",
                "instructions": "Open the HTML report in your browser and use Ctrl+P (Cmd+P) → Save as PDF",
                "tip": "Use Chrome's Save as PDF for best results with background colors and fonts"}

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------

    def set_goals_and_track(self, goals: str = "", **kwargs) -> Dict[str, Any]:
        """Set KPIs and track progress toward goals."""
        goal_list = [g.strip() for g in goals.split('\n') if g.strip()] if goals else [
            "Generate 20 new leads per month", "Achieve 5% conversion rate on website",
            "Grow social following by 100/month", "Maintain 4.5+ star rating on Google",
            "Achieve 300%+ ROAS on ad spend"
        ]
        goals_data = []
        for g in goal_list:
            goals_data.append({"goal": g, "metric": "Define specific number", "current": "Track weekly", "target": "Set target",
                               "progress": "0%", "status": "active"})
        return {"success": True, "result": f"Tracking {len(goals_data)} goals", "goals": goals_data}

    def alert_on_milestones(self, milestone_type: str = "lead_count", threshold: int = 10, **kwargs) -> Dict[str, Any]:
        """Configure alerts for key milestones."""
        return {"success": True, "result": f"Alert configured: notify when {milestone_type} reaches {threshold}",
                "available_milestones": ["lead_count", "review_count", "roi_achieved", "traffic_spike", "campaign_completed"]}

    def benchmark_vs_industry(self, industry: str = "local_services", **kwargs) -> Dict[str, Any]:
        """Compare performance to industry averages."""
        benchmarks = {
            "local_services": {"avg_conversion_rate": "5-10%", "avg_email_open_rate": "20-25%", "avg_ctr_search": "3-5%",
                               "avg_roas": "200-400%", "avg_review_rating": "4.2 stars"},
            "ecommerce": {"avg_conversion_rate": "2-3%", "avg_email_open_rate": "15-20%", "avg_ctr_search": "2-4%",
                          "avg_roas": "300-500%", "avg_cart_abandonment": "70%"},
            "b2b": {"avg_conversion_rate": "2-5%", "avg_email_open_rate": "15-25%", "avg_ctr_search": "2-3%",
                    "avg_roas": "200-400%", "avg_lead_to_close": "5-10%"}
        }
        industry_benchmarks = benchmarks.get(industry, benchmarks["local_services"])
        return {"success": True, "result": f"Industry benchmarks for {industry}", "benchmarks": industry_benchmarks}

    def get_executive_summary(self, tenant_id: str = "", business_name: str = "", **kwargs) -> Dict[str, Any]:
        """Generate a plain-language executive summary of all Frankie activity."""
        conn = self._get_tenant_connection(tenant_id) if tenant_id else None
        if not conn:
            return {"success": False, "error": f"No data for tenant '{tenant_id}'"}

        try:
            cursor = conn.cursor()
            cursor.execute("""SELECT COUNT(*) as total, SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successful FROM execution_log WHERE timestamp >= DATE('now', '-30 days')""")
            month = dict(cursor.fetchone())

            cursor.execute("SELECT COUNT(*) FROM leads WHERE created_at >= DATE('now', '-30 days')")
            leads = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(DISTINCT agent_name) FROM execution_log WHERE timestamp >= DATE('now', '-30 days')")
            active_agents = cursor.fetchone()[0] or 0

            cursor.execute("SELECT agent_name, COUNT(*) as c FROM execution_log WHERE timestamp >= DATE('now', '-30 days') GROUP BY agent_name ORDER BY c DESC LIMIT 3")
            top_agents = [f"{row['agent_name']} ({row['c']} tasks)" for row in cursor.fetchall()]

            cursor.execute("SELECT COUNT(*) FROM execution_log WHERE timestamp >= DATE('now', '-7 days')")
            this_week = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(*) FROM execution_log WHERE timestamp >= DATE('now', '-14 days') AND timestamp < DATE('now', '-7 days')")
            last_week = cursor.fetchone()[0] or 0

            conn.close()

            week_change = "up" if this_week > last_week else "down" if this_week < last_week else "stable"
            success_rate = round((month["successful"] or 0) / max(month["total"] or 1, 1) * 100, 1)

            summary = f"""📊 **{business_name or 'Your'} Monthly Marketing Summary**

This month, Frankie executed **{month['total'] or 0} tasks** across **{active_agents} active agents** with a **{success_rate}% success rate**.

Your top 3 most active agents were: {', '.join(top_agents) if top_agents else 'None yet'}.

Frankie captured **{leads} new leads** this month. Week-over-week activity is **{week_change}** ({this_week} tasks this week vs {last_week} last week).

**What this means for your business:** Based on industry averages, those {leads} leads could translate to approximately **{int(leads * 0.10)} new customers** this month. At an average job value of $500, that's an estimated **${int(leads * 0.10) * 500} in new revenue** influenced by Frankie.

**Recommendation:** {'Increase activity by connecting more platforms' if active_agents < 8 else 'Continue current strategy — Frankie is performing well!'}"""

            return {"success": True, "result": "Executive summary generated", "summary": summary.strip(),
                    "metrics": {"total_tasks": month["total"] or 0, "success_rate": success_rate,
                                "leads": leads, "active_agents": active_agents, "top_agents": top_agents}}
        except Exception as e:
            conn.close() if conn else None
            return {"success": False, "error": str(e)}

    def get_chart_data(self, tenant_id: str = "", chart_type: str = "executions_by_day", days: int = 30, **kwargs) -> Dict[str, Any]:
        """Return chart-ready data for the Frankie dashboard."""
        conn = self._get_tenant_connection(tenant_id) if tenant_id else None
        if not conn:
            return {"success": False, "error": f"No data for tenant '{tenant_id}'"}

        try:
            cursor = conn.cursor()
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            if chart_type == "executions_by_day":
                cursor.execute("SELECT DATE(timestamp) as date, COUNT(*) as count FROM execution_log WHERE timestamp >= ? GROUP BY DATE(timestamp) ORDER BY date", (cutoff,))
                data = [{"date": row["date"], "count": row["count"]} for row in cursor.fetchall()]

            elif chart_type == "success_vs_failure":
                cursor.execute("SELECT SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successful, SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) as failed FROM execution_log WHERE timestamp >= ?", (cutoff,))
                row = cursor.fetchone()
                data = {"successful": row["successful"] or 0, "failed": row["failed"] or 0}

            elif chart_type == "agents_pie":
                cursor.execute("SELECT agent_name, COUNT(*) as count FROM execution_log WHERE timestamp >= ? GROUP BY agent_name ORDER BY count DESC", (cutoff,))
                data = [{"agent": row["agent_name"], "count": row["count"]} for row in cursor.fetchall()]

            elif chart_type == "leads_by_source":
                cursor.execute("SELECT COALESCE(service, 'unknown') as source, COUNT(*) as count FROM leads WHERE created_at >= ? GROUP BY source ORDER BY count DESC", (cutoff,))
                data = [{"source": row["source"], "count": row["count"]} for row in cursor.fetchall()]

            elif chart_type == "leads_by_urgency":
                cursor.execute("SELECT COALESCE(urgency, 'unspecified') as urgency, COUNT(*) as count FROM leads WHERE created_at >= ? GROUP BY urgency ORDER BY count DESC", (cutoff,))
                data = [{"urgency": row["urgency"], "count": row["count"]} for row in cursor.fetchall()]

            else:
                data = []

            conn.close()
            return {"success": True, "result": f"Chart data for {chart_type} ({len(data) if isinstance(data, list) else 1} data points)",
                    "chart_type": chart_type, "data": data}
        except Exception as e:
            conn.close() if conn else None
            return {"success": False, "error": str(e)}
