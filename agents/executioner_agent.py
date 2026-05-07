import json
import logging
import re
import smtplib
import threading
import time
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ExecutionerError(Exception):
    pass


class ExecutionerAgent:
    """Pure execution engine that runs approved drafts against real APIs.

    Unlike LLM-based agents, the Executioner has no system prompt, no draft/approval
    graph nodes, and no model. It's a registry of typed tool functions invoked by
    agent name or explicit tool name.

    Tools that send external communications (email, SMS, social posts) require
    explicit human confirmation before executing. The caller queues them via
    :meth:`execute`, then calls :meth:`confirm_execution` after the operator reviews.

    Runtime settings (SMTP credentials, social API keys, which tools require
    confirmation) are configurable through :meth:`update_settings` and exposed
    via the admin panel.
    """

    DEFAULT_SETTINGS: Dict[str, Any] = {
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_username": "",
        "smtp_password": "",
        "smtp_from_email": "",
        "smtp_use_tls": True,
        "facebook_page_id": "",
        "facebook_access_token": "",
        "instagram_account_id": "",
        "instagram_access_token": "",
        "confirm_tools": [
            "send_email",
            "send_sms",
            "post_to_facebook",
            "post_to_instagram",
        ],
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Initialize the ExecutionerAgent.

        Args:
            config: Dict with keys:
                - execution_log_path (str): Path to JSONL log file.
                  Defaults to ``logs/executions.jsonl``.
                - max_retries (int): Retry attempts on tool failure. Defaults to 3.
                - retry_delay (int): Seconds between retries. Defaults to 5.
        """
        config = config or {}
        self._execution_log_path = Path(
            config.get("execution_log_path", "logs/executions.jsonl")
        )
        self._max_retries = config.get("max_retries", 3)
        self._retry_delay = config.get("retry_delay", 5)
        self.tool_registry: Dict[str, Callable] = {}
        self._settings: Dict[str, Any] = dict(self.DEFAULT_SETTINGS)
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._io_lock = threading.Lock()
        self._pending_lock = threading.Lock()

        self._execution_log_path.parent.mkdir(parents=True, exist_ok=True)

        self._register_default_tools()
        logger.info(
            "ExecutionerAgent initialized (log=%s, retries=%s)",
            self._execution_log_path,
            self._max_retries,
        )

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def update_settings(self, settings: Dict[str, Any]) -> None:
        """Update runtime settings.

        Only supplied keys are changed; missing keys keep existing values.
        Settings are stored in-memory (not persisted across restarts).

        Args:
            settings: Dict with any of the keys defined in
                :attr:`DEFAULT_SETTINGS`.
        """
        self._settings.update(settings)
        logger.debug("Settings updated: %s", list(settings))

    def get_settings(self) -> Dict[str, Any]:
        """Return a copy of the current settings.

        Returns:
            Dict of all current settings.
        """
        return dict(self._settings)

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def register_tool(self, tool_name: str, tool_func: Callable) -> None:
        """Register a tool function by name.

        Args:
            tool_name: Unique identifier for the tool
                (e.g. ``publish_blog_post``, ``send_email``).
            tool_func: Callable that accepts a single string argument
                (the approved draft) and returns a dict:
                ``{"success": bool, "result": str, "error": Optional[str]}``.
        """
        self.tool_registry[tool_name] = tool_func
        logger.debug("Registered tool: %s", tool_name)

    def _register_default_tools(self) -> None:
        """Register the built-in tool implementations."""
        self.register_tool("publish_blog_post", self._publish_blog_post)
        self.register_tool("update_gmb", self._update_gmb)
        self.register_tool("post_to_facebook", self._post_to_facebook)
        self.register_tool("post_to_instagram", self._post_to_instagram)
        self.register_tool("send_email", self._send_email)
        self.register_tool("send_sms", self._send_sms)

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    def execute(
        self,
        agent_name: str,
        approved_draft: str,
        tool_name: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Execute an approved draft through a registered tool.

        When the resolved tool is in the ``confirm_tools`` list and
        ``force`` is ``False``, the execution is queued for human
        confirmation instead of running immediately.

        Args:
            agent_name: Source agent name used for auto-selection when
                ``tool_name`` is not given.
            approved_draft: The full approved draft text to execute.
            tool_name: Explicit tool name. When ``None``, the tool is
                auto-selected based on ``agent_name``:
                - ``local_seo`` → ``publish_blog_post``
                - ``social_media`` → ``post_to_facebook``
                - ``lead_conversion`` → ``send_email``
            force: If ``True``, bypass the confirmation queue and run
                immediately.

        Returns:
            Dict with keys ``success``, ``result``, ``error``, and
            ``execution_id``.  When queued for confirmation the result
            is ``"pending_confirmation"`` and the caller should prompt
            the operator to call :meth:`confirm_execution`.

        Raises:
            ExecutionerError: If no tool can be found for the given inputs.
        """
        resolved_tool = tool_name or self._select_tool(agent_name)

        if resolved_tool not in self.tool_registry:
            raise ExecutionerError(
                f"Tool '{resolved_tool}' not registered "
                f"(available: {list(self.tool_registry)})"
            )

        confirm_tools: List[str] = self._settings.get("confirm_tools", [])
        needs_confirmation = resolved_tool in confirm_tools and not force

        execution_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")

        if needs_confirmation:
            with self._pending_lock:
                self._pending[execution_id] = {
                    "execution_id": execution_id,
                    "agent_name": agent_name,
                    "tool_name": resolved_tool,
                    "approved_draft": approved_draft,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "status": "pending_confirmation",
                }
            logger.info(
                "Execution %s queued for confirmation (tool=%s)",
                execution_id,
                resolved_tool,
            )
            return {
                "success": True,
                "status": "pending_confirmation",
                "result": "Awaiting confirmation before execution",
                "error": None,
                "execution_id": execution_id,
            }

        return self._run_tool(
            execution_id=execution_id,
            agent_name=agent_name,
            tool_name=resolved_tool,
            approved_draft=approved_draft,
        )

    def _run_tool(
        self,
        execution_id: str,
        agent_name: str,
        tool_name: str,
        approved_draft: str,
    ) -> Dict[str, Any]:
        """Run a tool with retry logic and log the outcome.

        Args:
            execution_id: Unique identifier for this execution.
            agent_name: Source agent name.
            tool_name: Tool to invoke.
            approved_draft: Draft to pass to the tool.

        Returns:
            Result dict with execution_id.
        """
        tool_func = self.tool_registry[tool_name]
        last_error: Optional[str] = None

        for attempt in range(1, self._max_retries + 1):
            try:
                result_payload = tool_func(approved_draft)
                if result_payload.get("success", False):
                    self._log_execution(
                        execution_id=execution_id,
                        agent_name=agent_name,
                        tool_name=tool_name,
                        draft_preview=approved_draft[:200],
                        success=True,
                        result=result_payload.get("result", ""),
                        error=None,
                    )
                    logger.info(
                        "Execution %s succeeded (tool=%s, attempt=%s)",
                        execution_id,
                        tool_name,
                        attempt,
                    )
                    return {
                        "success": True,
                        "result": result_payload.get("result", ""),
                        "error": None,
                        "execution_id": execution_id,
                    }

                last_error = result_payload.get("error", "Tool returned no error")
                logger.warning(
                    "Execution %s attempt %s failed: %s",
                    execution_id,
                    attempt,
                    last_error,
                )

            except Exception as exc:
                last_error = str(exc)
                logger.error(
                    "Execution %s attempt %s exception: %s",
                    execution_id,
                    attempt,
                    last_error,
                )

            if attempt < self._max_retries:
                time.sleep(self._retry_delay)

        self._log_execution(
            execution_id=execution_id,
            agent_name=agent_name,
            tool_name=tool_name,
            draft_preview=approved_draft[:200],
            success=False,
            result="",
            error=last_error,
        )
        logger.error(
            "Execution %s failed after %s attempts", execution_id, self._max_retries
        )
        return {
            "success": False,
            "result": "",
            "error": last_error or "Unknown error",
            "execution_id": execution_id,
        }

    def confirm_execution(self, execution_id: str) -> Dict[str, Any]:
        """Confirm and execute a previously queued execution.

        Removes the execution from the pending queue and runs the tool.

        Args:
            execution_id: The execution identifier returned by
                :meth:`execute`.

        Returns:
            The result dict from the tool execution.
        """
        with self._pending_lock:
            pending = self._pending.pop(execution_id, None)

        if not pending:
            raise ExecutionerError(
                f"No pending execution with id '{execution_id}'"
            )

        logger.info(
            "Confirming execution %s (tool=%s)",
            execution_id,
            pending["tool_name"],
        )
        return self._run_tool(
            execution_id=execution_id,
            agent_name=pending["agent_name"],
            tool_name=pending["tool_name"],
            approved_draft=pending["approved_draft"],
        )

    def reject_execution(self, execution_id: str) -> Dict[str, Any]:
        """Reject a queued execution without running it.

        Args:
            execution_id: The execution identifier to reject.

        Returns:
            Dict confirming the rejection.
        """
        with self._pending_lock:
            pending = self._pending.pop(execution_id, None)

        if not pending:
            raise ExecutionerError(
                f"No pending execution with id '{execution_id}'"
            )

        logger.info("Rejecting execution %s", execution_id)

        self._log_execution(
            execution_id=execution_id,
            agent_name=pending["agent_name"],
            tool_name=pending["tool_name"],
            draft_preview=pending["approved_draft"][:200],
            success=False,
            result="",
            error="Rejected by operator",
        )
        return {
            "success": False,
            "result": "Rejected by operator",
            "error": "Rejected by operator",
            "execution_id": execution_id,
        }

    def get_pending_executions(self) -> List[Dict[str, Any]]:
        """Return all executions waiting for confirmation.

        Returns:
            List of pending execution dicts.
        """
        with self._pending_lock:
            return [
                {
                    "execution_id": e["execution_id"],
                    "agent_name": e["agent_name"],
                    "tool_name": e["tool_name"],
                    "draft_preview": e["approved_draft"][:200],
                    "created_at": e["created_at"],
                    "status": e["status"],
                }
                for e in self._pending.values()
            ]

    def _select_tool(self, agent_name: str) -> str:
        """Auto-select a tool based on the source agent name.

        Args:
            agent_name: Name of the agent that produced the draft.

        Returns:
            A registered tool name string.

        Raises:
            ExecutionerError: If ``agent_name`` has no mapped tool.
        """
        mapping = {
            "local_seo": "publish_blog_post",
            "social_media": "post_to_facebook",
            "lead_conversion": "send_email",
        }
        tool = mapping.get(agent_name)
        if not tool:
            raise ExecutionerError(
                f"No tool mapping for agent '{agent_name}'. "
                f"Provide an explicit tool_name or register a mapping."
            )
        return tool

    # ------------------------------------------------------------------
    # Built-in tool implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert text to a URL-safe slug."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s_]+", "-", text)
        text = re.sub(r"-+", "-", text)
        return text.strip("-")

    def _publish_blog_post(self, draft: str) -> Dict[str, Any]:
        """Write an approved blog post as a Markdown file.

        The file is saved to ``content/blog/<slug>-<timestamp>.md``.

        Args:
            draft: Full blog post content (Markdown or plain text).

        Returns:
            Result dict with ``success``, ``result`` (file path), ``error``.
        """
        try:
            blog_dir = Path("content/blog")
            blog_dir.mkdir(parents=True, exist_ok=True)

            first_line = draft.strip().split("\n")[0][:80]
            slug = self._slugify(first_line)
            if not slug:
                slug = "blog-post"
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"{slug}-{timestamp}.md"
            filepath = blog_dir / filename

            filepath.write_text(draft.strip(), encoding="utf-8")
            logger.info("Blog post written: %s", filepath)

            return {"success": True, "result": str(filepath), "error": None}
        except OSError as exc:
            return {"success": False, "result": "", "error": f"Failed to write blog post: {exc}"}

    def _update_gmb(self, draft: str) -> Dict[str, Any]:
        """Record a Google Business Profile update to a JSONL audit log.

        Args:
            draft: GMB update content (post copy, hours change, etc.).

        Returns:
            Result dict.
        """
        try:
            gmb_dir = Path("content/social")
            gmb_dir.mkdir(parents=True, exist_ok=True)
            gmb_file = gmb_dir / "gmb_updates.jsonl"

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": draft,
                "status": "pending_review",
            }

            with self._io_lock:
                with open(gmb_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")

            return {"success": True, "result": "GMB update recorded", "error": None}
        except OSError as exc:
            return {"success": False, "result": "", "error": str(exc)}

    def _post_to_facebook(self, draft: str) -> Dict[str, Any]:
        """Post content to Facebook or queue for manual review.

        When ``facebook_access_token`` is configured, posts via the
        Facebook Graph API. Otherwise queues to a JSONL file.

        Args:
            draft: Social media post content.

        Returns:
            Result dict.
        """
        token = self._settings.get("facebook_access_token", "")
        page_id = self._settings.get("facebook_page_id", "")

        if token and page_id:
            try:
                import requests as req

                url = f"https://graph.facebook.com/v19.0/{page_id}/feed"
                resp = req.post(
                    url,
                    data={"message": draft, "access_token": token},
                    timeout=15,
                )
                data = resp.json()
                if resp.status_code == 200 and data.get("id"):
                    logger.info("Facebook post published (id=%s)", data["id"])
                    return {
                        "success": True,
                        "result": f"Facebook post published (id={data['id']})",
                        "error": None,
                    }
                error_msg = data.get("error", {}).get("message", resp.text)
                return {"success": False, "result": "", "error": f"Facebook API error: {error_msg}"}
            except Exception as exc:
                return {"success": False, "result": "", "error": f"Facebook request failed: {exc}"}

        try:
            social_dir = Path("content/social")
            social_dir.mkdir(parents=True, exist_ok=True)
            fb_file = social_dir / "facebook_posts.jsonl"

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": draft,
                "status": "pending_review",
            }

            with self._io_lock:
                with open(fb_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")

            return {"success": True, "result": "Facebook post queued to file", "error": None}
        except OSError as exc:
            return {"success": False, "result": "", "error": str(exc)}

    def _post_to_instagram(self, draft: str) -> Dict[str, Any]:
        """Post content to Instagram or queue for manual review.

        When ``instagram_access_token`` is configured, posts via the
        Instagram Graph API. Otherwise queues to a JSONL file.

        Args:
            draft: Instagram post content (caption + optional hashtags).

        Returns:
            Result dict.
        """
        token = self._settings.get("instagram_access_token", "")
        account_id = self._settings.get("instagram_account_id", "")

        if token and account_id:
            try:
                import requests as req

                url = f"https://graph.facebook.com/v19.0/{account_id}/media"
                resp = req.post(
                    url,
                    data={"caption": draft, "access_token": token},
                    timeout=15,
                )
                creation_data = resp.json()
                if resp.status_code != 200 or not creation_data.get("id"):
                    error_msg = creation_data.get("error", {}).get("message", resp.text)
                    return {"success": False, "result": "", "error": f"Instagram API error: {error_msg}"}

                media_id = creation_data["id"]
                publish_url = f"https://graph.facebook.com/v19.0/{account_id}/media_publish"
                pub_resp = req.post(
                    publish_url,
                    data={"creation_id": media_id, "access_token": token},
                    timeout=15,
                )
                pub_data = pub_resp.json()
                if pub_resp.status_code == 200 and pub_data.get("id"):
                    logger.info("Instagram post published (id=%s)", pub_data["id"])
                    return {
                        "success": True,
                        "result": f"Instagram post published (id={pub_data['id']})",
                        "error": None,
                    }
                return {
                    "success": False,
                    "result": "",
                    "error": f"Instagram publish failed: {pub_data}",
                }
            except Exception as exc:
                return {"success": False, "result": "", "error": f"Instagram request failed: {exc}"}

        try:
            social_dir = Path("content/social")
            social_dir.mkdir(parents=True, exist_ok=True)
            ig_file = social_dir / "instagram_posts.jsonl"

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": draft,
                "status": "pending_review",
            }

            with self._io_lock:
                with open(ig_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")

            return {"success": True, "result": "Instagram post queued to file", "error": None}
        except OSError as exc:
            return {"success": False, "result": "", "error": str(exc)}

    def _send_email(self, draft: str) -> Dict[str, Any]:
        """Send an email via SMTP or queue to file.

        When SMTP credentials are configured (``smtp_host`` is set), sends
        the email via ``smtplib``. Otherwise appends to the sent-mail JSONL
        log as a queued item.

        The subject is extracted from a ``Subject:`` line in the draft body.

        Args:
            draft: Email content (may include a ``Subject:`` header line).

        Returns:
            Result dict.
        """
        subject_match = re.search(
            r"^(?:#\s*)?Subject\s*:\s*(.+)$", draft, re.MULTILINE | re.IGNORECASE
        )
        subject = subject_match.group(1).strip() if subject_match else "(no subject)"

        smtp_host = self._settings.get("smtp_host", "")

        if smtp_host:
            return self._send_email_smtp(draft, subject)

        return self._queue_email(draft, subject)

    def _send_email_smtp(self, draft: str, subject: str) -> Dict[str, Any]:
        """Send email via SMTP using configured credentials.

        Args:
            draft: Full email body.
            subject: Extracted subject line.

        Returns:
            Result dict.
        """
        smtp_port = int(self._settings.get("smtp_port", 587))
        smtp_user = self._settings.get("smtp_username", "")
        smtp_pass = self._settings.get("smtp_password", "")
        smtp_from = self._settings.get("smtp_from_email", smtp_user)
        use_tls = self._settings.get("smtp_use_tls", True)

        if not smtp_user:
            return {
                "success": False,
                "result": "",
                "error": "SMTP username not configured",
            }

        try:
            msg = MIMEText(draft, _charset="utf-8")
            msg["Subject"] = subject
            msg["From"] = smtp_from
            msg["To"] = smtp_from

            server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
            if use_tls:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
            server.quit()

            logger.info("Email sent via SMTP (subject=%s)", subject)
            return {
                "success": True,
                "result": f"Email sent via SMTP: {subject}",
                "error": None,
            }
        except Exception as exc:
            logger.error("SMTP send failed: %s", exc)
            return {"success": False, "result": "", "error": f"SMTP send failed: {exc}"}

    def _queue_email(self, draft: str, subject: str) -> Dict[str, Any]:
        """Queue an email to the sent-mail JSONL log.

        Args:
            draft: Full email body.
            subject: Extracted subject line.

        Returns:
            Result dict.
        """
        try:
            email_dir = Path("content/emails")
            email_dir.mkdir(parents=True, exist_ok=True)
            email_file = email_dir / "sent.jsonl"

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "subject": subject,
                "body": draft,
                "status": "queued",
            }

            with self._io_lock:
                with open(email_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")

            return {"success": True, "result": f"Email queued: {subject}", "error": None}
        except OSError as exc:
            return {"success": False, "result": "", "error": str(exc)}

    def _send_sms(self, draft: str) -> Dict[str, Any]:
        """Queue an SMS to the SMS log.

        Args:
            draft: SMS message content.

        Returns:
            Result dict.
        """
        try:
            sms_dir = Path("content/emails")
            sms_dir.mkdir(parents=True, exist_ok=True)
            sms_file = sms_dir / "sms.jsonl"

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": draft,
                "status": "queued",
            }

            with self._io_lock:
                with open(sms_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")

            return {"success": True, "result": "SMS queued", "error": None}
        except OSError as exc:
            return {"success": False, "result": "", "error": str(exc)}

    # ------------------------------------------------------------------
    # Execution log
    # ------------------------------------------------------------------

    def _log_execution(
        self,
        execution_id: str,
        agent_name: str,
        tool_name: str,
        draft_preview: str,
        success: bool,
        result: str,
        error: Optional[str],
    ) -> None:
        """Append an execution record to the JSONL log file.

        Args:
            execution_id: Unique execution identifier.
            agent_name: Source agent name.
            tool_name: Tool used.
            draft_preview: First 200 characters of the draft.
            success: Whether execution succeeded.
            result: Execution result string.
            error: Error message on failure, else None.
        """
        record = {
            "execution_id": execution_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_name": agent_name,
            "tool_name": tool_name,
            "draft_preview": draft_preview,
            "success": success,
            "result": result,
            "error": error,
        }
        with self._io_lock:
            self._execution_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._execution_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

    def get_execution_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Read recent execution records from the JSONL log.

        Args:
            limit: Maximum number of records to return, newest first.
                Defaults to 50.

        Returns:
            List of execution dicts in reverse chronological order.
        """
        if not self._execution_log_path.exists():
            return []

        records: List[Dict[str, Any]] = []
        with self._io_lock:
            with open(self._execution_log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning("Skipping malformed log line")

        records.reverse()
        return records[:limit]

    def get_execution_by_id(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Find a specific execution by its ID.

        Args:
            execution_id: The execution identifier to search for.

        Returns:
            Matching record dict, or ``None`` if not found.
        """
        if not self._execution_log_path.exists():
            return None

        with self._io_lock:
            with open(self._execution_log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            record = json.loads(line)
                            if record.get("execution_id") == execution_id:
                                return record
                        except json.JSONDecodeError:
                            continue
        return None


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    agent = ExecutionerAgent({
        "execution_log_path": "logs/executions.jsonl",
        "max_retries": 3,
        "retry_delay": 5,
    })

    test_draft = """\
# Laval 24/7 Plumbing — Why Regular Maintenance Saves You Money

Regular plumbing maintenance isn't just about preventing emergencies—it's about
protecting your investment. At Laval 24/7 Plumbing, we recommend annual
inspections to catch small issues before they become expensive repairs.

Call us today at (450) 555-0199 to schedule your inspection!"""

    print("=" * 60)
    print("ExecutionerAgent Test — Confirmation Flow")
    print("=" * 60)

    blog_result = agent.execute(
        agent_name="local_seo",
        approved_draft=test_draft,
        tool_name="publish_blog_post",
    )
    print(f"\nBlog publish (no confirmation needed): {json.dumps(blog_result, indent=2)}")

    fb_result = agent.execute(
        agent_name="social_media",
        approved_draft="Big news! 24/7 plumbing in Laval. Call (450) 555-0199!",
        tool_name="post_to_facebook",
    )
    print(f"\nFacebook (needs confirmation): {json.dumps(fb_result, indent=2)}")

    pending = agent.get_pending_executions()
    print(f"\nPending confirmations: {len(pending)}")
    for p in pending:
        print(f"  {p['execution_id'][:20]}...  {p['tool_name']}")

    if pending:
        exec_id = pending[0]["execution_id"]
        confirmed = agent.confirm_execution(exec_id)
        print(f"\nConfirmed execution: {json.dumps(confirmed, indent=2)}")

    email_result = agent.execute(
        agent_name="lead_conversion",
        approved_draft="Subject: Your Free Inspection\n\nBody here",
        tool_name="send_email",
    )
    print(f"\nEmail (needs confirmation): {json.dumps(email_result, indent=2)}")

    print(f"\n{'=' * 60}")
    print(f"Execution History (last 5):")
    print(f"{'=' * 60}")
    for entry in agent.get_execution_history(limit=5):
        print(
            f"  [{entry['execution_id'][:16]}...] "
            f"{entry['tool_name']:25s} "
            f"{'OK' if entry['success'] else 'FAIL':5s} "
            f"{entry['result'][:60]}"
        )
