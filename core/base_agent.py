import logging
import re
import threading
from pathlib import Path
from typing import Any

from core.llm_adapter import LLMAdapter

logger = logging.getLogger(__name__)

FRENCH_KEYWORDS = [
    'bonjour', 'salut', 'bjr', 'allo',
    'je', 'tu', 'il', 'elle', 'on', 'nous', 'vous', 'ils', 'elles',
    'le', 'la', 'les', 'un', 'une', 'des', 'du', 'ce', 'ces',
    'mon', 'ton', 'son', 'ma', 'ta', 'sa',
    'est', 'sont', 'dans', 'avec', 'pour', 'sur', 'par',
    'comment', 'français', 'parle', 'parler', 'parlez',
    'aide', 'aidez', 'merci', 'svp', 's\'il vous plaît',
    'peux', 'peut', 'veux', 'veut', 'fait', 'faire',
    'quoi', 'qui', 'où', 'quand', 'pourquoi', 'combien',
    'ça', 'cela', 'notre', 'votre', 'leur',
]


class BaseAgent:
    _available_models: list[str] | None = None
    _models_lock = threading.Lock()

    def __init__(self, agent_id: str, config: dict[str, Any]):
        with BaseAgent._models_lock:
            if BaseAgent._available_models is None:
                BaseAgent._available_models = LLMAdapter.get_available_models()

        self._agent_id = agent_id
        self._config = config
        self._validate_config()

        self._enabled = config.get("enabled", True)
        self._enabled_lock = threading.Lock()

        self._model = config["model"]
        self._system_prompt_file = config["system_prompt_file"]
        self._credentials = config.get("credentials", {})
        self._system_prompt = self._load_system_prompt()
        self._logger = logging.getLogger(self.__class__.__module__)
        self._logger.info("%s initialized: %s", self.__class__.__name__, agent_id)

    def _validate_config(self) -> None:
        required_fields = ["agent_id", "model", "system_prompt_file"]
        for field in required_fields:
            if field not in self._config:
                raise ValueError(f"Missing required config field: '{field}'")

        if self._config["model"] not in (BaseAgent._available_models or []):
            raise ValueError(
                f"Invalid model '{self._config['model']}'. "
                f"Valid models: {BaseAgent._available_models}"
            )

    def _load_system_prompt(self) -> str:
        raw_path = Path(self._system_prompt_file)
        if raw_path.is_symlink():
            raise ValueError(f"System prompt path must not be a symlink: {self._system_prompt_file}")
        path = raw_path.resolve()
        prompts_dir = Path("prompts").resolve()
        if not str(path).startswith(str(prompts_dir) + "/"):
            raise ValueError(f"System prompt file must be within prompts/ directory: {self._system_prompt_file}")
        if not path.exists():
            raise FileNotFoundError(f"System prompt file not found: {path}")
        if not path.is_file():
            raise ValueError(f"System prompt path is not a file: {path}")
        return path.read_text(encoding="utf-8").strip()

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def enabled(self) -> bool:
        with self._enabled_lock:
            return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        with self._enabled_lock:
            self._enabled = value

    @property
    def model(self) -> str:
        return self._model

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    def _get_llm_adapter(self) -> LLMAdapter:
        api_key = self._credentials.get("api_key", "")
        if not api_key:
            raise ValueError(
                "No API key configured. Go to Admin → Settings → Configuration to enter your LLM provider API key."
            )
        return LLMAdapter(
            model=self._model,
            api_key=api_key,
            api_base=self._credentials.get("api_base"),
            temperature=0.7,
        )

    @staticmethod
    def _detect_language(task: str) -> str:
        text_lower = task.lower()
        french_count = sum(1 for kw in FRENCH_KEYWORDS if re.search(r'\b' + re.escape(kw) + r'\b', text_lower))
        return "fr" if french_count >= 3 else "en"

    @staticmethod
    def _get_language_instruction(task: str) -> str:
        lang = BaseAgent._detect_language(task)
        if lang == "fr":
            return "IMPORTANT: The user is communicating in French. You MUST respond entirely in French. Use proper French grammar and vocabulary."
        return "IMPORTANT: Respond in English."

    @staticmethod
    def _parse_confidence(draft: str) -> float:
        """Extract confidence score from the end of an agent's draft.

        Expects the draft to end with ``CONFIDENCE: <0-100>`` (optionally
        followed by a ``REASONING:`` line). Returns 0.0 if not found.
        """
        match = re.search(r'CONFIDENCE\s*:\s*(\d{1,3})', draft)
        if match:
            score = int(match.group(1))
            return max(0.0, min(1.0, score / 100.0))
        return 0.0

    @staticmethod
    def _strip_confidence_metadata(draft: str) -> str:
        """Remove CONFIDENCE and REASONING metadata lines from the end of a draft."""
        lines = draft.rstrip().split("\n")
        cleaned = [line for line in lines if not re.match(
            r'^\s*(CONFIDENCE|REASONING)\s*:', line
        )]
        return "\n".join(cleaned).strip()

    def _build_system_content(self, task: str) -> str:
        language_instruction = self._get_language_instruction(task)
        confidence_instruction = (
            "When you finish your response, end with two lines:\n"
            "CONFIDENCE: <0-100>\n"
            "REASONING: <brief explanation of your confidence level>\n"
            "The confidence score represents how sure you are that this "
            "output is correct, complete, and ready to execute."
        )
        return (
            f"{self._system_prompt}\n\n"
            f"{language_instruction}\n\n"
            f"{confidence_instruction}"
        )

    def _invoke_llm(self, task: str, user_id: int = 0) -> dict[str, Any]:
        adapter = self._get_llm_adapter()
        system_content = self._build_system_content(task)

        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as FuturesTimeout
        def _invoke():
            return adapter.invoke(system_content, task,
                                  user_id=user_id,
                                  endpoint="agent_invoke",
                                  agent_id=self._agent_id)

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(_invoke)
            raw = future.result(timeout=120)
        except FuturesTimeout as err:
            raise RuntimeError("LLM invocation timed out after 120 seconds") from err
        finally:
            executor.shutdown(wait=False)
        return {
            "draft_output": self._strip_confidence_metadata(raw),
            "language": self._detect_language(task),
            "confidence": self._parse_confidence(raw),
        }

    def _stream_llm(self, task: str, user_id: int = 0):
        """Stream LLM response tokens, yielding each chunk as it arrives.

        After the final token, yields a sentinel dict with the full result:
        ``{"type": "result", "draft_output": ..., "language": ..., "confidence": ...}``
        """
        adapter = self._get_llm_adapter()
        system_content = self._build_system_content(task)
        collected: list[str] = []

        for token in adapter.stream(system_content, task,
                                    user_id=user_id,
                                    endpoint="agent_chat",
                                    agent_id=self._agent_id):
            collected.append(token)
            yield token

        raw = "".join(collected)
        yield {
            "type": "result",
            "draft_output": self._strip_confidence_metadata(raw),
            "language": self._detect_language(task),
            "confidence": self._parse_confidence(raw),
        }

    @staticmethod
    def _slugify(text: str) -> str:
        import re
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s_]+", "-", text)
        text = re.sub(r"-+", "-", text)
        return text.strip("-")

    @staticmethod
    def _save_output(subdir: str, prefix: str, content: str, ext: str = "md") -> str:
        from datetime import datetime
        from pathlib import Path
        target_dir = Path("content") / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        first_line = content.strip().split("\n")[0][:60] if content else "output"
        slug = BaseAgent._slugify(first_line) or "output"
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        fp = target_dir / f"{prefix}-{slug}-{timestamp}.{ext}"
        fp.write_text(content.strip(), encoding="utf-8")
        return str(fp)


