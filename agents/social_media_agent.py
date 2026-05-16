from core.base_agent import BaseAgent
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)


class SocialMediaAgent(BaseAgent):
    """Social Media & Content Manager for local small businesses.

    Specializes in content calendar creation, platform-specific posts,
    visual content briefs, and local engagement strategies for SMBs.
    """

    def __init__(self, agent_id: str, config: Dict[str, Any]) -> None:
        """Initialize SocialMediaAgent.

        Args:
            agent_id: Unique identifier for the agent.
            config: Configuration dict with model, credentials, and prompt file.
        """
        super().__init__(agent_id, config)
        logger.info(f"SocialMediaAgent initialized: {agent_id}")

    def execute(self, draft_output: str) -> str:
        """Execute the Social Media task with the approved draft.

        For MVP, this simply confirms the draft output.
        Full execution with social platform APIs will be added in Phase 2.

        Args:
            draft_output: The approved draft output from the LLM.

        Returns:
            Confirmation message with the draft content.
        """
        logger.info(f"SocialMediaAgent executing task for agent_id: {self.agent_id}")
        logger.info(f"Draft output length: {len(draft_output)} characters")

        result = f"Social Media task executed successfully.\n\nContent:\n{draft_output}"
        logger.info("Social Media task completed")
        return result

    def get_tools(self) -> List[Any]:
        """Return tools available to this agent.

        Returns:
            Empty list for MVP. Tools will be added in Phase 2.
        """
        return []
