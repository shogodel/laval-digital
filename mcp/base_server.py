"""
Base class for all Frankie MCP servers.
Each server exposes tools that Frankie can call to execute marketing tasks.
"""
import logging
from typing import Dict, Any, Callable, List, Optional

logger = logging.getLogger(__name__)


class MCPServer:
    """Base class for MCP (Marketing Command Protocol) servers.

    Each server handles one domain (SEO, social, email, etc.) and exposes
    tools that Frankie's orchestrator can call.
    """

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.tools: Dict[str, Callable] = {}
        self.tool_descriptions: Dict[str, str] = {}
        self._register_tools()

    def _register_tools(self) -> None:
        """Override in subclasses to register domain-specific tools."""
        pass

    def register_tool(self, name: str, func: Callable, description: str = "") -> None:
        """Register a tool that Frankie can call.

        Args:
            name: Tool name (e.g., 'publish_blog_post')
            func: Callable that accepts **kwargs and returns {"success": bool, "result": str, "error": str}
            description: Human-readable description for Frankie
        """
        self.tools[name] = func
        self.tool_descriptions[name] = description or (func.__doc__ or "No description")
        logger.info(f"[{self.name}] Registered tool: {name}")

    def call_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """Call a registered tool by name.

        Args:
            tool_name: Name of the tool to call
            **kwargs: Arguments to pass to the tool

        Returns:
            {"success": bool, "result": str, "error": str or None}
        """
        if tool_name not in self.tools:
            return {
                "success": False,
                "result": "",
                "error": f"Tool '{tool_name}' not found in {self.name} server. Available: {list(self.tools.keys())}"
            }

        try:
            return self.tools[tool_name](**kwargs)
        except Exception as e:
            logger.error(f"[{self.name}] Tool '{tool_name}' failed: {e}")
            return {"success": False, "result": "", "error": str(e)}

    def list_tools(self) -> List[Dict[str, str]]:
        """Return all registered tools with descriptions."""
        return [
            {"name": name, "description": self.tool_descriptions.get(name, "No description")}
            for name in self.tools
        ]

    def get_status(self) -> Dict[str, Any]:
        """Return server status. Override in subclasses to check API connectivity."""
        return {
            "server": self.name,
            "description": self.description,
            "tools": len(self.tools),
            "connected": True
        }
