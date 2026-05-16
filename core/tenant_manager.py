import os
import re
import sqlite3
import uuid
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_AGENTS = [
    "local_seo", "social_media", "lead_conversion", "paid_ads",
    "growth_hacker", "reputation", "email_marketing", "tiktok",
    "outreach", "backlinks", "executioner",
    "content_strategy", "technical_seo", "reporting",
    "cro", "video", "sms_marketing",
]


class TenantManager:
    """
    Manages multi-tenant database isolation.

    Architecture: Database-per-tenant.
    - Direct clients: /tenants/direct/<client_id>.db
    - Resellers: /tenants/resellers/<reseller_id>/reseller.db
    - Reseller clients: /tenants/resellers/<reseller_id>/<client_id>.db

    Each tenant database contains its own:
    - Agent configurations (api keys, LLM preferences, on/off states)
    - Active threads and approvals
    - Client business details
    - Payment schedules
    - Lead data
    - Execution logs
    """

    def __init__(self, base_path: str = "tenants") -> None:
        """Initialize the TenantManager.

        Args:
            base_path: Root directory for tenant databases.
        """
        self.base_path = Path(base_path)
        self.direct_path = self.base_path / "direct"
        self.reseller_path = self.base_path / "resellers"
        self._lock = threading.Lock()
        self._thread_local = threading.local()
        self._last_used: Dict[str, str] = {}
        self._create_directories()

    # ------------------------------------------------------------------
    # Directory setup
    # ------------------------------------------------------------------

    def _create_directories(self) -> None:
        """Create the tenant directory structure if it does not exist."""
        try:
            self.direct_path.mkdir(parents=True, exist_ok=True)
            self.reseller_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error("Failed to create tenant directories: %s", e)
            raise

    # ------------------------------------------------------------------
    # Database path helpers
    # ------------------------------------------------------------------

    def _get_db_path(self, tenant_id: str, tenant_type: str,
                     reseller_id: Optional[str] = None) -> Path:
        """Resolve the database file path for a tenant without creating it.

        Args:
            tenant_id: Unique identifier for the tenant.
            tenant_type: ``"direct"``, ``"reseller"``, or ``"reseller_client"``.
            reseller_id: Required when tenant_type is ``"reseller_client"``.

        Returns:
            Resolved Path to the database file.

        Raises:
            ValueError: If tenant_type is unknown, or if the resolved
                path escapes the allowed tenant directory.
        """
        if tenant_type == "direct":
            resolved = (self.direct_path / f"{tenant_id}.db").resolve()
            allowed = self.direct_path.resolve()
        elif tenant_type == "reseller":
            resolved = (self.reseller_path / tenant_id / "reseller.db").resolve()
            allowed = self.reseller_path.resolve()
        elif tenant_type == "reseller_client":
            resolved = (self.reseller_path / reseller_id / f"{tenant_id}.db").resolve()
            allowed = self.reseller_path.resolve()
        else:
            raise ValueError(f"Invalid tenant_type: {tenant_type}")

        if not str(resolved).startswith(str(allowed) + "/"):
            raise ValueError(
                f"Resolved path {resolved} escapes allowed directory {allowed}"
            )

        return resolved

    # ------------------------------------------------------------------
    # Schema DDL
    # ------------------------------------------------------------------

    @staticmethod
    def _schema_sql() -> Dict[str, str]:
        """Return a dict of CREATE TABLE statements keyed by table name."""
        return {
            "agents": """
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
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
                    confidence_threshold REAL DEFAULT 0.7
                )
            """,
            "threads": """
                CREATE TABLE IF NOT EXISTS threads (
                    thread_id TEXT PRIMARY KEY,
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
            """,
            "client_details": """
                CREATE TABLE IF NOT EXISTS client_details (
                    id INTEGER PRIMARY KEY,
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
                )
            """,
            "payments": """
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    installment_number INTEGER,
                    amount REAL,
                    due_date TEXT,
                    paid INTEGER DEFAULT 0,
                    paid_date TEXT,
                    notes TEXT
                )
            """,
            "leads": """
                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    phone TEXT,
                    service TEXT,
                    urgency TEXT,
                    created_at TEXT,
                    status TEXT DEFAULT 'new'
                )
            """,
            "execution_log": """
                CREATE TABLE IF NOT EXISTS execution_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    execution_id TEXT,
                    agent_name TEXT,
                    tool_name TEXT,
                    draft_preview TEXT,
                    success INTEGER DEFAULT 0,
                    result TEXT,
                    error TEXT,
                    timestamp TEXT
                )
            """,
            "affiliate_leads": """
                CREATE TABLE IF NOT EXISTS affiliate_leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ref_code TEXT,
                    lead_email TEXT,
                    lead_name TEXT,
                    status TEXT DEFAULT 'lead',
                    commission REAL,
                    created_at TEXT
                )
            """,
            "users": """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('client', 'affiliate', 'reseller')),
                    display_name TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_login TEXT
                )
            """,
            "schema_version": """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
            """,
            "deployments": """
                CREATE TABLE IF NOT EXISTS deployments (
                    id TEXT PRIMARY KEY,
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
                )
            """,
            "pending_actions": """
                CREATE TABLE IF NOT EXISTS pending_actions (
                    id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    provider TEXT DEFAULT 'web',
                    content TEXT NOT NULL,
                    subject TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                )
            """,
            "affiliates": """
                CREATE TABLE IF NOT EXISTS affiliates (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    phone TEXT DEFAULT '',
                    total_earnings REAL DEFAULT 0,
                    paid_earnings REAL DEFAULT 0,
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    last_login TEXT
                )
            """,
            "commissions": """
                CREATE TABLE IF NOT EXISTS commissions (
                    id TEXT PRIMARY KEY,
                    affiliate_code TEXT NOT NULL,
                    client_email TEXT,
                    client_name TEXT,
                    amount REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    paid_at TEXT
                )
            """,
            "payouts": """
                CREATE TABLE IF NOT EXISTS payouts (
                    id TEXT PRIMARY KEY,
                    affiliate_code TEXT NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    processed_at TEXT
                )
            """,
            "mcp_credentials": """
                CREATE TABLE IF NOT EXISTS mcp_credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_name TEXT NOT NULL,
                    platform TEXT,
                    credential_key TEXT NOT NULL,
                    credential_value TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(server_name, platform, credential_key)
                )
            """,
        }

    # ------------------------------------------------------------------
    # Schema migrations
    # ------------------------------------------------------------------

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Apply pending schema migrations in order."""

        _MIGRATIONS: list[tuple[int, str]] = [
            # version 2: ensure users table exists (legacy databases)
            (2, "users"),
            # version 3: add autonomy/confidence to agents
            (3, "ALTER TABLE agents ADD COLUMN autonomy TEXT DEFAULT 'manual'"),
            # version 4: add confidence_threshold to agents
            (4, "ALTER TABLE agents ADD COLUMN confidence_threshold REAL DEFAULT 0.7"),
            # version 5: ensure pending_actions table exists
            (5, "pending_actions"),
            # version 6: ensure mcp_credentials table exists
            (6, "mcp_credentials"),
        ]

        try:
            version = conn.execute(
                "SELECT COALESCE(MAX(version), 1) FROM schema_version"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            # schema_version table doesn't exist yet
            version = 0

        now = datetime.now(timezone.utc).isoformat()

        for mig_version, statement in _MIGRATIONS:
            if mig_version > version:
                try:
                    if statement in self._schema_sql():
                        conn.execute(self._schema_sql()[statement])
                    else:
                        conn.execute(statement)
                    conn.execute(
                        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                        (mig_version, now),
                    )
                    conn.commit()
                    logger.info("Applied migration v%d: %s", mig_version, statement[:60])
                except (sqlite3.OperationalError, sqlite3.IntegrityError) as e:
                    logger.warning("Migration v%d skipped (%s): %s", mig_version, statement[:60], e)
                    conn.rollback()

    # ------------------------------------------------------------------
    # Seed helpers
    # ------------------------------------------------------------------

    def _seed_agents(self, cursor: sqlite3.Cursor) -> None:
        """Insert default agent rows for every built-in agent.

        Args:
            cursor: Active database cursor.
        """
        now = datetime.now(timezone.utc).isoformat()
        for agent_id in DEFAULT_AGENTS:
            try:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO agents
                        (agent_id, enabled, model, status, last_invoked)
                    VALUES (?, 1, 'deepseek-chat', 'idle', ?)
                    """,
                    (agent_id, now),
                )
            except sqlite3.Error as e:
                logger.warning("Failed to seed agent %s: %s", agent_id, e)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_tenant_database(self, tenant_id: str,
                               tenant_type: str = "direct",
                               reseller_id: Optional[str] = None) -> str:
        """Create a new tenant database with all required tables and seed data.

        Args:
            tenant_id: Unique identifier for the tenant.
            tenant_type: ``"direct"``, ``"reseller"``, or ``"reseller_client"``.
            reseller_id: Required when tenant_type is ``"reseller_client"``.

        Returns:
            Absolute path to the created database file.

        Raises:
            ValueError: If tenant_type is unknown.
            sqlite3.Error: If database creation fails.
        """
        db_path = self._get_db_path(tenant_id, tenant_type, reseller_id)

        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            cursor = conn.cursor()

            # Create all tables
            for name, ddl in self._schema_sql().items():
                cursor.execute(ddl)
                logger.debug("Created table %s in %s", name, db_path)

            # Seed default agent rows
            self._seed_agents(cursor)

            # Create indexes for common query patterns
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_threads_status ON threads(status)",
                "CREATE INDEX IF NOT EXISTS idx_threads_routed_agent ON threads(routed_agent)",
                "CREATE INDEX IF NOT EXISTS idx_execution_log_agent ON execution_log(agent_name)",
                "CREATE INDEX IF NOT EXISTS idx_execution_log_timestamp ON execution_log(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)",
                "CREATE INDEX IF NOT EXISTS idx_affiliate_leads_ref ON affiliate_leads(ref_code)",
                "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)",
                "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
            ]
            for idx in indexes:
                cursor.execute(idx)

            # Record schema version
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (1, ?)",
                (now,),
            )

            conn.commit()
            conn.close()

            logger.info("Created tenant database: %s", db_path)
            return str(db_path.resolve())

        except sqlite3.Error as e:
            logger.error("Failed to create tenant database %s: %s", db_path, e)
            # Clean up partial file on failure
            if db_path.exists():
                db_path.unlink()
            raise

    def get_connection(self, tenant_id: str,
                       tenant_type: str = "direct",
                       reseller_id: Optional[str] = None) -> sqlite3.Connection:
        """Return a cached database connection for a tenant.

        Creates the database on first access if it does not exist.
        Connections are thread-local to avoid SQLite thread-safety issues.

        Args:
            tenant_id: Unique identifier for the tenant.
            tenant_type: ``"direct"``, ``"reseller"``, or ``"reseller_client"``.
            reseller_id: Required when tenant_type is ``"reseller_client"``.

        Returns:
            ``sqlite3.Connection`` with ``row_factory = sqlite3.Row``.
        """
        cache_key = f"{tenant_type}:{reseller_id or 'none'}:{tenant_id}"

        if not hasattr(self._thread_local, "connections"):
            self._thread_local.connections = {}

        if cache_key in self._thread_local.connections:
            self._last_used[cache_key] = datetime.now(timezone.utc).isoformat()
            return self._thread_local.connections[cache_key]

        db_path = self._get_db_path(tenant_id, tenant_type, reseller_id)

        if not db_path.exists():
            self.create_tenant_database(tenant_id, tenant_type, reseller_id)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        # Apply any pending schema migrations
        self._migrate_schema(conn)

        self._thread_local.connections[cache_key] = conn
        self._last_used[cache_key] = datetime.now(timezone.utc).isoformat()
        logger.debug("Opened connection for tenant %s (%s)", tenant_id, db_path)
        return conn

    def close_connection(self, tenant_id: str,
                         tenant_type: str = "direct",
                         reseller_id: Optional[str] = None) -> None:
        """Close and remove a single tenant connection from the cache.

        Args:
            tenant_id: Unique identifier for the tenant.
            tenant_type: ``"direct"``, ``"reseller"``, or ``"reseller_client"``.
            reseller_id: Required when tenant_type is ``"reseller_client"``.
        """
        cache_key = f"{tenant_type}:{reseller_id or 'none'}:{tenant_id}"

        if not hasattr(self._thread_local, "connections"):
            return

        conn = self._thread_local.connections.pop(cache_key, None)
        self._last_used.pop(cache_key, None)
        if conn:
            conn.close()
            logger.debug("Closed connection for tenant %s", tenant_id)

    def list_tenants(self, tenant_type: str = "direct",
                     reseller_id: Optional[str] = None) -> List[str]:
        """List all tenant identifiers of a given type.

        Args:
            tenant_type: ``"direct"``, ``"reseller"``, or ``"reseller_client"``.
            reseller_id: Required when tenant_type is ``"reseller_client"``.

        Returns:
            List of tenant ID strings.
        """
        try:
            if tenant_type == "direct":
                return [p.stem for p in self.direct_path.glob("*.db")]

            if tenant_type == "reseller":
                return [p.parent.name for p in self.reseller_path.glob("*/reseller.db")]

            if tenant_type == "reseller_client":
                return [
                    p.stem
                    for p in (self.reseller_path / reseller_id).glob("*.db")
                    if p.stem != "reseller"
                ]

            logger.warning("list_tenants called with unknown type: %s", tenant_type)
            return []

        except OSError as e:
            logger.error("Failed to list tenants of type %s: %s", tenant_type, e)
            return []

    def delete_tenant(self, tenant_id: str,
                      tenant_type: str = "direct",
                      reseller_id: Optional[str] = None) -> bool:
        """Delete a tenant database and remove its cached connection.

        Args:
            tenant_id: Unique identifier for the tenant.
            tenant_type: ``"direct"``, ``"reseller"``, or ``"reseller_client"``.
            reseller_id: Required when tenant_type is ``"reseller_client"``.

        Returns:
            ``True`` if the database was deleted, ``False`` if it did not exist.
        """
        # Close and remove from cache first
        self.close_connection(tenant_id, tenant_type, reseller_id)

        try:
            db_path = self._get_db_path(tenant_id, tenant_type, reseller_id)
            if db_path.exists():
                db_path.unlink()
                logger.info("Deleted tenant database: %s", db_path)
                return True
            logger.debug("Tenant database not found for deletion: %s", db_path)
            return False
        except OSError as e:
            logger.error("Failed to delete tenant database %s: %s", db_path, e)
            return False

    def cleanup_stale_connections(self, max_idle_minutes: int = 30) -> int:
        """Close connections idle for more than ``max_idle_minutes``.

        Args:
            max_idle_minutes: Maximum idle time in minutes before closing.

        Returns:
            Number of connections closed.
        """
        now = datetime.now(timezone.utc)
        closed = 0
        if not hasattr(self._thread_local, "connections"):
            return 0
        stale = [
            key for key, last in self._last_used.items()
            if (now - datetime.fromisoformat(last)).total_seconds() > max_idle_minutes * 60
        ]
        for key in stale:
            conn = self._thread_local.connections.pop(key, None)
            self._last_used.pop(key, None)
            if conn:
                try:
                    conn.close()
                    closed += 1
                except sqlite3.Error as e:
                    logger.warning("Error closing stale connection %s: %s", key, e)
        if closed:
            logger.info("Closed %d stale connection(s)", closed)
        return closed

    def close_all(self) -> None:
        """Close every active database connection and clear the cache."""
        if not hasattr(self._thread_local, "connections"):
            return
        for cache_key, conn in self._thread_local.connections.items():
            try:
                conn.close()
            except sqlite3.Error as e:
                logger.warning("Error closing connection %s: %s", cache_key, e)
        self._thread_local.connections.clear()
        self._last_used.clear()
        logger.info("All tenant connections closed")

    def get_agent_autonomy(self, tenant_id: str) -> Dict[str, Dict[str, Any]]:
        """Load autonomy settings for all agents in a tenant.

        Args:
            tenant_id: The tenant identifier.

        Returns:
            Dict mapping agent_id -> {autonomy, confidence_threshold}
        """
        try:
            conn = self.get_connection(tenant_id)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT agent_id, autonomy, confidence_threshold FROM agents"
            )
            result = {}
            for row in cursor.fetchall():
                result[row["agent_id"]] = {
                    "autonomy": row["autonomy"] or "manual",
                    "confidence_threshold": row["confidence_threshold"] or 0.7,
                }
            return result
        except Exception as e:
            logger.error("Failed to load autonomy for %s: %s", tenant_id, e)
            return {}

    def set_agent_autonomy(
        self, tenant_id: str, agent_id: str,
        autonomy: str, confidence_threshold: float,
    ) -> None:
        """Update autonomy settings for a single agent in a tenant.

        Args:
            tenant_id: The tenant identifier.
            agent_id: The agent identifier.
            autonomy: One of ``manual``, ``suggest``, ``auto``, ``silent``.
            confidence_threshold: Minimum confidence for auto-execution (0.0-1.0).
        """
        try:
            conn = self.get_connection(tenant_id)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE agents SET autonomy = ?, confidence_threshold = ? WHERE agent_id = ?",
                (autonomy, confidence_threshold, agent_id),
            )
            conn.commit()
        except Exception as e:
            logger.error(
                "Failed to set autonomy for %s/%s: %s", tenant_id, agent_id, e
            )
