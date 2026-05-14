"""Push notification manager — sends Web Push notifications to PWA subscribers.

Uses the ``pywebpush`` library for encrypted push delivery via browser's
native push service. Falls back gracefully if the library is not installed.

Subscriptions are persisted to ``data/push_subscriptions.jsonl`` so they
survive server restarts but are not stored in tenant databases (they are
browser-scoped, not tenant-scoped).

VAPID keys can be set via environment variables ``VAPID_PUBLIC_KEY`` and
``VAPID_PRIVATE_KEY``. If unset, ephemeral keys are generated on each
startup (existing subscriptions will become invalid after restart, which
is fine — the browser recovers automatically).
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SUBSCRIPTIONS_FILE = Path("data/push_subscriptions.jsonl")

try:
    from pywebpush import webpush, WebPushException
    HAS_PYWEBPUSH = True
except ImportError:
    HAS_PYWEBPUSH = False
    logger.info("pywebpush not installed — push disabled. Install: pip install pywebpush")


class PushManager:
    """Manages Web Push subscriptions and sends push notifications.

    Thread-safe. Degrades gracefully if ``pywebpush`` is not installed.
    Subscriptions are stored in a JSONL file for persistence.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscriptions: List[Dict[str, Any]] = []
        self._vapid_private_key = os.getenv("VAPID_PRIVATE_KEY", "")
        self._vapid_claims = {"sub": "mailto:lavaldigital@gmail.com"}
        self._load_subscriptions()

    @property
    def public_key(self) -> str:
        return os.getenv("VAPID_PUBLIC_KEY", "")

    @property
    def enabled(self) -> bool:
        return HAS_PYWEBPUSH and bool(self._vapid_private_key) and bool(self.public_key)

    # ── Subscription persistence ───────────────────────────────────────

    def _load_subscriptions(self) -> None:
        if not SUBSCRIPTIONS_FILE.exists():
            return
        with self._lock:
            self._subscriptions = []
            try:
                SUBSCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(SUBSCRIPTIONS_FILE, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                self._subscriptions.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                logger.warning("Failed to load push subscriptions: %s", e)

    def _save_subscriptions(self) -> None:
        try:
            SUBSCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with open(SUBSCRIPTIONS_FILE, "w") as f:
                    for sub in self._subscriptions:
                        f.write(json.dumps(sub) + "\n")
        except Exception as e:
            logger.warning("Failed to save push subscriptions: %s", e)

    # ── Subscribe / Unsubscribe ────────────────────────────────────────

    def subscribe(self, subscription: Dict[str, Any]) -> bool:
        endpoint = subscription.get("endpoint", "")
        if not endpoint:
            return False
        with self._lock:
            exists = any(s.get("endpoint") == endpoint for s in self._subscriptions)
            if not exists:
                self._subscriptions.append(subscription)
                self._save_subscriptions()
        return True

    def unsubscribe(self, endpoint: str) -> bool:
        with self._lock:
            before = len(self._subscriptions)
            self._subscriptions = [s for s in self._subscriptions if s.get("endpoint") != endpoint]
            if len(self._subscriptions) < before:
                self._save_subscriptions()
            return len(self._subscriptions) < before

    # ── Send notifications ─────────────────────────────────────────────

    def send(self, title: str, body: str, icon: str = "/static/logo.svg", url: str = "/admin/dashboard") -> int:
        """Send a push notification to all active subscribers.

        Args:
            title: Notification title.
            body: Notification body text.
            icon: Icon URL (defaults to app logo).
            url: URL to open when notification is clicked.

        Returns:
            Number of successful sends.
        """
        if not self.enabled:
            return 0

        payload = json.dumps({
            "title": title,
            "body": body,
            "icon": icon,
            "url": url,
            "badge": "/static/logo.svg",
        })

        with self._lock:
            subs = list(self._subscriptions)

        success = 0
        expired = []
        for sub in subs:
            try:
                webpush(
                    subscription_info=sub,
                    data=payload,
                    vapid_private_key=self._vapid_private_key,
                    vapid_claims=self._vapid_claims,
                )
                success += 1
            except WebPushException as e:
                if e.response and e.response.status_code in (404, 410):
                    expired.append(sub.get("endpoint", ""))
                else:
                    logger.warning("Push send failed: %s", e)
            except Exception as e:
                logger.warning("Push send error: %s", e)

        if expired:
            with self._lock:
                for ep in expired:
                    self._subscriptions = [s for s in self._subscriptions if s.get("endpoint") != ep]
                self._save_subscriptions()

        return success

    def send_event(self, event_type: str, agent: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Send a push notification mapped from an orchestrator event."""
        data = data or {}
        if event_type == "agent_executed":
            self.send(
                title=f"✅ {agent} completed",
                body=(data.get("draft_preview") or "Task executed.")[:120],
            )
        elif event_type == "agent_failed":
            self.send(
                title=f"❌ {agent} failed",
                body=(data.get("error") or "Task failed.")[:120],
            )
        elif event_type == "approval_needed":
            self.send(
                title=f"🤔 {agent} needs approval",
                body=(data.get("draft_preview") or "New draft ready for review.")[:120],
                url="/admin",
            )
        elif event_type == "approval_responded":
            self.send(
                title=f"📋 {agent} processed",
                body="Your approval response has been received.",
            )
