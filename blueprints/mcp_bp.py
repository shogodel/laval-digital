"""MCP blueprint — MCP server management API routes."""
import logging

from datetime import datetime, timezone
from flask import Blueprint, request
from mcp import get_all_mcp_servers, get_mcp_server, AGENT_MCP_ROUTING
from core import database
from core.api_helpers import api_success, api_error
from core.auth import admin_required
from core.app_state import get_credential_cipher, get_current_user_id, safe_error

logger = logging.getLogger(__name__)

mcp_bp = Blueprint("mcp", __name__, url_prefix="")


# ---------------------------------------------------------------------------
# MCP Server API routes
# ---------------------------------------------------------------------------


@mcp_bp.route("/api/mcp/servers", methods=["GET"])
def list_mcp_servers():
    auth_check = admin_required()
    if auth_check:
        return auth_check
    servers = {}
    for name, server in get_all_mcp_servers().items():
        servers[name] = server.get_status()
    return api_success({"servers": servers})


@mcp_bp.route("/api/mcp/servers/<server_name>/tools", methods=["GET"])
def list_mcp_tools(server_name):
    auth_check = admin_required()
    if auth_check:
        return auth_check
    server = get_mcp_server(server_name)
    if not server:
        return api_error(f"MCP server '{server_name}' not found", 404)
    return api_success({"server": server_name, "tools": server.list_tools()})


@mcp_bp.route("/api/mcp/call", methods=["POST"])
def call_mcp_tool():
    auth_check = admin_required()
    if auth_check:
        return auth_check
    data = request.json
    if not data:
        return api_error("No data provided", 400)

    server_name = data.get("server", "")
    tool_name = data.get("tool", "")
    params = data.get("params", {})

    if not server_name or not tool_name:
        return api_error("server and tool are required", 400)

    server = get_mcp_server(server_name)
    if not server:
        return api_error(f"MCP server '{server_name}' not found", 404)

    result = server.call_tool(tool_name, **params)
    return api_success(result)


@mcp_bp.route("/api/mcp/credentials", methods=["GET"])
def get_mcp_credentials():
    auth_check = admin_required()
    if auth_check:
        return auth_check
    tenant_id = get_current_user_id()
    if not tenant_id:
        return api_error("No tenant selected", 400, data={"credentials": {}})

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT server_name, platform, credential_key, credential_value FROM mcp_credentials WHERE user_id = ?", (int(tenant_id),))
        creds = {}
        for row in cursor.fetchall():
            key = f"{row['server_name']}.{row['platform']}.{row['credential_key']}"
            creds[key] = "********"
        return api_success({"credentials": creds})
    except Exception as e:
        return safe_error(e, 500)


@mcp_bp.route("/api/mcp/credentials", methods=["POST"])
def save_mcp_credentials():
    auth_check = admin_required()
    if auth_check:
        return auth_check
    tenant_id = get_current_user_id()
    if not tenant_id:
        return api_error("No tenant selected", 400)

    data = request.json
    server_name = data.get("server_name", "")
    platform = data.get("platform", "")
    credentials = data.get("credentials", {})

    if not server_name:
        return api_error("server_name is required", 400)

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cipher = get_credential_cipher()

        for key, value in credentials.items():
            encrypted = cipher.encrypt(str(value).encode()).decode()
            cursor.execute("""
                INSERT OR REPLACE INTO mcp_credentials
                (user_id, server_name, platform, credential_key, credential_value, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM mcp_credentials WHERE server_name=? AND platform=? AND credential_key=?), ?), ?)
            """, (int(tenant_id), server_name, platform, key, encrypted, server_name, platform, key, now, now))

        conn.commit()
        return api_success(message=f"Credentials saved for {server_name}")
    except Exception as e:
        return safe_error(e, 500)


@mcp_bp.route("/api/mcp/credentials/<server_name>", methods=["DELETE"])
def delete_mcp_credentials(server_name):
    auth_check = admin_required()
    if auth_check:
        return auth_check
    tenant_id = get_current_user_id()
    if not tenant_id:
        return api_error("No tenant selected", 400)

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM mcp_credentials WHERE user_id = ? AND server_name = ?", (int(tenant_id), server_name))
        conn.commit()
        return api_success(message=f"Credentials deleted for {server_name}")
    except Exception as e:
        return safe_error(e, 500)


@mcp_bp.route("/api/mcp/execute", methods=["POST"])
def execute_via_mcp():
    auth_check = admin_required()
    if auth_check:
        return auth_check
    data = request.json
    if not data:
        return api_error("No data provided", 400)

    agent_id = data.get("agent_id", "")
    content = data.get("content", "")

    if not agent_id or not content:
        return api_error("agent_id and content are required", 400)

    mapping = AGENT_MCP_ROUTING.get(agent_id)
    if not mapping:
        return api_error(f"No MCP mapping for agent '{agent_id}'", 400)

    server_name, tool_name = mapping
    server = get_mcp_server(server_name)
    if not server:
        return api_error(f"MCP server '{server_name}' not found", 404)

    result = server.call_tool(tool_name, content=content)
    return api_success(result)
