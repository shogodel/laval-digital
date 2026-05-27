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
        logger.info("LocalSEOAgent executing task for agent_id: %s", self.agent_id)
        logger.info("Draft output length: %s characters", len(draft_output))
        fp = self._save_output("local_seo", "gmb-update", draft_output)
        logger.info("Local SEO task completed — saved to %s", fp)
        return f"Local SEO task completed successfully.\n\nSaved to: {fp}\n\n{draft_output}"


