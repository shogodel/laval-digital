"""Initial schema — all tables after v14 migrations.

Creates every table and index that exists in a fully migrated database.
Safe to run on an existing database (all CREATEs use IF NOT EXISTS).
Supports both SQLite and PostgreSQL backends.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    """Return True if the current database backend is SQLite."""
    bind = op.get_bind()
    return bind.engine.name == "sqlite"


def _autoinc() -> str:
    """Return the auto-increment primary key DDL fragment for current backend."""
    return "INTEGER PRIMARY KEY AUTOINCREMENT" if _is_sqlite() else "SERIAL PRIMARY KEY"


def _substr_expr(col: str) -> str:
    """Return the substring expression for the given column."""
    return f"substr({col},1,7)" if _is_sqlite() else f"LEFT({col}, 7)"


AUTO = _autoinc


def upgrade() -> None:
    _is_sqlite()

    # ── Platform tables ──────────────────────────────────────────
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            id {_autoinc()},
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
        )
    """)

    op.execute("""
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
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_feedback (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            agent_id TEXT,
            feedback_type TEXT,
            content TEXT,
            approved INTEGER,
            created_at TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_preferences (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            agent_id TEXT,
            pref_key TEXT,
            pref_value TEXT,
            updated_at TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_findings (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            source_agent TEXT,
            finding_type TEXT,
            summary TEXT,
            detail TEXT,
            created_at TEXT,
            expires_at TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)

    # ── Per-user data tables ────────────────────────────────────
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS agent_configs (
            id {_autoinc()},
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
        )
    """)

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS threads (
            id {_autoinc()},
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
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            name TEXT,
            phone TEXT,
            service TEXT,
            urgency TEXT,
            created_at TEXT,
            status TEXT DEFAULT 'new'
        )
    """)

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS execution_log (
            id {_autoinc()},
            user_id INTEGER NOT NULL REFERENCES users(id),
            execution_id TEXT,
            agent_name TEXT,
            tool_name TEXT,
            draft_preview TEXT,
            success INTEGER DEFAULT 0,
            result TEXT,
            error TEXT,
            timestamp TEXT
        )
    """)

    op.execute("""
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
        )
    """)

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS mcp_credentials (
            id {_autoinc()},
            user_id INTEGER NOT NULL REFERENCES users(id),
            server_name TEXT NOT NULL,
            platform TEXT,
            credential_key TEXT NOT NULL,
            credential_value TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, server_name, platform, credential_key)
        )
    """)

    # ── Migration-added tables ──────────────────────────────────
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS login_attempts (
            id {_autoinc()},
            ip TEXT NOT NULL,
            success INTEGER NOT NULL,
            attempted_at TEXT NOT NULL
        )
    """)

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS llm_usage_log (
            id {_autoinc()},
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
        )
    """)

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS user_llm_quotas (
            id {_autoinc()},
            user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
            requests_per_hour INTEGER DEFAULT 60,
            requests_per_day INTEGER DEFAULT 500,
            tokens_per_day INTEGER DEFAULT 1000000,
            cost_per_day REAL DEFAULT 5.00,
            cost_per_month REAL DEFAULT 100.00,
            blocked INTEGER DEFAULT 0
        )
    """)

    # ── Shopify tables (with all migration-added columns) ───────
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS shops (
            id {_autoinc()},
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
        )
    """)

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS webhook_events (
            id {_autoinc()},
            shop TEXT NOT NULL,
            topic TEXT NOT NULL,
            body TEXT NOT NULL,
            received_at TEXT NOT NULL,
            processed INTEGER DEFAULT 0
        )
    """)

    # ── Indexes ─────────────────────────────────────────────────
    for idx_sql in [
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
        f"CREATE INDEX IF NOT EXISTS idx_llm_usage_user_month ON llm_usage_log(user_id, {_substr_expr('timestamp')})",
        "CREATE INDEX IF NOT EXISTS idx_shops_active ON shops(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_shops_domain ON shops(shop)",
        "CREATE INDEX IF NOT EXISTS idx_webhook_events_shop ON webhook_events(shop)",
        "CREATE INDEX IF NOT EXISTS idx_webhook_events_topic ON webhook_events(topic)",
    ]:
        op.execute(idx_sql)


def downgrade() -> None:
    """No downgrade from initial schema — data loss risk."""
    pass
