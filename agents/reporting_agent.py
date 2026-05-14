import logging
from typing import Any, Dict, List

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class ReportingAgent(BaseAgent):
    """Analytics & Reporting Agent — compiles cross-channel performance,
    generates insights, and produces client-ready monthly reports."""

    def execute(self, draft_output: str) -> str:
        return f"Report ready for review: {draft_output[:80]}..."

    def get_tools(self) -> List[Any]:
        return []
