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
        """Execute the Short-Form Video task with the approved draft.

        For MVP, this simply confirms the draft output.
        Full execution with video platform APIs will be added in Phase 2.

        Args:
            draft_output: The approved draft output from the LLM.

        Returns:
            Confirmation message with the draft content.
        """
        logger.info(f"TikTokAgent executing task for agent_id: {self.agent_id}")
        logger.info(f"Draft output length: {len(draft_output)} characters")

        result = f"Short-Form Video task executed successfully.\n\nContent:\n{draft_output}"
        logger.info("Short-Form Video task completed")
        return result

    def get_tools(self) -> List[Any]:
        """Return tools available to this agent.

        Returns:
            Empty list for MVP. Tools will be added in Phase 2.
        """
        return []
