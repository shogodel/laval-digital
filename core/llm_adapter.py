import logging
from typing import Optional, Generator

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.language_models import BaseChatModel

try:
    from litellm import ChatLiteLLM
except ImportError:
    ChatLiteLLM = None  # type: ignore

logger = logging.getLogger(__name__)

# SUPPORTED_MODELS identical to BaseAgent.VALID_MODELS format
SUPPORTED_MODELS = {
    "deepseek-chat": {
        "provider": "deepseek",
        "model": "deepseek-chat",
    },
    "gpt-4o": {
        "provider": "openai",
        "model": "gpt-4o",
    },
    "claude-3.5-sonnet": {
        "provider": "anthropic",
        "model": "claude-3.5-sonnet",
    },
}


class LLMAdapterError(Exception):
    """Custom exception for LLMAdapter failures."""
    pass


class LLMAdapter:
    """Production-grade multi-LLM adapter for LangGraph agents.

    Supports switching between DeepSeek, GPT-4o, and Claude 3.5 Sonnet
    via LiteLLM, with per-agent API key management and error handling.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        api_base: Optional[str] = None,
        temperature: float = 0.7
    ) -> None:
        """Initialize LLMAdapter.

        Args:
            model: LLM model identifier (must be in SUPPORTED_MODELS).
            api_key: Provider API key for the selected model.
            api_base: Optional custom API base URL (e.g., for DeepSeek).
            temperature: Sampling temperature for LLM generation (0.0-1.0).

        Raises:
            ValueError: If model is not in SUPPORTED_MODELS.
        """
        if model not in SUPPORTED_MODELS:
            raise ValueError(
                f"Unsupported model '{model}'. Valid models: {list(SUPPORTED_MODELS.keys())}"
            )
        self._model = model
        self._api_key = api_key
        self._api_base = api_base
        self._temperature = temperature
        logger.info(f"Initialized LLMAdapter for model: {model}")

    @property
    def model(self) -> str:
        """Get the configured LLM model identifier.

        Returns:
            Model string from SUPPORTED_MODELS.
        """
        return self._model

    def _get_llm(self) -> BaseChatModel:
        """Create and return a configured LiteLLM chat model instance.

        Returns:
            ChatLiteLLM instance configured for the agent's model.

        Raises:
            LLMAdapterError: If litellm is not installed or configuration is invalid.
        """
        if ChatLiteLLM is None:
            raise LLMAdapterError(
                "litellm is required for multi-LLM support. Install with: pip install litellm"
            )
        
        model_config = SUPPORTED_MODELS[self._model]
        llm_kwargs = {
            "model": f"{model_config['provider']}/{model_config['model']}",
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
        logger.debug(f"Invoking LLM {self._model} with task: {user_message[:50]}...")
        
        try:
            llm = self._get_llm()
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]
            response = llm.invoke(messages)
            logger.debug(f"LLM response received: {response.content[:100]}...")
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
        logger.debug(f"Streaming LLM {self._model} with task: {user_message[:50]}...")
        
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
