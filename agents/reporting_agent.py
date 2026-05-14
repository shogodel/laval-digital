import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class ReportingAgent(BaseAgent):
    """Analytics & Reporting Agent — compiles cross-channel performance,
    generates insights, and produces client-ready monthly reports."""

    def __init__(self, agent_id: str, config: Dict[str, Any]):
        super().__init__(agent_id, config)
        self._report_dir = Path("content/reports")
        self._report_dir.mkdir(parents=True, exist_ok=True)

    def execute(self, draft_output: str) -> str:
        return f"Report generated: {draft_output[:80]}..."

    def get_tools(self) -> List[Any]:
        return []

    def save_report(self, draft: str) -> Dict[str, Any]:
        try:
            first_line = draft.strip().split("\n")[0][:60]
            slug = self._slugify(first_line)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"report-{slug}-{timestamp}.html"
            filepath = self._report_dir / filename
            filepath.write_text(draft.strip(), encoding="utf-8")
            logger.info("Report saved: %s", filepath)
            return {"success": True, "result": str(filepath), "error": None}
        except OSError as e:
            logger.error("Failed to save report: %s", e)
            return {"success": False, "result": "", "error": "Failed to save report."}

    @staticmethod
    def _slugify(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s_]+", "-", text)
        text = re.sub(r"-+", "-", text)
        return text.strip("-")[:40]
