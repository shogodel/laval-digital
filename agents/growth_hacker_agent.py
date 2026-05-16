from core.base_agent import BaseAgent
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)


class GrowthHackerAgent(BaseAgent):
    """Growth Hacker agent for finding unconventional, low-cost growth strategies.

    Specializes in growth audits, viral loops, CRO, partnership strategies,
    content hacking, automation hacks, and data-driven experiments for local SMBs.
    """

    def __init__(self, agent_id: str, config: Dict[str, Any]) -> None:
        """Initialize GrowthHackerAgent.

        Args:
            agent_id: Unique identifier for the agent.
            config: Configuration dict with model, credentials, and prompt file.
        """
        super().__init__(agent_id, config)
        logger.info(f"GrowthHackerAgent initialized: {agent_id}")

    def execute(self, draft_output: str) -> str:
        """Execute the Growth Hacker task with the approved draft.

        Routes the approved draft to the ExecutionerAgent for implementation.
        For MVP, returns a confirmation message.

        Args:
            draft_output: The approved draft output from the LLM.

        Returns:
            Confirmation message with the draft content for executioner.
        """
        logger.info(f"GrowthHackerAgent executing task for agent_id: {self.agent_id}")
        logger.info(f"Draft output length: {len(draft_output)} characters")
        logger.info("Routing approved draft to Executioner for growth strategy delivery")

        result = f"Growth Hacker task queued for execution.\n\nContent:\n{draft_output}"
        logger.info("Growth Hacker task completed")
        return result

    def get_tools(self) -> List[Any]:
        """Return tools available to this agent.

        Returns:
            Empty list for MVP. Tools will be added in Phase 2.
        """
        return []
