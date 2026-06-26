"""Shopify App blueprint — install, auth callback, webhooks, app proxy, embedded admin."""
import hashlib
import hmac
import json
import logging
from base64 import b64encode as _b64encode
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for

from core import database
from core.api_helpers import api_error, api_success
from core.shopify_auth import (
    SHOPIFY_API_KEY,
    SHOPIFY_API_SECRET,
    SHOPIFY_APP_HOME,
    SHOPIFY_APP_SCOPES,
    build_install_url,
    deactivate_shop,
    ensure_shop_tables,
    exchange_code_for_token,
    get_shop_by_domain,
    get_shop_data,
    get_shop_token,
    graphql,
    register_shop,
    validate_hmac,
)

logger = logging.getLogger(__name__)

shopify_bp = Blueprint("shopify", __name__, url_prefix="")


def _verify_webhook(request_obj) -> dict[str, Any] | None:
    """Verify and parse a Shopify webhook."""
    topic = request_obj.headers.get("X-Shopify-Topic", "")
    shop = request_obj.headers.get("X-Shopify-Shop-Domain", "")
    hmac_header = request_obj.headers.get("X-Shopify-Hmac-Sha256", "")
    body = request_obj.get_data(as_text=True)

    if not topic or not shop or not hmac_header:
        return None

    expected = hmac.new(
        SHOPIFY_API_SECRET.encode(), body.encode(), hashlib.sha256
    ).digest()
    expected_b64 = _b64encode(expected).decode()

    if not hmac.compare_digest(expected_b64, hmac_header):
        logger.warning("Webhook HMAC mismatch for %s topic %s", shop, topic)
        return None

    return {"topic": topic, "shop": shop, "body": body}


# ── App Installation & Auth ──────────────────────────────────────


@shopify_bp.route("/api/auth/install")
def install():
    """Step 1: Redirect merchant to Shopify OAuth."""
    shop = request.args.get("shop", "").strip().lower()
    if not shop or not shop.endswith(".myshopify.com"):
        return api_error("Invalid shop parameter", 400)
    redirect_uri = f"{SHOPIFY_APP_HOME}/api/auth/callback"
    install_url = build_install_url(shop, redirect_uri)
    return redirect(install_url)


@shopify_bp.route("/api/auth/callback")
def callback():
    """Step 2: Handle OAuth callback, exchange code for token, store shop."""
    query_params = dict(request.args)

    if not validate_hmac(query_params):
        return api_error("HMAC validation failed", 401)

    shop = query_params.get("shop", "").strip().lower()
    code = query_params.get("code", "")

    if not shop or not code:
        return api_error("Missing shop or code parameter", 400)

    token_data = exchange_code_for_token(shop, code)
    if not token_data:
        return api_error("Failed to exchange authorization code", 500)

    access_token = token_data.get("access_token", "")
    scopes = token_data.get("scope", SHOPIFY_APP_SCOPES)

    register_shop(shop, access_token, scopes)

    shop_info = get_shop_data(shop, access_token)
    if shop_info:
        conn = database._get_conn()
        conn.execute(
            """UPDATE shops SET
                name = ?, email = ?, domain = ?,
                province = ?, country = ?, currency = ?, plan_name = ?,
                myshopify_domain = ?
               WHERE shop = ?""",
            (
                shop_info.get("name"),
                shop_info.get("email"),
                shop_info.get("domain"),
                shop_info.get("province"),
                shop_info.get("country_code"),
                shop_info.get("currency"),
                shop_info.get("plan_display_name"),
                shop_info.get("myshopify_domain"),
                shop,
            ),
        )
        conn.commit()

    session["shop"] = shop
    session["access_token"] = access_token

    return redirect(url_for("shopify.admin_embedded"))


# ── Webhooks ─────────────────────────────────────────────────────


@shopify_bp.route("/api/webhooks", methods=["POST"])
def webhook_handler():
    """Unified webhook endpoint — verifies HMAC and dispatches by topic."""
    verified = _verify_webhook(request)
    if not verified:
        abort(401)

    topic = verified["topic"]
    shop = verified["shop"]
    body = verified["body"]
    now = datetime.now(UTC).isoformat()

    conn = database._get_conn()
    conn.execute(
        "INSERT INTO webhook_events (shop, topic, body, received_at) VALUES (?, ?, ?, ?)",
        (shop, topic, body, now),
    )
    conn.commit()

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = {}

    handler = _WEBHOOK_HANDLERS.get(topic)
    if handler:
        try:
            handler(shop, data)
        except Exception as e:
            logger.error("Webhook handler error for %s %s: %s", shop, topic, e)

    conn.execute(
        "UPDATE webhook_events SET processed = 1 WHERE shop = ? AND topic = ? AND received_at = ?",
        (shop, topic, now),
    )
    conn.commit()

    return "", 200


def _handle_app_uninstalled(shop: str, data: dict):
    """Clean up when a shop uninstalls the app."""
    logger.info("Shop %s uninstalled the app", shop)
    deactivate_shop(shop)


def _handle_shop_redact(shop: str, data: dict):
    """Delete all data for a shop (GDPR compliance)."""
    logger.info("Shop redact request for %s", shop)
    deactivate_shop(shop)
    conn = database._get_conn()
    conn.execute("DELETE FROM webhook_events WHERE shop = ?", (shop,))
    conn.commit()


def _handle_customers_redact(shop: str, data: dict):
    """Delete customer data (GDPR)."""
    customer_ids = data.get("customers_to_redact", [])
    logger.info("Customer redact for shop %s: %d customers", shop, len(customer_ids))


def _handle_customers_data_request(shop: str, data: dict):
    """Return customer data (GDPR)."""
    customer_ids = data.get("customers_to_request", [])
    logger.info("Customer data request for shop %s: %d customers", shop, len(customer_ids))


_WEBHOOK_HANDLERS = {
    "app/uninstalled": _handle_app_uninstalled,
    "shop/redact": _handle_shop_redact,
    "customers/redact": _handle_customers_redact,
    "customers/data_request": _handle_customers_data_request,
}


# ── Embedded Admin ───────────────────────────────────────────────


@shopify_bp.route("/admin")
def admin_embedded():
    """Serve the embedded Shopify admin via App Bridge.

    Sets shop in session so subsequent API calls can identify the tenant
    without exposing the OAuth token to client-side JS.
    """
    shop = request.args.get("shop", session.get("shop", ""))
    if not shop:
        return api_error("Shop parameter required", 400)

    session["shop"] = shop

    return render_template(
        "shopify/admin.html",
        shop=shop,
        api_key=SHOPIFY_API_KEY,
    )


# ── App Proxy Routes ─────────────────────────────────────────────


@shopify_bp.route("/apps/frankie")
@shopify_bp.route("/apps/frankie/<path:subpath>")
def app_proxy(subpath: str = ""):
    """App Proxy routes — served through Shopify's proxy on the shop's domain."""
    shop = request.args.get("shop", "")
    if not validate_hmac(dict(request.args)):
        return api_error("HMAC validation failed", 401)

    if subpath == "dashboard" or not subpath:
        return render_template("shopify/proxy_dashboard.html", shop=shop)
    elif subpath == "blog":
        return render_template("shopify/proxy_blog.html", shop=shop)
    elif subpath.startswith("blog/"):
        slug = subpath.split("/", 1)[1]
        return render_template("shopify/proxy_article.html", shop=shop, slug=slug)

    return jsonify({"error": "Not found"}), 404


# ── API endpoints for admin JS ────────────────────────────────────


@shopify_bp.route("/api/shopify/shop", methods=["GET"])
def api_shop_info():
    """Return current shop info for the admin UI."""
    shop = request.args.get("shop", session.get("shop", ""))
    if not shop:
        return api_error("No shop", 400)
    token = get_shop_token(shop)
    if not token:
        return api_error("Shop not installed", 404)
    shop_data = get_shop_by_domain(shop)
    if not shop_data:
        return api_error("Shop not found", 404)
    return api_success({
        "shop": shop_data["shop"],
        "name": shop_data.get("name", ""),
        "email": shop_data.get("email", ""),
        "domain": shop_data.get("domain", ""),
        "currency": shop_data.get("currency", ""),
        "plan": shop_data.get("plan_name", ""),
        "billing_plan": shop_data.get("billing_plan", "free"),
        "installed_at": shop_data.get("installed_at", ""),
    })


@shopify_bp.route("/api/shopify/products", methods=["GET"])
def api_products():
    """List products from the Shopify store via GraphQL."""
    shop = request.args.get("shop", session.get("shop", ""))
    if not shop:
        return api_error("No shop", 400)
    result = graphql(shop, """
        {
            products(first: 50) {
                edges {
                    node {
                        id
                        title
                        handle
                        status
                        totalInventory
                        availableForSale
                        variants(first: 5) {
                            edges { node { id title price currencyCode } }
                        }
                    }
                }
            }
        }
    """)
    if not result:
        return api_error("Failed to fetch products", 500)
    return api_success(result.get("data", {}).get("products", {}).get("edges", []))


@shopify_bp.route("/api/shopify/orders", methods=["GET"])
def api_orders():
    """List recent orders."""
    shop = request.args.get("shop", session.get("shop", ""))
    if not shop:
        return api_error("No shop", 400)
    result = graphql(shop, """
        {
            orders(first: 50, sortKey: CREATED_AT, reverse: true) {
                edges {
                    node {
                        id
                        name
                        totalPriceSet { shopMoney { amount currencyCode } }
                        createdAt
                        displayFinancialStatus
                        displayFulfillmentStatus
                        email
                        customer { id displayName }
                    }
                }
            }
        }
    """)
    if not result:
        return api_error("Failed to fetch orders", 500)
    return api_success(result.get("data", {}).get("orders", {}).get("edges", []))


# ── Billing API (Recurring Charges) ─────────────────────────────


@shopify_bp.route("/api/shopify/billing/create", methods=["POST"])
def create_billing_charge():
    """Create a recurring application charge for the shop."""
    shop = request.args.get("shop", session.get("shop", ""))
    token = get_shop_token(shop)
    if not token:
        return api_error("Shop not active", 400)

    data = request.json or {}
    plan = data.get("plan", "monthly")
    plans = {
        "monthly": {"name": "AI Marketing Monthly", "price": 59.99, "trial_days": 7},
        "yearly": {"name": "AI Marketing Yearly", "price": 599.99, "trial_days": 14},
    }
    selected = plans.get(plan, plans["monthly"])

    return_url = f"{SHOPIFY_APP_HOME}/api/shopify/billing/callback?shop={shop}"
    result = graphql(shop, """
        mutation($name: String!, $amount: Decimal!, $trialDays: Int!, $returnUrl: URL!) {
            appSubscriptionCreate(
                name: $name
                returnUrl: $returnUrl
                test: true
                lineItems: [{
                    plan: { appRecurringPricingDetails: { price: { amount: $amount, currencyCode: USD }, interval: EVERY_30_DAYS } }
                }]
            ) {
                appSubscription { id }
                confirmationUrl
                userErrors { field message }
            }
        }
    """, {
        "name": selected["name"],
        "amount": str(selected["price"]),
        "trialDays": selected["trial_days"],
        "returnUrl": return_url,
    })

    if not result:
        return api_error("Failed to create charge", 500)

    errors = result.get("data", {}).get("appSubscriptionCreate", {}).get("userErrors", [])
    if errors:
        return api_error("; ".join(e["message"] for e in errors), 400)

    confirmation_url = result.get("data", {}).get("appSubscriptionCreate", {}).get("confirmationUrl")
    return api_success({"confirmation_url": confirmation_url})


@shopify_bp.route("/api/shopify/billing/callback")
def billing_callback():
    """Handle the billing confirmation callback."""
    shop = request.args.get("shop", session.get("shop", ""))
    charge_id = request.args.get("charge_id", "")

    if shop and charge_id:
        conn = database._get_conn()
        conn.execute(
            "UPDATE shops SET billing_plan = 'monthly' WHERE shop = ?",
            (shop,),
        )
        conn.commit()

    return redirect(url_for("shopify.admin_embedded", shop=shop))


# ── Agent Name API ──────────────────────────────────────────────

_RESTRICTED_NAMES = [
    "jesus", "jesus christ", "christ", "christ jesus",
    "mary", "the virgin mary", "mary the virgin", "virgin mary",
    "the holy trinity", "holy trinity", "trinity",
    "god", "almighty", "savior", "saviour", "messiah",
    "the father", "the son", "the holy spirit", "holy spirit",
]


def _validate_agent_name(name: str) -> str | None:
    """Validate an agent name. Returns error message or None if valid."""
    name = name.strip()
    if not name:
        return "Name cannot be empty"
    if len(name) > 50:
        return "Name must be under 50 characters"
    lower = name.lower().strip()
    for restricted in _RESTRICTED_NAMES:
        if restricted in lower:
            return f"Name '{name}' contains a restricted word and cannot be used."
    if re.search(r'[<>{}]', name):
        return "Name contains invalid characters"
    return None


@shopify_bp.route("/api/shopify/agent-name", methods=["GET", "PUT"])
def api_agent_name():
    """Get or set the custom agent name for this shop."""
    shop = request.args.get("shop", session.get("shop", ""))
    if not shop:
        return api_error("No shop", 400)

    conn = database._get_conn()

    # Ensure column exists (migration safety)
    try:
        conn.execute("SELECT agent_name FROM shops LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE shops ADD COLUMN agent_name TEXT DEFAULT NULL")
        conn.commit()

    if request.method == "PUT":
        data = request.json or {}
        name = data.get("name", "").strip()
        error = _validate_agent_name(name)
        if error:
            return api_error(error, 400)
        conn.execute("UPDATE shops SET agent_name = ? WHERE shop = ?", (name, shop))
        conn.commit()
        return api_success({"name": name})

    row = conn.execute("SELECT agent_name FROM shops WHERE shop = ?", (shop,)).fetchone()
    current = row["agent_name"] if row and row["agent_name"] else None
    return api_success({"name": current})


# ── Register webhooks at install time ────────────────────────────


@shopify_bp.route("/api/shopify/register-webhooks", methods=["POST"])
def register_webhooks():
    """Register required webhooks for the current shop."""
    shop = request.args.get("shop", session.get("shop", ""))
    token = get_shop_token(shop)
    if not token:
        return api_error("Shop not active", 400)

    topics = [
        "app/uninstalled",
        "shop/redact",
        "customers/redact",
        "customers/data_request",
    ]

    results = []
    for topic in topics:
        result = graphql(shop, """
            mutation webhookSubscriptionCreate($topic: WebhookSubscriptionTopic!, $webhookSubscription: WebhookSubscriptionInput!) {
                webhookSubscriptionCreate(topic: $topic, webhookSubscription: $webhookSubscription) {
                    webhookSubscription { id }
                    userErrors { field message }
                }
            }
        """, {
            "topic": topic.upper().replace("/", "_"),
            "webhookSubscription": {
                "callbackUrl": f"{SHOPIFY_APP_HOME}/api/webhooks",
                "format": "JSON",
            },
        })
        results.append({"topic": topic, "result": result})

    return api_success({"results": results})
