"""Tests for core/events.py — EventBus pub/sub."""
import threading
import time

import pytest

from core.events import EventBus


class TestEventBus:
    def test_publish_and_subscribe(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.publish("test_event", "test_agent", {"key": "value"})
        event = q.get(timeout=1)
        assert event["type"] == "test_event"
        assert event["agent"] == "test_agent"
        assert event["data"]["key"] == "value"

    def test_multiple_subscribers(self):
        bus = EventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.publish("multi", "agent", {"n": 1})
        e1 = q1.get(timeout=1)
        e2 = q2.get(timeout=1)
        assert e1["id"] == e2["id"]

    def test_unsubscribe(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.publish("missed", "agent", {})
        with pytest.raises(Exception):
            q.get(timeout=0.5)

    def test_event_has_id_and_timestamp(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.publish("info", "agent", {})
        event = q.get(timeout=1)
        assert "id" in event
        assert len(event["id"]) == 12
        assert "timestamp" in event

    def test_get_history(self):
        bus = EventBus()
        bus.publish("e1", "a1")
        bus.publish("e2", "a2", {"x": 1})
        history = bus.get_history()
        assert len(history) == 2
        assert history[0]["type"] == "e1"
        assert history[1]["type"] == "e2"

    def test_get_history_filtered_by_type(self):
        bus = EventBus()
        bus.publish("type_a", "a1")
        bus.publish("type_b", "a2")
        bus.publish("type_a", "a3")
        filtered = bus.get_history(event_type="type_a")
        assert len(filtered) == 2
        assert all(e["type"] == "type_a" for e in filtered)

    def test_get_history_limit(self):
        bus = EventBus()
        for i in range(10):
            bus.publish(f"e{i}", "agent")
        limited = bus.get_history(limit=3)
        assert len(limited) == 3

    def test_get_history_filtered_by_agent(self):
        bus = EventBus()
        bus.publish("e1", "a1")
        bus.publish("e2", "a2")
        bus.publish("e3", "a1")
        filtered = bus.get_history(agent="a1")
        assert len(filtered) == 2
        assert all(e["agent"] == "a1" for e in filtered)

    def test_history_pruning(self, monkeypatch):
        bus = EventBus()
        # Override max history to test pruning
        monkeypatch.setattr("core.events.MAX_HISTORY", 3)
        monkeypatch.setattr("core.events.MAX_EVENT_AGE_SECONDS", 9999)
        for i in range(5):
            bus.publish(f"e{i}", "agent")
        assert len(bus.get_history()) == 3

    def test_thread_safety(self):
        bus = EventBus()
        results = []

        def publisher():
            for i in range(20):
                bus.publish("thr", "agent", {"i": i})
                time.sleep(0.001)

        def subscriber():
            q = bus.subscribe()
            received = []
            for _ in range(20):
                try:
                    received.append(q.get(timeout=2))
                except Exception:
                    break
            results.append(len(received))

        threads = [
            threading.Thread(target=publisher),
            threading.Thread(target=subscriber),
            threading.Thread(target=subscriber),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # At least some events reached each subscriber
        assert all(r > 0 for r in results)