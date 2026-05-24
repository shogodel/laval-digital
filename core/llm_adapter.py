import logging
from typing import Any, Dict, List, Optional, Generator

import requests
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.language_models import BaseChatModel

try:
    from langchain_litellm import ChatLiteLLM
except ImportError:
    ChatLiteLLM = None  # type: ignore

try:
    from litellm import model_list
except ImportError:
    model_list = None

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
        providers = [
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
            from urllib.parse import urlparse

            api_base = self._api_base or "https://api.deepseek.com/v1"
            parsed = urlparse(api_base)
            if parsed.hostname:
                import socket
                try:
                    addrs = socket.getaddrinfo(parsed.hostname, None)
                    for _, _, _, _, sockaddr in addrs:
                        ip = sockaddr[0]
                        ipv4 = ip.split(":")[-1] if ":" in ip else ip
                        if "." in ipv4:
                            parts = [int(x) for x in ipv4.split(".")]
                            if parts[0] in (127, 10, 0) or (parts[0] == 169 and parts[1] == 254) or (parts[0] == 192 and parts[1] == 168) or (parts[0] == 172 and 16 <= parts[1] <= 31) or (parts[0] == 100 and 64 <= parts[1] <= 127):
                                raise ValueError("api_base resolves to a private IP")
                        elif ":" in ip:
                            if ip.startswith("::1") or ip.startswith("fc") or ip.startswith("fd") or ip.startswith("fe80") or ip.startswith("ff") or ip.startswith("2001:db8"):
                                raise ValueError("api_base resolves to a private/reserved IPv6")
                            import ipaddress
                            if ipaddress.IPv6Address(ip).is_link_local:
                                raise ValueError("api_base resolves to a link-local IPv6")
                except (socket.gaierror, ValueError) as e:
                    raise ValueError(f"Invalid api_base: {e}")

            return ChatOpenAI(
                model=self._model,
                api_key=self._api_key,
                base_url=api_base,
                temperature=self._temperature,
            )

        # All other models: use ChatLiteLLM
        if ChatLiteLLM is None:
            raise LLMAdapterError(
                "litellm is required for multi-LLM support. Install with: pip install litellm"
            )

        llm_kwargs = {
            "model": self._model,
            "api_key": self._api_key,
            "temperature": self._temperature,
        }
        if self._api_base:
            llm_kwargs["api_base"] = self._api_base

        try:
            return ChatLiteLLM(**llm_kwargs)
        except Exception as e:
            raise LLMAdapterError(f"Failed to initialize LLM: {str(e)}") from e

    def invoke(self, system_prompt: str, user_message: str) -> str:
        """Invoke the LLM with system prompt and user message.

        Args:
            system_prompt: System prompt to guide LLM behavior.
            user_message: User task or query to process.

        Returns:
            LLM response content as a string.

        Raises:
            LLMAdapterError: If LLM invocation fails for any reason.
        """
        logger.debug("Invoking LLM %s with task: %s...", self._model, user_message[:50])

        try:
            llm = self._get_llm()
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]
            response = llm.invoke(messages)
            logger.debug("LLM response received: %s...", response.content[:100])
            return response.content
        except Exception as e:
            error_msg = f"LLM invocation failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise LLMAdapterError(error_msg) from e

    def stream(self, system_prompt: str, user_message: str) -> Generator[str, None, None]:
        """Stream LLM response tokens in real-time.

        Args:
            system_prompt: System prompt to guide LLM behavior.
            user_message: User task or query to process.

        Yields:
            Individual tokens from the LLM response.

        Raises:
            LLMAdapterError: If LLM streaming fails for any reason.
        """
        logger.debug("Streaming LLM %s with task: %s...", self._model, user_message[:50])

        try:
            llm = self._get_llm()
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]

            for chunk in llm.stream(messages):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            error_msg = f"LLM streaming failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise LLMAdapterError(error_msg) from e
