"""ResellerManager — persistent reseller system backed by the platform database.

Replaces the hardcoded ``RESELLER_PRICING`` dict and in-memory
``reseller_applications`` list with proper database tables.

Reseller tiers, package pricing, and applications are stored in the
platform ``_affiliates`` database (shared with the affiliate system).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.tenant_manager import TenantManager

logger = logging.getLogger(__name__)

PLATFORM_TENANT = "_affiliates"

RESELLER_SCHEMA = {
    "reseller_tiers": """
        CREATE TABLE IF NOT EXISTS reseller_tiers (
            tier TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            wholesale_discount_pct REAL DEFAULT 0,
            min_monthly_clients INT DEFAULT 0,
            mrr_per_client REAL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """,
    "reseller_pricing": """
        CREATE TABLE IF NOT EXISTS reseller_pricing (
            tier TEXT NOT NULL,
            package TEXT NOT NULL,
            wholesale_price REAL NOT NULL,
            map_price REAL NOT NULL,
            suggested_price REAL NOT NULL,
            PRIMARY KEY (tier, package)
        )
    """,
    "reseller_applications": """
        CREATE TABLE IF NOT EXISTS reseller_applications (
            id TEXT PRIMARY KEY,
            agency_name TEXT NOT NULL,
            contact_name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT DEFAULT '',
            client_count TEXT DEFAULT '',
            tier TEXT DEFAULT 'standard',
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            processed_at TEXT
        )
    """,
}

DEFAULT_TIERS = [
    {"tier": "standard", "label": "Standard Partner", "discount": 0, "min_clients": 0, "mrr": 1500},
    {"tier": "silver", "label": "Silver Partner", "discount": 5, "min_clients": 5, "mrr": 2000},
    {"tier": "gold", "label": "Gold Partner", "discount": 10, "min_clients": 15, "mrr": 2500},
    {"tier": "platinum", "label": "Platinum Partner", "discount": 15, "min_clients": 30, "mrr": 3000},
]

DEFAULT_PRICING = {
    "core_suite": {"wholesale": 4500, "map": 8500, "suggested": 9500},
    "growth_suite": {"wholesale": 7000, "map": 12500, "suggested": 13500},
    "full_empire": {"wholesale": 9500, "map": 16500, "suggested": 17500},
}


class ResellerManager:
    """Persistent reseller operations backed by the platform database."""

    def __init__(self, tenant_manager: TenantManager) -> None:
        self._tm = tenant_manager
        self._ensure_schema()

    # ── Platform DB setup ──────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        """Create the platform DB and ensure reseller tables exist."""
        try:
            self._tm.create_tenant_database(PLATFORM_TENANT, "direct")
        except Exception:
            pass
        conn = self._tm.get_connection(PLATFORM_TENANT)
        cursor = conn.cursor()
        for ddl in RESELLER_SCHEMA.values():
            cursor.execute(ddl)
        # Seed default tiers if empty
        cursor.execute("SELECT COUNT(*) as cnt FROM reseller_tiers")
        if cursor.fetchone()["cnt"] == 0:
            for t in DEFAULT_TIERS:
                cursor.execute(
                    "INSERT INTO reseller_tiers (tier, label, wholesale_discount_pct, min_monthly_clients, mrr_per_client, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (t["tier"], t["label"], t["discount"], t["min_clients"], t["mrr"],
                     datetime.now(timezone.utc).isoformat()),
                )
        # Seed default pricing if empty
        cursor.execute("SELECT COUNT(*) as cnt FROM reseller_pricing")
        if cursor.fetchone()["cnt"] == 0:
            for pkg, prices in DEFAULT_PRICING.items():
                for t in DEFAULT_TIERS:
                    discount = t["discount"] / 100.0
                    cursor.execute(
                        "INSERT INTO reseller_pricing (tier, package, wholesale_price, map_price, suggested_price) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (t["tier"], pkg,
                         round(prices["wholesale"] * (1 - discount)),
                         prices["map"],
                         prices["suggested"]),
                    )
        conn.commit()

    def _conn(self):
        return self._tm.get_connection(PLATFORM_TENANT)

    # ── Tiers ──────────────────────────────────────────────────────────

    def get_tiers(self) -> List[Dict[str, Any]]:
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT tier, label, wholesale_discount_pct, min_monthly_clients, mrr_per_client "
                "FROM reseller_tiers ORDER BY min_monthly_clients ASC"
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("Failed to get tiers: %s", e)
            return []

    def update_tier(self, tier: str, **kwargs) -> bool:
        try:
            conn = self._conn()
            cursor = conn.cursor()
            sets = []
            vals = []
            for key, val in kwargs.items():
                col = {
                    "label": "label",
                    "discount_pct": "wholesale_discount_pct",
                    "min_clients": "min_monthly_clients",
                    "mrr": "mrr_per_client",
                }.get(key)
                if col:
                    sets.append(f"{col} = ?")
                    vals.append(val)
            if sets:
                vals.append(tier)
                cursor.execute(
                    f"UPDATE reseller_tiers SET {', '.join(sets)} WHERE tier = ?", vals
                )
                conn.commit()
                return True
            return False
        except Exception as e:
            logger.error("Failed to update tier %s: %s", tier, e)
            return False

    # ── Pricing ────────────────────────────────────────────────────────

    def get_pricing(self, tier: str = "standard") -> Dict[str, Dict[str, float]]:
        """Return package pricing for a specific reseller tier.

        Returns a dict keyed by package name:
        ``{"core_suite": {"wholesale": ..., "map": ..., "suggested": ...}}``
        """
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT package, wholesale_price, map_price, suggested_price "
                "FROM reseller_pricing WHERE tier = ?", (tier,)
            )
            result = {}
            for row in cursor.fetchall():
                result[row["package"]] = {
                    "wholesale": row["wholesale_price"],
                    "map": row["map_price"],
                    "suggested": row["suggested_price"],
                }
            return result
        except Exception as e:
            logger.error("Failed to get pricing for tier %s: %s", tier, e)
            return {}

    def update_pricing(self, tier: str, package: str, **kwargs) -> bool:
        try:
            conn = self._conn()
            cursor = conn.cursor()
            sets = []
            vals = []
            for key, val in kwargs.items():
                col = {"wholesale": "wholesale_price", "map": "map_price", "suggested": "suggested_price"}.get(key)
                if col:
                    sets.append(f"{col} = ?")
                    vals.append(val)
            if sets:
                vals.extend([tier, package])
                cursor.execute(
                    f"UPDATE reseller_pricing SET {', '.join(sets)} WHERE tier = ? AND package = ?",
                    vals,
                )
                conn.commit()
                return True
            return False
        except Exception as e:
            logger.error("Failed to update pricing: %s", e)
            return False

    # ── Applications ───────────────────────────────────────────────────

    def create_application(
        self, agency: str, contact: str, email: str, phone: str = "", client_count: str = "",
    ) -> Dict[str, Any]:
        app_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO reseller_applications
                   (id, agency_name, contact_name, email, phone, client_count, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (app_id, agency, contact, email, phone, client_count, now),
            )
            conn.commit()
            return {"id": app_id, "agency_name": agency, "contact_name": contact, "status": "pending"}
        except Exception as e:
            logger.error("Failed to create reseller application: %s", e)
            raise

    def get_applications(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            conn = self._conn()
            cursor = conn.cursor()
            if status:
                cursor.execute(
                    "SELECT id, agency_name, contact_name, email, phone, client_count, tier, status, created_at "
                    "FROM reseller_applications WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                )
            else:
                cursor.execute(
                    "SELECT id, agency_name, contact_name, email, phone, client_count, tier, status, created_at "
                    "FROM reseller_applications ORDER BY created_at DESC"
                )
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []

    def process_application(self, app_id: str, status: str, tier: str = "standard") -> bool:
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE reseller_applications SET status = ?, tier = ?, processed_at = ? WHERE id = ?",
                (status, tier, now, app_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error("Failed to process application %s: %s", app_id, e)
            return False

    # ── Reseller profile ───────────────────────────────────────────────

    def _get_reseller_tier(self, tenant_id: str) -> str:
        """Determine a reseller's tier based on their client count."""
        try:
            clients = self._tm.list_tenants("reseller_client", tenant_id)
            client_count = len(clients)
            tiers = self.get_tiers()
            best_tier = "standard"
            for t in tiers:
                if client_count >= t["min_monthly_clients"]:
                    best_tier = t["tier"]
            return best_tier
        except Exception:
            return "standard"

    def get_reseller_stats(self, tenant_id: str) -> Dict[str, Any]:
        """Return computed stats for a reseller, including MRR based on tier."""
        clients = []
        try:
            reseller_clients = self._tm.list_tenants("reseller_client", tenant_id)
            for cid in reseller_clients:
                try:
                    cconn = self._tm.get_connection(cid, "reseller_client", tenant_id)
                    ccursor = cconn.cursor()
                    ccursor.execute(
                        "SELECT business_name, package, created_at, site_url, payment_status "
                        "FROM client_details LIMIT 1"
                    )
                    crow = ccursor.fetchone()
                    if crow:
                        cdict = dict(crow)
                        cdict["status"] = "live" if cdict.get("site_url") else "pending"
                        clients.append(cdict)
                except Exception:
                    continue
        except Exception:
            pass

        total = len(clients)
        live = sum(1 for c in clients if c.get("status") == "live")
        pending = total - live

        tier = self._get_reseller_tier(tenant_id)
        tier_data = {}
        for t in self.get_tiers():
            if t["tier"] == tier:
                tier_data = t
                break
        mrr_per_client = tier_data.get("mrr_per_client", 1500)
        mrr = total * mrr_per_client

        return {
            "clients": clients,
            "total_clients": total,
            "live_sites": live,
            "pending_deployments": pending,
            "monthly_recurring": mrr,
            "tier": tier,
            "mrr_per_client": mrr_per_client,
        }
