import logging
from typing import Any, Dict, List

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class SMSMarketingAgent(BaseAgent):
    """SMS Marketing Agent — campaign planning, sequence design,
    opt-in compliance, and promotional SMS strategy."""

    def execute(self, draft_output: str) -> str:
        return f"SMS campaign ready for review: {draft_output[:80]}..."

    def get_tools(self) -> List[Any]:
        return []
