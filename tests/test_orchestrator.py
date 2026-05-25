"""Unit tests for core/orchestrator.py.

All LLM calls are mocked — no real API calls.
"""
from unittest.mock import MagicMock, patch
import pytest

from core.orchestrator import Orchestrator
from core.llm_adapter import LLMAdapter


@pytest.fixture
def mock_llm():
    llm = MagicMock(spec=LLMAdapter)

    def fake_invoke(system_prompt="", user_message="", **kwargs):
        return "**Agent:** local_seo | **Status:** Pending Approval\nCONFIDENCE: 90\nREASONING: SEO match"
    llm.invoke.side_effect = fake_invoke
    return llm


@pytest.fixture
def agent_registry_with_prompts():
    """Returns a registry with mock agents that have system prompts loaded."""
    agents = {}
    for agent_id in ("local_seo", "social_media", "backlinks", "reporting"):
        mock = MagicMock()
        mock.agent_id = agent_id
        mock.system_prompt = f"You are an expert in {agent_id}."
        mock.enabled = True
        mock.model = "deepseek-chat"
        agents[agent_id] = mock
    return agents


@pytest.fixture
def orchestrator(mock_llm, agent_registry_with_prompts):
    return Orchestrator(mock_llm, agent_registry_with_prompts)


class TestProcessMessage:
    def test_panic_mode(self, orchestrator):
        orchestrator.panic()
        result = orchestrator.process_message("do something", "thread-1")
        assert result["status"] == "panicked"
        assert "stopped" in result["response"].lower()

    def test_approve_message(self, orchestrator):
        result = orchestrator.process_message("approve", "thread-1")
        assert result["status"] == "no_pending"

    def test_reject_message(self, orchestrator):
        result = orchestrator.process_message("reject", "thread-1")
        assert result["status"] == "no_pending"

    def test_process_routes_message(self, orchestrator):
        result = orchestrator.process_message("I need SEO help", "thread-1")
        assert result["status"] == "pending_approval"
        assert result["pending_approval"] is True
        assert result["agent"] == "local_seo"

    def test_process_respects_user_id(self, orchestrator):
        result = orchestrator.process_message("help with seo", "thread-1", user_id=42)
        assert result["pending_approval"] is True

    def test_process_empty_message(self, orchestrator):
        result = orchestrator.process_message("", "thread-1")
        assert result["status"] in ("pending_approval", "error")

    def test_long_message_truncated(self, orchestrator):
        long_msg = "SEO " * 1000
        result = orchestrator.process_message(long_msg, "thread-1")
        assert result["status"] in ("pending_approval", "error")


class TestFormatHistory:
    def test_none_history(self):
        assert Orchestrator._format_history(None) == ""

    def test_empty_history(self):
        assert Orchestrator._format_history([]) == ""

    def test_single_turn(self):
        history = [{"role": "user", "content": "hello"}]
        block = Orchestrator._format_history(history)
        assert "User: hello" in block

    def test_assistant_turn(self):
        history = [{"role": "assistant", "content": "Hi there"}]
        block = Orchestrator._format_history(history)
        assert "Assistant: Hi there" in block

    def test_truncated_to_ten_turns(self):
        history = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        block = Orchestrator._format_history(history)
        assert block.count("User: msg ") == 10

    def test_content_truncated_at_500_chars(self):
        long_content = "x" * 1000
        history = [{"role": "user", "content": long_content}]
        block = Orchestrator._format_history(history)
        assert "xxx" in block
        assert len(block) < 600

    def test_missing_fields_handled(self):
        history = [{"role": "user"}, {"content": "hi"}]
        block = Orchestrator._format_history(history)
        assert block is not None


class TestSelectAgentPrompt:
    def test_frankie_source_returns_none(self, orchestrator):
        prompt, agent = orchestrator._select_agent_prompt("SEO help", source="frankie")
        assert prompt is None
        assert agent is None

    def test_seo_keyword_match(self, orchestrator):
        prompt, agent = orchestrator._select_agent_prompt(
            "I need help with Google Business Profile and local rankings",
            source="chat"
        )
        assert agent == "local_seo"

    def test_social_media_keyword_match(self, orchestrator):
        prompt, agent = orchestrator._select_agent_prompt(
            "Post on Facebook and Instagram",
            source="chat"
        )
        assert agent == "social_media"

    def test_no_match_falls_back(self, orchestrator):
        prompt, agent = orchestrator._select_agent_prompt(
            "Hello, how are you?",
            source="chat"
        )
        assert prompt is None
        assert agent is None

    def test_case_insensitive_matching(self, orchestrator):
        prompt, agent = orchestrator._select_agent_prompt(
            "SEO AND SOCIAL MEDIA STRATEGY",
            source="chat"
        )
        assert agent is not None

    def test_backlinks_matching(self, orchestrator):
        prompt, agent = orchestrator._select_agent_prompt(
            "We need link building and guest posts",
            source="chat"
        )
        assert agent == "backlinks"

    def test_reporting_matching(self, orchestrator):
        prompt, agent = orchestrator._select_agent_prompt(
            "Show me the analytics dashboard and ROI metrics",
            source="chat"
        )
        assert agent == "reporting"


class TestGetWelcome:
    def test_welcome_english(self, orchestrator):
        result = orchestrator.get_welcome("en")
        assert result["status"] == "welcome"
        assert result["agent"] == "orchestrator"

    def test_welcome_french(self, orchestrator):
        result = orchestrator.get_welcome("fr")
        assert result["status"] == "welcome"

    def test_welcome_fallback_on_error(self, orchestrator):
        orchestrator._llm_adapter.invoke.side_effect = Exception("LLM down")
        result = orchestrator.get_welcome("en")
        assert result["status"] == "welcome"
        assert "marketing" in result["response"].lower()


class TestGetSuggestions:
    def test_suggestions_english(self, orchestrator):
        orchestrator._llm_adapter.invoke.side_effect = None
        orchestrator._llm_adapter.invoke.return_value = "1. Improve SEO\n2. Run ads"
        result = orchestrator.get_suggestions("en")
        assert result["status"] == "suggestions"

    def test_suggestions_fallback_on_error(self, orchestrator):
        orchestrator._llm_adapter.invoke.side_effect = Exception("fail")
        result = orchestrator.get_suggestions("en")
        assert result["status"] == "suggestions"


class TestDetectLanguage:
    def test_detect_english(self, orchestrator):
        assert orchestrator._detect_language("hello world") == "en"

    def test_detect_french(self, orchestrator):
        assert orchestrator._detect_language("bonjour je veux de l'aide merci") == "fr"

    def test_detect_empty(self, orchestrator):
        assert orchestrator._detect_language("") == "en"


class TestHandleApproval:
    def test_approval_no_pending(self, orchestrator):
        result = orchestrator._handle_approval("nonexistent", True)
        assert result["status"] == "no_pending"

    def test_rejection_no_pending(self, orchestrator):
        result = orchestrator._handle_approval("nonexistent", False)
        assert result["status"] == "no_pending"


class TestPendingDrafts:
    def test_get_pending_drafts_empty(self, orchestrator):
        assert orchestrator.get_pending_drafts() == {}

    def test_get_pending_drafts_filtered(self, orchestrator):
        assert orchestrator.get_pending_drafts(user_id=1) == {}

    def test_get_pending_drafts_none_user_id(self, orchestrator):
        assert orchestrator.get_pending_drafts(user_id=None) == {}
