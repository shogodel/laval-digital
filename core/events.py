import contextlib
import logging
import threading
import uuid
from datetime import UTC, datetime
from queue import Full, Queue
from typing import Any

logger = logging.getLogger(__name__)

MAX_HISTORY = 2000
MAX_EVENT_AGE_SECONDS = 600


class EventBus:
    """Thread-safe pub/sub event bus for real-time agent events.

    Agents and the orchestrator publish events. The SSE endpoint subscribes
    and pushes them to the browser. Events older than MAX_EVENT_AGE_SECONDS
    are pruned from history to bound memory.
    """

    def __init__(self) -> None:
        self._subscribers: list[Queue] = []
        self._history: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def publish(
        self,
        event_type: str,
        agent: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Publish an event to all active subscribers.

        Args:
            event_type: One of ``agent_processing``, ``agent_executed``,
                ``agent_failed``, ``approval_needed``, ``approval_responded``.
            agent: Agent identifier (e.g. ``local_seo``) or ``orchestrator``.
            data: Optional payload dict.
        """
        event: dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "type": event_type,
            "agent": agent,
            "data": data or {},
            "timestamp": datetime.now(UTC).isoformat(),
        }
        with self._lock:
            self._history.append(event)
            self._prune()
            dead: list[Queue] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except Full:
                    logger.debug("Subscriber queue full, dropping event")
                except Exception as e:
                    logger.warning("Removing dead subscriber: %s", e)
                    dead.append(q)
            for q in dead:
                with contextlib.suppress(ValueError):
                    self._subscribers.remove(q)

    MAX_SUBSCRIBERS = 1000

    def subscribe(self) -> Queue:
        """Return a Queue that receives all future events."""
        q: Queue = Queue(maxsize=1000)
        with self._lock:
            if len(self._subscribers) >= self.MAX_SUBSCRIBERS:
                logger.warning("Subscriber cap reached (%s), refusing new subscriber", self.MAX_SUBSCRIBERS)
                return q  # still return a functional queue, just not subscribed
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: Queue) -> None:
        """Remove a subscriber queue."""
        with self._lock, contextlib.suppress(ValueError):
            self._subscribers.remove(q)

    def get_history(
        self,
        limit: int = 200,
        event_type: str | None = None,
        agent: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent events, optionally filtered."""
        with self._lock:
            events = list(self._history)
        if event_type:
            events = [e for e in events if e["type"] == event_type]
        if agent:
            events = [e for e in events if e["agent"] == agent]
        return events[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate stats from recent history."""
        with self._lock:
            events = list(self._history[-500:])
        by_agent: dict[str, dict[str, int]] = {}
        total_executed = 0
        total_failed = 0
        for e in events:
            agent = e["agent"]
            if agent not in by_agent:
                by_agent[agent] = {"processing": 0, "executed": 0, "failed": 0, "approval_needed": 0}
            t = e["type"]
            if t in by_agent[agent]:
                by_agent[agent][t] += 1
            if t == "agent_executed":
                total_executed += 1
            elif t == "agent_failed":
                total_failed += 1
        return {
            "by_agent": by_agent,
            "total_executed": total_executed,
            "total_failed": total_failed,
            "total_events": len(events),
        }

    def _prune(self) -> None:
        now = datetime.now(UTC)
        self._history = [
            e for e in self._history
            if (now - _parse_ts(e["timestamp"])).total_seconds() < MAX_EVENT_AGE_SECONDS
        ][-MAX_HISTORY:]


def _parse_ts(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception as e:
        logger.debug("Timestamp parse failed for '%s': %s", ts[:50], e)
        return datetime.now(UTC)


# Module-level singleton accessor
_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = EventBus()
    return _bus
