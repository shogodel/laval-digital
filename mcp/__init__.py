"""
Frankie MCP Server Registry.
Discovers and manages all MCP servers.
"""
import logging
from typing import Dict, Optional, Tuple
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
_mcp_servers: Dict[str, MCPServer] = {}

# ── Single source of truth: agent → MCP server/tool routing ──────
AGENT_MCP_ROUTING: Dict[str, Tuple[str, str]] = {
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


def init_mcp_servers() -> Dict[str, MCPServer]:
    """Initialize all MCP servers. Called once at Flask startup."""
    global _mcp_servers

    # Register SEO server
    seo = SEOMCPServer()
    _mcp_servers[seo.name] = seo

    # Register Social Media server
    social = SocialMCPServer()
    _mcp_servers[social.name] = social

    # Register Email server
    email = EmailMCPServer()
    _mcp_servers[email.name] = email

    # Register Google Business Profile server
    gmb = GMBMCPServer()
    _mcp_servers[gmb.name] = gmb

    # Register Ads server
    ads = AdsMCPServer()
    _mcp_servers[ads.name] = ads

    # Register Analytics server
    analytics = AnalyticsMCPServer()
    _mcp_servers[analytics.name] = analytics

    # Register Website server
    website = WebsiteMCPServer()
    _mcp_servers[website.name] = website

    # Register E-Commerce server
    ecommerce = EcommerceMCPServer()
    _mcp_servers[ecommerce.name] = ecommerce

    logger.info(f"MCP servers initialized: {list(_mcp_servers.keys())}")
    return _mcp_servers


def get_mcp_server(name: str) -> Optional[MCPServer]:
    """Get an MCP server by name."""
    return _mcp_servers.get(name)


def get_all_mcp_servers() -> Dict[str, MCPServer]:
    """Get all registered MCP servers."""
    return _mcp_servers


def get_all_mcp_tools() -> Dict[str, list]:
    """Get all tools from all MCP servers."""
    return {name: server.list_tools() for name, server in _mcp_servers.items()}
