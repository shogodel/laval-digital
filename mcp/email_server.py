"""
Email MCP Server for Frankie.
Handles email sending via SMTP, SendGrid, Mailgun, or Gmail.
"""
import logging
import smtplib
import re
import json
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, Any
from .base_server import MCPServer

logger = logging.getLogger(__name__)


class EmailMCPServer(MCPServer):
    """MCP Server for email marketing."""

    def __init__(self):
        super().__init__(
            name="email",
            description="Email marketing — SendGrid, Mailgun, Gmail SMTP, custom SMTP"
        )

    def _register_tools(self) -> None:
        self.register_tool("send_email", self.send_email,
            "Send an email via configured SMTP or provider")
        self.register_tool("send_campaign", self.send_campaign,
            "Send a bulk email campaign to a list")
        self.register_tool("test_connection", self.test_connection,
            "Test email configuration by sending a test email")

    def send_email(self, content: str, to_email: str = "", subject: str = "",
                   api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Send an email via configured SMTP or provider."""
        subject_match = re.search(r"^(?:#\s*)?Subject\s*:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
        if not subject:
            subject = subject_match.group(1).strip() if subject_match else "Message from Frankie"
        if not to_email and api_credentials:
            to_email = api_credentials.get("from_email", "")
        if api_credentials and api_credentials.get("smtp_host"):
            return self._send_smtp(content, subject, to_email, api_credentials)
        return self._queue_email(content, subject, to_email)

    def send_campaign(self, content: str, list_name: str = "",
                      api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Send a bulk email campaign to a list."""
        return self._queue_email(content, f"Campaign: {list_name}", "list@placeholder")

    def test_connection(self, api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Test email configuration by sending a test email."""
        if not api_credentials or not api_credentials.get("smtp_host"):
            return {"success": False, "result": "", "error": "No SMTP credentials configured"}
        try:
            return self._send_smtp(
                "Frankie email test — your configuration works!",
                "Frankie Test Email",
                api_credentials.get("from_email", ""),
                api_credentials
            )
        except Exception as e:
            return {"success": False, "result": "", "error": str(e)}

    def _send_smtp(self, content: str, subject: str, to: str, creds: Dict) -> Dict[str, Any]:
        """Send email via SMTP."""
        smtp_host = creds.get("smtp_host", "")
        smtp_port = int(creds.get("smtp_port", 587))
        smtp_user = creds.get("smtp_username", "")
        smtp_pass = creds.get("smtp_password", "")
        smtp_from = creds.get("from_email", smtp_user)
        use_tls = creds.get("smtp_use_tls", True)

        if not smtp_user:
            return {"success": False, "result": "", "error": "SMTP username not configured"}

        try:
            msg = MIMEText(content, _charset="utf-8")
            msg["Subject"] = subject
            msg["From"] = smtp_from
            msg["To"] = to or smtp_from

            server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
            if use_tls:
                server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
            server.quit()

            return {"success": True, "result": f"Email sent: {subject}", "error": None}
        except Exception as e:
            return {"success": False, "result": "", "error": f"SMTP failed: {e}"}

    def _queue_email(self, content: str, subject: str, to: str) -> Dict[str, Any]:
        """Queue an email for later execution."""
        try:
            email_dir = Path("content/emails")
            email_dir.mkdir(parents=True, exist_ok=True)
            record = {"subject": subject, "to": to, "body": content, "status": "queued"}
            with open(email_dir / "queue.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            return {"success": True, "result": f"Email queued: {subject}", "error": None}
        except Exception as e:
            return {"success": False, "result": "", "error": str(e)}
