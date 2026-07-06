"""Blueprint for Google Ads API endpoints (agency partnership model)."""
from __future__ import annotations

import logging

from flask import Blueprint, request
from flask_login import current_user

from core import database
from core.api_helpers import api_error, api_success
from core.app_state import get_current_user_id, safe_error, safe_int
from core.settings import GOOGLE_ADS_MCC_ID, google_ads_configured

logger = logging.getLogger(__name__)
ads_bp = Blueprint("ads", __name__)


def _require_auth():
    if not current_user.is_authenticated or current_user.role not in ("admin", "user"):
        return api_error("Authentication required", 401)
    return None


@ads_bp.route("/api/ads/health", methods=["GET"])
def api_ads_health():
    from core.ads_auth import ads_credential_health
    return api_success(ads_credential_health())


@ads_bp.route("/api/ads/connections", methods=["GET"])
def api_list_connections():
    auth_err = _require_auth()
    if auth_err:
        return auth_err
    uid = get_current_user_id()
    if not uid:
        return api_error("No user context", 400)
    connections = database.list_ad_connections(uid)
    return api_success({"connections": connections})


@ads_bp.route("/api/ads/discover", methods=["GET"])
def api_discover_accounts():
    if not google_ads_configured():
        return api_error("Google Ads not configured — set GOOGLE_ADS_* env vars", 400)
    from core.ads_auth import get_customer_details, list_accessible_customers
    accounts = list_accessible_customers()
    enriched = []
    for acct in accounts:
        details = get_customer_details(acct["customer_id"])
        if details:
            enriched.append(details)
        else:
            enriched.append(acct)
    return api_success({
        "accounts": enriched,
        "mcc_id": GOOGLE_ADS_MCC_ID,
    })


@ads_bp.route("/api/ads/connect", methods=["POST"])
def api_connect_account():
    auth_err = _require_auth()
    if auth_err:
        return auth_err
    uid = get_current_user_id()
    if not uid:
        return api_error("No user context", 400)
    data = request.get_json(silent=True) or {}
    customer_id = data.get("customer_id", "").strip()
    if not customer_id:
        return api_error("customer_id is required", 400)
    row_id = database.add_ad_connection(
        user_id=uid,
        platform="google_ads",
        customer_id=customer_id,
        account_name=data.get("account_name", ""),
        currency_code=data.get("currency_code", ""),
        time_zone=data.get("time_zone", ""),
    )
    if row_id:
        return api_success({"connection_id": row_id, "customer_id": customer_id})
    return api_error("Failed to connect account", 500)


@ads_bp.route("/api/ads/disconnect", methods=["POST"])
def api_disconnect_account():
    auth_err = _require_auth()
    if auth_err:
        return auth_err
    uid = get_current_user_id()
    if not uid:
        return api_error("No user context", 400)
    data = request.get_json(silent=True) or {}
    customer_id = data.get("customer_id", "").strip()
    if not customer_id:
        return api_error("customer_id is required", 400)
    ok = database.remove_ad_connection(user_id=uid, platform="google_ads", customer_id=customer_id)
    if ok:
        return api_success({"disconnected": customer_id})
    return api_error("Failed to disconnect account", 500)
