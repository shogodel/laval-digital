"""
Frankie MCP Server Registry.
Discovers and manages all MCP servers.
"""
import json
import logging
import threading
from pathlib import Path
from typing import Optional
from .base_server import MCPServer
from .seo_server import SEOMCPServer
from .social_server import SocialMCPServer
from .email_server import EmailMCPServer
from .gmb_server import GMBMCPServer
from .ads_server import AdsMCPServer
from .analytics_server import AnalyticsMCPServer
from .website_server import WebsiteMCPServer
from .ecommerce_server import EcommerceMCPServer

logger = logging.getLogger(__name__)

# Registry of all active MCP servers
_mcp_servers: dict[str, MCPServer] = {}
_mcp_servers_lock = threading.Lock()

# ── Single source of truth: agent → MCP server/tool routing ──────
AGENT_MCP_ROUTING: dict[str, tuple[str, str]] = {
    "local_seo": ("seo", "publish_blog_post"),
    "social_media": ("social", "post_to_facebook"),
    "lead_conversion": ("email", "send_email"),
    "paid_ads": ("ads", "create_google_ads_campaign"),
    "growth_hacker": ("analytics", "analyze_trends"),
    "reputation": ("gmb", "respond_to_review"),
    "email_marketing": ("email", "send_campaign"),
    "tiktok": ("social", "post_to_tiktok"),
    "outreach": ("email", "send_email"),
    "backlinks": ("seo", "find_backlink_opportunities"),
    "content_strategy": ("seo", "publish_blog_post"),
    "cro": ("website", "track_conversions"),
    "technical_seo": ("seo", "run_site_audit"),
    "video": ("social", "post_to_youtube"),
    "sms_marketing": ("email", "send_email"),
    "reporting": ("analytics", "generate_monthly_report"),
}


def _load_mcp_config() -> dict[str, dict]:
    """Load MCP server config from config.json if it exists."""
    config_path = Path(__file__).parent / "config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def init_mcp_servers() -> dict[str, MCPServer]:
    """Initialize all MCP servers. Called once at Flask startup."""
    global _mcp_servers
    mcp_config = _load_mcp_config()
    with _mcp_servers_lock:
        servers_to_init = [
            SEOMCPServer(), SocialMCPServer(), EmailMCPServer(),
            GMBMCPServer(), AdsMCPServer(), AnalyticsMCPServer(),
            WebsiteMCPServer(), EcommerceMCPServer(),
        ]

        for server in servers_to_init:
            server_cfg = mcp_config.get(server.name, {})
            if server_cfg.get("enabled") is False:
                logger.info("MCP server '%s' disabled in config, skipping", server.name)
                continue
            _mcp_servers[server.name] = server

        logger.info("MCP servers initialized: %s", list(_mcp_servers.keys()))
        return _mcp_servers


def get_mcp_server(name: str) -> Optional[MCPServer]:
    """Get an MCP server by name."""
    with _mcp_servers_lock:
        return _mcp_servers.get(name)


def get_all_mcp_servers() -> dict[str, MCPServer]:
    """Get all registered MCP servers."""
    with _mcp_servers_lock:
        return dict(_mcp_servers)


def get_all_mcp_tools() -> dict[str, list]:
    """Get all tools from all MCP servers."""
    with _mcp_servers_lock:
        return {name: server.list_tools() for name, server in _mcp_servers.items()}
