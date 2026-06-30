"""Blueprint for schedule CRUD endpoints."""
import logging

from flask import Blueprint, request

from core.api_helpers import api_error, api_success
from core.app_state import get_scheduler_manager, safe_int


logger = logging.getLogger(__name__)
schedules_bp = Blueprint("schedules", __name__)


@schedules_bp.route("/api/schedules", methods=["GET"])
def api_list_schedules():
    tenant_id = request.args.get("tenant_id", "")
    schedules = get_scheduler_manager().get_schedules(user_id=safe_int(tenant_id) if tenant_id else None)
    return api_success({"schedules": schedules, "enabled": get_scheduler_manager().enabled})


@schedules_bp.route("/api/schedules", methods=["POST"])
def api_create_schedule():
    data = request.json
    if not data:
        return api_error("No data", 400)
    tenant_id = data.get("tenant_id", "")
    agent_id = data.get("agent_id", "")
    task = data.get("task", "")
    cron = data.get("cron", "")
    lang = data.get("language", "en")
    if not all([tenant_id, agent_id, task, cron]):
        return api_error("tenant_id, agent_id, task, and cron are required", 400)
    sid = get_scheduler_manager().create_schedule(safe_int(tenant_id), agent_id, task, cron, lang)
    return api_success({"id": sid}, status_code=201)


@schedules_bp.route("/api/schedules/<schedule_id>", methods=["DELETE"])
def api_delete_schedule(schedule_id):
    ok = get_scheduler_manager().delete_schedule(schedule_id)
    return api_success({"success": ok})


@schedules_bp.route("/api/schedules/<schedule_id>/toggle", methods=["POST"])
def api_toggle_schedule(schedule_id):
    data = request.json
    enabled = (data or {}).get("enabled", True)
    ok = get_scheduler_manager().toggle_schedule(schedule_id, enabled)
    return api_success({"success": ok})
