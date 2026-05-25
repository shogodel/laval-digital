import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from core import database

logger = logging.getLogger(__name__)

MODEL_PRICING = {
    "deepseek-chat": {"input": 0.27, "output": 0.27},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "claude-3.5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    "gemini-1.5-pro": {"input": 3.50, "output": 10.50},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
}

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_INPUT_PRICE = 1.00
DEFAULT_OUTPUT_PRICE = 2.00

DEFAULT_QUOTAS = {
    "requests_per_hour": 60,
    "requests_per_day": 500,
    "tokens_per_day": 1000000,
    "cost_per_day": 5.00,
    "cost_per_month": 100.00,
}

_estimator_cache: dict = {}
_estimator_lock = threading.Lock()


def _get_token_estimator(model: str):
    key = "default"
    if model.startswith("deepseek"):
        key = "deepseek"
    elif model.startswith("gpt"):
        key = "gpt"
    with _estimator_lock:
        if key in _estimator_cache:
            return _estimator_cache[key]
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            _estimator_cache[key] = enc
            logger.debug("Using tiktoken cl100k_base for model %s", model)
            return enc
        except Exception:
            _estimator_cache[key] = None
            return None


def count_tokens(text: str, model: str = DEFAULT_MODEL) -> int:
    enc = _get_token_estimator(model)
    if enc:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    return max(1, len(text) // 4)


def _get_model_pricing(model: str) -> tuple[float, float]:
    prices = MODEL_PRICING.get(model)
    if prices:
        return prices["input"], prices["output"]
    for prefix, prices in MODEL_PRICING.items():
        if model.startswith(prefix):
            return prices["input"], prices["output"]
    return DEFAULT_INPUT_PRICE, DEFAULT_OUTPUT_PRICE


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    input_price, output_price = _get_model_pricing(model)
    return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000


def get_or_create_quota(user_id: int) -> dict:
    conn = database._get_conn()
    row = conn.execute(
        "SELECT * FROM user_llm_quotas WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row:
        return dict(row)
    conn.execute(
        """INSERT OR IGNORE INTO user_llm_quotas
           (user_id, requests_per_hour, requests_per_day, tokens_per_day, cost_per_day, cost_per_month)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, DEFAULT_QUOTAS["requests_per_hour"], DEFAULT_QUOTAS["requests_per_day"],
         DEFAULT_QUOTAS["tokens_per_day"], DEFAULT_QUOTAS["cost_per_day"], DEFAULT_QUOTAS["cost_per_month"]),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM user_llm_quotas WHERE user_id = ?", (user_id,)
    ).fetchone()
    return dict(row) if row else dict(DEFAULT_QUOTAS, blocked=0)


class RateLimitExceeded(Exception):
    def __init__(self, message: str, limit_type: str = "rate"):
        self.limit_type = limit_type
        super().__init__(message)


def check_rate_limits(user_id: int) -> None:
    if user_id <= 0:
        return
    conn = database._get_conn()
    quota = get_or_create_quota(user_id)
    if quota.get("blocked"):
        raise RateLimitExceeded(
            "Your LLM access has been blocked. Contact your administrator.",
            limit_type="blocked",
        )
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    hour_ago = (now - timedelta(hours=1)).isoformat()
    day_ago = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    month_start = now.strftime("%Y-%m") + "-01T00:00:00"

    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM llm_usage_log
           WHERE user_id = ? AND timestamp > ?""",
        (user_id, hour_ago),
    ).fetchone()
    if row and row["cnt"] >= quota["requests_per_hour"]:
        raise RateLimitExceeded(
            f"Rate limit exceeded: {quota['requests_per_hour']} requests per hour.",
            limit_type="hourly_rate",
        )

    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM llm_usage_log
           WHERE user_id = ? AND timestamp > ?""",
        (user_id, day_ago),
    ).fetchone()
    if row and row["cnt"] >= quota["requests_per_day"]:
        raise RateLimitExceeded(
            f"Rate limit exceeded: {quota['requests_per_day']} requests per day.",
            limit_type="daily_rate",
        )

    row = conn.execute(
        """SELECT COALESCE(SUM(total_tokens), 0) as total FROM llm_usage_log
           WHERE user_id = ? AND timestamp > ?""",
        (user_id, day_ago),
    ).fetchone()
    if row and row["total"] >= quota["tokens_per_day"]:
        raise RateLimitExceeded(
            f"Token limit exceeded: {quota['tokens_per_day']} tokens per day.",
            limit_type="daily_tokens",
        )

    row = conn.execute(
        """SELECT COALESCE(SUM(cost), 0) as total FROM llm_usage_log
           WHERE user_id = ? AND timestamp > ?""",
        (user_id, day_ago),
    ).fetchone()
    if row and row["total"] >= quota["cost_per_day"]:
        raise RateLimitExceeded(
            f"Cost limit exceeded: ${quota['cost_per_day']:.2f} per day.",
            limit_type="daily_cost",
        )

    row = conn.execute(
        """SELECT COALESCE(SUM(cost), 0) as total FROM llm_usage_log
           WHERE user_id = ? AND timestamp > ?""",
        (user_id, month_start),
    ).fetchone()
    if row and row["total"] >= quota["cost_per_month"]:
        raise RateLimitExceeded(
            f"Cost limit exceeded: ${quota['cost_per_month']:.2f} per month.",
            limit_type="monthly_cost",
        )


def log_usage(
    user_id: int,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    endpoint: str = "unknown",
    agent_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> None:
    if user_id <= 0:
        return
    try:
        total_tokens = prompt_tokens + completion_tokens
        cost = calculate_cost(model, prompt_tokens, completion_tokens)
        conn = database._get_conn()
        conn.execute(
            """INSERT INTO llm_usage_log
               (user_id, timestamp, model, prompt_tokens, completion_tokens, total_tokens, cost, endpoint, agent_id, thread_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, datetime.now(timezone.utc).isoformat(), model,
             prompt_tokens, completion_tokens, total_tokens, cost,
             endpoint, agent_id, thread_id),
        )
        conn.commit()
        logger.debug("Logged LLM usage: user=%d model=%s tokens=%d cost=%.4f", user_id, model, total_tokens, cost)
    except Exception as e:
        logger.warning("Failed to log LLM usage: %s", e)
