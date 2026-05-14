import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.base_agent import BaseAgent
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)


class LocalSEOAgent(BaseAgent):
    """Local SEO agent for optimizing SMB visibility in local search results.

    Specializes in Google Business Profile optimization, local keyword research,
    citation management, and local content strategy for small businesses.
    """

    def __init__(self, agent_id: str, config: Dict[str, Any]) -> None:
        """Initialize LocalSEOAgent.

        Args:
            agent_id: Unique identifier for the agent.
            config: Configuration dict with model, credentials, and prompt file.
        """
        super().__init__(agent_id, config)
        logger.info(f"LocalSEOAgent initialized: {agent_id}")

    def execute(self, draft_output: str) -> str:
        """Execute the Local SEO task with the approved draft.

        For MVP, this simply confirms the draft output.
        Full execution with Google APIs will be added in Phase 2.

        Args:
            draft_output: The approved draft output from the LLM.

        Returns:
            Confirmation message with the draft content.
        """
        logger.info(f"LocalSEOAgent executing task for agent_id: {self.agent_id}")
        logger.info(f"Draft output length: {len(draft_output)} characters")

        result = f"Local SEO task executed successfully.\n\nContent:\n{draft_output}"
        logger.info("Local SEO task completed")
        return result

    def get_tools(self) -> List[Any]:
        """Return tools available to this agent.

        Returns:
            Empty list for MVP. Tools will be added in Phase 2.
        """
        return []


if __name__ == "__main__":

    config = {
        "agent_id": "local_seo_test",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/local_seo.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY", "dummy-key-for-testing"),
            "api_base": "https://api.deepseek.com/v1"
        }
    }

    print("Initializing LocalSEOAgent...")
    agent = LocalSEOAgent("local_seo_test", config)

    print("Building agent graph...")
    graph = agent.build_graph()
    print("Graph built successfully!")

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if api_key:
        print("\nInvoking graph with test task...")
        from langgraph.graph import StateGraph
        from core.base_agent import AgentState

        result = graph.invoke({
            "task": "Optimize Google Business Profile for a plumber in Laval",
            "draft_output": None,
            "approved": None,
            "feedback": None,
            "result": None,
        })
        print(f"\nResult: {result.get('result', 'No result')}")
    else:
        print("\nSkipping graph invocation (no DEEPSEEK_API_KEY found)")
        print("Set DEEPSEEK_API_KEY environment variable to test with real API")
