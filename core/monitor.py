"""Proactive monitoring — background thread that checks agent health,
pending approvals, and execution metrics, then sends push alerts.

Runs every 5 minutes.  Starts automatically when the app boots.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class _Monitor:
    def __init__(self) -> None:
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._orchestrator_getter = None
        self._push_getter = None
        self._last_alert: Dict[str, float] = {}
        self._alert_cooldown = 300  # 5 minutes

    def start(self, get_orchestrator, get_push) -> None:
        self._orchestrator_getter = get_orchestrator
        self._push_getter = get_push
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Proactive monitor started (interval=300s)")

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.debug("Monitor tick error: %s", e)
            time.sleep(300)

    def _tick(self) -> None:
        orch = self._orchestrator_getter() if self._orchestrator_getter else None
        push = self._push_getter() if self._push_getter else None
        if not orch or not push:
            return

        now = time.time()

        # 1. Pending approvals alert
        pending = len(orch.get_pending_drafts())
        if pending > 0 and self._can_alert("pending", now):
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        push.send,
                        title=f"\U0001F4CB {pending} approval{'s' if pending > 1 else ''} pending",
                        body=f"You have {pending} draft{'s' if pending > 1 else ''} waiting for review.",
                        url="/admin",
                    )
                    future.result(timeout=10)
            except (FuturesTimeout, Exception):
                logger.warning("Push notification timed out or failed")
            self._last_alert["pending"] = now

        # 2. Stale activity check
        activities = orch.get_activity_feed(1)
        if activities:
            last_activity = activities[0].get("timestamp", "")
            if last_activity:
                try:
                    last_dt = datetime.fromisoformat(last_activity)
                    hours_idle = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                    if hours_idle > 4 and self._can_alert("idle", now):
                        try:
                            push.send(
                                title="\u23F0 No activity in 4+ hours",
                                body="Your agents have been quiet. Check in to review pending items.",
                                url="/admin/dashboard",
                            )
                        except Exception:
                            logger.warning("Push notification failed", exc_info=True)
                        self._last_alert["idle"] = now
                except Exception as e:
                    logger.debug("Exception in %s: %s", __name__, e)

        # 3. Panic check
        if orch.is_panicked and self._can_alert("panic", now):
            try:
                push.send(
                    title="\u26A0\ufe0f Agents are stopped",
                    body="All agents are currently panicked. Click to resume.",
                    url="/admin/dashboard",
                )
            except Exception:
                logger.warning("Push notification failed", exc_info=True)
            self._last_alert["panic"] = now

    def _can_alert(self, key: str, now: float) -> bool:
        last = self._last_alert.get(key, 0)
        return now - last > self._alert_cooldown


monitor = _Monitor()
