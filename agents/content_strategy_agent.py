import logging
import re
from typing import Any, Dict, List, Optional
from pathlib import Path
from datetime import datetime, timezone
import json
import uuid

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class ContentStrategyAgent(BaseAgent):
    """Content Strategy Agent — creates editorial calendars, content briefs,
    multi-channel repurposing plans, and content performance strategies."""

    def __init__(self, agent_id: str, config: Dict[str, Any]):
        super().__init__(agent_id, config)
        self._content_dir = Path("content/strategy")
        self._content_dir.mkdir(parents=True, exist_ok=True)

    def execute(self, draft_output: str) -> str:
        return f"Content strategy saved: {draft_output[:80]}..."

    def get_tools(self) -> List[Any]:
        return []

    def save_calendar(self, draft: str) -> Dict[str, Any]:
        try:
            slug = self._slugify(draft.strip().split("\n")[0][:60])
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"calendar-{slug}-{timestamp}.jsonl"
            filepath = self._content_dir / filename
            record = {
                "id": uuid.uuid4().hex[:12],
                "type": "content_calendar",
                "content": draft,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            logger.info("Content calendar saved: %s", filepath)
            return {"success": True, "result": str(filepath), "error": None}
        except OSError as e:
            logger.error("Failed to save calendar: %s", e)
            return {"success": False, "result": "", "error": "Failed to save content calendar."}

    @staticmethod
    def _slugify(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s_]+", "-", text)
        text = re.sub(r"-+", "-", text)
        return text.strip("-")[:40]
