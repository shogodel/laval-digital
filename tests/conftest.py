"""Shared test fixtures."""
import os
import sys
import tempfile
import threading

import pytest

# Point all database operations to a temporary file for test isolation
_db_fd, _db_path = tempfile.mkstemp(suffix=".test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import database after setting DATABASE_URL so it picks up the temp path
from core import database as _db  # noqa: E402


@pytest.fixture
def _clean_db():
    """Ensure a clean database before each test."""
    _db.init_db()
    yield
    conn = _db._get_conn()
    conn.execute("PRAGMA foreign_keys = OFF")
    for tbl in ("login_attempts", "mcp_credentials", "webhook_events",
                "execution_log", "threads", "pending_actions",
                "agent_feedback", "agent_preferences", "agent_findings",
                "agent_schedules", "agent_configs", "leads",
                "llm_usage_log", "user_llm_quotas", "shops", "users"):
        conn.execute(f"DELETE FROM {tbl}")
    conn.commit()
    _db.reset_conn()


@pytest.fixture
def db_conn(_clean_db):
    """Return a clean database connection."""
    return _db._get_conn()


def pytest_unconfigure():
    """Clean up the temporary database file."""
    os.close(_db_fd)
    try:
        os.unlink(_db_path)
    except OSError:
        pass