"""Blueprint for agent configuration, invocation, chat, and model discovery."""
import json
import logging
import uuid
from datetime import UTC, datetime

from flask import Blueprint, Response, request, stream_with_context
from flask_login import current_user

from core import database
from core.api_helpers import api_error, api_success
from core.app_state import (
    get_agent_configs,
    get_agent_registry,
    get_current_user_id,
    safe_error,
    safe_int,
    update_agent_activity,
)
from core.auth import admin_required
from core.llm_adapter import LLMAdapter

logger = logging.getLogger(__name__)
agents_bp = Blueprint("agents", __name__)


@agents_bp.route("/api/agents", methods=["GET"])
def get_agents():
    tenant_id = get_current_user_id()
    agents_status = []

    if tenant_id:
        from core.app_state import get_tenant_agent_activity
        activity = get_tenant_agent_activity(tenant_id)
        for agent_id, agent in get_agent_registry().items():
            act = activity.get(agent_id, {})
            agents_status.append({
                "agent_id": agent_id,
                "enabled": bool(act.get("enabled", agent.enabled)),
                "model": agent.model,
                "api_key": "",
                "status": act.get("status", "idle"),
                "last_invoked": act.get("last_invoked"),
                "task_count": act.get("task_count", 0),
                "success_count": act.get("success_count", 0),
                "failure_count": act.get("failure_count", 0),
                "last_draft_preview": act.get("last_draft_preview"),
            })
    else:
        for agent_id, agent in get_agent_registry().items():
            agents_status.append({
                "agent_id": agent_id,
                "enabled": agent.enabled,
                "model": agent.model,
                "api_key": "",
                "status": "idle",
                "last_invoked": None,
                "task_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "last_draft_preview": None,
            })

    return api_success({"agents": agents_status})


@agents_bp.route("/api/agents/<agent_id>", methods=["GET"])
def get_agent_stats(agent_id):
    if agent_id not in get_agent_registry():
        return api_error("Agent not found", 404)
    tenant_id = get_current_user_id()
    stats = {"agent_id": agent_id, "task_count": 0, "success_count": 0, "failure_count": 0, "enabled": None, "model": get_agent_registry()[agent_id].model}
    if tenant_id:
        try:
            conn = database._get_conn()
            row = conn.execute(
                "SELECT enabled, task_count, success_count, failure_count FROM agent_configs WHERE agent_id = ? AND user_id = ?",
                (agent_id, safe_int(tenant_id)),
            ).fetchone()
            if row:
                r = dict(row)
                r["enabled"] = bool(r["enabled"])
                stats.update(r)
        except Exception as e:
            logger.error("Silent exception in get_agent_stats: %s", e)
    return api_success(stats)


@agents_bp.route("/api/agents/<agent_id>/toggle", methods=["POST"])
@admin_required
def toggle_agent(agent_id):
    if agent_id not in get_agent_registry():
        return api_error("Agent not found", 404)

    agent = get_agent_registry()[agent_id]
    user_id = session.get("active_user_id") or (str(current_user.id) if not current_user.is_anonymous else None)
    enabled = not agent.enabled
    if user_id and user_id != "admin":
        try:
            conn = database._get_conn()
            uid = safe_int(user_id)
            row = conn.execute(
                "SELECT enabled FROM agent_configs WHERE agent_id = ? AND user_id = ?",
                (agent_id, uid),
            ).fetchone()
            current = bool(row["enabled"]) if row else None
            enabled = not current if current is not None else not agent.enabled
            cur = conn.execute(
                "UPDATE agent_configs SET enabled = ? WHERE agent_id = ? AND user_id = ?",
                (int(enabled), agent_id, uid),
            )
            if cur.rowcount == 0:
                conn.execute(
                    "INSERT INTO agent_configs (agent_id, user_id, enabled) VALUES (?, ?, ?)",
                    (agent_id, uid, int(enabled)),
                )
            conn.commit()
        except Exception as e:
            logger.error("Failed to persist toggle: %s", e)

    agent.enabled = enabled
    return api_success({"agent_id": agent_id, "enabled": enabled})


@agents_bp.route("/api/agents/<agent_id>/config", methods=["GET"])
@admin_required
def get_agent_config(agent_id):
    if agent_id not in get_agent_configs():
        return api_error("Agent not found", 404)
    config = get_agent_configs()[agent_id]
    api_key = config.get("credentials", {}).get("api_key", "")
    masked_key = ("****" + api_key[-4:]) if api_key and len(api_key) > 4 else ""
    return api_success({
        "agent_id": agent_id,
        "model": config.get("model", "deepseek-chat"),
        "api_key": masked_key,
        "api_base": config.get("credentials", {}).get("api_base", ""),
    })


@agents_bp.route("/api/models", methods=["GET"])
def get_available_models():
    try:
        models = LLMAdapter.get_available_models()
        return api_success({"models": models})
    except Exception:
        logger.warning("Failed to fetch models from LLM provider, using fallback list", exc_info=True)
        return api_success({
            "models": ["deepseek-chat", "gpt-4o", "claude-3.5-sonnet"]
        })


@agents_bp.route("/api/models/detect", methods=["POST"])
def detect_models():
    data = request.json or {}
    api_key = data.get("api_key", "")
    if not api_key:
        return api_error("API key is required", 400)
    try:
        result = LLMAdapter.detect_models(api_key)
        return api_success(result)
    except Exception as e:
        logger.error("Model detection failed: %s", type(e).__name__)
        return api_error("Model detection failed.", 500, data={"provider": "unknown", "models": []})


@agents_bp.route("/api/executions", methods=["GET"])
@admin_required
def get_executions():
    limit = request.args.get("limit", 50, type=int)
    from core.app_state import get_executioner
    history = get_executioner().get_execution_history(limit)
    return api_success({"executions": history})


@agents_bp.route("/api/agents/<agent_id>/autonomy", methods=["GET", "PUT"])
@admin_required
def api_agent_autonomy(agent_id):
    user_id = get_current_user_id()
    if not user_id:
        return api_error("No user selected", 400)

    conn = database._get_conn()
    uid = safe_int(user_id)

    if request.method == "PUT":
        data = request.json
        if not data:
            return api_error("No data provided", 400)

        autonomy = data.get("autonomy", "manual")
        threshold = float(data.get("confidence_threshold", 0.7))

        if autonomy not in ("manual", "suggest", "auto", "silent"):
            return api_error(f"Invalid autonomy '{autonomy}'. Must be one of: manual, suggest, auto, silent", 400)

        conn.execute(
            "UPDATE agent_configs SET autonomy = ?, confidence_threshold = ? WHERE user_id = ? AND agent_id = ?",
            (autonomy, threshold, uid, agent_id),
        )
        conn.commit()
        return api_success({"agent_id": agent_id, "autonomy": autonomy, "confidence_threshold": threshold})

    rows = conn.execute(
        "SELECT agent_id, autonomy, confidence_threshold FROM agent_configs WHERE user_id = ?",
        (uid,),
    ).fetchall()
    configs = {r["agent_id"]: {"autonomy": r["autonomy"], "confidence_threshold": r["confidence_threshold"]} for r in rows}
    cfg = configs.get(agent_id, {"autonomy": "manual", "confidence_threshold": 0.7})
    return api_success({"agent_id": agent_id, **cfg})


@agents_bp.route("/api/agents/autonomy/bulk", methods=["GET"])
@admin_required
def api_all_agent_autonomy():
    user_id = get_current_user_id()
    if not user_id:
        return api_error("No user selected", 400)
    conn = database._get_conn()
    rows = conn.execute(
        "SELECT agent_id, autonomy, confidence_threshold FROM agent_configs WHERE user_id = ?",
        (safe_int(user_id),),
    ).fetchall()
    configs = {r["agent_id"]: {"autonomy": r["autonomy"], "confidence_threshold": r["confidence_threshold"]} for r in rows}
    return api_success({"autonomy": configs})


@agents_bp.route("/api/agents/<agent_id>/invoke", methods=["POST"])
@admin_required
def invoke_agent(agent_id):
    if agent_id not in get_agent_registry():
        return api_error("Agent not found", 404)

    agent = get_agent_registry()[agent_id]

    if not agent.enabled:
        return api_error("Agent is disabled", 403)

    data = request.json or {}
    task = data.get("task")

    if not task:
        return api_error("No task provided", 400)

    tenant_id = get_current_user_id()
    now_iso = datetime.now(UTC).isoformat()

    try:
        if tenant_id:
            try:
                update_agent_activity(tenant_id, agent_id, status="processing")
            except Exception as e:
                logger.error("Silent exception in invoke_agent: %s", e)

        result = agent.invoke_llm(task)
        draft = result.get("draft_output", "")
        draft_preview = (draft[:120] + "...") if len(draft) > 120 else draft

        if tenant_id:
            try:
                update_agent_activity(
                    tenant_id, agent_id,
                    status="idle", last_invoked=now_iso,
                    last_draft_preview=draft_preview,
                )
            except Exception as e:
                logger.error("Silent exception in invoke_agent: %s", e)

        return api_success({"agent_id": agent_id, "result": result})
    except Exception as e:
        if tenant_id:
            try:
                update_agent_activity(tenant_id, agent_id, status="idle")
            except Exception as e:
                logger.warning("Failed to reset agent activity for tenant %s agent %s: %s", tenant_id, agent_id, e)
        return safe_error(e, 500)


@agents_bp.route("/api/agents/<agent_id>/chat", methods=["POST"])
@admin_required
def agent_chat(agent_id):
    if agent_id not in get_agent_registry():
        return api_error(f"Agent '{agent_id}' not found", 404)

    agent = get_agent_registry()[agent_id]
    if not agent.enabled:
        return api_error("Agent is disabled", 403)

    data = request.json
    if not data:
        return api_error("No data provided", 400)

    message = data.get("message", "").strip()
    thread_id = data.get("thread_id", str(uuid.uuid4()))
    language = data.get("language", "")

    if not message:
        return api_error("No message provided", 400)

    if not language:
        from core.base_agent import BaseAgent
        language = BaseAgent._detect_language(message)

    tenant_id = get_current_user_id()
    now_iso = datetime.now(UTC).isoformat()

    conversation_context = ""
    if tenant_id:
        try:
            uid = safe_int(tenant_id)
            conn = database._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT agent_task, agent_draft FROM threads WHERE thread_id = ? AND user_id = ? ORDER BY created_at ASC LIMIT 20",
                (thread_id, uid)
            )
            history = cursor.fetchall()
            if history:
                conversation_context = "\n\n--- Previous conversation in this thread ---\n"
                for row in history:
                    conversation_context += f"User: {row['agent_task']}\nAgent: {row['agent_draft'][:300]}...\n"
                conversation_context += "--- End of history ---\n\n"
        except Exception as e:
            logger.error("Silent exception in agent_chat: %s", e)

    full_task = f"{conversation_context}Current request: {message}" if conversation_context else message
    stream = data.get("stream", False)

    def _store_draft(draft_text: str) -> None:
        if tenant_id:
            try:
                uid = safe_int(tenant_id)
                conn = database._get_conn()
                conn.execute(
                    """INSERT INTO threads
                       (thread_id, routed_agent, agent_task, agent_draft, status, created_at, updated_at, user_id)
                       VALUES (?, ?, ?, ?, 'chat', ?, ?, ?)""",
                    (thread_id, agent_id, message, draft_text, now_iso, now_iso, uid),
                )
                conn.commit()
                update_agent_activity(
                    tenant_id, agent_id,
                    status="idle", last_invoked=now_iso,
                    last_draft_preview=(draft_text[:120] + "...") if len(draft_text) > 120 else draft_text,
                )
            except Exception as e:
                logger.error("Silent exception in _store_draft: %s", e)

    try:
        if stream:
            def generate():
                collected: list[str] = []
                for item in agent.stream_llm(full_task):
                    if isinstance(item, str):
                        collected.append(item)
                        yield f"data: {json.dumps({'type': 'token', 'content': item})}\n\n"
                    else:
                        draft = item.get("draft_output", "")
                        thinking = f"Agent '{agent_id}' processed your request using model '{agent.model}'."
                        _store_draft(draft)
                        yield f"data: {json.dumps({'type': 'done', 'response': draft, 'thread_id': thread_id, 'language': language, 'thinking': thinking, 'model': agent.model})}\n\n"
            return Response(stream_with_context(generate()), mimetype='text/event-stream')
        else:
            result = agent.invoke_llm(full_task)
            draft = result.get("draft_output", "")
            _store_draft(draft)
            return api_success({
                "agent_id": agent_id,
                "response": draft,
                "thread_id": thread_id,
                "language": language,
                "thinking": f"Agent '{agent_id}' processed your request using model '{agent.model}'. The agent applied its specialized system prompt to generate this response.",
                "model": agent.model,
            })
    except Exception as e:
        logger.error("Agent chat failed for %s: %s", agent_id, e)
        return safe_error(e, 500)


@agents_bp.route("/api/agents/<agent_id>/threads", methods=["GET"])
def get_agent_threads(agent_id):
    if agent_id not in get_agent_registry():
        return api_error(f"Agent '{agent_id}' not found", 404)

    tenant_id = get_current_user_id()
    if not tenant_id:
        return api_success({"threads": []})

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT DISTINCT thread_id,
                      MIN(created_at) as started_at,
                      (SELECT agent_task FROM threads t2 WHERE t2.thread_id = threads.thread_id ORDER BY created_at ASC LIMIT 1) as first_message
               FROM threads
               WHERE routed_agent = ? AND user_id = ? AND status = 'chat'
               GROUP BY thread_id
               ORDER BY started_at DESC LIMIT 30""",
            (agent_id, safe_int(tenant_id))
        )
        threads = []
        for row in cursor.fetchall():
            threads.append({
                "thread_id": row["thread_id"],
                "started_at": row["started_at"],
                "first_message": (row["first_message"] or "")[:80] + "..." if row["first_message"] and len(row["first_message"]) > 80 else (row["first_message"] or "New conversation"),
            })
        return api_success({"threads": threads})
    except Exception as e:
        return safe_error(e, 500)


@agents_bp.route("/api/agents/<agent_id>/threads/<thread_id>", methods=["GET"])
def get_agent_thread_history(agent_id, thread_id):
    if agent_id not in get_agent_registry():
        return api_error(f"Agent '{agent_id}' not found", 404)

    tenant_id = get_current_user_id()
    if not tenant_id:
        return api_success({"messages": []})

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT agent_task, agent_draft, created_at
               FROM threads
               WHERE thread_id = ? AND user_id = ? AND routed_agent = ?
               ORDER BY created_at ASC""",
            (thread_id, safe_int(tenant_id), agent_id)
        )
        messages = []
        for row in cursor.fetchall():
            messages.append({
                "role": "user",
                "content": row["agent_task"],
                "timestamp": row["created_at"],
            })
            messages.append({
                "role": "agent",
                "content": row["agent_draft"],
                "timestamp": row["created_at"],
            })
        return api_success({"messages": messages, "thread_id": thread_id, "agent_id": agent_id})
    except Exception as e:
        return safe_error(e, 500)
