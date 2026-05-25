"""Unit tests for core/rate_limiter.py."""
import os
import tempfile
import pytest

_tmp_db = tempfile.mktemp(suffix=".db")
os.environ["FRANKIE_DB_PATH"] = _tmp_db

from core.rate_limiter import (
    count_tokens,
    calculate_cost,
    get_or_create_quota,
    log_usage,
    check_rate_limits,
    RateLimitExceeded,
    MODEL_PRICING,
)
from core.database import init_db, create_user, _get_conn, reset_conn


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    reset_conn()
    init_db()
    create_user("test@test.com", "hash", "user", "Test User")
    yield
    os.unlink(_tmp_db)
    os.environ.pop("FRANKIE_DB_PATH", None)


class TestCountTokens:
    def test_short_text(self):
        n = count_tokens("hello world")
        assert n > 0
        assert isinstance(n, int)

    def test_empty_text(self):
        assert count_tokens("") == 0

    def test_longer_text(self):
        short = count_tokens("short text")
        long = count_tokens("this is a much longer piece of text content")
        assert long >= short

    def test_with_model(self):
        n = count_tokens("hello world", model="gpt-4o")
        assert n > 0


class TestCalculateCost:
    def test_deepseek_chat(self):
        cost = calculate_cost("deepseek-chat", 1000, 500)
        expected = (1000 * 0.27 + 500 * 0.27) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_gpt4o(self):
        cost = calculate_cost("gpt-4o", 1000, 500)
        expected = (1000 * 2.50 + 500 * 10.00) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_unknown_model(self):
        cost = calculate_cost("unknown-model", 1000, 500)
        expected = (1000 * 1.00 + 500 * 2.00) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_zero_tokens(self):
        cost = calculate_cost("deepseek-chat", 0, 0)
        assert cost == 0.0

    def test_prefix_matching(self):
        cost = calculate_cost("deepseek-reasoner-v2", 1000, 500)
        expected = (1000 * 0.55 + 500 * 2.19) / 1_000_000
        assert cost == pytest.approx(expected)


class TestGetOrCreateQuota:
    def test_creates_quota_for_existing_user(self):
        quota = get_or_create_quota(1)
        assert quota["requests_per_hour"] == 60
        assert quota["requests_per_day"] == 500
        assert quota["tokens_per_day"] == 1_000_000
        assert quota["cost_per_day"] == 5.0
        assert quota["cost_per_month"] == 100.0
        assert quota["blocked"] == 0

    def test_returns_existing_quota(self):
        quota1 = get_or_create_quota(1)
        quota2 = get_or_create_quota(1)
        assert quota1["user_id"] == quota2["user_id"]


class TestCheckRateLimits:
    def test_skips_for_anonymous(self):
        check_rate_limits(0)

    def test_negative_user_id_skipped(self):
        check_rate_limits(-1)

    def test_new_user_passes_limits(self):
        check_rate_limits(1)

    def test_blocks_after_exceeding(self):
        conn = _get_conn()
        conn.execute(
            "UPDATE user_llm_quotas SET requests_per_hour = 0 WHERE user_id = 1"
        )
        conn.commit()
        with pytest.raises(RateLimitExceeded, match="Rate limit exceeded"):
            check_rate_limits(1)
        conn.execute(
            "UPDATE user_llm_quotas SET requests_per_hour = 60 WHERE user_id = 1"
        )
        conn.commit()


class TestLogUsage:
    def test_skips_for_anonymous(self):
        log_usage(0, "deepseek-chat", 100, 50)

    def test_logs_for_authenticated(self):
        log_usage(1, "deepseek-chat", 100, 50, endpoint="test", agent_id="test_agent")
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM llm_usage_log WHERE user_id = 1 AND endpoint = 'test'"
        ).fetchone()
        assert row is not None
        assert row["model"] == "deepseek-chat"
        assert row["total_tokens"] == 150
        assert row["cost"] > 0

    def test_logs_multiple_calls(self):
        log_usage(1, "gpt-4o", 500, 200, endpoint="test")
        conn = _get_conn()
        rows = conn.execute(
            "SELECT COUNT(*) as cnt FROM llm_usage_log WHERE user_id = 1"
        ).fetchall()
        assert rows[0]["cnt"] >= 2


class TestModelPricing:
    def test_all_models_have_pricing(self):
        assert "deepseek-chat" in MODEL_PRICING
        assert "gpt-4o" in MODEL_PRICING
        assert "gpt-4o-mini" in MODEL_PRICING
        assert "claude-3.5-sonnet" in MODEL_PRICING
        assert "gemini-1.5-pro" in MODEL_PRICING

    def test_pricing_positive(self):
        for model, prices in MODEL_PRICING.items():
            assert prices["input"] > 0
            assert prices["output"] > 0
