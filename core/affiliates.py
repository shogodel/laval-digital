import logging
import threading
import time
import uuid
from datetime import datetime, UTC
from typing import Any, Optional

from core import database

logger = logging.getLogger(__name__)

_cache: set[str] = set()
_cache_ts: float = 0
_CACHE_TTL = 60
_cache_lock = threading.Lock()


class AffiliateManager:
    def __init__(self):
        pass

    def _conn(self):
        return database._get_conn()

    # ── Code validation (cached) ───────────────────────────────────────

    def get_valid_codes(self) -> set[str]:
        global _cache, _cache_ts
        now = time.time()
        with _cache_lock:
            if now - _cache_ts < _CACHE_TTL and _cache:
                return set(_cache)
            codes = self._fetch_all_codes()
            _cache = set(codes)
            _cache_ts = now
            return set(_cache)

    def _fetch_all_codes(self) -> list[str]:
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT code FROM affiliates WHERE status = 'active'"
            ).fetchall()
            return [r["code"] for r in rows]
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

    def create_affiliate(self, name: str, email: str, phone: str = "",
                         code: Optional[str] = None) -> dict[str, Any]:
        if not code:
            code = "REF" + uuid.uuid4().hex[:6].upper()
        now = datetime.now(UTC).isoformat()
        try:
            conn = self._conn()
            conn.execute(
                """INSERT INTO affiliates (code, name, email, phone, status, created_at)
                   VALUES (?, ?, ?, ?, 'active', ?)""",
                (code, name, email, phone, now),
            )
            conn.commit()
            self.invalidate_cache()
            return {"code": code, "name": name, "email": email, "status": "active"}
        except Exception as e:
            logger.error("Failed to create affiliate %s: %s", email, e)
            raise

    def get_affiliate(self, code: str) -> Optional[dict[str, Any]]:
        try:
            conn = self._conn()
            row = conn.execute(
                "SELECT code, name, email, phone, total_earnings, paid_earnings, status, created_at "
                "FROM affiliates WHERE code = ?", (code,)
            ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error("Failed to get affiliate %s: %s", code, e)
        return None

    def update_earnings(self, code: str, amount: float) -> None:
        try:
            conn = self._conn()
            conn.execute(
                "UPDATE affiliates SET total_earnings = total_earnings + ? WHERE code = ?",
                (amount, code),
            )
            conn.commit()
        except Exception as e:
            logger.error("Failed to update earnings for %s: %s", code, e)

    # ── Commissions ────────────────────────────────────────────────────

    def add_commission(self, affiliate_code: str, client_email: str,
                       client_name: str, amount: float) -> Optional[str]:
        commission_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC).isoformat()
        try:
            conn = self._conn()
            conn.execute(
                """INSERT INTO commissions
                   (id, affiliate_code, client_email, client_name, amount, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (commission_id, affiliate_code, client_email, client_name, amount, now),
            )
            conn.commit()
            self.update_earnings(affiliate_code, amount)
            return commission_id
        except Exception as e:
            logger.error("Failed to add commission: %s", e)
            return None

    def get_commissions(self, affiliate_code: str, limit: int = 50) -> list[dict[str, Any]]:
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT id, client_email, client_name, amount, status, created_at, paid_at "
                "FROM commissions WHERE affiliate_code = ? ORDER BY created_at DESC LIMIT ?",
                (affiliate_code, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to get commissions: %s", e)
            return []

    def get_all_commissions(self, limit: int = 100) -> list[dict[str, Any]]:
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT c.id, c.affiliate_code, a.name AS affiliate_name, "
                "c.client_email, c.client_name, c.amount, c.status, c.created_at, c.paid_at "
                "FROM commissions c LEFT JOIN affiliates a ON c.affiliate_code = a.code "
                "ORDER BY c.created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to get all commissions: %s", e)
            return []

    # ── Payouts ────────────────────────────────────────────────────────

    def create_payout(self, affiliate_code: str, amount: float) -> Optional[str]:
        payout_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC).isoformat()
        try:
            conn = self._conn()
            conn.execute(
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
        now = datetime.now(UTC).isoformat()
        try:
            conn = self._conn()
            row = conn.execute(
                "SELECT affiliate_code, amount FROM payouts WHERE id = ? AND status = 'pending'",
                (payout_id,),
            ).fetchone()
            if not row:
                return False
            conn.execute(
                "UPDATE payouts SET status = 'processed', processed_at = ? WHERE id = ?",
                (now, payout_id),
            )
            conn.execute(
                "UPDATE affiliates SET paid_earnings = paid_earnings + ? WHERE code = ?",
                (row["amount"], row["affiliate_code"]),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to process payout %s: %s", payout_id, e)
            return False

    def get_payouts(self, affiliate_code: Optional[str] = None,
                    limit: int = 50) -> list[dict[str, Any]]:
        try:
            conn = self._conn()
            if affiliate_code:
                rows = conn.execute(
                    "SELECT id, amount, status, created_at, processed_at "
                    "FROM payouts WHERE affiliate_code = ? ORDER BY created_at DESC LIMIT ?",
                    (affiliate_code, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT p.id, p.affiliate_code, a.name AS affiliate_name, "
                    "p.amount, p.status, p.created_at, p.processed_at "
                    "FROM payouts p LEFT JOIN affiliates a ON p.affiliate_code = a.code "
                    "ORDER BY p.created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to get payouts: %s", e)
            return []

    # ── Lead tracking ──────────────────────────────────────────────────

    def track_lead(self, ref_code: str, ip: str, user_agent: str,
                   landing_page: str) -> None:
        try:
            conn = self._conn()
            safe_ip = ip[:30].replace("<", "").replace(">", "").replace("&", "")
            safe_page = landing_page[:100].replace("<", "").replace(">", "").replace("&", "")
            conn.execute(
                """INSERT INTO affiliate_leads
                   (ref_code, lead_email, lead_name, status, created_at)
                   VALUES (?, ?, ?, 'lead', ?)""",
                (ref_code, f"lead@{safe_ip}", f"Lead from {safe_page}",
                 datetime.now(UTC).isoformat()),
            )
            conn.commit()
        except Exception as e:
            logger.warning("Failed to track lead for %s: %s", ref_code, e)

    def get_leads(self, affiliate_code: str, limit: int = 50) -> list[dict[str, Any]]:
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT id, lead_email, lead_name, status, commission, created_at "
                "FROM affiliate_leads WHERE ref_code = ? ORDER BY created_at DESC LIMIT ?",
                (affiliate_code, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to get leads: %s", e)
            return []

    def get_all_affiliates(self) -> list[dict[str, Any]]:
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT code, name, email, phone, total_earnings, paid_earnings, "
                "status, created_at, last_login FROM affiliates ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to get all affiliates: %s", e)
            return []
