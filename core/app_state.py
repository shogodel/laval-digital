"""Shared application state — lazily imported to break circular imports.

All getters import from ``app`` at call time (when routes are actually
handled), by which point ``app.py`` is fully initialized.
"""

from typing import Any, Dict, Optional
from threading import Lock


def _get_app_attr(name: str):
    import importlib
    return getattr(importlib.import_module("app"), name)


# ── Agent / LLM state ─────────────────────────────────────────────────────

def get_agent_registry() -> dict:
    return _get_app_attr("agent_registry")


def get_llm_adapter():
    return _get_app_attr("llm_adapter")


def get_orchestrator():
    return _get_app_attr("get_orchestrator")()


def get_executioner():
    return _get_app_attr("executioner")


def get_push_manager():
    return _get_app_attr("push_manager")


def get_agent_memory():
    return _get_app_attr("agent_memory")


def get_speech_engine():
    return _get_app_attr("speech_engine")


def get_affiliate_manager():
    return _get_app_attr("affiliate_manager")


def get_scheduler_manager():
    return _get_app_attr("scheduler_manager")


def get_agent_meta() -> Dict[str, Dict[str, str]]:
    return _get_app_attr("AGENT_META")


def get_agent_configs() -> dict:
    return _get_app_attr("AGENT_CONFIGS")


def get_agent_personalities() -> dict:
    return _get_app_attr("AGENT_PERSONALITIES")


def get_email_bridge():
    return _get_app_attr("email_bridge")


def get_credential_cipher():
    return _get_app_attr("_credential_cipher")


# ── Helper functions ───────────────────────────────────────────────────────

def get_current_user_id() -> Optional[str]:
    return _get_app_attr("get_current_user_id")()


def safe_int(val, default=0) -> int:
    return _get_app_attr("_safe_int")(val, default)


def safe_error(e: Exception, status: int = 500):
    return _get_app_attr("_safe_error")(e, status)


def update_agent_activity(user_id: str, agent_id: str, **kwargs) -> None:
    return _get_app_attr("update_tenant_agent_activity")(user_id, agent_id, **kwargs)
