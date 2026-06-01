"""Shared application state — populated by app.py at boot time.

All getters reference module-level variables set once during startup,
avoiding fragile call-time importlib.import_module() patterns.
"""

from typing import Any

# Module-level state — set by app.py at boot time
_agent_registry: dict | None = None
_llm_adapter = None
_orchestrator_fn = None  # factory function (lazy-built singleton)
_executioner = None
_push_manager = None
_agent_memory = None
_speech_engine = None
_affiliate_manager = None
_scheduler_manager = None
_agent_meta: dict[str, dict[str, str]] | None = None
_agent_configs: dict | None = None
_agent_personalities: dict | None = None
_email_bridge = None
_credential_cipher = None
_current_user_id_fn = None
_safe_int_fn = None
_safe_error_fn = None
_update_agent_activity_fn = None
_safe_url_fn = None
_encrypt_credential_fn = None
_get_tenant_agent_activity_fn = None


def _require(name: str, value: Any):
    if value is None:
        raise RuntimeError(f"app_state.{name} accessed before boot — app.py must populate it first")
    return value


def init_agent_registry(v: dict): global _agent_registry; _agent_registry = v
def init_llm_adapter(v): global _llm_adapter; _llm_adapter = v
def init_orchestrator_fn(v): global _orchestrator_fn; _orchestrator_fn = v
def init_executioner(v): global _executioner; _executioner = v
def init_push_manager(v): global _push_manager; _push_manager = v
def init_agent_memory(v): global _agent_memory; _agent_memory = v
def init_speech_engine(v): global _speech_engine; _speech_engine = v
def init_affiliate_manager(v): global _affiliate_manager; _affiliate_manager = v
def init_scheduler_manager(v): global _scheduler_manager; _scheduler_manager = v
def init_agent_meta(v): global _agent_meta; _agent_meta = v
def init_agent_configs(v): global _agent_configs; _agent_configs = v
def init_agent_personalities(v): global _agent_personalities; _agent_personalities = v
def init_email_bridge(v): global _email_bridge; _email_bridge = v
def init_credential_cipher(v): global _credential_cipher; _credential_cipher = v
def init_current_user_id_fn(v): global _current_user_id_fn; _current_user_id_fn = v
def init_safe_int_fn(v): global _safe_int_fn; _safe_int_fn = v
def init_safe_error_fn(v): global _safe_error_fn; _safe_error_fn = v
def init_update_agent_activity_fn(v): global _update_agent_activity_fn; _update_agent_activity_fn = v
def init_safe_url_fn(v): global _safe_url_fn; _safe_url_fn = v
def init_encrypt_credential_fn(v): global _encrypt_credential_fn; _encrypt_credential_fn = v
def init_get_tenant_agent_activity_fn(v): global _get_tenant_agent_activity_fn; _get_tenant_agent_activity_fn = v


def get_agent_registry() -> dict:
    return _require("agent_registry", _agent_registry)


def get_llm_adapter():
    return _require("llm_adapter", _llm_adapter)


def get_orchestrator():
    return _require("orchestrator_fn", _orchestrator_fn)()


def get_executioner():
    return _require("executioner", _executioner)


def get_push_manager():
    return _require("push_manager", _push_manager)


def get_agent_memory():
    return _require("agent_memory", _agent_memory)


def get_speech_engine():
    return _require("speech_engine", _speech_engine)


def get_affiliate_manager():
    return _require("affiliate_manager", _affiliate_manager)


def get_scheduler_manager():
    return _require("scheduler_manager", _scheduler_manager)


def get_agent_meta() -> dict[str, dict[str, str]]:
    return _require("agent_meta", _agent_meta)


def get_agent_configs() -> dict:
    return _require("agent_configs", _agent_configs)


def get_agent_personalities() -> dict:
    return _require("agent_personalities", _agent_personalities)


def get_email_bridge():
    return _require("email_bridge", _email_bridge)


def get_credential_cipher():
    return _require("credential_cipher", _credential_cipher)


def get_current_user_id() -> str | None:
    return _require("current_user_id_fn", _current_user_id_fn)()


def safe_int(val, default=0) -> int:
    return _require("safe_int_fn", _safe_int_fn)(val, default)


def safe_error(e: Exception, status: int = 500):
    return _require("safe_error_fn", _safe_error_fn)(e, status)


def update_agent_activity(user_id: str, agent_id: str, **kwargs) -> None:
    return _require("update_agent_activity_fn", _update_agent_activity_fn)(user_id, agent_id, **kwargs)


def safe_url(url: str, timeout: int = 10):
    return _require("safe_url_fn", _safe_url_fn)(url, timeout)


def encrypt_credential(plaintext: str) -> str:
    return _require("encrypt_credential_fn", _encrypt_credential_fn)(plaintext)


def get_tenant_agent_activity(user_id: str) -> dict:
    return _require("get_tenant_agent_activity_fn", _get_tenant_agent_activity_fn)(user_id)
