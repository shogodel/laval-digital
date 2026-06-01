"""Executioner blueprint — settings, SMTP test, social validation, pending actions."""
import logging
import smtplib
import socket
from email.mime.text import MIMEText

from flask import Blueprint, request

from core.api_helpers import api_error, api_success
from core.app_state import get_executioner
from core.auth import admin_required

logger = logging.getLogger(__name__)

executioner_bp = Blueprint("executioner", __name__, url_prefix="/api/executioner")


@executioner_bp.route("/settings", methods=["GET", "PUT"])
@admin_required
def handle_executioner_settings():
    exe = get_executioner()
    if request.method == "PUT":
        data = request.json
        if data:
            exe.update_settings(data)
        return api_success(exe.get_public_settings())
    return api_success(exe.get_public_settings())


@executioner_bp.route("/test-smtp", methods=["POST"])
@admin_required
def test_smtp():
    data = request.json
    if not data:
        return api_error("No data provided", 400)

    to_email = data.get("to_email", "")
    if not to_email:
        return api_error("No recipient email provided", 400)

    try:
        msg = MIMEText(
            "This is a test email from your Laval Digital platform. "
            "Your SMTP configuration is working correctly! 🚀"
        )
        msg["Subject"] = "Laval Digital — SMTP Test Email"
        msg["From"] = data.get("smtp_from_email", "")
        msg["To"] = to_email

        smtp_host = data.get("smtp_host", "smtp.gmail.com")
        try:
            addrs = socket.getaddrinfo(smtp_host, None)
            for _, _, _, _, sockaddr in addrs:
                smtp_ip = sockaddr[0]
                ipv4 = smtp_ip.split(":")[-1] if ":" in smtp_ip else smtp_ip
                if "." in ipv4:
                    ip_parts = [int(x) for x in ipv4.split(".")]
                    if (ip_parts[0] == 127 or ip_parts[0] == 10 or ip_parts[0] == 0 or
                        ip_parts[0] == 169 and ip_parts[1] == 254 or
                        ip_parts[0] == 192 and ip_parts[1] == 168 or
                        ip_parts[0] == 172 and 16 <= ip_parts[1] <= 31):
                        return api_error("SMTP host resolves to a private IP address", 400)
                if ":" in smtp_ip and (smtp_ip.startswith("::1") or smtp_ip.startswith("fc") or smtp_ip.startswith("fd") or smtp_ip.startswith("fe80")):
                        return api_error("SMTP host resolves to a private IPv6 address", 400)
        except socket.gaierror:
            return api_error(f"Could not resolve SMTP host: {smtp_host}", 400)

        with smtplib.SMTP(smtp_host,
                          int(data.get("smtp_port", 587)), timeout=15) as server:
            if data.get("smtp_use_tls", True):
                server.starttls()
            server.login(data.get("smtp_username", ""), data.get("smtp_password", ""))
            server.send_message(msg)

        return api_success({"message": "Test email sent"})
    except Exception as e:
        logger.error("Internal error: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 500)


@executioner_bp.route("/validate-social-key", methods=["POST"])
@admin_required
def validate_social_key():
    data = request.json
    if not data:
        return api_error("No data provided", 400)

    provider = data.get("provider", "socialapi")
    api_key = data.get("api_key", "")

    if not api_key:
        return api_error("No API key provided", 400)

    try:
        if provider == "socialapi":
            from socialapi import SocialAPI
            client = SocialAPI(api_key=api_key)
            accounts = client.accounts.list()
            return api_success({
                "accounts": [{"platform": a.platform, "account_name": a.account_name} for a in accounts]
            })
        else:
            return api_error(f"Provider '{provider}' is not yet supported.", 400)
    except ImportError:
        return api_error("socialapi package is not installed. Run: pip install socialapi", 500)
    except Exception as e:
        logger.error("Internal error: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 500)


@executioner_bp.route("/social-settings", methods=["POST"])
@admin_required
def save_social_settings():
    data = request.json
    exe = get_executioner()
    exe.update_settings({
        "social_api_provider": data.get("provider", "socialapi"),
        "social_api_key": data.get("api_key", ""),
    })
    return api_success({"message": "Social media settings saved."})


@executioner_bp.route("/pending", methods=["GET"])
@admin_required
def get_pending_executions():
    exe = get_executioner()
    return api_success({"pending": exe.get_pending_executions()})


@executioner_bp.route("/confirm/<execution_id>", methods=["POST"])
@admin_required
def confirm_execution(execution_id):
    exe = get_executioner()
    try:
        result = exe.confirm_execution(execution_id)
        return api_success(result)
    except Exception as e:
        logger.error("Confirm execution failed: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 400)


@executioner_bp.route("/reject/<execution_id>", methods=["POST"])
@admin_required
def reject_execution(execution_id):
    exe = get_executioner()
    try:
        result = exe.reject_execution(execution_id)
        return api_success(result)
    except Exception as e:
        logger.error("Reject execution failed: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 400)


@executioner_bp.route("/execute-chat", methods=["POST"])
@admin_required
def execute_chat_response():
    data = request.json
    if not data:
        return api_error("No data provided", 400)

    agent_id = data.get("agent_id", "")
    content = data.get("content", "")

    if not agent_id or not content:
        return api_error("Agent ID and content are required", 400)

    try:
        exe = get_executioner()
        result = exe.execute(agent_id, content)
        return api_success(result)
    except Exception as e:
        logger.error("Execute chat failed: %s", e, exc_info=True)
        return api_error("An internal error occurred.", 500)
