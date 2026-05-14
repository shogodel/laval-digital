import logging
from typing import Any, Dict, List

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class ContentStrategyAgent(BaseAgent):
    """Content Strategy Agent — creates editorial calendars, content briefs,
    multi-channel repurposing plans, and content performance strategies."""

    def execute(self, draft_output: str) -> str:
        return f"Content strategy ready for review: {draft_output[:80]}..."

    def get_tools(self) -> List[Any]:
        return []
