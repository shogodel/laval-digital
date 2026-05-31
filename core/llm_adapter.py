import logging
import threading
from typing import Any, Dict, List, Optional, Generator

import requests
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.language_models import BaseChatModel

from core.rate_limiter import check_rate_limits, count_tokens, log_usage, RateLimitExceeded

try:
    from langchain_litellm import ChatLiteLLM
except ImportError:
    ChatLiteLLM = None  # type: ignore

model_list: Optional[list[Any]] = None
try:
    from litellm import model_list as _litellm_model_list
    model_list = _litellm_model_list
except ImportError:
    pass

logger = logging.getLogger(__name__)

_FALLBACK_MODELS = [
    "deepseek-chat",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
    "claude-3.5-sonnet",
    "claude-3-opus-20240229",
    "claude-3-haiku-20240307",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "mistral-large-latest",
    "mistral-medium",
]


class LLMAdapterError(Exception):
    """Custom exception for LLMAdapter failures."""
    pass


LLM_TIMEOUT = 120

_MAX_CONCURRENT_LLM = 4
_llm_semaphore = threading.BoundedSemaphore(_MAX_CONCURRENT_LLM)


class LLMAdapter:
    """Production-grade multi-LLM adapter for LangGraph agents.

    Supports any model available via LiteLLM, with per-agent API key
    management and dynamic model discovery through litellm.model_list.
    """

    _available_models_cache: Optional[List[str]] = None

    def __init__(
        self,
        model: str,
        api_key: str,
        api_base: Optional[str] = None,
        temperature: float = 0.7
    ) -> None:
        """Initialize LLMAdapter.

        Args:
            model: LLM model identifier (e.g., 'gpt-4o', 'claude-3.5-sonnet').
            api_key: Provider API key for the selected model.
            api_base: Optional custom API base URL (e.g., for DeepSeek).
            temperature: Sampling temperature for LLM generation (0.0-1.0).

        Raises:
            ValueError: If model is not valid according to is_valid_model().
        """
        if not self.is_valid_model(model):
            raise ValueError(
                f"Unsupported model '{model}'. "
                f"Use get_available_models() to see all supported models."
            )
        self._model = model
        self._api_key = api_key
        self._api_base = api_base
        self._temperature = temperature
        logger.info("Initialized LLMAdapter for model: %s", model)

    @property
    def model(self) -> str:
        """Get the configured LLM model identifier.

        Returns:
            Model string passed during initialization.
        """
        return self._model

    @classmethod
    def get_available_models(cls) -> List[str]:
        """Return all available LLM model IDs via litellm.

        Results are cached on first call to avoid repeated lookups.

        Returns:
            Sorted list of model ID strings.
        """
        if cls._available_models_cache is not None:
            return cls._available_models_cache

        if model_list and isinstance(model_list, list):
            cls._available_models_cache = sorted(model_list)
            logger.info("Discovered %d models via litellm", len(cls._available_models_cache))
        else:
            cls._available_models_cache = _FALLBACK_MODELS
            logger.warning("litellm model_list unavailable, using %d fallback models", len(_FALLBACK_MODELS))

        return cls._available_models_cache

    @classmethod
    def is_valid_model(cls, model: str) -> bool:
        """Check if a given model string is valid.

        Args:
            model: Model identifier to validate.

        Returns:
            True if the model is in the available models list.
        """
        available = cls.get_available_models()
        return model in available

    @classmethod
    def detect_models(cls, api_key: str) -> Dict[str, Any]:
        """Detect provider from API key and return its available models.

        Uses key prefix heuristics to try the most likely provider first,
        falling back to other providers if the endpoint rejects the key.

        Args:
            api_key: Provider API key to test.

        Returns:
            Dict with 'provider' (str) and 'models' (list of str).
            'provider' is 'unknown' if no provider accepts the key.
        """
        providers: List[Dict[str, Any]] = [
            {
                "name": "anthropic",
                "url": "https://api.anthropic.com/v1/models",
                "headers": {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                "parse": lambda d: [m["name"] for m in d.get("data", [])],
            },
            {
                "name": "google",
                "url": "https://generativelanguage.googleapis.com/v1/models",
                "headers": {"X-Goog-Api-Key": api_key},
                "parse": lambda d: [m["name"] for m in d.get("models", [])],
            },
            {
                "name": "openai",
                "url": "https://api.openai.com/v1/models",
                "headers": {"Authorization": f"Bearer {api_key}"},
                "parse": lambda d: [m["id"] for m in d.get("data", [])],
            },
            {
                "name": "deepseek",
                "url": "https://api.deepseek.com/models",
                "headers": {"Authorization": f"Bearer {api_key}"},
                "parse": lambda d: [m["id"] for m in d.get("data", [])],
            },
            {
                "name": "mistral",
                "url": "https://api.mistral.ai/v1/models",
                "headers": {"Authorization": f"Bearer {api_key}"},
                "parse": lambda d: [m["id"] for m in d.get("data", [])],
            },
        ]

        if api_key.startswith("sk-ant-"):
            order = ["anthropic", "openai", "deepseek", "mistral", "google"]
        elif api_key.startswith("AIza"):
            order = ["google", "openai", "deepseek", "mistral", "anthropic"]
        else:
            order = ["openai", "deepseek", "mistral", "google", "anthropic"]

        provider_map = {p["name"]: p for p in providers}

        for name in order:
            p = provider_map.get(name)
            if not p:
                continue
            try:
                resp = requests.get(p["url"], headers=p["headers"], timeout=10)
                if resp.status_code == 200:
                    models = p["parse"](resp.json())
                    if models:
                        logger.info("Detected provider '%s' with %d models", name, len(models))
                        return {"provider": name, "models": sorted(models)}
            except (requests.RequestException, ValueError):
                logger.debug("Provider '%s' rejected the provided key", name)
                continue

        logger.warning("No provider accepted the provided API key")
        return {"provider": "unknown", "models": []}

    def _get_llm(self) -> BaseChatModel:
        """Create and return a configured chat model instance.

        DeepSeek models use ChatOpenAI pointed at the DeepSeek API — this is the
        only reliable authentication method for DeepSeek.
        All other models use ChatLiteLLM.
        """
        # DeepSeek: use ChatOpenAI (OpenAI-compatible endpoint)
        if self._model.startswith("deepseek"):
            from langchain_openai import ChatOpenAI

            from mcp._safe_url import is_safe_url as _is_safe_url
            api_base = self._api_base or "https://api.deepseek.com/v1"
            if not _is_safe_url(api_base):
                raise ValueError("api_base resolves to a private/reserved IP")

            return ChatOpenAI(
                model=self._model,
                api_key=self._api_key,
                base_url=api_base,
                temperature=self._temperature,
                timeout=120,
            )

        # All other models: use ChatLiteLLM
        if ChatLiteLLM is None:
            raise LLMAdapterError(
                "litellm is required for multi-LLM support. Install with: pip install litellm"
            )

        llm_kwargs: Dict[str, Any] = {
            "model": self._model,
            "api_key": self._api_key,
            "temperature": self._temperature,
            "timeout": LLM_TIMEOUT,
        }
        if self._api_base:
            llm_kwargs["api_base"] = self._api_base

        try:
            return ChatLiteLLM(**llm_kwargs)
        except Exception as e:
            raise LLMAdapterError(f"Failed to initialize LLM: {str(e)}") from e

    def invoke(self, system_prompt: str, user_message: str,
               user_id: int = 0, endpoint: str = "unknown",
               agent_id: Optional[str] = None, thread_id: Optional[str] = None) -> str:
        """Invoke the LLM with system prompt and user message.

        Args:
            system_prompt: System prompt to guide LLM behavior.
            user_message: User task or query to process.
            user_id: User ID for rate limiting and cost tracking (0 = anonymous/system).
            endpoint: Label identifying the caller (e.g. 'orchestrator', 'agent_chat').
            agent_id: Optional agent ID for usage logging.
            thread_id: Optional thread ID for usage logging.

        Returns:
            LLM response content as a string.

        Raises:
            LLMAdapterError: If LLM invocation fails for any reason.
            RateLimitExceeded: If user has exceeded rate or cost limits.
        """
        logger.debug("Invoking LLM %s with task: %s...", self._model, user_message[:50])

        if user_id > 0:
            check_rate_limits(user_id)

        prompt_tokens = count_tokens(system_prompt + user_message, self._model)

        if not _llm_semaphore.acquire(timeout=30):
            raise LLMAdapterError(
                f"System at capacity ({_MAX_CONCURRENT_LLM} concurrent LLM calls). "
                "Please retry later."
            )
        try:
            llm = self._get_llm()
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]
            response = llm.invoke(messages)
            completion = response.content if isinstance(response.content, str) else ""
            logger.debug("LLM response received: %s...", completion[:100])

            completion_tokens = count_tokens(completion, self._model)
            if user_id > 0:
                log_usage(user_id, self._model, prompt_tokens, completion_tokens,
                          endpoint=endpoint, agent_id=agent_id, thread_id=thread_id)

            return completion
        except RateLimitExceeded:
            raise
        except Exception as e:
            error_msg = f"LLM invocation failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise LLMAdapterError(error_msg) from e
        finally:
            _llm_semaphore.release()

    def stream(self, system_prompt: str, user_message: str,
               user_id: int = 0, endpoint: str = "unknown",
               agent_id: Optional[str] = None, thread_id: Optional[str] = None) -> Generator[str, None, None]:
        """Stream LLM response tokens in real-time.

        Args:
            system_prompt: System prompt to guide LLM behavior.
            user_message: User task or query to process.
            user_id: User ID for rate limiting and cost tracking (0 = anonymous/system).
            endpoint: Label identifying the caller (e.g. 'orchestrator', 'agent_chat').
            agent_id: Optional agent ID for usage logging.
            thread_id: Optional thread ID for usage logging.

        Yields:
            Individual tokens from the LLM response.

        Raises:
            LLMAdapterError: If LLM streaming fails for any reason.
            RateLimitExceeded: If user has exceeded rate or cost limits.
        """
        logger.debug("Streaming LLM %s with task: %s...", self._model, user_message[:50])

        if user_id > 0:
            check_rate_limits(user_id)

        prompt_tokens = count_tokens(system_prompt + user_message, self._model)
        collected: list[str] = []

        if not _llm_semaphore.acquire(timeout=30):
            raise LLMAdapterError(
                f"System at capacity ({_MAX_CONCURRENT_LLM} concurrent LLM calls). "
                "Please retry later."
            )
        try:
            llm = self._get_llm()
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]

            for chunk in llm.stream(messages):
                content_part = chunk.content if isinstance(chunk.content, str) else ""
                if content_part:
                    collected.append(content_part)
                    yield content_part

            completion = "".join(collected)
            completion_tokens = count_tokens(completion, self._model)
            if user_id > 0:
                log_usage(user_id, self._model, prompt_tokens, completion_tokens,
                          endpoint=endpoint, agent_id=agent_id, thread_id=thread_id)
        except RateLimitExceeded:
            raise
        except Exception as e:
            error_msg = f"LLM streaming failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise LLMAdapterError(error_msg) from e
        finally:
            _llm_semaphore.release()
