"""Google Ads authentication and client management (agency partnership model).

We own the MCC + developer token. Shops add our MCC as a partner and we
access their accounts through our API credentials. No per-user OAuth needed.
"""
from __future__ import annotations

import logging
from typing import Any

from core.settings import GOOGLE_ADS_CONFIG, google_ads_configured

logger = logging.getLogger(__name__)

_ADS_API_VERSION = "v24"


def get_google_ads_client() -> Any | None:
    """Return a configured ``GoogleAdsClient`` or ``None`` if credentials missing."""
    if not google_ads_configured():
        logger.warning("Google Ads credentials not configured")
        return None
    try:
        from google.ads.googleads.client import GoogleAdsClient
        return GoogleAdsClient.load_from_dict(GOOGLE_ADS_CONFIG)
    except Exception as e:
        logger.error("Failed to create Google Ads client: %s", e, exc_info=True)
        return None


def get_google_ads_service(service_name: str):
    """Get a Google Ads API service by name (e.g. ``CustomerService``)."""
    client = get_google_ads_client()
    if client is None:
        return None
    try:
        return client.get_service(service_name, version=_ADS_API_VERSION)
    except Exception as e:
        logger.error("Failed to get service %s: %s", service_name, e, exc_info=True)
        return None


def list_accessible_customers() -> list[dict[str, Any]]:
    """List all customer accounts accessible under our MCC.

    Returns a list of dicts with customer_id and resource_name.
    Returns empty list on error.
    """
    service = get_google_ads_service("CustomerService")
    if service is None:
        return []
    try:
        response = service.list_accessible_customers()
        result: list[dict[str, Any]] = []
        for rn in response.resource_names:
            cid = rn.split("/")[-1]
            result.append({"customer_id": cid, "resource_name": rn})
        return result
    except Exception as e:
        logger.error("Failed to list accessible customers: %s", e, exc_info=True)
        return []


def get_customer_details(customer_id: str) -> dict[str, Any] | None:
    """Get details for a specific Google Ads customer account.

    Returns dict with name, currency_code, time_zone, can_manage_clients, etc.
    """
    client = get_google_ads_client()
    if client is None:
        return None
    try:
        ga_service = client.get_service("GoogleAdsService", version=_ADS_API_VERSION)
        query = (
            "SELECT customer.id, customer.descriptive_name, "
            "customer.currency_code, customer.time_zone, "
            "customer.can_manage_clients, customer.auto_tagging_enabled "
            "FROM customer"
        )
        stream = ga_service.search(customer_id=customer_id, query=query)
        for row in stream:
            c = row.customer
            return {
                "customer_id": customer_id,
                "descriptive_name": c.descriptive_name,
                "currency_code": c.currency_code,
                "time_zone": c.time_zone,
                "can_manage_clients": c.can_manage_clients,
                "auto_tagging_enabled": c.auto_tagging_enabled,
            }
        return {"customer_id": customer_id, "descriptive_name": f"Account {customer_id}"}
    except Exception as e:
        logger.error("Failed to get customer %s: %s", customer_id, e, exc_info=True)
        return None


def ads_credential_health() -> dict[str, object]:
    """Verify Google Ads credentials are functional.

    Returns a dict with status and detail.
    """
    result: dict[str, object] = {
        "service": "google_ads",
        "status": "ok",
        "detail": "",
    }
    if not google_ads_configured():
        result["status"] = "missing"
        result["detail"] = "Google Ads environment variables not set"
        return result
    try:
        accounts = list_accessible_customers()
        result["account_count"] = len(accounts)
        if not accounts:
            result["status"] = "no_accounts"
            result["detail"] = "Credentials work but no accessible customer accounts found"
        else:
            result["detail"] = f"Connected — {len(accounts)} account(s) accessible"
    except Exception as e:
        result["status"] = "error"
        result["detail"] = str(e)
    return result


def search_google_ads(customer_id: str, query: str) -> list[dict[str, Any]]:
    """Execute a GAQL query on a customer account. Returns list of row dicts."""
    client = get_google_ads_client()
    if client is None:
        return []
    try:
        ga_service = client.get_service("GoogleAdsService", version=_ADS_API_VERSION)
        stream = ga_service.search(customer_id=customer_id, query=query)
        results: list[dict[str, Any]] = []
        for row in stream:
            results.append(_row_to_dict(row))
        return results
    except Exception as e:
        logger.error("GAQL search failed for %s: %s", customer_id, e, exc_info=True)
        return []


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a Google Ads row to a plain dict."""
    result: dict[str, Any] = {}
    for field in row.DESCRIPTOR.fields:
        val = getattr(row, field.name)
        if hasattr(val, "DESCRIPTOR"):
            val = _row_to_dict(val)
        elif hasattr(val, "__iter__") and not isinstance(val, (str, bytes)):
            try:
                val = [str(v) for v in val]
            except TypeError:
                val = str(val)
        result[field.name] = val
    return result
