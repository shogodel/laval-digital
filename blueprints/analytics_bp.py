"""Analytics blueprint — performance summaries, lead metrics, reports."""
import calendar
import logging
import smtplib
import ssl
import threading
import uuid
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import bleach

from flask import Blueprint, request, session
from flask_login import current_user

from core import database
from core.analytics import AnalyticsEngine
from core.api_helpers import api_error, api_success
from core.app_state import get_current_user_id, get_executioner
from core.auth import admin_required

logger = logging.getLogger(__name__)

analytics_bp = Blueprint("analytics", __name__, url_prefix="")

_report_history: list[dict[str, Any]] = []
_report_history_lock = threading.Lock()

_ALLOWED_HTML_TAGS = frozenset({
    "p", "br", "strong", "em", "u", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "a", "code", "pre", "blockquote", "img", "hr",
    "table", "thead", "tbody", "tr", "th", "td", "span", "div",
    "section", "header", "footer", "main", "article",
})
_ALLOWED_HTML_ATTRS = {
    "a": ("href", "title", "rel"), "img": ("src", "alt", "title", "width", "height"),
    "td": ("colspan", "rowspan"), "th": ("colspan", "rowspan"),
    "*": ("class", "id"),
}
_ALLOWED_HTML_PROTOCOLS = frozenset({"https", "http", "mailto"})


def _safe_int(val, default=0):
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _leads_by_month(engine, months: int = 6) -> list:
    from datetime import date as dt_date
    result = []
    today = dt_date.today()
    for i in range(months - 1, -1, -1):
        m = today.month - i
        y = today.year
        while m < 1:
            m += 12
            y -= 1
        start = f"{y}-{m:02d}-01"
        last_day = calendar.monthrange(y, m)[1]
        end = f"{y}-{m:02d}-{last_day}"
        rows = engine._fetchall(
            "SELECT COUNT(*) as cnt FROM leads WHERE DATE(created_at) >= ? AND DATE(created_at) <= ?",
            (start, end),
        )
        cnt = rows[0]["cnt"] if rows else 0
        result.append({"label": f"{calendar.month_abbr[m]}", "count": cnt})
    return result


def _send_report_email(html: str, user_id: str):
    try:
        engine = AnalyticsEngine(_safe_int(user_id))
        biz_row = engine._fetchone("SELECT business_name, email FROM client_details WHERE user_id = ?", (_safe_int(user_id),))
        business_name = biz_row["business_name"] if biz_row else user_id
        client_email = biz_row["email"] if biz_row else None
        if not client_email:
            return api_error("No client email found", 400)
        settings = get_executioner().get_smtp_config()
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Monthly Performance Report — {business_name}"
        msg["From"] = settings.get("smtp_from_email", "reports@lavaldigital.ca")
        msg["To"] = client_email
        part = MIMEText(html, "html")
        msg.attach(part)
        ssl_context = ssl.create_default_context()
        with smtplib.SMTP(settings.get("smtp_host", "smtp.gmail.com"), settings.get("smtp_port", 587)) as server:
            if settings.get("smtp_use_tls", True):
                server.starttls(context=ssl_context)
            if settings.get("smtp_username"):
                server.login(settings["smtp_username"], settings.get("smtp_password", ""))
            server.send_message(msg)
        return api_success({"message": f"Report emailed to {client_email}"})
    except Exception as e:
        logger.error("Failed to email report: %s", e)
        return api_error("An internal error occurred.", 500)


@analytics_bp.route("/api/analytics/summary")
def api_analytics_summary():
    if not (current_user.is_authenticated and current_user.role == "admin"):
        return api_error("Unauthorized", 401)
    user_id = request.args.get("client", "").strip()
    days = int(request.args.get("days", 30))
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    is_admin = current_user.is_authenticated and current_user.role == "admin"
    session_user = session.get("active_user_id") or getattr(current_user, "id", None)
    if user_id and is_admin:
        engine = AnalyticsEngine(_safe_int(user_id))
        perf = engine.get_performance_summary()
        leads = engine.get_lead_metrics(start_date, end_date)
        agents = engine.get_agent_metrics(start_date, end_date)
        execs = engine.get_execution_metrics(start_date, end_date)
        return api_success({
            "total_clients": 1,
            "total_leads": perf.get("leads_this_month", 0),
            "total_tasks": perf.get("tasks_this_month", 0),
            "success_rate": perf.get("success_rate", 0),
            "success_count": execs.get("success_count", 0),
            "fail_count": execs.get("fail_count", 0),
            "avg_success_rate": perf.get("success_rate", 0),
            "leads_this_month": perf.get("leads_this_month", 0),
            "tasks_this_month": perf.get("tasks_this_month", 0),
            "active_agents": perf.get("active_agents", 0),
            "total_agents": perf.get("total_agents", 0),
            "avg_response_time": agents.get("avg_response_time", 0),
            "leads_by_month": _leads_by_month(engine),
            "tasks_per_agent": agents.get("tasks_per_agent", []),
            "failures_by_tool": execs.get("failures_by_tool", {}),
            "recent_leads": engine._fetchall(
                "SELECT name, service, urgency, status FROM leads ORDER BY created_at DESC LIMIT 50"
            ),
            "recent_executions": engine._fetchall(
                "SELECT agent_name, tool_name, success, timestamp FROM execution_log ORDER BY timestamp DESC LIMIT 50"
            ),
            "per_client": [{
                "user_id": user_id,
                "leads": perf.get("leads_this_month", 0),
                "tasks": perf.get("tasks_this_month", 0),
                "success_rate": perf.get("success_rate", 0),
                "active_agents": perf.get("active_agents", 0),
            }],
        })
    if is_admin:
        all_users = database.list_users(role='user')
        all_user_ids = [str(u["id"]) for u in all_users]
        total_leads = 0
        total_tasks = 0
        total_success = 0
        total_fail = 0
        all_tasks_per_agent = {}
        all_failures_by_tool = {}
        all_leads_by_month = {}
        all_recent_leads = []
        all_recent_execs = []
        for uid in all_user_ids:
            e = AnalyticsEngine(int(uid))
            perf = e.get_performance_summary()
            agents_m = e.get_agent_metrics(start_date, end_date)
            execs_m = e.get_execution_metrics(start_date, end_date)
            total_leads += perf.get("leads_this_month", 0)
            total_tasks += perf.get("tasks_this_month", 0)
            total_success += execs_m.get("success_count", 0)
            total_fail += execs_m.get("fail_count", 0)
            for a in agents_m.get("tasks_per_agent", []):
                name = a["agent"]
                if name not in all_tasks_per_agent:
                    all_tasks_per_agent[name] = {"agent": name, "total": 0, "success": 0, "fail": 0, "success_rate": 0}
                all_tasks_per_agent[name]["total"] += a["total"]
                all_tasks_per_agent[name]["success"] += a["success"]
                all_tasks_per_agent[name]["fail"] += a["fail"]
            for tool, cnt in execs_m.get("failures_by_tool", {}).items():
                all_failures_by_tool[tool] = all_failures_by_tool.get(tool, 0) + cnt
            for m in _leads_by_month(e):
                lbl = m["label"]
                all_leads_by_month[lbl] = all_leads_by_month.get(lbl, 0) + m["count"]
            all_recent_leads.extend(
                e._fetchall("SELECT name, service, urgency, status FROM leads ORDER BY created_at DESC LIMIT 20")
            )
            all_recent_execs.extend(
                e._fetchall("SELECT agent_name, tool_name, success, timestamp FROM execution_log ORDER BY timestamp DESC LIMIT 20")
            )
        for a in all_tasks_per_agent.values():
            a["success_rate"] = round((a["success"] / a["total"] * 100) if a["total"] else 0, 1)
        leads_by_month = [{"label": k, "count": v} for k, v in sorted(all_leads_by_month.items())]
        total_clients = len(all_user_ids)
        avg_sr = round((total_success / (total_success + total_fail) * 100) if (total_success + total_fail) else 0, 1)
        return api_success({
            "total_clients": total_clients,
            "total_leads": total_leads,
            "total_tasks": total_tasks,
            "success_count": total_success,
            "fail_count": total_fail,
            "avg_success_rate": avg_sr,
            "active_agents": len(all_tasks_per_agent),
            "total_agents": len(database.DEFAULT_AGENTS),
            "leads_this_month": total_leads,
            "tasks_this_month": total_tasks,
            "leads_by_month": leads_by_month,
            "tasks_per_agent": list(all_tasks_per_agent.values()),
            "failures_by_tool": all_failures_by_tool,
            "recent_leads": sorted(all_recent_leads, key=lambda x: x.get("name", ""))[:20],
            "recent_executions": sorted(all_recent_execs, key=lambda x: x.get("timestamp", ""), reverse=True)[:20],
        })
    if not is_admin and session_user:
        engine = AnalyticsEngine(int(session_user))
        perf = engine.get_performance_summary()
        leads = engine.get_lead_metrics(start_date, end_date)
        agents = engine.get_agent_metrics(start_date, end_date)
        execs = engine.get_execution_metrics(start_date, end_date)
        return api_success({
            "leads_this_month": perf.get("leads_this_month", 0),
            "tasks_this_month": perf.get("tasks_this_month", 0),
            "success_rate": perf.get("success_rate", 0),
            "active_agents": perf.get("active_agents", 0),
            "total_agents": perf.get("total_agents", 0),
            "avg_response_time": agents.get("avg_response_time", 0),
            "conversion_rate": leads.get("conversion_rate", 0),
            "leads_by_month": _leads_by_month(engine),
            "tasks_per_agent": agents.get("tasks_per_agent", []),
            "failures_by_tool": execs.get("failures_by_tool", {}),
            "recent_leads": engine._fetchall(
                "SELECT name, service, urgency, status FROM leads ORDER BY created_at DESC LIMIT 20"
            ),
            "recent_executions": engine._fetchall(
                "SELECT agent_name, tool_name, success, timestamp FROM execution_log ORDER BY timestamp DESC LIMIT 20"
            ),
        })
    return api_error("Unauthorized", 401)


@analytics_bp.route("/api/analytics/leads")
@admin_required
def api_analytics_leads():
    user_id = request.args.get("client", "").strip() or session.get("active_user_id") or get_current_user_id()
    start = request.args.get("start")
    end = request.args.get("end")
    if not user_id:
        return api_error("No user context", 400)
    engine = AnalyticsEngine(_safe_int(user_id))
    return api_success(engine.get_lead_metrics(start, end))


@analytics_bp.route("/api/analytics/agents")
@admin_required
def api_analytics_agents():
    user_id = request.args.get("client", "").strip() or session.get("active_user_id") or get_current_user_id()
    start = request.args.get("start")
    end = request.args.get("end")
    if not user_id:
        return api_error("No user context", 400)
    engine = AnalyticsEngine(_safe_int(user_id))
    return api_success(engine.get_agent_metrics(start, end))


@analytics_bp.route("/api/analytics/executions")
@admin_required
def api_analytics_executions():
    user_id = request.args.get("client", "").strip() or session.get("active_user_id") or get_current_user_id()
    start = request.args.get("start")
    end = request.args.get("end")
    if not user_id:
        return api_error("No user context", 400)
    engine = AnalyticsEngine(_safe_int(user_id))
    return api_success(engine.get_execution_metrics(start, end))


@analytics_bp.route("/api/analytics/report/generate", methods=["POST"])
@admin_required
def api_analytics_generate_report():
    data = request.json
    user_id = data.get("user_id") or session.get("active_user_id")
    month = data.get("month")
    year = data.get("year")
    if not user_id:
        return api_error("user_id required", 400)
    engine = AnalyticsEngine(_safe_int(user_id))
    html = engine.generate_monthly_report(year, month)
    return api_success({"html": html})


@analytics_bp.route("/api/analytics/report/save", methods=["POST"])
@admin_required
def api_analytics_save_report():
    data = request.json
    report_id = uuid.uuid4().hex[:12]
    raw_html = data.get("html", "")
    entry = {
        "id": report_id,
        "user_id": user_id or "",
        "month": data.get("month"),
        "year": data.get("year"),
        "html": bleach.clean(
            raw_html,
            tags=_ALLOWED_HTML_TAGS,
            attributes=_ALLOWED_HTML_ATTRS,
            protocols=_ALLOWED_HTML_PROTOCOLS,
            strip=True,
        ),
        "created_at": datetime.now(UTC).isoformat(),
    }
    with _report_history_lock:
        _report_history.insert(0, entry)
        _report_history[:] = _report_history[:100]
    return api_success({"id": report_id})


@analytics_bp.route("/api/analytics/reports/history", methods=["GET"])
@admin_required
def api_analytics_report_history():
    user_id = request.args.get("user_id", "")
    with _report_history_lock:
        reports = [r for r in _report_history if not user_id or r.get("user_id") == user_id]
    safe = [{"id": r["id"], "month": r["month"], "year": r["year"], "created_at": r["created_at"]} for r in reports]
    return api_success({"reports": safe})


@analytics_bp.route("/api/analytics/report/<report_id>", methods=["GET"])
@admin_required
def api_analytics_get_report(report_id):
    with _report_history_lock:
        for r in _report_history:
            if r["id"] == report_id:
                return api_success({"html": r["html"]})
    return api_error("Report not found", 404)


@analytics_bp.route("/api/analytics/report/<report_id>/email", methods=["POST"])
@admin_required
def api_analytics_email_saved_report(report_id):
    with _report_history_lock:
        report = None
        for r in _report_history:
            if r["id"] == report_id:
                report = r
                break
    if not report:
        return api_error("Report not found", 404)
    return _send_report_email(report["html"], report["user_id"])


@analytics_bp.route("/api/analytics/report/email", methods=["POST"])
@admin_required
def api_analytics_email_report():
    data = request.json
    user_id = data.get("user_id")
    raw_html = data.get("html")
    if not user_id or not raw_html:
        return api_error("user_id and html are required", 400)
    html = bleach.clean(
        raw_html,
        tags=_ALLOWED_HTML_TAGS,
        attributes=_ALLOWED_HTML_ATTRS,
        protocols=_ALLOWED_HTML_PROTOCOLS,
        strip=True,
    )
    return _send_report_email(html, user_id)
