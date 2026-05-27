from core.base_agent import BaseAgent
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)


class BacklinksAgent(BaseAgent):
    """Backlinks agent for building quality backlinks for local businesses.

    Specializes in citation building, guest post prospecting, broken link
    building, and outreach for small business SEO.
    """

    def __init__(self, agent_id: str, config: Dict[str, Any]) -> None:
        """Initialize BacklinksAgent.

        Args:
            agent_id: Unique identifier for the agent.
            config: Configuration dict with model, credentials, and prompt file.
        """
        super().__init__(agent_id, config)
        logger.info(f"BacklinksAgent initialized: {agent_id}")

    def execute(self, draft_output: str) -> str:
        logger.info("BacklinksAgent executing task for agent_id: %s", self.agent_id)
        logger.info("Draft output length: %s characters", len(draft_output))
        fp = self._save_output("backlinks", "outreach", draft_output)
        logger.info("Backlinks task completed — saved to %s", fp)
        return f"Backlinks task completed successfully.\n\nSaved to: {fp}\n\n{draft_output}"


