import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class TechnicalSEOAgent(BaseAgent):
    """Technical SEO Agent — schema markup, site speed analysis,
    crawl audit recommendations, XML sitemaps, and core web vitals strategy."""

    def __init__(self, agent_id: str, config: Dict[str, Any]):
        super().__init__(agent_id, config)
        self._output_dir = Path("content/technical_seo")
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def execute(self, draft_output: str) -> str:
        return f"Technical SEO report saved: {draft_output[:80]}..."

    def get_tools(self) -> List[Any]:
        return []

    def save_report(self, draft: str, report_type: str = "audit") -> Dict[str, Any]:
        try:
            first_line = draft.strip().split("\n")[0][:60]
            slug = self._slugify(first_line)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"{report_type}-{slug}-{timestamp}.md"
            filepath = self._output_dir / filename
            filepath.write_text(draft.strip(), encoding="utf-8")
            logger.info("Technical SEO report saved: %s", filepath)
            return {"success": True, "result": str(filepath), "error": None}
        except OSError as e:
            logger.error("Failed to save technical SEO report: %s", e)
            return {"success": False, "result": "", "error": str(e)}

    def generate_schema(self, business_type: str, business_name: str, city: str, phone: str) -> str:
        schemas = {
            "plumber": "LocalBusiness",
            "electrician": "LocalBusiness",
            "landscaper": "LocalBusiness",
            "roofer": "LocalBusiness",
            "hvac": "LocalBusiness",
            "cleaner": "LocalBusiness",
            "painter": "LocalBusiness",
        }
        schema_type = schemas.get(business_type, "LocalBusiness")
        return json.dumps({
            "@context": "https://schema.org",
            "@type": schema_type,
            "name": business_name,
            "address": {"@type": "PostalAddress", "addressLocality": city, "addressCountry": "CA"},
            "telephone": phone,
            "url": f"https://{self._slugify(business_name)}.lavaldigital.ca",
        }, indent=2)

    @staticmethod
    def _slugify(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s_]+", "-", text)
        text = re.sub(r"-+", "-", text)
        return text.strip("-")[:40]
