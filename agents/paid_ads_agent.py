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
        logger.info("PaidAdsAgent executing task for agent_id: %s", self.agent_id)
        logger.info("Draft output length: %s characters", len(draft_output))
        fp = self._save_output("ads", "campaign", draft_output)
        logger.info("Paid Ads task completed — saved to %s", fp)
        return f"Paid Ads task completed successfully.\n\nSaved to: {fp}\n\n{draft_output}"


