from core.base_agent import BaseAgent
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)


class GrowthHackerAgent(BaseAgent):
    """Growth Hacker agent for finding unconventional, low-cost growth strategies.

    Specializes in growth audits, viral loops, CRO, partnership strategies,
    content hacking, automation hacks, and data-driven experiments for local SMBs.
    """

    def __init__(self, agent_id: str, config: Dict[str, Any]) -> None:
        """Initialize GrowthHackerAgent.

        Args:
            agent_id: Unique identifier for the agent.
            config: Configuration dict with model, credentials, and prompt file.
        """
        super().__init__(agent_id, config)
        logger.info(f"GrowthHackerAgent initialized: {agent_id}")

    def execute(self, draft_output: str) -> str:
        logger.info("GrowthHackerAgent executing task for agent_id: %s", self.agent_id)
        logger.info("Draft output length: %s characters", len(draft_output))
        fp = self._save_output("growth", "strategy", draft_output)
        logger.info("Growth Hacker task completed — saved to %s", fp)
        return f"Growth Hacker task completed successfully.\n\nSaved to: {fp}\n\n{draft_output}"


