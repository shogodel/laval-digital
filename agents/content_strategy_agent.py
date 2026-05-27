import logging
from typing import Any, Dict, List

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class ContentStrategyAgent(BaseAgent):
    """Content Strategy Agent — creates editorial calendars, content briefs,
    multi-channel repurposing plans, and content performance strategies."""

    def __init__(self, agent_id: str, config: Dict[str, Any]) -> None:
        super().__init__(agent_id, config)
        logger.info("ContentStrategyAgent initialized: %s", agent_id)

    def execute(self, draft_output: str) -> str:
        logger.info("ContentStrategyAgent executing task for agent_id: %s", self.agent_id)
        logger.info("Draft output length: %s characters", len(draft_output))
        fp = self._save_output("strategy", "calendar", draft_output)
        logger.info("Content Strategy task completed — saved to %s", fp)
        return f"Content Strategy task completed successfully.\n\nSaved to: {fp}\n\n{draft_output}"


