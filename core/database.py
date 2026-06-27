"""Single-database backend for the Shopify AI Marketing Specialist.

All user-scoped data has a user_id column.
"""

import contextlib
import logging
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

def _db_path() -> Path:
    return Path(os.environ.get("SHOPIFY_DB_PATH", str(Path(__file__).parent.parent / "data" / "shopify.db")))
_local = threading.local()

DEFAULT_AGENTS = [
    "local_seo", "social_media", "lead_conversion", "paid_ads",
    "growth_hacker", "reputation", "email_marketing", "tiktok",
    "outreach", "backlinks", "executioner",
    "content_strategy", "technical_seo", "reporting",
    "cro", "video", "sms_marketing",
]


def _get_conn() -> sqlite3.Connection:
    """Return the thread-local database connection, creating it if needed.

    Fork-safe: detects ``os.fork()`` (e.g. gunicorn worker spawn) and
    discards connections inherited from the parent process.
    """
    current_tid = threading.get_ident()
    current_pid = os.getpid()
    stale = (
        not hasattr(_local, "conn")
        or _local.conn is None
        or getattr(_local, "tid", None) != current_tid
        or getattr(_local, "pid", None) != current_pid
    )
    if stale:
        if hasattr(_local, "conn") and _local.conn is not None and getattr(_local, "pid", None) != current_pid:
            try:
                _local.conn.close()
            except Exception as e:
                logger.warning("Failed to close stale connection (pid %s): %s", current_pid, e)
        db_path = _db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(db_path), timeout=30)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA foreign_keys = ON")
        _local.conn.execute("PRAGMA journal_mode = WAL")
        _local.conn.execute("PRAGMA busy_timeout = 30000")
        _local.tid = current_tid
        _local.pid = current_pid
    return _local.conn


def reset_conn() -> None:
    """Reset the thread-local connection (call on error to force reconnect)."""
    if hasattr(_local, "conn"):
        try:
            _local.conn.close()
        except Exception as e:
            logger.debug("Exception in %s: %s", __name__, e)
        _local.conn = None


def init_db() -> None:
    """Create all tables and apply migrations. Called once at startup."""
    conn = _get_conn()

    # ---- platform tables ----
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'user', 'shop')),
            display_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login TEXT
        );

        CREATE TABLE IF NOT EXISTS agent_schedules (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            agent_id TEXT NOT NULL,
            task_template TEXT NOT NULL,
            cron_expr TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            language TEXT DEFAULT 'en',
            created_at TEXT NOT NULL,
            last_run TEXT
        );

        CREATE TABLE IF NOT EXISTS agent_feedback (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            agent_id TEXT,
            feedback_type TEXT,
            content TEXT,
            approved INTEGER,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS agent_preferences (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            agent_id TEXT,
            pref_key TEXT,
            pref_value TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS agent_findings (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            source_agent TEXT,
            finding_type TEXT,
            summary TEXT,
            detail TEXT,
            created_at TEXT,
            expires_at TEXT
        );

        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
    """)

    # ---- per-user data tables ----
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            agent_id TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            model TEXT DEFAULT 'deepseek-chat',
            api_key TEXT,
            api_base TEXT,
            system_prompt_file TEXT,
            task_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            last_invoked TEXT,
            last_draft_preview TEXT,
            status TEXT DEFAULT 'idle',
            autonomy TEXT DEFAULT 'manual',
            confidence_threshold REAL DEFAULT 0.7,
            UNIQUE(user_id, agent_id)
        );

        CREATE TABLE IF NOT EXISTS threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            thread_id TEXT NOT NULL,
            routed_agent TEXT,
            agent_task TEXT,
            agent_draft TEXT,
            approved INTEGER DEFAULT 0,
            feedback TEXT,
            final_result TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            name TEXT,
            phone TEXT,
            service TEXT,
            urgency TEXT,
            created_at TEXT,
            status TEXT DEFAULT 'new'
        );

        CREATE TABLE IF NOT EXISTS execution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            execution_id TEXT,
            agent_name TEXT,
            tool_name TEXT,
            draft_preview TEXT,
            success INTEGER DEFAULT 0,
            result TEXT,
            error TEXT,
            timestamp TEXT
        );

        CREATE TABLE IF NOT EXISTS pending_actions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            agent_name TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            provider TEXT DEFAULT 'web',
            content TEXT NOT NULL,
            subject TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS mcp_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            server_name TEXT NOT NULL,
            platform TEXT,
            credential_key TEXT NOT NULL,
            credential_value TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, server_name, platform, credential_key)
        );
    """)

    conn.commit()
    _run_migrations(conn)
    _seed_default_agents(conn)


def _get_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
    return row["v"] if row and row["v"] else 0


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
        (version, datetime.now(UTC).isoformat()),
    )


def _run_migrations(conn: sqlite3.Connection) -> None:
    current = _get_schema_version(conn)

    for version, sqls in MIGRATIONS:
        if version <= current:
            continue
        for sql in sqls:
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(sql)  # column/table/index already exists (legacy catch-up)
        _set_schema_version(conn, version)
        conn.commit()
        logger.info("Migration v%d applied", version)


MIGRATIONS: list[tuple[int, list[str]]] = [
    (1, [
        "ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'",
        "ALTER TABLE users ADD COLUMN trial_ends_at TEXT",
        "ALTER TABLE users ADD COLUMN stripe_customer_id TEXT",
        "UPDATE users SET status = 'active' WHERE status IS NULL",
    ]),
    (2, [
        "ALTER TABLE users ADD COLUMN tenant_id INTEGER REFERENCES users(id)",
    ]),
    (3, [
        "ALTER TABLE leads RENAME TO leads_old",
        "CREATE TABLE IF NOT EXISTS leads (id TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id), name TEXT, phone TEXT, service TEXT, urgency TEXT, created_at TEXT, status TEXT DEFAULT 'new')",
        "INSERT OR IGNORE INTO leads (id, user_id, name, phone, service, urgency, created_at, status) SELECT id, user_id, name, phone, service, urgency, created_at, status FROM leads_old",
        "DROP TABLE IF EXISTS leads_old",
    ]),
    (4, [
        "CREATE TABLE IF NOT EXISTS login_attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT NOT NULL, success INTEGER NOT NULL, attempted_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_time ON login_attempts(ip, attempted_at)",
    ]),
    (5, [
        "ALTER TABLE client_details ADD COLUMN managed_service INTEGER DEFAULT 0",
        "ALTER TABLE client_details ADD COLUMN managed_since TEXT",
        "ALTER TABLE client_details ADD COLUMN site_url TEXT",
    ]),
    (6, [
        "DROP TABLE IF EXISTS deployments",
        "DROP TABLE IF EXISTS payments",
    ]),
    (7, [
        "CREATE TABLE IF NOT EXISTS llm_usage_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id), timestamp TEXT NOT NULL, model TEXT NOT NULL, prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0, total_tokens INTEGER DEFAULT 0, cost REAL DEFAULT 0.0, endpoint TEXT NOT NULL DEFAULT 'unknown', agent_id TEXT, thread_id TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_llm_usage_user_time ON llm_usage_log(user_id, timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_llm_usage_user_month ON llm_usage_log(user_id, substr(timestamp,1,7))",
    ]),
    (8, [
        "CREATE TABLE IF NOT EXISTS user_llm_quotas (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id), requests_per_hour INTEGER DEFAULT 60, requests_per_day INTEGER DEFAULT 500, tokens_per_day INTEGER DEFAULT 1000000, cost_per_day REAL DEFAULT 5.00, cost_per_month REAL DEFAULT 100.00, blocked INTEGER DEFAULT 0)",
    ]),
    (9, [
        "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
        "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)",
        "CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_configs_user ON agent_configs(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_threads_user ON threads(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_leads_user ON leads(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_execution_log_user ON execution_log(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_execution_log_ts ON execution_log(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_pending_actions_user ON pending_actions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_pending_actions_status ON pending_actions(status)",
        "CREATE INDEX IF NOT EXISTS idx_mcp_credentials_user ON mcp_credentials(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_schedules_user ON agent_schedules(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_feedback_user ON agent_feedback(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_findings_user ON agent_findings(user_id)",
    ]),
    (10, [
        "CREATE TABLE IF NOT EXISTS shops ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "shop TEXT NOT NULL UNIQUE, "
        "access_token TEXT NOT NULL, "
        "user_id INTEGER REFERENCES users(id), "
        "myshopify_domain TEXT, "
        "name TEXT, "
        "email TEXT, "
        "domain TEXT, "
        "province TEXT, "
        "country TEXT, "
        "currency TEXT, "
        "plan_name TEXT, "
        "installed_at TEXT NOT NULL, "
        "uninstalled_at TEXT, "
        "scopes TEXT NOT NULL, "
        "is_active INTEGER DEFAULT 1, "
        "trial_expires_at TEXT, "
        "billing_plan TEXT DEFAULT 'free', "
        "last_webhook_at TEXT"
        ")",
        "CREATE TABLE IF NOT EXISTS webhook_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "shop TEXT NOT NULL, "
        "topic TEXT NOT NULL, "
        "body TEXT NOT NULL, "
        "received_at TEXT NOT NULL, "
        "processed INTEGER DEFAULT 0"
        ")",
        "CREATE INDEX IF NOT EXISTS idx_shops_active ON shops(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_shops_domain ON shops(shop)",
        "CREATE INDEX IF NOT EXISTS idx_webhook_events_shop ON webhook_events(shop)",
        "CREATE INDEX IF NOT EXISTS idx_webhook_events_topic ON webhook_events(topic)",
    ]),
    (11, [
        "ALTER TABLE agent_schedules ADD COLUMN shop TEXT",
        "ALTER TABLE agent_schedules ADD COLUMN next_run TEXT",
    ]),
    (12, [
        "ALTER TABLE shops ADD COLUMN agent_name TEXT DEFAULT NULL",
    ]),
    (13, [
        "ALTER TABLE shops ADD COLUMN is_platform_admin INTEGER DEFAULT 0",
    ]),
    (14, [
        "DROP TABLE IF EXISTS client_details",
        "DROP TABLE IF EXISTS payments",
        "DROP TABLE IF EXISTS deployments",
    ]),
]


def _seed_default_agents(conn: sqlite3.Connection) -> None:
    """Insert default agent_config rows for every agent."""
    rows = conn.execute("SELECT id FROM users WHERE role IN ('user', 'admin')").fetchall()
    now = datetime.now(UTC).isoformat()
    for row in rows:
        uid = row["id"]
        for agent_id in DEFAULT_AGENTS:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO agent_configs
                       (user_id, agent_id, enabled, model, status, last_invoked)
                       VALUES (?, ?, 1, 'deepseek-chat', 'idle', ?)""",
                    (uid, agent_id, now),
                )
            except Exception as e:
                logger.warning("Failed to seed agent %s for user %d: %s", agent_id, uid, e)
    conn.commit()


def list_users(role: str | None = None) -> list[dict]:
    """List all users, optionally filtered by role."""
    conn = _get_conn()
    if role:
        rows = conn.execute("SELECT * FROM users WHERE role = ? ORDER BY id", (role,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def get_user_by_email(email: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(uid: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return dict(row) if row else None


def create_user(email: str, password_hash: str, role: str,
                display_name: str = "", tenant_id: int | None = None) -> int:
    conn = _get_conn()
    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        """INSERT INTO users (email, password_hash, role, display_name, created_at, tenant_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (email, password_hash, role, display_name or email.split("@")[0], now, tenant_id),
    )
    conn.commit()
    uid = cur.lastrowid
    _seed_default_agents(conn)
    if uid is None:
        raise RuntimeError("Failed to create user — INSERT did not return a rowid")
    return uid


_ALLOWED_USER_COLUMNS = frozenset({
    "email", "display_name", "role", "password_hash", "status",
    "trial_ends_at", "stripe_customer_id", "last_login", "tenant_id",
})
_USER_UPDATE_SQL = {
    col: f"UPDATE users SET {col} = ? WHERE id = ?"  # noqa: S608 — col is validated against hardcoded frozenset
    for col in _ALLOWED_USER_COLUMNS
}


def update_user(uid: int, **kwargs) -> None:
    conn = _get_conn()
    for key, val in kwargs.items():
        sql = _USER_UPDATE_SQL.get(key)
        if sql is None:
            raise ValueError(f"Unknown column: {key}")
        conn.execute(sql, (val, uid))
    conn.commit()


def delete_user(uid: int) -> None:
    conn = _get_conn()
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM agent_configs WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM threads WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM leads WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM execution_log WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM pending_actions WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM mcp_credentials WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM agent_feedback WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM agent_preferences WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM agent_findings WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM agent_schedules WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM llm_usage_log WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM user_llm_quotas WHERE user_id = ?", (uid,))
        conn.execute("UPDATE users SET tenant_id = NULL WHERE tenant_id = ?", (uid,))
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
