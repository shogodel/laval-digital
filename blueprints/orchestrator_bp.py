"""Blueprint for orchestrator, tasks, approvals, dashboard/ask, inbox, events, threads."""
import json
import logging
import uuid
from datetime import UTC, datetime

from flask import Blueprint, request, session
from flask_login import current_user

from blueprints._shared import AGENT_PERSONALITIES, _safe_tenant_id
from core import database
from core.api_helpers import api_error, api_success
from core.app_state import (
    get_agent_registry,
    get_current_user_id,
    get_executioner,
    get_orchestrator,
    safe_error,
    safe_int,
)
from core.auth import admin_required
from core.events import get_event_bus


logger = logging.getLogger(__name__)
orchestrator_bp = Blueprint("orchestrator", __name__)


@orchestrator_bp.route("/api/tasks", methods=["POST"])
@admin_required
def submit_task():
    data = request.json or {}
    user_request = data.get("request", "").strip()

    if not user_request:
        return api_error("No request provided", 400)

    thread_id = data.get("thread_id", str(uuid.uuid4()))
    language = data.get("language", "")

    try:
        orch = get_orchestrator()

        user_id = get_current_user_id()
        autonomy_config = None
        if user_id:
            conn = database._get_conn()
            rows = conn.execute(
                "SELECT agent_id, autonomy, confidence_threshold FROM agent_configs WHERE user_id = ?",
                (safe_int(user_id),),
            ).fetchall()
            autonomy_config = {
                r["agent_id"]: {"autonomy": r["autonomy"], "confidence_threshold": r["confidence_threshold"]}
                for r in rows
            }

        conversation_history: list = []
        if user_id:
            cursor = conn.execute(
                "SELECT agent_task, agent_draft FROM threads WHERE thread_id = ? AND user_id = ? AND status = 'chat' ORDER BY created_at ASC",
                (thread_id, safe_int(user_id)),
            )
            for row in cursor.fetchall():
                if row["agent_task"]:
                    conversation_history.append({"role": "user", "content": row["agent_task"]})
                if row["agent_draft"]:
                    conversation_history.append({"role": "assistant", "content": row["agent_draft"]})

        result = orch.process_message(
            user_request, thread_id,
            language=language or None,
            autonomy_config=autonomy_config,
            user_id=safe_int(user_id) if user_id else 0,
            conversation_history=conversation_history[-20:],
        )

        return api_success(result)
    except Exception as e:
        logger.error("Task failed: %s", e, exc_info=True)
        return api_error("I had trouble processing that request. Please try again.", 500, data={
            "response": "I had trouble processing that request. Please try again.",
            "agent": "error",
            "status": "error",
            "thread_id": thread_id,
            "pending_approval": False
        })


@orchestrator_bp.route("/api/approvals", methods=["GET"])
@admin_required
def get_approvals():
    orch = get_orchestrator()
    user_id = get_current_user_id()
    approvals = []
    for thread_id, draft_info in orch.get_pending_drafts(user_id).items():
        approvals.append({
            "thread_id": thread_id,
            "agent": draft_info.get("agent", "unknown"),
            "draft": draft_info.get("draft", ""),
            "task": draft_info.get("task", "")
        })
    logger.info("Returning %d pending approvals", len(approvals))
    return api_success({"approvals": approvals})


@orchestrator_bp.route("/api/approvals/<thread_id>/respond", methods=["POST"])
def respond_approval(thread_id):
    tenant_id = get_current_user_id()
    if not tenant_id:
        return api_error("Authentication required", 401)
    data = request.json or {}
    approved = data.get("approved", False)
    now_iso = datetime.now(UTC).isoformat()

    orch = get_orchestrator()

    drafts = orch.get_pending_drafts(tenant_id)
    if thread_id in drafts:
        result = orch.handle_approval(thread_id, approved=approved)
        # Mark thread approved in DB so the DB-fallback path
        # does not re-execute the same draft.
        uid = _safe_tenant_id(tenant_id)
        if uid is not None:
            try:
                conn = database._get_conn()
                conn.execute(
                    "UPDATE threads SET approved = ?, status = 'completed', updated_at = ? WHERE thread_id = ? AND user_id = ?",
                    (int(approved), datetime.now(UTC).isoformat(), thread_id, uid),
                )
                conn.commit()
            except Exception as e:
                logger.warning("Failed to update thread approval status: %s", e)
        return api_success({
            "thread_id": thread_id,
            "status": "completed" if approved else "rejected",
            "execution": result.get("execution"),
            "response": result.get("response"),
        })

    uid = _safe_tenant_id(tenant_id)
    if uid is None:
        return api_error("Invalid tenant", 400)
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT routed_agent, agent_draft, approved FROM threads WHERE thread_id = ? AND user_id = ?",
            (thread_id, uid),
        )
        row = cursor.fetchone()
        if not row:
            return api_error("Thread not found", 404)

        if row["approved"]:
            return api_success({
                "thread_id": thread_id,
                "status": "already_processed",
                "execution": None,
            })

        agent_name = row["routed_agent"]
        draft = row["agent_draft"]
        execution_result = None

        cursor.execute(
            "UPDATE threads SET approved = ?, status = 'completed', updated_at = ? WHERE thread_id = ? AND user_id = ?",
            (int(approved), now_iso, thread_id, uid),
        )
        conn.commit()

        if approved and agent_name and agent_name in get_agent_registry():
            exec_result = None
            try:
                exec_result = get_executioner().execute(agent_name, draft)
            except Exception as exec_err:
                exec_result = {"success": False, "error": str(exec_err)}

            execution_result = {
                "success": exec_result.get("success", False),
                "result": exec_result.get("result", "")
            }

        return api_success({
            "thread_id": thread_id,
            "status": "completed",
            "execution": execution_result
        })
    except Exception as e:
        return safe_error(e, 500)


@orchestrator_bp.route("/api/orchestrator/panic", methods=["POST"])
@admin_required
def api_panic():
    orch = get_orchestrator()
    orch.panic()
    return api_success({"status": "panicked", "message": "All agents stopped."})


@orchestrator_bp.route("/api/orchestrator/resume", methods=["POST"])
@admin_required
def api_resume():
    orch = get_orchestrator()
    orch.clear_panic()
    return api_success({"status": "active", "message": "Agents resumed."})


@orchestrator_bp.route("/api/orchestrator/status", methods=["GET"])
@admin_required
def api_orchestrator_status():
    orch = get_orchestrator()
    user_id = get_current_user_id()
    return api_success({
        "panicked": orch.is_panicked,
        "pending_drafts": len(orch.get_pending_drafts(user_id)),
        "activity_count": len(orch.get_activity_feed(200)),
    })


@orchestrator_bp.route("/api/orchestrator/activity", methods=["GET"])
@admin_required
def api_activity():
    limit = request.args.get("limit", 50, type=int)
    orch = get_orchestrator()
    return api_success({"activities": orch.get_activity_feed(limit)})


@orchestrator_bp.route("/api/orchestrator/undo", methods=["POST"])
@admin_required
def api_undo():
    orch = get_orchestrator()
    result = orch.undo_last()
    return api_success(result) if result else api_success({"action": "nothing_to_undo"})


@orchestrator_bp.route("/api/dashboard/ask", methods=["POST"])
@admin_required
def api_dashboard_ask():
    data = request.json
    query = (data or {}).get("query", "").strip()
    if not query:
        return api_error("No query provided", 400)
    lang = "fr" if (session.get("lang") == "fr" or (request.accept_languages and request.accept_languages.best and request.accept_languages.best.startswith("fr"))) else "en"
    try:
        orch = get_orchestrator()
        user_id = get_current_user_id()
        autonomy_config = None
        if user_id:
            conn = database._get_conn()
            rows = conn.execute(
                "SELECT agent_id, autonomy, confidence_threshold FROM agent_configs WHERE user_id = ?",
                (safe_int(user_id),),
            ).fetchall()
            autonomy_config = {
                r["agent_id"]: {"autonomy": r["autonomy"], "confidence_threshold": r["confidence_threshold"]}
                for r in rows
            }

        result = orch.process_message(
            user_message=query,
            thread_id="frankie-" + uuid.uuid4().hex[:8],
            language=lang if lang else None,
            autonomy_config=autonomy_config,
            user_id=safe_int(user_id) if user_id else 0,
            source="frankie",
        )

        status = result.get("status", "error")
        response = result.get("response", "")

        if status == "pending_approval":
            agent = result.get("agent", "agent")
            p = AGENT_PERSONALITIES.get(agent, {})
            emoji = p.get("emoji", "\U0001f916")
            draft_preview = (response or "")[:200]
            en = f"{emoji} I asked **{p.get('short', agent)}** to handle this. Here's the draft:\n\n{draft_preview}\n\n---\n\nYou can **approve** or **reject** it in the Tasks tab."
            fr = f"{emoji} J'ai demand\u00e9 \u00e0 **{p.get('short_fr', agent)}** de s'en occuper. Voici le projet :\n\n{draft_preview}\n\n---\n\nVous pouvez **approuver** ou **rejeter** dans l'onglet T\u00e2ches."
            return api_success({"response": fr if lang == "fr" else en, "pending_approval": True, "agent": agent, "thread_id": result.get("thread_id")})
        elif status == "auto_executed":
            agent = result.get("agent", "agent")
            p = AGENT_PERSONALITIES.get(agent, {})
            emoji = p.get("emoji", "\u2705")
            en = f"{emoji} Done! **{p.get('short', agent)}** handled it automatically."
            fr = f"{emoji} Termin\u00e9 ! **{p.get('short_fr', agent)}** s'en est occup\u00e9 automatiquement."
            return api_success({"response": fr if lang == "fr" else en})
        elif status == "executed_silent":
            return api_success({"response": "\u2705 Done."})
        elif status == "error":
            return api_success({"response": response or "I couldn't process that."})
        else:
            return api_success({"response": response or "Done."})
    except Exception as e:
        logger.error("Frankie query failed: %s", e, exc_info=True)
        fallback = "Je n'ai pas pu traiter \u00e7a. Essayez de me parler des agents, des approbations ou de l'activit\u00e9 r\u00e9cente." if lang == "fr" else "I couldn't process that. Try asking about agents, approvals, or recent activity."
        return api_success({"response": fallback})


@orchestrator_bp.route("/api/inbox", methods=["GET"])
@admin_required
def api_inbox():
    limit = request.args.get("limit", 50, type=int)
    orch = get_orchestrator()
    user_id = session.get("active_user_id")
    uid = _safe_tenant_id(user_id) if user_id else None
    items = []

    for tid, info in orch.get_pending_drafts(uid).items():
        items.append({
            "type": "approval",
            "agent": info.get("agent", "?"),
            "summary": (info.get("draft", "") or "")[:120],
            "thread_id": tid,
            "created_at": info.get("created_at", ""),
            "icon": "\U0001f914",
        })

    for a in orch.get_activity_feed(limit):
        items.append({
            "type": "activity",
            "agent": a.get("agent", "?"),
            "summary": a.get("draft_preview", "")[:120],
            "action": a.get("action", ""),
            "created_at": a.get("timestamp", ""),
            "icon": "\u2705" if a.get("success") else "\u274c",
        })

    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return api_success({"items": items[:limit]})


@orchestrator_bp.route("/api/events/stream")
@admin_required
def api_events_stream():
    event_bus = get_event_bus()
    q = event_bus.subscribe()

    def generate():
        from queue import Empty as _QueueEmpty
        try:
            while True:
                try:
                    event = q.get(timeout=10)
                    yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                except _QueueEmpty:
                    yield f"event: heartbeat\ndata: {{\"ts\": \"{datetime.now(UTC).isoformat()}\"}}\n\n"
        except GeneratorExit:
            event_bus.unsubscribe(q)

    from flask import current_app as app
    return app.response_class(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@orchestrator_bp.route("/api/events/history", methods=["GET"])
@admin_required
def api_events_history():
    limit = request.args.get("limit", 100, type=int)
    event_type = request.args.get("type", "").strip() or None
    agent = request.args.get("agent", "").strip() or None
    events = get_event_bus().get_history(limit=limit, event_type=event_type, agent=agent)
    return api_success({"events": events})


@orchestrator_bp.route("/api/events/stats", methods=["GET"])
@admin_required
def api_events_stats():
    return api_success(get_event_bus().get_stats())


@orchestrator_bp.route("/api/threads")
def api_list_threads():
    if current_user.is_authenticated and current_user.role == "admin":
        tenant_id = session.get("active_user_id")
    else:
        tenant_id = getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return api_success({"threads": []})

    agent_filter = request.args.get("agent", "")
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        if agent_filter:
            cursor.execute(
                ("SELECT thread_id, agent_task, created_at FROM threads "
                 "WHERE status = 'chat' AND routed_agent = ? AND user_id = ? "
                 "ORDER BY created_at DESC LIMIT 50"),
                (agent_filter, safe_int(tenant_id)),
            )
        else:
            cursor.execute(
                "SELECT thread_id, agent_task, created_at FROM threads WHERE status = 'chat' AND user_id = ? ORDER BY created_at DESC LIMIT 50",
                (safe_int(tenant_id),)
            )
        rows = cursor.fetchall()
        return api_success({
            "threads": [
                {"thread_id": r["thread_id"], "agent_task": r["agent_task"], "created_at": r["created_at"]}
                for r in rows
            ]
        })
    except Exception as e:
        return safe_error(e, 500)


@orchestrator_bp.route("/api/threads/<thread_id>/messages")
def api_get_thread_messages(thread_id):
    if current_user.is_authenticated and current_user.role == "admin":
        tenant_id = session.get("active_user_id")
    else:
        tenant_id = getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return api_success({"messages": []})

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT agent_task, agent_draft, result FROM threads WHERE thread_id = ? AND user_id = ? AND status = 'chat' ORDER BY created_at ASC",
            (thread_id, safe_int(tenant_id)),
        )
        rows = cursor.fetchall()
        messages = []
        for r in rows:
            messages.append({"role": "user", "content": r["agent_task"]})
            messages.append({"role": "agent", "content": r["agent_draft"], "thinking": None})
        return api_success({"messages": messages})
    except Exception as e:
        return safe_error(e, 500)
