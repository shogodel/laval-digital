import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.base_agent import BaseAgent
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)


class PaidAdsAgent(BaseAgent):
    """Paid Ads agent for creating high-converting ad campaigns.

    Specializes in Google Ads, Facebook/Instagram Ads, keyword strategy,
    ad copy creation, budget allocation, and A/B testing for local SMBs.
    """

    def __init__(self, agent_id: str, config: Dict[str, Any]) -> None:
        """Initialize PaidAdsAgent.

        Args:
            agent_id: Unique identifier for the agent.
            config: Configuration dict with model, credentials, and prompt file.
        """
        super().__init__(agent_id, config)
        logger.info(f"PaidAdsAgent initialized: {agent_id}")

    def execute(self, draft_output: str) -> str:
        """Execute the Paid Ads task with the approved draft.

        Routes the approved draft to the ExecutionerAgent for publishing
        to ad platforms. For MVP, returns a confirmation message.

        Args:
            draft_output: The approved draft output from the LLM.

        Returns:
            Confirmation message with the draft content for executioner.
        """
        logger.info(f"PaidAdsAgent executing task for agent_id: {self.agent_id}")
        logger.info(f"Draft output length: {len(draft_output)} characters")
        logger.info("Routing approved draft to Executioner for ad platform delivery")

        result = f"Paid Ads task queued for execution.\n\nContent:\n{draft_output}"
        logger.info("Paid Ads task completed")
        return result

    def get_tools(self) -> List[Any]:
        """Return tools available to this agent.

        Returns:
            Empty list for MVP. Tools will be added in Phase 2.
        """
        return []


if __name__ == "__main__":

    config = {
        "agent_id": "paid_ads_test",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/paid_ads.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY", "dummy-key-for-testing"),
            "api_base": "https://api.deepseek.com/v1"
        }
    }

    print("Initializing PaidAdsAgent...")
    agent = PaidAdsAgent("paid_ads_test", config)

    print("Building agent graph...")
    graph = agent.build_graph()
    print("Graph built successfully!")

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if api_key:
        print("\nInvoking graph with test task...")
        from langgraph.graph import StateGraph
        from core.base_agent import AgentState

        result = graph.invoke(
            {
                "task": "Create a Google Ads campaign for a 24/7 emergency plumber in Laval with $500 budget",
                "draft_output": None,
                "approved": None,
                "feedback": None,
                "result": None,
            },
            {"configurable": {"thread_id": "paid_ads_test_run"}},
        )
        print(f"\nResult: {result.get('result', 'No result')}")
    else:
        print("\nSkipping graph invocation (no DEEPSEEK_API_KEY found)")
        print("Set DEEPSEEK_API_KEY environment variable to test with real API")
