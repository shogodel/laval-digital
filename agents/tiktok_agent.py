from core.base_agent import BaseAgent
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)


class TikTokAgent(BaseAgent):
    """Short-Form Video Content agent for TikTok, Instagram Reels, and YouTube Shorts.

    Specializes in content calendars, script writing, hook generation, trend adaptation,
    before/after content, educational snippets, and behind-the-scenes content.
    """

    def __init__(self, agent_id: str, config: Dict[str, Any]) -> None:
        """Initialize TikTokAgent.

        Args:
            agent_id: Unique identifier for the agent.
            config: Configuration dict with model, credentials, and prompt file.
        """
        super().__init__(agent_id, config)
        logger.info(f"TikTokAgent initialized: {agent_id}")

    def execute(self, draft_output: str) -> str:
        logger.info("TikTokAgent executing task for agent_id: %s", self.agent_id)
        logger.info("Draft output length: %s characters", len(draft_output))
        fp = self._save_output("video", "short-form", draft_output)
        logger.info("Short-Form Video task completed — saved to %s", fp)
        return f"Short-Form Video task completed successfully.\n\nSaved to: {fp}\n\n{draft_output}"


