import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class VideoAgent(BaseAgent):
    """Video Production Agent — YouTube scripting, explainer videos,
    ad video scripts, video SEO, and long-form content strategy."""

    def __init__(self, agent_id: str, config: Dict[str, Any]):
        super().__init__(agent_id, config)
        self._output_dir = Path("content/video")
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def execute(self, draft_output: str) -> str:
        return f"Video script saved: {draft_output[:80]}..."

    def get_tools(self) -> List[Any]:
        return []

    def save_script(self, draft: str) -> Dict[str, Any]:
        try:
            slug = self._slugify(draft.strip().split("\n")[0][:60])
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            fp = self._output_dir / f"video-{slug}-{ts}.md"
            fp.write_text(draft.strip(), encoding="utf-8")
            logger.info("Video script saved: %s", fp)
            return {"success": True, "result": str(fp), "error": None}
        except OSError as e:
            logger.error("Failed to save video script: %s", e)
            return {"success": False, "result": "", "error": "Failed to save video script."}

    @staticmethod
    def _slugify(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s_]+", "-", text)
        text = re.sub(r"-+", "-", text)
        return text.strip("-")[:40]
