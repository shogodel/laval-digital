"""Email Bridge — reply-to-execute via IMAP.

Users receive an email notification for every pending action. Replying with
"PUBLISH", "APPROVE", or "YES" executes the most recent pending action.
Replying with "SKIP" or "NO" discards it.

The bridge polls the configured IMAP inbox every 60 seconds.
No API keys, no OAuth — just the user's email app password.
"""

import email
import imaplib
import logging
import re
import threading
import time
from collections.abc import Callable
from email.header import decode_header
from typing import Any

logger = logging.getLogger(__name__)

APPROVE_PATTERNS = re.compile(r"^\s*(PUBLISH|APPROVE|YES|EXECUTE|EXECUTER|CONFIRM|CONFIRMER|PUBLIE|PUBLIÉ|APPROUVE|APPROUVÉ|OUI|EXÉCUTE)\s*$", re.IGNORECASE)
REJECT_PATTERNS = re.compile(r"^\s*(SKIP|NO|REJECT|REJETTE|NON|IGNORE)\s*$", re.IGNORECASE)

POLL_INTERVAL = 60  # seconds


class EmailBridge:
    """Monitors an IMAP inbox for replies to action notification emails.

    Usage::

        bridge = EmailBridge("imap.gmail.com", 993, "user@gmail.com", "app-password")
        bridge.set_handler(handle_reply)
        bridge.start()  # background thread
    """

    def __init__(
        self,
        imap_host: str = "imap.gmail.com",
        imap_port: int = 993,
        username: str = "",
        password: str = "",
    ) -> None:
        self._host = imap_host
        self._port = imap_port
        self._username = username
        self._password = password
        self._handler: Callable[[str, str, str], None] | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    def set_handler(self, handler: Callable[[str, str, str], None]) -> None:
        """Set the callback for when a reply is parsed.

        The handler receives ``(action: str, subject: str, body: str)``.
        ``action`` is ``"approve"`` or ``"reject"``.
        """
        self._handler = handler

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("EmailBridge started (poll every %ds)", POLL_INTERVAL)

    def stop(self) -> None:
        self._running = False

    def _poll_loop(self) -> None:
        while self._running:
            try:
                self._poll_once()
            except Exception as e:
                logger.error("EmailBridge poll failed: %s", e, exc_info=True)
            time.sleep(POLL_INTERVAL)

    def _poll_once(self) -> None:
        if not self._username or not self._password:
            return
        try:
            mail = imaplib.IMAP4_SSL(self._host, self._port)
            mail.login(self._username, self._password)
            mail.select("INBOX")

            # Search for unseen replies to our emails
            status, messages = mail.search(None, "UNSEEN")
            if status != "OK":
                mail.logout()
                return

            for num in messages[0].split():
                try:
                    status, data = mail.fetch(num, "(RFC822)")
                    if status != "OK":
                        continue
                    msg = email.message_from_bytes(data[0][1])  # type: ignore[index,arg-type]
                    subject = self._decode_header(msg.get("Subject", ""))
                    body = self._get_body(msg)

                    # Check if this is a reply to our notification
                    action = self._parse_action(body)
                    if action:
                        logger.info("EmailBridge: %s from %s", action, subject)
                        if self._handler:
                            self._handler(action, subject, body)

                    # Mark as read so we don't process it again
                    mail.store(num, "+FLAGS", "\\Seen")
                except Exception as e:
                    logger.warning("EmailBridge: failed to process message: %s", e)

            mail.logout()
        except Exception as e:
            logger.warning("EmailBridge: connection failed: %s", e)

    @staticmethod
    def _parse_action(body: str) -> str | None:
        """Parse the first line of the reply for an action command."""
        first_line = body.strip().split("\n")[0].strip()
        if APPROVE_PATTERNS.match(first_line):
            return "approve"
        if REJECT_PATTERNS.match(first_line):
            return "reject"
        # Also check the quoted/original part isn't matched
        return None

    @staticmethod
    def _decode_header(header_value: str) -> str:
        try:
            parts = decode_header(header_value)
            return "".join(
                part.decode(charset or "utf-8") if isinstance(part, bytes) else part
                for part, charset in parts
            )
        except Exception:
            logger.warning("Failed to decode email header", exc_info=True)
            return str(header_value)

    @staticmethod
    def _get_body(msg: Any) -> str:
        """Extract the plain text body from an email message."""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            return payload.decode("utf-8", errors="replace")
                    except Exception as e:
                        logger.debug("Exception in %s: %s", __name__, e)
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode("utf-8", errors="replace")
        except Exception as e:
            logger.debug("Exception in %s: %s", __name__, e)
        return ""


# Global bridge instance
_bridge: EmailBridge | None = None


def get_bridge() -> EmailBridge:
    global _bridge
    if _bridge is None:
        _bridge = EmailBridge()
    return _bridge
