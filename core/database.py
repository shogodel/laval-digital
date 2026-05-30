"""Single-database backend for Frankie.

Replaces the multi-tenant TenantManager with one SQLite database
at data/frankie.db.  All user-scoped data has a user_id column.
"""

import os
import sqlite3
import logging
import threading
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def _db_path() -> Path:
    return Path(os.environ.get("FRANKIE_DB_PATH", str(Path(__file__).parent.parent / "data" / "frankie.db")))
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
            except Exception:
                pass
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
            role TEXT NOT NULL CHECK(role IN ('admin', 'user', 'affiliate')),
            display_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login TEXT
        );

        CREATE TABLE IF NOT EXISTS affiliates (
            code TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT DEFAULT '',
            total_earnings REAL DEFAULT 0,
            paid_earnings REAL DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            last_login TEXT
        );

        CREATE TABLE IF NOT EXISTS commissions (
            id TEXT PRIMARY KEY,
            affiliate_code TEXT NOT NULL,
            client_email TEXT,
            client_name TEXT,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            paid_at TEXT
        );

        CREATE TABLE IF NOT EXISTS payouts (
            id TEXT PRIMARY KEY,
            affiliate_code TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            processed_at TEXT
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

        CREATE TABLE IF NOT EXISTS client_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            business_name TEXT,
            contact_name TEXT,
            email TEXT,
            phone TEXT,
            city TEXT,
            services TEXT,
            niche TEXT,
            package TEXT,
            price REAL,
            affiliate_code TEXT,
            payment_status TEXT DEFAULT 'pending',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            installment_number INTEGER,
            amount REAL,
            due_date TEXT,
            paid INTEGER DEFAULT 0,
            paid_date TEXT,
            notes TEXT
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

        CREATE TABLE IF NOT EXISTS affiliate_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            ref_code TEXT,
            lead_email TEXT,
            lead_name TEXT,
            status TEXT DEFAULT 'lead',
            commission REAL,
            created_at TEXT
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

        CREATE TABLE IF NOT EXISTS deployments (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            business_name TEXT,
            subdomain TEXT,
            niche TEXT,
            package TEXT,
            status TEXT DEFAULT 'running',
            stations_completed TEXT,
            error TEXT,
            site_url TEXT,
            admin_url TEXT,
            ssl_provisioned INTEGER DEFAULT 0,
            email_sent INTEGER DEFAULT 0,
            created_at TEXT,
            completed_at TEXT
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
        (version, datetime.now(timezone.utc).isoformat()),
    )


def _run_migrations(conn: sqlite3.Connection) -> None:
    current = _get_schema_version(conn)

    for version, sqls in MIGRATIONS:
        if version <= current:
            continue
        for sql in sqls:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # column/table/index already exists (legacy catch-up)
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
        "CREATE INDEX IF NOT EXISTS idx_client_details_user ON client_details(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_leads_user ON leads(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_execution_log_user ON execution_log(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_execution_log_ts ON execution_log(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_pending_actions_user ON pending_actions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_pending_actions_status ON pending_actions(status)",
        "CREATE INDEX IF NOT EXISTS idx_mcp_credentials_user ON mcp_credentials(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_affiliate_leads_user ON affiliate_leads(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_schedules_user ON agent_schedules(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_feedback_user ON agent_feedback(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_findings_user ON agent_findings(user_id)",
    ]),
]


def _seed_default_agents(conn: sqlite3.Connection) -> None:
    """Insert default agent_config rows for every agent."""
    rows = conn.execute("SELECT id FROM users WHERE role IN ('user', 'admin')").fetchall()
    now = datetime.now(timezone.utc).isoformat()
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


def list_users(role: Optional[str] = None) -> List[dict]:
    """List all users, optionally filtered by role."""
    conn = _get_conn()
    if role:
        rows = conn.execute("SELECT * FROM users WHERE role = ? ORDER BY id", (role,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def get_user_by_email(email: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(uid: int) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return dict(row) if row else None


def create_user(email: str, password_hash: str, role: str,
                display_name: str = "", tenant_id: Optional[int] = None) -> int:
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO users (email, password_hash, role, display_name, created_at, tenant_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (email, password_hash, role, display_name or email.split("@")[0], now, tenant_id),
    )
    conn.commit()
    uid = cur.lastrowid
    _seed_default_agents(conn)
    return uid


def update_user(uid: int, **kwargs) -> None:
    conn = _get_conn()
    _ALLOWED_USER_COLUMNS = {
        "email", "display_name", "role", "password_hash", "status",
        "trial_ends_at", "stripe_customer_id", "last_login", "tenant_id",
    }
    for key, val in kwargs.items():
        if key not in _ALLOWED_USER_COLUMNS:
            raise ValueError(f"Unknown column: {key}")
        conn.execute(
            "UPDATE users SET {} = ? WHERE id = ?".format(key),
            (val, uid),
        )
    conn.commit()


def delete_user(uid: int) -> None:
    conn = _get_conn()
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM agent_configs WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM threads WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM client_details WHERE user_id = ?", (uid,))
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
        conn.execute("DELETE FROM affiliate_leads WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM affiliates WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM commissions WHERE affiliate_code IN (SELECT code FROM affiliates WHERE user_id = ?)", (uid,))
        conn.execute("DELETE FROM payouts WHERE affiliate_code IN (SELECT code FROM affiliates WHERE user_id = ?)", (uid,))
        conn.execute("UPDATE users SET tenant_id = NULL WHERE tenant_id = ?", (uid,))
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
