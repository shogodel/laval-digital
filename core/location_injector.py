"""Location context injector for Laval Digital agents.

Reads client_config.json and injects location-specific context
into every task sent to the Local SEO and Paid Ads agents.
"""
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class LocationInjector:
    """Injects client location context into agent tasks."""

    def __init__(self, config_path: str = "config/client_config.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            logger.warning(f"Client config not found at {self.config_path}")
            return {}
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_location_context(self) -> str:
        """Build a location context string from client config."""
        if not self.config:
            return ""

        address = self.config.get("address", {})
        service_area = self.config.get("service_area", {})

        context = f"""
=== CLIENT LOCATION CONTEXT ===
Business: {self.config.get('business_name', 'Unknown')}
Address: {address.get('street', '')}, {address.get('city', '')}, {address.get('province', '')} {address.get('postal_code', '')}
Primary City: {service_area.get('primary_city', 'Unknown')}
Service Radius: {service_area.get('radius_km', 50)}km
Secondary Cities: {', '.join(service_area.get('secondary_cities', []))}
Neighborhoods: {', '.join(service_area.get('neighborhoods', []))}
Services: {', '.join(self.config.get('services', []))}
==============================
"""
        return context.strip()

    def inject(self, task: str, agent_type: str) -> str:
        """Inject location context into a task for location-aware agents.

        Args:
            task: The original task string.
            agent_type: The type of agent (e.g., 'local_seo', 'paid_ads').

        Returns:
            Task string with location context prepended.
        """
        location_aware_agents = ["local_seo", "paid_ads", "growth_hacker"]

        if agent_type not in location_aware_agents:
            return task

        context = self.get_location_context()
        if not context:
            logger.warning("No location context available. Task may lack local specificity.")
            return task

        enhanced_task = f"{context}\n\n=== TASK ===\n{task}"
        logger.info(f"Injected location context for agent: {agent_type}")
        return enhanced_task
