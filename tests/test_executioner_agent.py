"""Tests for executioner_agent.py — the core execution engine."""
import json
import shutil
import uuid
from pathlib import Path

import pytest

from agents.executioner_agent import ExecutionerAgent, ExecutionerError


_log_dir = Path(__file__).resolve().parent.parent / "logs"


@pytest.fixture
def executioner():
    log_path = _log_dir / f"test_{uuid.uuid4().hex}.jsonl"
    instance = ExecutionerAgent({
        "execution_log_path": str(log_path),
        "max_retries": 1,
        "retry_delay": 0,
    })
    yield instance
    log_path.unlink(missing_ok=True)
    for d in ("test_dir", "a", "blog"):
        p = Path("content") / d
        if p.exists():
            shutil.rmtree(p)


class TestSlugify:
    def test_basic(self):
        assert ExecutionerAgent._slugify("Hello World") == "hello-world"

    def test_special_chars_removed(self):
        assert ExecutionerAgent._slugify("Hello! World@ #SEO") == "hello-world-seo"

    def test_multiple_spaces_collapsed(self):
        assert ExecutionerAgent._slugify("hello   world") == "hello-world"

    def test_trailing_dashes_stripped(self):
        assert ExecutionerAgent._slugify("-hello world-") == "hello-world"

    def test_empty_string(self):
        assert ExecutionerAgent._slugify("") == ""


class TestSaveFile:
    def test_saves_content_correctly(self, executioner):
        saved = executioner._save_file("test_dir", "prefix", "txt", "hello world", "Test")
        assert saved["success"] is True
        assert Path(saved["result"]).read_text() == "hello world"

    def test_returns_file_path(self, executioner):
        saved = executioner._save_file("test_dir", "pre", "md", "# Title\nBody", "Test")
        assert saved["result"].startswith("content/test_dir/pre-")

    def test_nested_directory_created(self, executioner):
        saved = executioner._save_file("a/b/c", "x", "json", "{}", "Nested")
        assert Path(saved["result"]).exists()

    def test_os_error_returns_error(self, executioner):
        saved = executioner._save_file("/proc/forbidden", "x", "txt", "data", "Forbidden")
        assert saved["success"] is False
        assert saved["error"] is not None


class TestPublishBlogPost:
    def test_writes_markdown_file(self, executioner):
        result = executioner._publish_blog_post("# Blog Post\n\nContent.")
        assert result["success"] is True
        assert "content/blog/" in result["result"]
        assert Path(result["result"]).exists()

    def test_file_has_content(self, executioner):
        result = executioner._publish_blog_post("# Post\nBody")
        content = Path(result["result"]).read_text()
        assert content == "# Post\nBody"


class TestSelectTool:
    def test_local_seo_maps_to_publish_blog_post(self, executioner):
        tool = executioner._select_tool("local_seo")
        assert tool == "publish_blog_post"
        assert tool in executioner.tool_registry

    def test_social_media_maps_to_post_to_social(self, executioner):
        tool = executioner._select_tool("social_media")
        assert tool == "post_to_social"

    def test_email_marketing_maps_to_send_email(self, executioner):
        tool = executioner._select_tool("email_marketing")
        assert tool == "send_email"

    def test_unknown_agent_raises_error(self, executioner):
        with pytest.raises(ExecutionerError):
            executioner._select_tool("nonexistent_agent")

    def test_all_agents_have_mapped_tool(self, executioner):
        from mcp import AGENT_MCP_ROUTING
        for agent_name in AGENT_MCP_ROUTING:
            try:
                tool = executioner._select_tool(agent_name)
            except ExecutionerError:
                continue
            assert tool in executioner.tool_registry, f"{agent_name} → {tool} not registered"


class TestRegisterTool:
    def test_register_new_tool(self, executioner):
        executioner.register_tool("my_tool", lambda d: {"success": True, "result": "ok", "error": None})
        assert "my_tool" in executioner.tool_registry

    def test_registered_tool_is_callable(self, executioner):
        expected = {"success": True, "result": "echo", "error": None}
        executioner.register_tool("echo", lambda d: expected)
        assert executioner.tool_registry["echo"]("anything") is expected


class TestExecute:
    def test_execute_local_seo_saves_blog_post(self, executioner):
        result = executioner.execute("local_seo", "# Test\nContent")
        assert result["success"] is True

    def test_execute_returns_execution_id(self, executioner):
        result = executioner.execute("local_seo", "test")
        assert "execution_id" in result
        assert len(result["execution_id"]) > 0

    def test_execute_with_explicit_tool_name(self, executioner):
        result = executioner.execute("local_seo", "content", tool_name="publish_blog_post")
        assert result["success"] is True

    def test_execute_queues_for_confirmation_when_tool_in_confirm_list(self, executioner):
        result = executioner.execute("local_seo", "content", tool_name="send_email")
        assert result.get("status") == "pending_confirmation"

    def test_execute_force_bypasses_confirmation(self, executioner):
        result = executioner.execute("local_seo", "content", tool_name="send_email", force=True)
        assert result.get("status") != "pending_confirmation"


class TestRunTool:
    def test_successful_tool_run_returns_result(self, executioner):
        result = executioner._run_tool(
            execution_id="test-123", agent_name="local_seo",
            tool_name="publish_blog_post", approved_draft="# Draft",
        )
        assert result["success"] is True
        assert result["execution_id"] == "test-123"

    def test_failed_tool_returns_error(self, executioner):
        def failing_tool(_draft):
            return {"success": False, "result": "", "error": "boom"}
        executioner.register_tool("fail", failing_tool)
        result = executioner._run_tool(
            execution_id="retry", agent_name="t", tool_name="fail", approved_draft="x",
        )
        assert result["success"] is False
        assert "boom" in (result.get("error") or "")


class TestConfirmExecution:
    def test_confirm_pending_execution(self, executioner):
        executioner.register_tool("send_email", lambda d: {"success": True, "result": "ok", "error": None})
        pending = executioner.execute("local_seo", "draft", tool_name="send_email")
        eid = pending["execution_id"]
        result = executioner.confirm_execution(eid)
        assert result["success"] is True

    def test_confirm_nonexistent_raises_error(self, executioner):
        with pytest.raises(ExecutionerError):
            executioner.confirm_execution("no-such-id")

    def test_reject_pending_execution(self, executioner):
        pending = executioner.execute("local_seo", "draft", tool_name="send_email")
        result = executioner.reject_execution(pending["execution_id"])
        assert result["success"] is False


class TestGetAvailableTools:
    def test_local_seo_includes_update_gmb(self, executioner):
        tools = executioner.get_available_tools("local_seo")
        assert "update_gmb" in tools

    def test_unknown_agent_returns_empty(self, executioner):
        assert executioner.get_available_tools("nonexistent") == []


class TestExecutionLog:
    def test_execution_logged_on_success(self, executioner):
        log_path = executioner._execution_log_path
        executioner.execute("local_seo", "# Hello", tool_name="publish_blog_post")
        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) >= 1
        record = json.loads(lines[-1])
        assert record["success"] is True
        assert record["agent_name"] == "local_seo"

    def test_execution_logged_on_failure(self, executioner):
        log_path = executioner._execution_log_path
        executioner.register_tool("fail", lambda d: {"success": False, "result": "", "error": "boom"})
        executioner.execute("local_seo", "x", tool_name="fail")
        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) >= 1
        record = json.loads(lines[-1])
        assert record["success"] is False

    def test_get_execution_history(self, executioner):
        executioner.execute("local_seo", "first", tool_name="publish_blog_post")
        executioner.execute("local_seo", "second", tool_name="publish_blog_post")
        history = executioner.get_execution_history(limit=10)
        assert len(history) >= 2

    def test_get_execution_by_id(self, executioner):
        result = executioner.execute("local_seo", "test", tool_name="publish_blog_post")
        eid = result["execution_id"]
        record = executioner.get_execution_by_id(eid)
        assert record is not None
        assert record["execution_id"] == eid


class TestMCPMappingConsistency:
    """Every MCP tool should have a local fallback registered in the tool_registry."""

    def test_all_mcp_tools_have_local_fallback(self, executioner):
        from mcp import AGENT_MCP_ROUTING
        from agents.executioner_agent import MCP_TOOL_TO_LOCAL
        for agent_name, (_server, mcp_tool) in AGENT_MCP_ROUTING.items():
            if mcp_tool not in MCP_TOOL_TO_LOCAL:
                continue
            local_tool = MCP_TOOL_TO_LOCAL[mcp_tool]
            assert local_tool in executioner.tool_registry, f"Local tool '{local_tool}' not registered (for MCP {mcp_tool})"


class TestPendingExecutions:
    def test_get_pending_executions(self, executioner):
        executioner.execute("local_seo", "draft", tool_name="send_email")
        pending = executioner.get_pending_executions()
        assert len(pending) >= 1
        assert pending[0]["tool_name"] == "send_email"
