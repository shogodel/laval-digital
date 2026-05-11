import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.base_agent import BaseAgent
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)


class OutreachAgent(BaseAgent):
    """Outreach agent for prospecting and personalized email campaigns.

    Writes outreach emails, finds prospect contact info, and sequences campaigns.
    """

    def __init__(self, agent_id: str, config: Dict[str, Any]) -> None:
        super().__init__(agent_id, config)
        logger.info(f"OutreachAgent initialized: {agent_id}")

    def execute(self, draft_output: str) -> str:
        logger.info(f"OutreachAgent executing task for agent_id: {self.agent_id}")
        logger.info(f"Draft output length: {len(draft_output)} characters")
        result = f"Outreach task queued for execution.\n\nContent:\n{draft_output}"
        logger.info("Outreach task completed")
        return result

    def get_tools(self) -> List[Any]:
        return []


if __name__ == "__main__":
    import os
    from core.llm_adapter import LLMAdapter

    config = {
        "agent_id": "outreach_test",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/outreach.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY", "dummy-key-for-testing"),
            "api_base": "https://api.deepseek.com/v1"
        }
    }

    print("Initializing OutreachAgent...")
    agent = OutreachAgent("outreach_test", config)

    print("Building agent graph...")
    graph = agent.build_graph()
    print("Graph built successfully!")
    print("\nSet DEEPSEEK_API_KEY to test with a real task.")
