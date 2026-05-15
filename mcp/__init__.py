"""
Frankie MCP Server Registry.
Discovers and manages all MCP servers.
"""
import logging
from typing import Dict, Optional
from .base_server import MCPServer
from .seo_server import SEOMCPServer

logger = logging.getLogger(__name__)

# Registry of all active MCP servers
_mcp_servers: Dict[str, MCPServer] = {}


def init_mcp_servers() -> Dict[str, MCPServer]:
    """Initialize all MCP servers. Called once at Flask startup."""
    global _mcp_servers

    # Register SEO server
    seo = SEOMCPServer()
    _mcp_servers[seo.name] = seo

    # Future servers will be registered here:
    # from .social_server import SocialMCPServer
    # _mcp_servers["social"] = SocialMCPServer()
    # from .email_server import EmailMCPServer
    # _mcp_servers["email"] = EmailMCPServer()
    # from .gmb_server import GMBMCPServer
    # _mcp_servers["gmb"] = GMBMCPServer()
    # from .ads_server import AdsMCPServer
    # _mcp_servers["ads"] = AdsMCPServer()

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
