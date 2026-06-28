"""Shopify OAuth 2.0, HMAC verification, session tokens, and shop data management.

Replaces core/auth.py as the primary authentication layer for Shopify App mode.
"""
import hashlib
import hmac
import logging
import os
import uuid
from base64 import b64encode
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import jwt
import requests
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes as cry_hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from flask import request

from core import database

logger = logging.getLogger(__name__)

SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY", "")
SHOPIFY_API_SECRET = os.getenv("SHOPIFY_API_SECRET", "")
SHOPIFY_APP_SCOPES = os.getenv(
    "SHOPIFY_APP_SCOPES",
    "read_products,write_products,read_orders,write_orders,"
    "read_customers,write_customers,read_inventory,write_inventory,"
    "read_marketing_events,write_marketing_events,"
    "read_discounts,write_discounts,read_fulfillments,write_fulfillments,"
    "read_online_store_pages,write_online_store_pages,"
    "read_online_store_navigation,write_online_store_navigation,"
    "read_reports,write_reports,read_themes,write_themes,"
    "read_analytics,read_content,write_content,read_files,write_files,"
    "read_price_rules,write_price_rules,read_shipping,write_shipping",
)
SHOPIFY_APP_HOME = os.getenv("SHOPIFY_APP_HOME", "https://lavaldigital.ca")
ADMIN_SHOP_DOMAIN = os.getenv("ADMIN_SHOP_DOMAIN", "").strip().lower()
SESSION_TOKEN_EXPIRY = timedelta(hours=2)


def _derive_fernet_key() -> Fernet:
    secret = os.getenv("FLASK_SECRET_KEY", "").encode()
    salt_str = os.getenv("CREDENTIAL_SALT")
    if salt_str:
        salt = salt_str.encode()[:16].ljust(16, b'\0')
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        kdf: Any = PBKDF2HMAC(algorithm=cry_hashes.SHA256(), length=32, salt=salt, iterations=100_000)
    else:
        kdf = HKDF(algorithm=cry_hashes.SHA256(), length=32, info=b"laval-shopify-token", salt=None)
    key = b64encode(kdf.derive(secret))
    return Fernet(key)


def _encrypt_token(plaintext: str) -> str:
    return _derive_fernet_key().encrypt(plaintext.encode()).decode()


def _decrypt_token(ciphertext: str) -> str:
    return _derive_fernet_key().decrypt(ciphertext.encode()).decode()


def validate_hmac(query_params: dict[str, str]) -> bool:
    """Validate HMAC from Shopify's OAuth redirect or App Proxy request."""
    hmac_param = query_params.pop("hmac", None)
    if not hmac_param:
        return False
    sorted_params = "&".join(
        f"{k}={v}" for k, v in sorted(query_params.items())
    )
    expected = hmac.new(
        SHOPIFY_API_SECRET.encode(),
        sorted_params.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, hmac_param)


def validate_hmac_from_request() -> bool:
    """Validate HMAC from current request querystring."""
    params = dict(request.args)
    return validate_hmac(params)


def build_install_url(shop: str, redirect_uri: str | None = None) -> str:
    """Build the Shopify OAuth install URL for a shop."""
    scopes = SHOPIFY_APP_SCOPES
    state = str(uuid.uuid4())
    base = f"https://{shop}/admin/oauth/authorize"
    params = {
        "client_id": SHOPIFY_API_KEY,
        "scope": scopes,
        "redirect_uri": redirect_uri or f"{SHOPIFY_APP_HOME}/api/auth/callback",
        "state": state,
    }
    return f"{base}?{urlencode(params)}"


def exchange_code_for_token(shop: str, code: str) -> dict[str, Any] | None:
    """Exchange the OAuth code for a permanent access token."""
    url = f"https://{shop}/admin/oauth/access_token"
    payload = {
        "client_id": SHOPIFY_API_KEY,
        "client_secret": SHOPIFY_API_SECRET,
        "code": code,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("Failed to exchange code for token for %s: %s", shop, e)
        return None


def get_shop_data(shop: str, access_token: str) -> dict[str, Any] | None:
    """Fetch shop info via Admin REST API."""
    url = f"https://{shop}/admin/api/2024-01/shop.json"
    headers = {"X-Shopify-Access-Token": access_token}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json().get("shop")
    except Exception as e:
        logger.error("Failed to fetch shop data for %s: %s", shop, e)
        return None


# ── Database helpers ──────────────────────────────────────────────


def ensure_shop_tables():
    """Create shops and webhook_events tables if they don't exist.

    NOTE: This mirrors the schema in database.py migration v10.
    Keep both in sync if columns change.
    """
    conn = database._get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            last_webhook_at TEXT
        );

        CREATE TABLE IF NOT EXISTS webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop TEXT NOT NULL,
            topic TEXT NOT NULL,
            body TEXT NOT NULL,
            received_at TEXT NOT NULL,
            processed INTEGER DEFAULT 0
        );
    """)
    conn.commit()


def _ensure_shop_user(shop: str) -> int:
    """Create or find an internal user record for this shop."""
    conn = database._get_conn()
    row = conn.execute("SELECT id FROM users WHERE email = ? AND role = 'shop'", (shop,)).fetchone()
    if row:
        return row["id"]
    from werkzeug.security import generate_password_hash
    import secrets
    now = datetime.now(UTC).isoformat()
    conn.execute("PRAGMA ignore_check_constraints = ON")
    cur = conn.execute(
        """INSERT INTO users (email, password_hash, role, display_name, created_at)
           VALUES (?, ?, 'shop', ?, ?)""",
        (shop, generate_password_hash(secrets.token_hex(32)), shop, now),
    )
    conn.execute("PRAGMA ignore_check_constraints = OFF")
    conn.commit()
    uid = cur.lastrowid
    if uid is None:
        raise RuntimeError("Failed to create shop user")
    _seed_shop_agent_configs(conn, uid)
    return uid


def _seed_shop_agent_configs(conn, user_id: int) -> None:
    """Seed default agent configs for a new shop."""
    from core.database import DEFAULT_AGENTS
    now = datetime.now(UTC).isoformat()
    for agent_id in DEFAULT_AGENTS:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO agent_configs
                   (user_id, agent_id, enabled, model, status, last_invoked)
                   VALUES (?, ?, 1, 'deepseek-chat', 'idle', ?)""",
                (user_id, agent_id, now),
            )
        except Exception as e:
            logger.warning("Failed to seed agent %s for shop user %d: %s", agent_id, user_id, e)
    conn.commit()


def register_shop(shop: str, access_token: str, scopes: str) -> int | None:
    """Insert or update a shop record, creating an internal user."""
    conn = database._get_conn()
    now = datetime.now(UTC).isoformat()
    try:
        user_id = _ensure_shop_user(shop)
        is_admin = 1 if ADMIN_SHOP_DOMAIN and shop == ADMIN_SHOP_DOMAIN else 0
        cur = conn.execute(
            """INSERT INTO shops (shop, access_token, user_id, scopes, installed_at, is_platform_admin)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(shop) DO UPDATE SET
                   access_token = excluded.access_token,
                   user_id = excluded.user_id,
                   scopes = excluded.scopes,
                   is_active = 1,
                   uninstalled_at = NULL,
                   is_platform_admin = MAX(is_platform_admin, excluded.is_platform_admin)""",
            (shop, _encrypt_token(access_token), user_id, scopes, now, is_admin),
        )
        conn.commit()
        return cur.lastrowid
    except Exception as e:
        logger.error("Failed to register shop %s: %s", shop, e)
        return None


def deactivate_shop(shop: str) -> None:
    """Mark a shop as uninstalled."""
    conn = database._get_conn()
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE shops SET is_active = 0, uninstalled_at = ? WHERE shop = ?",
        (now, shop),
    )
    conn.commit()


def get_shop_token(shop: str) -> str | None:
    """Get the decrypted access token for a shop."""
    conn = database._get_conn()
    row = conn.execute(
        "SELECT access_token FROM shops WHERE shop = ? AND is_active = 1",
        (shop,),
    ).fetchone()
    if row:
        try:
            return _decrypt_token(row["access_token"])
        except Exception as e:
            logger.error("Failed to decrypt token for %s: %s", shop, e)
    return None


def get_active_shops() -> list[dict[str, Any]]:
    """List all active shops."""
    conn = database._get_conn()
    rows = conn.execute(
        "SELECT * FROM shops WHERE is_active = 1 ORDER BY installed_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_shop_by_domain(shop: str) -> dict[str, Any] | None:
    """Get a shop by its domain."""
    conn = database._get_conn()
    row = conn.execute(
        "SELECT * FROM shops WHERE shop = ?", (shop,)
    ).fetchone()
    return dict(row) if row else None


# ── Session Token (JWT) helpers ─────────────────────────────────


def verify_session_token(token: str) -> dict[str, Any] | None:
    """Verify a Shopify session token (JWT) and return its payload."""
    try:
        payload = jwt.decode(
            token,
            SHOPIFY_API_SECRET,
            algorithms=["HS256"],
            options={"require": ["iss", "dest", "aud", "exp", "nbf", "iat"]},
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Expired session token")
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid session token: %s", e)
    return None


def get_current_shop_from_session() -> str | None:
    """Extract the shop domain from the current request's session token or querystring."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        payload = verify_session_token(token)
        if payload:
            shop = payload.get("dest", "").replace("https://", "")
            return shop

    shop = request.args.get("shop")
    if shop:
        return shop

    return None


# ── GraphQL helper ──────────────────────────────────────────────


def graphql(shop: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Execute a GraphQL query against the Shopify Admin API."""
    token = get_shop_token(shop)
    if not token:
        logger.warning("No token found for shop %s", shop)
        return None
    url = f"https://{shop}/admin/api/2024-01/graphql.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("GraphQL error for %s: %s", shop, e)
        return None


def rest_get(shop: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Execute a GET request against the Shopify Admin REST API."""
    token = get_shop_token(shop)
    if not token:
        return None
    url = f"https://{shop}/admin/api/2024-01/{path.lstrip('/')}"
    headers = {"X-Shopify-Access-Token": token}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("REST GET error for %s %s: %s", shop, path, e)
        return None


def rest_post(shop: str, path: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Execute a POST request against the Shopify Admin REST API."""
    token = get_shop_token(shop)
    if not token:
        return None
    url = f"https://{shop}/admin/api/2024-01/{path.lstrip('/')}"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("REST POST error for %s %s: %s", shop, path, e)
        return None


def rest_put(shop: str, path: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Execute a PUT request against the Shopify Admin REST API."""
    token = get_shop_token(shop)
    if not token:
        return None
    url = f"https://{shop}/admin/api/2024-01/{path.lstrip('/')}"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    try:
        resp = requests.put(url, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("REST PUT error for %s %s: %s", shop, path, e)
        return None
