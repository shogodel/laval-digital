from core.base_agent import BaseAgent
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)


class OutreachAgent(BaseAgent):
    """Outreach agent for prospecting and personalized email campaigns.

    Writes outreach emails, finds prospect contact info, and sequences campaigns.
    """

    def __init__(self, agent_id: str, config: Dict[str, Any]) -> None:
        super().__init__(agent_id, config)
        logger.info(f"OutreachAgent initialized: {agent_id}")

    def execute(self, draft_output: str) -> str:
        logger.info("OutreachAgent executing task for agent_id: %s", self.agent_id)
        logger.info("Draft output length: %s characters", len(draft_output))
        fp = self._save_output("outreach", "prospect", draft_output)
        logger.info("Outreach task completed — saved to %s", fp)
        return f"Outreach task completed successfully.\n\nSaved to: {fp}\n\n{draft_output}"


