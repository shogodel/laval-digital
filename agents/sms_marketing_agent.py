import logging
from typing import Any, Dict, List

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class SMSMarketingAgent(BaseAgent):
    """SMS Marketing Agent — campaign planning, sequence design,
    opt-in compliance, and promotional SMS strategy."""

    def __init__(self, agent_id: str, config: Dict[str, Any]) -> None:
        super().__init__(agent_id, config)
        logger.info("SMSMarketingAgent initialized: %s", agent_id)

    def execute(self, draft_output: str) -> str:
        logger.info("SMSMarketingAgent executing task for agent_id: %s", self.agent_id)
        logger.info("Draft output length: %s characters", len(draft_output))
        fp = self._save_output("sms_campaigns", "campaign", draft_output)
        logger.info("SMS Marketing task completed — saved to %s", fp)
        return f"SMS Marketing task completed successfully.\n\nSaved to: {fp}\n\n{draft_output}"


