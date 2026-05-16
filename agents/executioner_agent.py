import json
import logging
import os
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
        "social_api_provider": "socialapi",
        "social_api_key": "",
        "confirm_tools": [
            "send_email",
            "send_sms",
            "post_to_social",
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
            Dict of all current settings including secrets.
            Intended for internal use only.
        """
        return dict(self._settings)

    def get_public_settings(self) -> Dict[str, Any]:
        """Return settings safe for external API responses (secrets removed).

        Returns:
            Dict with ``smtp_password`` replaced by a masked placeholder.
        """
        public = dict(self._settings)
        if public.get("smtp_password"):
            public["smtp_password"] = "********"
        return public

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
        self.register_tool("post_to_social", self._post_to_social)
        self.register_tool("post_to_social_unified", self._post_to_social_unified)
        self.register_tool("send_email", self._send_email)
        self.register_tool("send_sms", self._send_sms)
        self.register_tool("save_content_calendar", self._save_content_calendar)
        self.register_tool("save_technical_seo_report", self._save_technical_seo_report)
        self.register_tool("generate_schema_json", self._generate_schema_json)
        self.register_tool("save_report", self._save_report)
        self.register_tool("save_cro_analysis", self._save_cro_analysis)
        self.register_tool("save_video_script", self._save_video_script)
        self.register_tool("save_sms_campaign", self._save_sms_campaign)

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

        Tries MCP execution first, falls back to built-in tools.

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
                - ``social_media`` → ``post_to_social``
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
        # Try MCP execution first
        try:
            from mcp import get_mcp_server, AGENT_MCP_ROUTING
            mapping = AGENT_MCP_ROUTING.get(agent_name)
            if mapping:
                server_name, mcp_tool = mapping
                mcp_server = get_mcp_server(server_name)
                if mcp_server:
                    try:
                        result = mcp_server.call_tool(mcp_tool, content=approved_draft)
                        if result.get("success"):
                            return {
                                "success": True,
                                "result": f"MCP: {result.get('result', 'Done')}",
                                "error": None,
                                "execution_id": f"mcp-{server_name}-{mcp_tool}"
                            }
                    except Exception as e:
                        logger.warning(f"MCP call failed for {server_name}/{mcp_tool}: {e}")
        except ImportError:
            pass  # MCP not available, fall back to built-in tools
        except Exception as e:
            logger.warning(f"MCP execution failed, falling back: {e}")

        resolved_tool = tool_name or self._select_tool(agent_name)

        if resolved_tool not in self.tool_registry:
            raise ExecutionerError(
                f"Tool '{resolved_tool}' not registered "
                f"(available: {list(self.tool_registry)})"
            )

        confirm_tools: List[str] = self._settings.get("confirm_tools", [])
        needs_confirmation = resolved_tool in confirm_tools and not force

        execution_id = uuid.uuid4().hex

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
            "social_media": "post_to_social",
            "lead_conversion": "send_email",
            "paid_ads": "post_to_social",
            "growth_hacker": "publish_blog_post",
            "reputation": "send_email",
            "email_marketing": "send_email",
            "tiktok": "post_to_social",
            "outreach": "send_email",
            "backlinks": "publish_blog_post",
            "content_strategy": "save_content_calendar",
            "cro": "save_cro_analysis",
            "video": "save_video_script",
            "sms_marketing": "save_sms_campaign",
            "technical_seo": "save_technical_seo_report",
            "reporting": "save_report",
        }
        tool = mapping.get(agent_name)
        if not tool:
            raise ExecutionerError(
                f"No tool mapping for agent '{agent_name}'. "
                f"Provide an explicit tool_name or register a mapping."
            )
        return tool

    def get_available_tools(self, agent_name: str) -> list:
        """Return all tools available for a given agent, including alternatives.

        Args:
            agent_name: Name of the agent.

        Returns:
            List of registered tool name strings.
        """
        alternatives = {
            "local_seo": ["update_gmb"],
        }
        primary = self._select_tool(agent_name)
        extra = alternatives.get(agent_name, [])
        return [primary] + extra

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
            logger.error("Blog post write failed: %s", exc)
            return {"success": False, "result": "", "error": "Failed to write blog post."}

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
            logger.error("GMB update failed: %s", exc)
            return {"success": False, "result": "", "error": "Failed to record GMB update."}

    def _post_to_social(self, draft: str) -> Dict[str, Any]:
        """Post content to all connected social platforms via unified API.

        Uses the configured ``social_api_key`` with the chosen provider
        (SocialAPI, Buffer, Hootsuite, or Custom). Falls back to queuing
        to a JSONL file when no API key is configured.

        Args:
            draft: Social media post content.

        Returns:
            Result dict.
        """
        provider = self._settings.get("social_api_provider", "socialapi")
        api_key = self._settings.get("social_api_key", "")

        if api_key:
            try:
                import requests as req

                if provider == "socialapi":
                    resp = req.post(
                        "https://api.socialapi.com/v1/posts",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={"message": draft},
                        timeout=15,
                    )
                    data = resp.json()
                    if resp.status_code == 200 and data.get("success"):
                        logger.info("Social post published via SocialAPI")
                        return {"success": True, "result": "Posted via SocialAPI", "error": None}
                    error_msg = data.get("error", resp.text)
                    return {"success": False, "result": "", "error": f"SocialAPI error: {error_msg}"}

                elif provider == "buffer":
                    resp = req.post(
                        "https://api.bufferapp.com/1/updates/create.json",
                        data={"access_token": api_key, "text": draft, "profile_ids[]": []},
                        timeout=15,
                    )
                    data = resp.json()
                    if resp.status_code == 200 and data.get("success"):
                        return {"success": True, "result": "Posted via Buffer", "error": None}
                    return {"success": False, "result": "", "error": f"Buffer error: {data}"}

                elif provider == "hootsuite":
                    resp = req.post(
                        "https://platform.hootsuite.com/v1/messages",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={"text": draft, "socialProfiles": []},
                        timeout=15,
                    )
                    data = resp.json()
                    if resp.status_code in (200, 201) and data.get("id"):
                        return {"success": True, "result": "Posted via Hootsuite", "error": None}
                    return {"success": False, "result": "", "error": f"Hootsuite error: {data}"}

                else:
                    # Custom/Generic — user provides their own API endpoint via env
                    custom_url = os.getenv("SOCIAL_API_CUSTOM_URL", "")
                    if custom_url:
                        resp = req.post(
                            custom_url,
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                            },
                            json={"message": draft},
                            timeout=15,
                        )
                        data = resp.json()
                        if resp.status_code in (200, 201):
                            return {"success": True, "result": "Posted via custom API", "error": None}
                        return {"success": False, "result": "", "error": f"Custom API error: {data}"}

                    return {"success": False, "result": "", "error": "No custom API URL configured (set SOCIAL_API_CUSTOM_URL)"}

            except Exception as exc:
                return {"success": False, "result": "", "error": f"Social API request failed: {exc}"}

        # Fallback: queue to JSONL file for manual review
        try:
            social_dir = Path("content/social")
            social_dir.mkdir(parents=True, exist_ok=True)
            social_file = social_dir / "social_posts.jsonl"

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": draft,
                "provider": provider,
                "status": "pending_review",
            }

            with self._io_lock:
                with open(social_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")

            return {"success": True, "result": "Social post queued to file", "error": None}
        except OSError as exc:
            logger.error("Social post queue failed: %s", exc)
            return {"success": False, "result": "", "error": "Failed to queue social post."}

    def _post_to_social_unified(self, draft: str) -> Dict[str, Any]:
        """Post to multiple social platforms using the configured unified API."""
        provider = self._settings.get("social_api_provider", "")
        api_key = self._settings.get("social_api_key", "")

        if not api_key:
            return {"success": False, "result": "", "error": "No unified social API key configured."}

        try:
            if provider == "socialapi":
                from socialapi import SocialAPI
                client = SocialAPI(api_key=api_key)

                accounts = client.accounts.list()
                platforms = [{"platform": a.platform, "account_id": a.id} for a in accounts]

                post = client.publishing.create(text=draft, platforms=platforms)
                return {"success": True, "result": f"Published to {len(platforms)} platforms.", "error": None}
            else:
                return {"success": False, "result": "", "error": f"Provider '{provider}' is not yet supported."}
        except Exception as e:
            logger.error("Unified social post failed: %s", e, exc_info=True)
            return {"success": False, "result": "", "error": "Social post failed."}

    def _send_email(self, draft: str) -> Dict[str, Any]:
        """Send an email via SMTP or queue to file.

        When SMTP credentials are configured (``smtp_host`` is set), sends
        the email via ``smtplib``. Otherwise appends to the sent-mail JSONL
        log as a queued item.

        The subject is extracted from a ``Subject:`` line and the recipient
        from a ``To:`` line in the draft body.

        Args:
            draft: Email content (may include ``Subject:`` and ``To:`` header lines).

        Returns:
            Result dict.
        """
        subject_match = re.search(
            r"^(?:#\s*)?Subject\s*:\s*(.+)$", draft, re.MULTILINE | re.IGNORECASE
        )
        subject = subject_match.group(1).strip() if subject_match else "(no subject)"

        to_match = re.search(
            r"^(?:#\s*)?To\s*:\s*(.+)$", draft, re.MULTILINE | re.IGNORECASE
        )
        recipient = to_match.group(1).strip() if to_match else ""

        smtp_host = self._settings.get("smtp_host", "")

        if smtp_host:
            return self._send_email_smtp(draft, subject, recipient)

        return self._queue_email(draft, subject, recipient)

    def _send_email_smtp(self, draft: str, subject: str, recipient: str) -> Dict[str, Any]:
        """Send email via SMTP using configured credentials.

        Args:
            draft: Full email body.
            subject: Extracted subject line.
            recipient: Recipient email address from draft ``To:`` header.

        Returns:
            Result dict.
        """
        smtp_host = self._settings.get("smtp_host", "")
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

        if not recipient:
            return {
                "success": False,
                "result": "",
                "error": "No recipient email found. Add a 'To: email@example.com' line to the draft.",
            }

        try:
            msg = MIMEText(draft, _charset="utf-8")
            msg["Subject"] = subject
            msg["From"] = smtp_from
            msg["To"] = recipient

            server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
            if use_tls:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
            server.quit()

            logger.info("Email sent via SMTP (to=%s, subject=%s)", recipient, subject)
            return {
                "success": True,
                "result": f"Email sent to {recipient}: {subject}",
                "error": None,
            }
        except Exception as exc:
            logger.error("SMTP send failed: %s", exc)
            return {"success": False, "result": "", "error": f"SMTP send failed: {exc}"}

    def _queue_email(self, draft: str, subject: str, recipient: str) -> Dict[str, Any]:
        """Queue an email to the sent-mail JSONL log.

        Args:
            draft: Full email body.
            subject: Extracted subject line.
            recipient: Recipient email address from draft ``To:`` header.

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
                "to": recipient,
                "body": draft,
                "status": "queued",
            }

            with self._io_lock:
                with open(email_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")

            return {"success": True, "result": f"Email queued: {subject}", "error": None}
        except OSError as exc:
            logger.error("Email queue failed: %s", exc)
            return {"success": False, "result": "", "error": "Failed to queue email."}

    def _send_sms(self, draft: str) -> Dict[str, Any]:
        """Queue an SMS to the SMS log.

        Args:
            draft: SMS message content.

        Returns:
            Result dict.
        """
        try:
            sms_dir = Path("content/sms")
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
            logger.error("SMS queue failed: %s", exc)
            return {"success": False, "result": "", "error": "Failed to queue SMS."}

    def _save_content_calendar(self, draft: str) -> Dict[str, Any]:
        try:
            cal_dir = Path("content/strategy")
            cal_dir.mkdir(parents=True, exist_ok=True)
            slug = self._slugify(draft.strip().split("\n")[0][:60])
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            fp = cal_dir / f"calendar-{slug}-{ts}.jsonl"
            record = {"id": uuid.uuid4().hex[:12], "type": "content_calendar", "content": draft, "created_at": datetime.now(timezone.utc).isoformat()}
            with open(fp, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            logger.info("Calendar saved: %s", fp)
            return {"success": True, "result": str(fp), "error": None}
        except OSError as exc:
            logger.error("Calendar save failed: %s", exc)
            return {"success": False, "result": "", "error": "Failed to save content calendar."}

    def _save_technical_seo_report(self, draft: str) -> Dict[str, Any]:
        try:
            ts_dir = Path("content/technical_seo")
            ts_dir.mkdir(parents=True, exist_ok=True)
            slug = self._slugify(draft.strip().split("\n")[0][:60])
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            fp = ts_dir / f"audit-{slug}-{ts}.md"
            fp.write_text(draft.strip(), encoding="utf-8")
            logger.info("Tech SEO report saved: %s", fp)
            return {"success": True, "result": str(fp), "error": None}
        except OSError as exc:
            logger.error("Tech SEO save failed: %s", exc)
            return {"success": False, "result": "", "error": "Failed to save technical SEO report."}

    def _generate_schema_json(self, draft: str) -> Dict[str, Any]:
        try:
            schema_dir = Path("content/technical_seo")
            schema_dir.mkdir(parents=True, exist_ok=True)
            slug = self._slugify(draft.strip().split("\n")[0][:60])
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            fp = schema_dir / f"schema-{slug}-{ts}.json"
            fp.write_text(draft.strip(), encoding="utf-8")
            logger.info("Schema saved: %s", fp)
            return {"success": True, "result": str(fp), "error": None}
        except OSError as exc:
            logger.error("Schema save failed: %s", exc)
            return {"success": False, "result": "", "error": "Failed to save schema markup."}

    def _save_report(self, draft: str) -> Dict[str, Any]:
        try:
            rep_dir = Path("content/reports")
            rep_dir.mkdir(parents=True, exist_ok=True)
            slug = self._slugify(draft.strip().split("\n")[0][:60])
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            fp = rep_dir / f"report-{slug}-{ts}.html"
            fp.write_text(draft.strip(), encoding="utf-8")
            logger.info("Report saved: %s", fp)
            return {"success": True, "result": str(fp), "error": None}
        except OSError as exc:
            logger.error("Report save failed: %s", exc)
            return {"success": False, "result": "", "error": "Failed to save report."}

    def _save_cro_analysis(self, draft: str) -> Dict[str, Any]:
        try:
            cd = Path("content/cro"); cd.mkdir(parents=True, exist_ok=True)
            slug = self._slugify(draft.strip().split("\n")[0][:60]); ts = datetime.now().strftime("%Y%m%d%H%M%S")
            fp = cd / f"cro-{slug}-{ts}.md"; fp.write_text(draft.strip(), encoding="utf-8")
            return {"success": True, "result": str(fp), "error": None}
        except OSError as exc:
            logger.error("CRO save failed: %s", exc)
            return {"success": False, "result": "", "error": "Failed to save CRO analysis."}

    def _save_video_script(self, draft: str) -> Dict[str, Any]:
        try:
            vd = Path("content/video"); vd.mkdir(parents=True, exist_ok=True)
            slug = self._slugify(draft.strip().split("\n")[0][:60]); ts = datetime.now().strftime("%Y%m%d%H%M%S")
            fp = vd / f"video-{slug}-{ts}.md"; fp.write_text(draft.strip(), encoding="utf-8")
            return {"success": True, "result": str(fp), "error": None}
        except OSError as exc:
            logger.error("Video save failed: %s", exc)
            return {"success": False, "result": "", "error": "Failed to save video script."}

    def _save_sms_campaign(self, draft: str) -> Dict[str, Any]:
        try:
            sd = Path("content/sms_campaigns"); sd.mkdir(parents=True, exist_ok=True)
            slug = self._slugify(draft.strip().split("\n")[0][:60]); ts = datetime.now().strftime("%Y%m%d%H%M%S")
            fp = sd / f"sms-{slug}-{ts}.md"; fp.write_text(draft.strip(), encoding="utf-8")
            return {"success": True, "result": str(fp), "error": None}
        except OSError as exc:
            logger.error("SMS campaign save failed: %s", exc)
            return {"success": False, "result": "", "error": "Failed to save SMS campaign."}

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
