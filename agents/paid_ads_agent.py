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
