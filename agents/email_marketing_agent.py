from core.base_agent import BaseAgent
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)


class EmailMarketingAgent(BaseAgent):
    """Email Marketing agent for nurturing leads and driving repeat business.

    Specializes in newsletter creation, promotional campaigns, lead nurture sequences,
    reactivation campaigns, post-service follow-ups, and list segmentation.
    """

    def __init__(self, agent_id: str, config: Dict[str, Any]) -> None:
        """Initialize EmailMarketingAgent.

        Args:
            agent_id: Unique identifier for the agent.
            config: Configuration dict with model, credentials, and prompt file.
        """
        super().__init__(agent_id, config)
        logger.info(f"EmailMarketingAgent initialized: {agent_id}")

    def execute(self, draft_output: str) -> str:
        logger.info("EmailMarketingAgent executing task for agent_id: %s", self.agent_id)
        logger.info("Draft output length: %s characters", len(draft_output))
        fp = self._save_output("emails", "campaign", draft_output)
        logger.info("Email Marketing task completed — saved to %s", fp)
        return f"Email Marketing task completed successfully.\n\nSaved to: {fp}\n\n{draft_output}"


