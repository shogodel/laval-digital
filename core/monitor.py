"""Proactive monitoring — background thread that checks agent health,
pending approvals, and execution metrics, then sends push alerts.

Runs every 5 minutes. Supports both direct-user (legacy) and Shopify modes.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import UTC, datetime

from core import database

logger = logging.getLogger(__name__)


class _Monitor:
    def __init__(self) -> None:
        self._running = False
        self._thread: threading.Thread | None = None
        self._orchestrator_getter = None
        self._push_getter = None
        self._last_alert: dict[str, float] = {}
        self._alert_cooldown = 300

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

    def _get_active_shops(self) -> list[dict]:
        """Get all active shop records from the database."""
        conn = database._get_conn()
        rows = conn.execute(
            "SELECT * FROM shops WHERE is_active = 1"
        ).fetchall()
        return [dict(r) for r in rows]

    def _tick(self) -> None:
        orch_fn = self._orchestrator_getter
        push = self._push_getter() if self._push_getter else None
        if not orch_fn or not push:
            return

        now = time.time()

        shops = self._get_active_shops()

        for shop_record in shops:
            try:
                self._check_shop(orch_fn, push, shop_record, now)
            except Exception as e:
                logger.debug("Monitor check error for shop %s: %s", shop_record.get("shop"), e)

    def _check_shop(self, orch_fn, push, shop_record: dict, now: float) -> None:
        """Run monitoring checks for a single shop/tenant."""
        orch = orch_fn()
        if not orch:
            return

        shop = shop_record.get("shop", "")

        # 1. Pending approvals alert
        pending = len(orch.get_pending_drafts())
        if pending > 0 and self._can_alert(f"pending:{shop}", now):
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
            self._last_alert[f"pending:{shop}"] = now

        # 2. Stale activity check
        activities = orch.get_activity_feed(1)
        if activities:
            last_activity = activities[0].get("timestamp", "")
            if last_activity:
                try:
                    last_dt = datetime.fromisoformat(last_activity)
                    hours_idle = (datetime.now(UTC) - last_dt).total_seconds() / 3600
                    if hours_idle > 4 and self._can_alert(f"idle:{shop}", now):
                        try:
                            push.send(
                                title="\u23F0 No activity in 4+ hours",
                                body="Your agents have been quiet. Check in to review pending items.",
                                url="/admin/dashboard",
                            )
                        except Exception:
                            logger.warning("Push notification failed", exc_info=True)
                        self._last_alert[f"idle:{shop}"] = now
                except Exception as e:
                    logger.debug("Exception in %s: %s", __name__, e)

    def _can_alert(self, key: str, now: float) -> bool:
        last = self._last_alert.get(key, 0)
        return now - last > self._alert_cooldown


monitor = _Monitor()
