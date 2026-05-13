"""AffiliateManager — persistent affiliate tracking backed by tenant databases.

Replaces the in-memory ``AFFILIATES`` dict and ``affiliate_leads`` list with
proper database tables.  Each affiliate has a row in the ``affiliates`` table,
commissions are tracked in ``commissions``, and payouts in ``payouts``.

Code validation is cached for 60 seconds to avoid scanning all tenant DBs
on every page load.
"""

import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from core.tenant_manager import TenantManager

logger = logging.getLogger(__name__)

# ── Cached valid codes ─────────────────────────────────────────────────
_cache: Set[str] = set()
_cache_ts: float = 0
_CACHE_TTL = 60  # seconds
_cache_lock = threading.Lock()


class AffiliateManager:
    """Persistent affiliate operations backed by the platform tenant DB.

    Uses a dedicated ``_affiliates`` database for the global affiliate
    registry.  Commission and lead records are stored in each affiliate's
    own tenant DB for isolation.
    """

    PLATFORM_TENANT = "_affiliates"

    def __init__(self, tenant_manager: TenantManager) -> None:
        self._tm = tenant_manager
        self._ensure_platform_db()

    # ── Platform database ──────────────────────────────────────────────

    def _ensure_platform_db(self) -> None:
        """Create the platform tenant DB if it doesn't exist."""
        try:
            self._tm.create_tenant_database(self.PLATFORM_TENANT, "direct")
        except Exception:
            pass  # already exists

    def _pconn(self):
        """Return a connection to the platform affiliates database."""
        return self._tm.get_connection(self.PLATFORM_TENANT)

    def _aconn(self, code: str):
        """Return a connection to a specific affiliate's tenant database."""
        try:
            return self._tm.get_connection(code)
        except Exception:
            self._tm.create_tenant_database(code, "direct")
            return self._tm.get_connection(code)

    # ── Code validation (cached) ───────────────────────────────────────

    def get_valid_codes(self) -> Set[str]:
        """Return all active affiliate codes, cached for 60 seconds."""
        global _cache, _cache_ts
        now = time.time()
        with _cache_lock:
            if now - _cache_ts < _CACHE_TTL and _cache:
                return set(_cache)
            codes = self._fetch_all_codes()
            _cache = set(codes)
            _cache_ts = now
            return set(_cache)

    def _fetch_all_codes(self) -> List[str]:
        try:
            conn = self._pconn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT code FROM affiliates WHERE status = 'active'"
            )
            return [row["code"] for row in cursor.fetchall()]
        except Exception as e:
            logger.error("Failed to fetch affiliate codes: %s", e)
            return []

    def invalidate_cache(self) -> None:
        with _cache_lock:
            _cache.clear()
            _cache_ts = 0

    def is_valid_code(self, code: str) -> bool:
        return code in self.get_valid_codes()

    # ── Affiliate CRUD ─────────────────────────────────────────────────

    def create_affiliate(
        self, name: str, email: str, phone: str = "", code: Optional[str] = None
    ) -> Dict[str, Any]:
        """Register a new affiliate and return their profile."""
        if not code:
            code = "REF" + uuid.uuid4().hex[:6].upper()
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._pconn()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO affiliates (code, name, email, phone, status, created_at)
                   VALUES (?, ?, ?, ?, 'active', ?)""",
                (code, name, email, phone, now),
            )
            conn.commit()
            self.invalidate_cache()

            # Also create their tenant database for lead isolation
            try:
                self._tm.create_tenant_database(code, "direct")
            except Exception:
                pass

            return {"code": code, "name": name, "email": email, "status": "active"}
        except Exception as e:
            logger.error("Failed to create affiliate %s: %s", email, e)
            raise

    def get_affiliate(self, code: str) -> Optional[Dict[str, Any]]:
        """Return an affiliate's profile or None."""
        try:
            conn = self._pconn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT code, name, email, phone, total_earnings, paid_earnings, status, created_at "
                "FROM affiliates WHERE code = ?", (code,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        except Exception as e:
            logger.error("Failed to get affiliate %s: %s", code, e)
        return None

    def update_earnings(self, code: str, amount: float) -> None:
        """Add a commission amount to an affiliate's total_earnings."""
        try:
            conn = self._pconn()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE affiliates SET total_earnings = total_earnings + ? WHERE code = ?",
                (amount, code),
            )
            conn.commit()
        except Exception as e:
            logger.error("Failed to update earnings for %s: %s", code, e)

    # ── Commissions ────────────────────────────────────────────────────

    def add_commission(
        self, affiliate_code: str, client_email: str,
        client_name: str, amount: float,
    ) -> Optional[str]:
        """Record a commission and update the affiliate's total earnings.

        Returns the commission ID or None on failure.
        """
        commission_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._pconn()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO commissions
                   (id, affiliate_code, client_email, client_name, amount, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (commission_id, affiliate_code, client_email, client_name, amount, now),
            )
            conn.commit()
            self.update_earnings(affiliate_code, amount)
            logger.info(
                "Commission $%.2f recorded for %s (client=%s)",
                amount, affiliate_code, client_email,
            )
            return commission_id
        except Exception as e:
            logger.error("Failed to add commission: %s", e)
            return None

    def get_commissions(
        self, affiliate_code: str, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return recent commissions for an affiliate."""
        try:
            conn = self._pconn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, client_email, client_name, amount, status, created_at, paid_at "
                "FROM commissions WHERE affiliate_code = ? ORDER BY created_at DESC LIMIT ?",
                (affiliate_code, limit),
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []

    def get_all_commissions(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return all commissions across all affiliates (admin view)."""
        try:
            conn = self._pconn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT c.id, c.affiliate_code, a.name AS affiliate_name, "
                "c.client_email, c.client_name, c.amount, c.status, c.created_at, c.paid_at "
                "FROM commissions c LEFT JOIN affiliates a ON c.affiliate_code = a.code "
                "ORDER BY c.created_at DESC LIMIT ?", (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []

    # ── Payouts ────────────────────────────────────────────────────────

    def create_payout(
        self, affiliate_code: str, amount: float,
    ) -> Optional[str]:
        """Create a payout request for an affiliate."""
        payout_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._pconn()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO payouts (id, affiliate_code, amount, status, created_at)
                   VALUES (?, ?, ?, 'pending', ?)""",
                (payout_id, affiliate_code, amount, now),
            )
            conn.commit()
            return payout_id
        except Exception as e:
            logger.error("Failed to create payout: %s", e)
            return None

    def process_payout(self, payout_id: str) -> bool:
        """Mark a payout as processed and update paid_earnings."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._pconn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT affiliate_code, amount FROM payouts WHERE id = ? AND status = 'pending'",
                (payout_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False
            cursor.execute(
                "UPDATE payouts SET status = 'processed', processed_at = ? WHERE id = ?",
                (now, payout_id),
            )
            cursor.execute(
                "UPDATE affiliates SET paid_earnings = paid_earnings + ? WHERE code = ?",
                (row["amount"], row["affiliate_code"]),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to process payout %s: %s", payout_id, e)
            return False

    def get_payouts(
        self, affiliate_code: Optional[str] = None, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return payouts, optionally filtered by affiliate."""
        try:
            conn = self._pconn()
            cursor = conn.cursor()
            if affiliate_code:
                cursor.execute(
                    "SELECT id, amount, status, created_at, processed_at "
                    "FROM payouts WHERE affiliate_code = ? ORDER BY created_at DESC LIMIT ?",
                    (affiliate_code, limit),
                )
            else:
                cursor.execute(
                    "SELECT p.id, p.affiliate_code, a.name AS affiliate_name, "
                    "p.amount, p.status, p.created_at, p.processed_at "
                    "FROM payouts p LEFT JOIN affiliates a ON p.affiliate_code = a.code "
                    "ORDER BY p.created_at DESC LIMIT ?", (limit,)
                )
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []

    # ── Lead tracking ──────────────────────────────────────────────────

    def track_lead(
        self, ref_code: str, ip: str, user_agent: str, landing_page: str,
    ) -> None:
        """Record an affiliate referral lead in the affiliate's tenant DB."""
        try:
            conn = self._aconn(ref_code)
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO affiliate_leads
                   (ref_code, lead_email, lead_name, status, created_at)
                   VALUES (?, ?, ?, 'lead', ?)""",
                (ref_code, f"lead@{ip}", f"Lead from {landing_page}",
                 datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except Exception as e:
            logger.warning("Failed to track lead for %s: %s", ref_code, e)

    def get_leads(
        self, affiliate_code: str, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return referral leads for an affiliate from their tenant DB."""
        try:
            conn = self._aconn(affiliate_code)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, lead_email, lead_name, status, commission, created_at "
                "FROM affiliate_leads ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []

    def get_all_affiliates(self) -> List[Dict[str, Any]]:
        """Return all affiliates (admin view)."""
        try:
            conn = self._pconn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT code, name, email, phone, total_earnings, paid_earnings, "
                "status, created_at, last_login FROM affiliates ORDER BY created_at DESC"
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []
