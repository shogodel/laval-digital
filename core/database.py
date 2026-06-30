"""Single-database backend for the Shopify AI Marketing Specialist.

Supports both SQLite (default, dev) and PostgreSQL (production, when
``DATABASE_URL`` starts with ``postgresql://``).  All user-scoped data
has a ``user_id`` column.  Uses Alembic for schema migrations.

Environment variables
--------------------
DATABASE_URL    — ``postgresql://user:pass@host/db`` or ``sqlite:///path``
                  (default: ``sqlite:///data/shopify.db``).
SHOPIFY_DB_PATH — Legacy; used only when ``DATABASE_URL`` is not set.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config as AlembicConfig

logger = logging.getLogger(__name__)


# ── Backend detection ──────────────────────────────────────────────

def _resolve_db_url() -> str:
    """Return the effective database URL."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    # Legacy fallback: SHOPIFY_DB_PATH → sqlite URL
    path = os.environ.get(
        "SHOPIFY_DB_PATH",
        str(Path(__file__).resolve().parent.parent / "data" / "shopify.db"),
    )
    return f"sqlite:///{Path(path).as_posix()}"


DATABASE_URL = _resolve_db_url()


def _backend() -> str:
    return "postgresql" if DATABASE_URL.startswith("postgresql://") else "sqlite"


def _is_pg() -> bool:
    return _backend() == "postgresql"


def get_backend() -> str:
    """Return ``'postgresql'`` or ``'sqlite'`` based on ``DATABASE_URL``."""
    return _backend()


# ── Connection pool configuration ──────────────────────────────────

DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "10"))

_pg_pool: Any = None
_pg_pool_pid: int | None = None
_pool_lock = threading.Lock()


def _get_pg_pool():
    """Return the module-level psycopg2 ``ThreadedConnectionPool``.

    Fork-safe: recreates the pool when the current PID differs from
    the PID that created it (handles gunicorn worker spawns).
    """
    global _pg_pool, _pg_pool_pid
    current_pid = os.getpid()

    if _pg_pool is not None and _pg_pool_pid != current_pid:
        with _pool_lock:
            if _pg_pool is not None and _pg_pool_pid != current_pid:
                try:
                    _pg_pool.closeall()
                except Exception:
                    pass
                _pg_pool = None

    if _pg_pool is None:
        with _pool_lock:
            if _pg_pool is None:
                import psycopg2
                import psycopg2.pool
                _pg_pool = psycopg2.pool.ThreadedConnectionPool(
                    DB_POOL_MIN, DB_POOL_MAX, DATABASE_URL,
                )
                _pg_pool_pid = current_pid
                logger.info(
                    "Created PG connection pool (min=%s, max=%s)",
                    DB_POOL_MIN, DB_POOL_MAX,
                )

    return _pg_pool


_local = threading.local()

DEFAULT_AGENTS = [
    "local_seo", "social_media", "lead_conversion", "paid_ads",
    "growth_hacker", "reputation", "email_marketing", "tiktok",
    "outreach", "backlinks", "executioner",
    "content_strategy", "technical_seo", "reporting",
    "cro", "video", "sms_marketing",
]


# ── Connection wrappers ────────────────────────────────────────────


class _SqliteConnection:
    """Innocent wrapper around ``sqlite3.Connection``.

    Exists purely so callers can call ``.execute()`` uniformly without
    knowing whether the backend is SQLite or PostgreSQL.
    """

    def __init__(self, db_path: Path) -> None:
        import sqlite3

        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._raw = sqlite3.connect(str(db_path), timeout=30)
        except sqlite3.OperationalError:
            dir_stat = db_path.parent.stat() if db_path.parent.exists() else None
            logger.error(
                "Cannot open database at %s — dir=%s owner=%s mode=%s — falling back to /tmp",
                db_path, db_path.parent,
                dir_stat.st_uid if dir_stat else "N/A",
                oct(dir_stat.st_mode) if dir_stat else "N/A",
            )
            import tempfile
            db_path = Path(tempfile.gettempdir()) / "shopify.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._raw = sqlite3.connect(str(db_path), timeout=30)
            logger.warning("Using fallback database at %s", db_path)
        self._raw.row_factory = sqlite3.Row
        self._raw.execute("PRAGMA foreign_keys = ON")
        self._raw.execute("PRAGMA journal_mode = WAL")
        self._raw.execute("PRAGMA busy_timeout = 30000")

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _SqliteCursor:
        return _SqliteCursor(self._raw.execute(sql, params or ()))

    def executescript(self, sql: str) -> None:
        self._raw.executescript(sql)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()

    def cursor(self) -> _SqliteCursor:
        return _SqliteCursor(self._raw.cursor())

    @property
    def raw_connection(self):
        return self._raw


class _SqliteCursor:
    """Wraps a ``sqlite3.Cursor`` to expose the same API as ``_PgCursor``."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchall(self) -> list[Any]:
        return self._cur.fetchall()

    @property
    def lastrowid(self) -> int | None:
        return self._cur.lastrowid

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount


class _PgConnection:
    """Wraps a pooled ``psycopg2`` connection to match ``sqlite3.Connection`` API.

    Borrows a connection from :func:`_get_pg_pool` on init and returns it
    on :meth:`close`.  ``?`` placeholders are transparently converted to
    ``%s``.
    """

    def __init__(self) -> None:
        import psycopg2.extras

        self._pool = _get_pg_pool()
        self._raw = self._pool.getconn()
        self._raw.autocommit = False
        self._closed = False
        self._cursor_factory = psycopg2.extras.RealDictCursor

    def _adapt(self, sql: str) -> tuple[str, tuple[Any, ...]]:
        """SQLite ``?`` → psycopg2 ``%s``."""
        i = 0
        parts: list[str] = []
        while True:
            idx = sql.find("?", i)
            if idx == -1:
                parts.append(sql[i:])
                break
            parts.append(sql[i:idx])
            parts.append("%s")
            i = idx + 1
        return "".join(parts)

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _PgCursor:
        adapted, adapted_params = self._adapt(sql), params or ()
        cur = self._raw.cursor(cursor_factory=self._cursor_factory)
        cur.execute(adapted, adapted_params)
        return _PgCursor(cur)

    def executescript(self, sql: str) -> None:
        for stmt in sql.split(";"):
            stripped = stmt.strip()
            if stripped:
                self.execute(stripped)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            try:
                self._pool.putconn(self._raw)
            except Exception as e:
                logger.warning("Failed to return PG connection to pool: %s", e)
                try:
                    self._raw.close()
                except Exception:
                    pass
            self._closed = True

    def cursor(self) -> _PgCursor:
        cur = self._raw.cursor(cursor_factory=self._cursor_factory)
        return _PgCursor(cur)

    @property
    def raw_connection(self):
        return self._raw


class _PgCursor:
    """Wraps a ``psycopg2`` cursor to expose ``lastrowid`` + dict rows."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchall(self) -> list[Any]:
        return self._cur.fetchall()

    @property
    def lastrowid(self) -> int | None:
        """Read last inserted row id via ``RETURNING`` clause.

        The caller *must* append ``RETURNING id`` to INSERT statements.
        If the cursor has a result set, returns the first column of the
        first row; otherwise ``None``.
        """
        try:
            row = self._cur.fetchone()
            if row:
                if isinstance(row, dict):
                    return next(iter(row.values()))
                return int(row[0])
        except Exception as e:
            logger.debug("lastrowid fetch failed: %s", e)
        return None

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount


def _get_conn() -> _SqliteConnection | _PgConnection:
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

        if _is_pg():
            _local.conn = _PgConnection()
        else:
            db_path = _sqlite_path()
            _local.conn = _SqliteConnection(db_path)

        _local.tid = current_tid
        _local.pid = current_pid
    return _local.conn


def _sqlite_path() -> Path:
    """Extract the file path from a ``sqlite:///`` URL."""
    # DATABASE_URL might be like "sqlite:///C:/path/to/db" or "sqlite:///relative/path"
    raw = DATABASE_URL
    if raw.startswith("sqlite:///"):
        raw = raw[len("sqlite:///"):]
    return Path(raw)


def reset_conn() -> None:
    """Reset the thread-local connection (call on error to force reconnect)."""
    if hasattr(_local, "conn"):
        try:
            _local.conn.close()
        except Exception as e:
            logger.debug("Exception in %s: %s", __name__, e)
        _local.conn = None


# ── SQL helpers ────────────────────────────────────────────────────





# ── Schema management ──────────────────────────────────────────────


def init_db() -> None:
    """Create all tables and apply migrations via Alembic. Called once at startup."""
    conn = _get_conn()

    if _is_pg():
        _init_db_pg(conn)
    else:
        _init_db_sqlite(conn)

    # Run Alembic migrations (handles indexes, missing columns, new tables)
    _run_alembic_migrations()

    # Seed default agent configs for any users
    _seed_default_agents(conn)


def _init_db_sqlite(conn: _SqliteConnection) -> None:
    """SQLite-specific base table creation."""
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
            id TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id),
            agent_id TEXT NOT NULL, task_template TEXT NOT NULL,
            cron_expr TEXT NOT NULL, enabled INTEGER DEFAULT 1,
            language TEXT DEFAULT 'en', created_at TEXT NOT NULL, last_run TEXT
        );
        CREATE TABLE IF NOT EXISTS agent_feedback (
            id TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id),
            agent_id TEXT, feedback_type TEXT, content TEXT,
            approved INTEGER, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS agent_preferences (
            id TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id),
            agent_id TEXT, pref_key TEXT, pref_value TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS agent_findings (
            id TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id),
            source_agent TEXT, finding_type TEXT, summary TEXT,
            detail TEXT, created_at TEXT, expires_at TEXT
        );
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agent_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            agent_id TEXT NOT NULL, enabled INTEGER DEFAULT 1,
            model TEXT DEFAULT 'deepseek-chat', api_key TEXT, api_base TEXT,
            system_prompt_file TEXT, task_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0, failure_count INTEGER DEFAULT 0,
            last_invoked TEXT, last_draft_preview TEXT, status TEXT DEFAULT 'idle',
            autonomy TEXT DEFAULT 'manual', confidence_threshold REAL DEFAULT 0.7,
            UNIQUE(user_id, agent_id)
        );
        CREATE TABLE IF NOT EXISTS threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            thread_id TEXT NOT NULL, routed_agent TEXT, agent_task TEXT,
            agent_draft TEXT, approved INTEGER DEFAULT 0, feedback TEXT,
            final_result TEXT, status TEXT DEFAULT 'pending',
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id),
            name TEXT, phone TEXT, service TEXT, urgency TEXT,
            created_at TEXT, status TEXT DEFAULT 'new'
        );
        CREATE TABLE IF NOT EXISTS execution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            execution_id TEXT, agent_name TEXT, tool_name TEXT,
            draft_preview TEXT, success INTEGER DEFAULT 0,
            result TEXT, error TEXT, timestamp TEXT
        );
        CREATE TABLE IF NOT EXISTS pending_actions (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            agent_name TEXT NOT NULL, tool_name TEXT NOT NULL,
            provider TEXT DEFAULT 'web', content TEXT NOT NULL, subject TEXT,
            status TEXT DEFAULT 'pending', created_at TEXT NOT NULL, completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS mcp_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            server_name TEXT NOT NULL, platform TEXT,
            credential_key TEXT NOT NULL, credential_value TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(user_id, server_name, platform, credential_key)
        );
    """)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL, success INTEGER NOT NULL, attempted_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS llm_usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            timestamp TEXT NOT NULL, model TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0, cost REAL DEFAULT 0.0,
            endpoint TEXT NOT NULL DEFAULT 'unknown', agent_id TEXT, thread_id TEXT
        );
        CREATE TABLE IF NOT EXISTS user_llm_quotas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
            requests_per_hour INTEGER DEFAULT 60,
            requests_per_day INTEGER DEFAULT 500,
            tokens_per_day INTEGER DEFAULT 1000000,
            cost_per_day REAL DEFAULT 5.00,
            cost_per_month REAL DEFAULT 100.00,
            blocked INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop TEXT NOT NULL UNIQUE, access_token TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id),
            myshopify_domain TEXT, name TEXT, email TEXT, domain TEXT,
            province TEXT, country TEXT, currency TEXT, plan_name TEXT,
            installed_at TEXT NOT NULL, uninstalled_at TEXT,
            scopes TEXT NOT NULL, is_active INTEGER DEFAULT 1,
            trial_expires_at TEXT, billing_plan TEXT DEFAULT 'free', last_webhook_at TEXT
        );
        CREATE TABLE IF NOT EXISTS webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop TEXT NOT NULL, topic TEXT NOT NULL,
            body TEXT NOT NULL, received_at TEXT NOT NULL, processed INTEGER DEFAULT 0
        );
    """)
    conn.commit()


def _init_db_pg(conn: _PgConnection) -> None:
    """PostgreSQL-specific base table creation."""
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'user', 'shop')),
            display_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login TEXT,
            status TEXT DEFAULT 'active',
            trial_ends_at TEXT,
            stripe_customer_id TEXT,
            tenant_id INTEGER REFERENCES users(id)
        )""",
        """
        CREATE TABLE IF NOT EXISTS agent_schedules (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            agent_id TEXT NOT NULL,
            task_template TEXT NOT NULL,
            cron_expr TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            language TEXT DEFAULT 'en',
            created_at TEXT NOT NULL,
            last_run TEXT,
            shop TEXT,
            next_run TEXT
        )""",
        """
        CREATE TABLE IF NOT EXISTS agent_feedback (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            agent_id TEXT,
            feedback_type TEXT,
            content TEXT,
            approved INTEGER,
            created_at TEXT
        )""",
        """
        CREATE TABLE IF NOT EXISTS agent_preferences (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            agent_id TEXT,
            pref_key TEXT,
            pref_value TEXT,
            updated_at TEXT
        )""",
        """
        CREATE TABLE IF NOT EXISTS agent_findings (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            source_agent TEXT,
            finding_type TEXT,
            summary TEXT,
            detail TEXT,
            created_at TEXT,
            expires_at TEXT
        )""",
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )""",
        """
        CREATE TABLE IF NOT EXISTS agent_configs (
            id SERIAL PRIMARY KEY,
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
        )""",
        """
        CREATE TABLE IF NOT EXISTS threads (
            id SERIAL PRIMARY KEY,
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
        )""",
        """
        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            name TEXT,
            phone TEXT,
            service TEXT,
            urgency TEXT,
            created_at TEXT,
            status TEXT DEFAULT 'new'
        )""",
        """
        CREATE TABLE IF NOT EXISTS execution_log (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            execution_id TEXT,
            agent_name TEXT,
            tool_name TEXT,
            draft_preview TEXT,
            success INTEGER DEFAULT 0,
            result TEXT,
            error TEXT,
            timestamp TEXT
        )""",
        """
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
        )""",
        """
        CREATE TABLE IF NOT EXISTS mcp_credentials (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            server_name TEXT NOT NULL,
            platform TEXT,
            credential_key TEXT NOT NULL,
            credential_value TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, server_name, platform, credential_key)
        )""",
        """
        CREATE TABLE IF NOT EXISTS login_attempts (
            id SERIAL PRIMARY KEY,
            ip TEXT NOT NULL,
            success INTEGER NOT NULL,
            attempted_at TEXT NOT NULL
        )""",
        """
        CREATE TABLE IF NOT EXISTS llm_usage_log (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            timestamp TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cost REAL DEFAULT 0.0,
            endpoint TEXT NOT NULL DEFAULT 'unknown',
            agent_id TEXT,
            thread_id TEXT
        )""",
        """
        CREATE TABLE IF NOT EXISTS user_llm_quotas (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
            requests_per_hour INTEGER DEFAULT 60,
            requests_per_day INTEGER DEFAULT 500,
            tokens_per_day INTEGER DEFAULT 1000000,
            cost_per_day REAL DEFAULT 5.00,
            cost_per_month REAL DEFAULT 100.00,
            blocked INTEGER DEFAULT 0
        )""",
        """
        CREATE TABLE IF NOT EXISTS shops (
            id SERIAL PRIMARY KEY,
            shop TEXT NOT NULL UNIQUE,
            access_token TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id),
            myshopify_domain TEXT,
            name TEXT,
            email TEXT,
            domain TEXT,
            province TEXT,
            country TEXT,
            currency TEXT,
            plan_name TEXT,
            installed_at TEXT NOT NULL,
            uninstalled_at TEXT,
            scopes TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            trial_expires_at TEXT,
            billing_plan TEXT DEFAULT 'free',
            last_webhook_at TEXT,
            agent_name TEXT DEFAULT NULL,
            is_platform_admin INTEGER DEFAULT 0
        )""",
        """
        CREATE TABLE IF NOT EXISTS webhook_events (
            id SERIAL PRIMARY KEY,
            shop TEXT NOT NULL,
            topic TEXT NOT NULL,
            body TEXT NOT NULL,
            received_at TEXT NOT NULL,
            processed INTEGER DEFAULT 0
        )""",
    ]
    for ddl in ddl_statements:
        conn.execute(ddl)

    # Create indexes that aren't deferred to Alembic
    indexes = [
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
        "CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_time ON login_attempts(ip, attempted_at)",
        "CREATE INDEX IF NOT EXISTS idx_llm_usage_user_time ON llm_usage_log(user_id, timestamp)",
        ("CREATE INDEX IF NOT EXISTS idx_llm_usage_user_month "
         "ON llm_usage_log(user_id, LEFT(timestamp, 7))"),
        "CREATE INDEX IF NOT EXISTS idx_shops_active ON shops(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_shops_domain ON shops(shop)",
        "CREATE INDEX IF NOT EXISTS idx_webhook_events_shop ON webhook_events(shop)",
        "CREATE INDEX IF NOT EXISTS idx_webhook_events_topic ON webhook_events(topic)",
    ]
    for idx in indexes:
        conn.execute(idx)

    conn.commit()


def _run_alembic_migrations() -> None:
    """Run Alembic migrations (handles transition from old ad-hoc system)."""
    alembic_cfg = AlembicConfig(
        str(Path(__file__).resolve().parent.parent / "alembic.ini")
    )

    # Override sqlalchemy.url so Alembic uses the same URL as the app
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)

    try:
        command.upgrade(alembic_cfg, "head")
        command.stamp(alembic_cfg, "head")
    except Exception as exc:
        logger.warning("Alembic upgrade error (transition): %s", exc)

    # Ensure alembic_version table exists (manual stamp if needed)
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
        if not row:
            if _is_pg():
                conn.execute(
                    "INSERT INTO alembic_version (version_num) VALUES (?) "
                    "ON CONFLICT (version_num) DO NOTHING",
                    ("001_initial_schema",),
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO alembic_version (version_num) VALUES (?)",
                    ("001_initial_schema",),
                )
            conn.commit()
            logger.info("Stamped Alembic version 001_initial_schema (fallback)")
    except Exception:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)"
        )
        if _is_pg():
            conn.execute(
                "INSERT INTO alembic_version (version_num) VALUES (?) "
                "ON CONFLICT (version_num) DO NOTHING",
                ("001_initial_schema",),
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO alembic_version (version_num) VALUES (?)",
                ("001_initial_schema",),
            )
        conn.commit()
        logger.info("Stamped Alembic version 001_initial_schema (created table)")

    # Transition catch-up: apply ALTER TABLE for columns that old databases may lack
    _ensure_columns(conn, "users", [
        ("status", "TEXT DEFAULT 'active'"),
        ("trial_ends_at", "TEXT"),
        ("stripe_customer_id", "TEXT"),
        ("tenant_id", "INTEGER REFERENCES users(id)"),
    ])
    _ensure_columns(conn, "agent_schedules", [
        ("shop", "TEXT"),
        ("next_run", "TEXT"),
    ])
    _ensure_columns(conn, "shops", [
        ("agent_name", "TEXT DEFAULT NULL"),
        ("is_platform_admin", "INTEGER DEFAULT 0"),
    ])
    conn.commit()


def _ensure_columns(conn: Any, table: str,
                    columns: list[tuple[str, str]]) -> None:
    """Add columns to *table* if they don't already exist."""
    if _is_pg():
        existing = {
            row["column_name"]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = ?",
                (table,),
            ).fetchall()
        }
    else:
        existing = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
    for col_name, col_def in columns:
        if col_name not in existing:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                logger.info("Added column %s.%s", table, col_name)
            except Exception as e:
                logger.warning("Could not add column %s.%s: %s", table, col_name, e)


def _seed_default_agents(conn: Any) -> None:
    """Insert default agent_config rows for every user."""
    rows = conn.execute("SELECT id FROM users WHERE role IN ('user', 'admin')").fetchall()
    now = datetime.now(UTC).isoformat()
    for row in rows:
        uid = row["id"]
        for agent_id in DEFAULT_AGENTS:
            try:
                if _is_pg():
                    conn.execute(
                        """INSERT INTO agent_configs
                           (user_id, agent_id, enabled, model, status, last_invoked)
                           VALUES (?, ?, 1, 'deepseek-chat', 'idle', ?)
                           ON CONFLICT (user_id, agent_id) DO NOTHING""",
                        (uid, agent_id, now),
                    )
                else:
                    conn.execute(
                        """INSERT OR IGNORE INTO agent_configs
                           (user_id, agent_id, enabled, model, status, last_invoked)
                           VALUES (?, ?, 1, 'deepseek-chat', 'idle', ?)""",
                        (uid, agent_id, now),
                    )
            except Exception as e:
                logger.warning("Failed to seed agent %s for user %d: %s", agent_id, uid, e)
    conn.commit()


# ── Public helper functions ────────────────────────────────────────


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
    if _is_pg():
        cur = conn.execute(
            """INSERT INTO users (email, password_hash, role, display_name, created_at, tenant_id)
               VALUES (?, ?, ?, ?, ?, ?) RETURNING id""",
            (email, password_hash, role, display_name or email.split("@")[0], now, tenant_id),
        )
    else:
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
    col: f"UPDATE users SET {col} = ? WHERE id = ?"
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


def export_user_data(uid: int) -> dict:
    """Collect all personal data for a user across every table (GDPR/CCPA)."""
    conn = _get_conn()
    data: dict = {}

    user = get_user_by_id(uid)
    data["user"] = dict(user) if user else None

    for table in ("agent_configs", "threads", "leads", "execution_log",
                  "pending_actions", "mcp_credentials", "agent_feedback",
                  "agent_preferences", "agent_findings", "agent_schedules",
                  "llm_usage_log", "user_llm_quotas"):
        rows = conn.execute(f"SELECT * FROM {table} WHERE user_id = ?", (uid,)).fetchall()
        data[table] = [dict(r) for r in rows]

    shops = [dict(s) for s in conn.execute("SELECT * FROM shops WHERE user_id = ?", (uid,)).fetchall()]
    data["shops"] = shops
    shop_domains = [s["shop"] for s in shops if s.get("shop")]

    webhook_events = []
    for shop in shop_domains:
        rows = conn.execute("SELECT * FROM webhook_events WHERE shop = ?", (shop,)).fetchall()
        for r in rows:
            webhook_events.append(dict(r))
    data["webhook_events"] = webhook_events

    return data


def delete_user(uid: int) -> None:
    conn = _get_conn()
    try:
        shops = [dict(s) for s in conn.execute("SELECT shop FROM shops WHERE user_id = ?", (uid,)).fetchall()]
        shop_domains = [s["shop"] for s in shops if s.get("shop")]

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
        for shop in shop_domains:
            conn.execute("DELETE FROM webhook_events WHERE shop = ?", (shop,))
        conn.execute("DELETE FROM shops WHERE user_id = ?", (uid,))
        conn.execute("UPDATE users SET tenant_id = NULL WHERE tenant_id = ?", (uid,))
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
