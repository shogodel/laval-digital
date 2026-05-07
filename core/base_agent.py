import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from core.llm_adapter import LLMAdapter

try:
    from litellm import ChatLiteLLM
except ImportError:
    ChatLiteLLM = None


class AgentState(TypedDict):
    task: str
    draft_output: Optional[str]
    approved: Optional[bool]
    feedback: Optional[str]
    result: Optional[str]


class BaseAgent(ABC):
    _available_models: Optional[List[str]] = None

    def __init__(self, agent_id: str, config: Dict[str, Any]):
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
        self._graph = None

    def _validate_config(self) -> None:
        required_fields = ["agent_id", "model", "system_prompt_file"]
        for field in required_fields:
            if field not in self._config:
                raise ValueError(f"Missing required config field: '{field}'")

        if self._config["model"] not in BaseAgent._available_models:
            raise ValueError(
                f"Invalid model '{self._config['model']}'. "
                f"Valid models: {BaseAgent._available_models}"
            )

        if not self._config.get("credentials", {}).get("api_key"):
            raise ValueError("Missing credentials.api_key in config")

    def _load_system_prompt(self) -> str:
        path = Path(self._system_prompt_file)
        if not path.exists():
            raise FileNotFoundError(f"System prompt file not found: {path}")
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

    def _get_llm(self) -> BaseChatModel:
        if ChatLiteLLM is None:
            raise ImportError(
                "litellm is required for multi-LLM support. "
                "Install with: pip install litellm"
            )

        llm_kwargs = {
            "model": self._model,
            "api_key": self._credentials["api_key"],
            "temperature": 0.7,
        }

        if "api_base" in self._credentials and self._credentials["api_base"]:
            llm_kwargs["api_base"] = self._credentials["api_base"]

        return ChatLiteLLM(**llm_kwargs)

    def _draft_node(self, state: AgentState) -> AgentState:
        llm = self._get_llm()
        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=state["task"]),
        ]

        response = llm.invoke(messages)
        state["draft_output"] = response.content
        return state

    def _approval_node(self, state: AgentState) -> AgentState:
        draft = state.get("draft_output", "")

        human_input = interrupt({
            "type": "approval_request",
            "agent_id": self._agent_id,
            "draft": draft,
            "message": f"Agent '{self._agent_id}' requests approval for draft output.",
        })

        state["approved"] = human_input.get("approved", False)
        state["feedback"] = human_input.get("feedback", "")
        return state

    def _execute_node(self, state: AgentState) -> AgentState:
        if state.get("approved"):
            try:
                result = self.execute(state["draft_output"])
                state["result"] = result
            except Exception as e:
                state["result"] = f"Execution error: {str(e)}"
        else:
            feedback = state.get("feedback", "No feedback provided")
            state["result"] = f"Task cancelled by human. Feedback: {feedback}"

        return state

    def build_graph(self):
        if self._graph is not None:
            return self._graph

        builder = StateGraph(AgentState)

        builder.add_node("draft", self._draft_node)
        builder.add_node("approval", self._approval_node)
        builder.add_node("execute", self._execute_node)

        builder.add_edge(START, "draft")
        builder.add_edge("draft", "approval")
        builder.add_edge("approval", "execute")
        builder.add_edge("execute", END)

        checkpointer = MemorySaver()
        self._graph = builder.compile(checkpointer=checkpointer)

        return self._graph

    @abstractmethod
    def execute(self, draft_output: str) -> str:
        pass

    @abstractmethod
    def get_tools(self) -> List[Any]:
        pass
