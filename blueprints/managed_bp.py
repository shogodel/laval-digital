"""Managed services blueprint — MRR, client management, bulk operations."""
import logging
import os
import uuid
from datetime import UTC, datetime

from flask import Blueprint, request
from flask_login import current_user

from core import database
from core.api_helpers import api_error, api_success
from core.app_state import get_agent_registry, get_executioner
from core.auth import admin_required, client_required

logger = logging.getLogger(__name__)

managed_bp = Blueprint("managed", __name__, url_prefix="")

MANAGED_MONTHLY_FEE = int(os.getenv("MANAGED_MONTHLY_FEE", "499"))


def _safe_int(val, default=0):
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


@managed_bp.route("/api/managed/upgrade", methods=["POST"])
@client_required
def api_managed_upgrade():
    """Upgrade the current client to managed services."""
    tenant_id = current_user.tenant_id
    now_iso = datetime.now(UTC).isoformat()
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE client_details SET managed_service = 1, managed_since = ? WHERE user_id = ?",
            (now_iso, _safe_int(tenant_id)),
        )
        conn.commit()

        try:
            cursor.execute(
                "INSERT INTO execution_log (user_id, execution_id, agent_name, tool_name, success, draft_preview, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_safe_int(tenant_id), str(uuid.uuid4()), "system", "managed_services", 1,
                 f"Client upgraded to Managed Services (${MANAGED_MONTHLY_FEE}/mo)", now_iso),
            )
            conn.commit()
        except Exception as e:
            logger.error("Silent exception in %s: %s", __name__, e)

        logger.info("Client %s upgraded to Managed Services", tenant_id)
        return api_success({"message": "Upgraded to Managed Services"})
    except Exception as e:
        logger.error("Failed to upgrade %s: %s", tenant_id, e)
        logger.error("Internal error: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 500)


@managed_bp.route("/api/managed/cancel", methods=["POST"])
@client_required
def api_managed_cancel():
    """Request cancellation of managed services (30-day notice)."""
    tenant_id = current_user.tenant_id
    now_iso = datetime.now(UTC).isoformat()
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE client_details SET managed_service = 0 WHERE user_id = ? AND managed_service = 1",
            (_safe_int(tenant_id),)
        )
        conn.commit()
        logger.info("Client %s cancelled Managed Services", tenant_id)
        try:
            cursor.execute(
                "INSERT INTO execution_log (user_id, execution_id, agent_name, tool_name, success, draft_preview, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_safe_int(tenant_id), str(uuid.uuid4()), "system", "managed_services", 1,
                 "Client cancelled Managed Services (30-day notice)", now_iso),
            )
            conn.commit()
        except Exception as e:
            logger.error("Silent exception in %s: %s", __name__, e)
        return api_success({"message": "Cancellation requested"})
    except Exception as e:
        logger.error("Failed to cancel managed for %s: %s", tenant_id, e)
        logger.error("Internal error: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 500)


@managed_bp.route("/api/managed/clients")
@admin_required
def api_managed_clients():
    filter_mode = request.args.get("filter", "active")
    all_tenants = [str(u["id"]) for u in database.list_users(role='user')]
    clients = []
    total_mrr = 0
    total_pending = 0
    past_due_count = 0

    for tid in all_tenants:
        try:
            conn = database._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT managed_service, managed_since, package FROM client_details WHERE user_id = ?",
                (int(tid),)
            )
            row = cursor.fetchone()
            if not row or not row.get("managed_service"):
                continue

            managed_since = row.get("managed_since")
            managed_since_str = managed_since[:10] if managed_since else None
            pkg = row.get("package", "")

            next_billing = None
            if managed_since:
                try:
                    from datetime import date as dt_date
                    ms_date = dt_date.fromisoformat(managed_since[:10])
                    from datetime import timedelta as td
                    next_date = ms_date + td(days=30)
                    while next_date < dt_date.today():
                        next_date += td(days=30)
                    next_billing = next_date.isoformat()
                except Exception as e:
                    logger.error("Silent exception in %s: %s", __name__, e)

            status = "active"
            if next_billing:
                try:
                    from datetime import date as dt_date
                    billing_dt = dt_date.fromisoformat(next_billing)
                    if billing_dt < dt_date.today():
                        status = "past_due"
                        past_due_count += 1
                except Exception as e:
                    logger.error("Silent exception in %s: %s", __name__, e)

            if filter_mode != "all" and status != filter_mode:
                continue

            total_mrr += MANAGED_MONTHLY_FEE

            try:
                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM threads WHERE user_id = ? AND status = 'pending_approval'",
                    (int(tid),)
                )
                pending_row = cursor.fetchone()
                pending_count = pending_row["cnt"] if pending_row else 0
                total_pending += pending_count
            except Exception:
                logger.warning("Failed to count pending approvals for tenant %s", tid, exc_info=True)
                pending_count = 0

            clients.append({
                "tenant_id": tid,
                "package": pkg,
                "managed_since": managed_since_str,
                "monthly_fee": MANAGED_MONTHLY_FEE,
                "next_billing": next_billing[:10] if next_billing else None,
                "status": status,
                "pending_approvals": pending_count,
            })
        except Exception:
            logger.warning("Failed to process managed client %s, skipping", tid, exc_info=True)
            continue

    return api_success({
        "clients": clients,
        "total_mrr": total_mrr,
        "total_pending_approvals": total_pending,
        "past_due_count": past_due_count,
    })


@managed_bp.route("/api/managed/pause", methods=["POST"])
@admin_required
def api_managed_pause():
    data = request.json
    tenant_id = data.get("tenant_id")
    if not tenant_id:
        return api_error("tenant_id required", 400)
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE client_details SET managed_service = 0 WHERE user_id = ? AND managed_service = 1",
            (_safe_int(tenant_id),)
        )
        conn.commit()
        logger.info("Admin paused Managed Services for %s", tenant_id)
        return api_success({"message": "Managed services paused"})
    except Exception as e:
        logger.error("Internal error: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 500)


@managed_bp.route("/api/managed/resume", methods=["POST"])
@admin_required
def api_managed_resume():
    data = request.json
    tenant_id = data.get("tenant_id")
    if not tenant_id:
        return api_error("tenant_id required", 400)
    now_iso = datetime.now(UTC).isoformat()
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE client_details SET managed_service = 1, managed_since = ? WHERE user_id = ?",
            (now_iso, _safe_int(tenant_id)),
        )
        conn.commit()
        logger.info("Admin resumed Managed Services for %s", tenant_id)
        return api_success({"message": "Managed services resumed"})
    except Exception as e:
        logger.error("Internal error: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 500)


@managed_bp.route("/api/managed/bulk-approve", methods=["POST"])
@admin_required
def api_managed_bulk_approve():
    data = request.json
    tenant_id = data.get("tenant_id")
    if not tenant_id:
        return api_error("tenant_id required", 400)
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT thread_id, routed_agent, agent_draft FROM threads WHERE user_id = ? AND status = 'pending_approval'",
            (_safe_int(tenant_id),)
        )
        pending = cursor.fetchall()
        approved_count = 0
        now_iso = datetime.now(UTC).isoformat()
        agent_registry = get_agent_registry()
        executioner = get_executioner()

        for row in pending:
            thread_id = row["thread_id"]
            agent_name = row["routed_agent"]
            draft = row["agent_draft"] or ""

            cursor.execute(
                "UPDATE threads SET approved = 1, status = 'completed', updated_at = ? WHERE thread_id = ? AND user_id = ?",
                (now_iso, thread_id, _safe_int(tenant_id)),
            )

            if agent_name and draft and agent_name in agent_registry:
                try:
                    exec_result = executioner.execute(agent_name, draft)
                    cursor.execute(
                        "INSERT INTO execution_log (user_id, execution_id, agent_name, tool_name, success, draft_preview, timestamp) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (_safe_int(tenant_id), str(uuid.uuid4()), agent_name, "managed_bulk_approve",
                         int(exec_result.get("success", False)),
                         (draft[:120] + "...") if len(draft) > 120 else draft, now_iso),
                    )
                except Exception as e:
                    logger.error("Silent exception in %s: %s", __name__, e)

            approved_count += 1

        conn.commit()
        logger.info("Bulk approved %d items for %s", approved_count, tenant_id)
        return api_success({
            "approved_count": approved_count,
            "message": f"Approved {approved_count} pending item(s)",
        })
    except Exception as e:
        logger.error("Bulk approve failed for %s: %s", tenant_id, e)
        logger.error("Internal error: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 500)


@managed_bp.route("/api/managed/mrr")
@admin_required
def api_managed_mrr():
    all_tenants = [str(u["id"]) for u in database.list_users(role='user')]
    active_count = 0
    for tid in all_tenants:
        try:
            conn = database._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT managed_service FROM client_details WHERE user_id = ?", (int(tid),))
            row = cursor.fetchone()
            if row and row.get("managed_service"):
                active_count += 1
        except Exception:
            logger.warning("Failed to check managed service for tenant %s, skipping", tid, exc_info=True)
            continue
    total_mrr = active_count * MANAGED_MONTHLY_FEE
    return api_success({
        "active_managed_clients": active_count,
        "monthly_fee": MANAGED_MONTHLY_FEE,
        "total_mrr": total_mrr,
    })
