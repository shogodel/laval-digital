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
        logger.info("SocialMediaAgent executing task for agent_id: %s", self.agent_id)
        logger.info("Draft output length: %s characters", len(draft_output))
        fp = self._save_output("social", "post", draft_output)
        logger.info("Social Media task completed — saved to %s", fp)
        return f"Social Media task completed successfully.\n\nSaved to: {fp}\n\n{draft_output}"


