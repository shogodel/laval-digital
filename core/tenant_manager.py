import os
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
        self._active_connections: Dict[str, sqlite3.Connection] = {}
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
            ValueError: If tenant_type is unknown.
        """
        if tenant_type == "direct":
            return self.direct_path / f"{tenant_id}.db"
        elif tenant_type == "reseller":
            return self.reseller_path / tenant_id / "reseller.db"
        elif tenant_type == "reseller_client":
            return self.reseller_path / reseller_id / f"{tenant_id}.db"
        raise ValueError(f"Invalid tenant_type: {tenant_type}")

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
                    status TEXT DEFAULT 'idle'
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
        }

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
            conn = sqlite3.connect(str(db_path))
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

        Args:
            tenant_id: Unique identifier for the tenant.
            tenant_type: ``"direct"``, ``"reseller"``, or ``"reseller_client"``.
            reseller_id: Required when tenant_type is ``"reseller_client"``.

        Returns:
            ``sqlite3.Connection`` with ``row_factory = sqlite3.Row``.
        """
        cache_key = f"{tenant_type}:{reseller_id or 'none'}:{tenant_id}"

        with self._lock:
            if cache_key in self._active_connections:
                self._last_used[cache_key] = datetime.now(timezone.utc).isoformat()
                return self._active_connections[cache_key]

            db_path = self._get_db_path(tenant_id, tenant_type, reseller_id)

            if not db_path.exists():
                self.create_tenant_database(tenant_id, tenant_type, reseller_id)

            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")

            # Migrate: ensure users table exists on existing databases
            try:
                conn.execute(self._schema_sql()["users"])
                conn.commit()
            except sqlite3.Error as e:
                logger.warning("Migration failed for users table in %s: %s", db_path, e)

            self._active_connections[cache_key] = conn
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

        with self._lock:
            conn = self._active_connections.pop(cache_key, None)
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
        with self._lock:
            stale = [
                key for key, last in self._last_used.items()
                if (now - datetime.fromisoformat(last)).total_seconds() > max_idle_minutes * 60
            ]
            for key in stale:
                conn = self._active_connections.pop(key, None)
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
        with self._lock:
            for cache_key, conn in self._active_connections.items():
                try:
                    conn.close()
                except sqlite3.Error as e:
                    logger.warning("Error closing connection %s: %s", cache_key, e)
            self._active_connections.clear()
            self._last_used.clear()
            logger.info("All tenant connections closed")
