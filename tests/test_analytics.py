"""Tests for core/analytics.py — AnalyticsEngine cache behavior."""
import time
from datetime import UTC, datetime, timedelta

import pytest

from core.analytics import AnalyticsEngine


class TestAnalyticsCache:
    def test_cache_hits(self, monkeypatch):
        engine = AnalyticsEngine(user_id=1)
        call_count = 0

        def query():
            nonlocal call_count
            call_count += 1
            return {"result": 42}

        first = engine._cached("key1", query)
        assert first == {"result": 42}
        assert call_count == 1

        second = engine._cached("key1", query)
        assert second == {"result": 42}
        assert call_count == 1  # Should use cache

    def test_cache_miss_new_key(self, monkeypatch):
        engine = AnalyticsEngine(user_id=1)
        call_count = 0

        def query():
            nonlocal call_count
            call_count += 1
            return {"value": call_count}

        result = engine._cached("new_key", query)
        assert result == {"value": 1}

    def test_cache_returns_stale_after_ttl(self, monkeypatch):
        engine = AnalyticsEngine(user_id=1)
        engine._cache_ttl = timedelta(milliseconds=50)
        call_count = 0

        def query():
            nonlocal call_count
            call_count += 1
            return {"val": call_count}

        engine._cached("ttl_test", query)
        assert call_count == 1

        engine._cached("ttl_test", query)
        assert call_count == 1  # Still within TTL

        time.sleep(0.1)
        engine._cached("ttl_test", query)
        assert call_count == 2  # Past TTL, should re-query

    def test_invalidate_cache(self, monkeypatch):
        engine = AnalyticsEngine(user_id=1)
        call_count = 0

        def query():
            nonlocal call_count
            call_count += 1
            return {"val": call_count}

        assert engine._cached("inv", query) == {"val": 1}
        engine.invalidate_cache()
        assert engine._cached("inv", query) == {"val": 2}

    def test_cache_prunes_expired_entries(self, monkeypatch):
        engine = AnalyticsEngine(user_id=1)
        engine._cache_ttl = timedelta(milliseconds=50)
        call_count = 0

        def query_a():
            nonlocal call_count
            call_count += 1
            return "a"

        def query_b():
            return "b"

        engine._cached("prune_a", query_a)
        engine._cached("prune_b", query_b)
        assert len(engine._cache) == 2

        time.sleep(0.1)
        # Accessing prune_b should trigger prune and remove expired prune_a
        engine._cached("prune_b", query_b)
        assert "prune_a" not in engine._cache
        assert "prune_b" in engine._cache