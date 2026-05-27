import logging
from typing import Any, Dict, List

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class ReportingAgent(BaseAgent):
    """Analytics & Reporting Agent — compiles cross-channel performance,
    generates insights, and produces client-ready monthly reports."""

    def __init__(self, agent_id: str, config: Dict[str, Any]) -> None:
        super().__init__(agent_id, config)
        logger.info("ReportingAgent initialized: %s", agent_id)

    def execute(self, draft_output: str) -> str:
        logger.info("ReportingAgent executing task for agent_id: %s", self.agent_id)
        logger.info("Draft output length: %s characters", len(draft_output))
        fp = self._save_output("reports", "report", draft_output)
        logger.info("Reporting task completed — saved to %s", fp)
        return f"Reporting task completed successfully.\n\nSaved to: {fp}\n\n{draft_output}"


