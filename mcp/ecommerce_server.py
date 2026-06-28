"""E-Commerce MCP Server — Shopify-native product, order, and customer management.

Uses the stored Shopify access token from the shop's OAuth flow instead of manual API keys.
"""
import logging
import re
from datetime import UTC, datetime
from typing import Any

import requests

from core.shopify_auth import graphql, rest_get, rest_put

from ._safe_url import _is_safe_url
from .base_server import MCPServer, _safe_error

logger = logging.getLogger(__name__)


class EcommerceMCPServer(MCPServer):
    """MCP Server for e-commerce — Shopify-native product, order, customer, and analytics management."""

    def __init__(self):
        super().__init__(
            name="ecommerce",
            description="E-commerce management — product optimization, customer analytics, pricing, Shopify integration"
        )

    def _register_tools(self) -> None:
        self.register_tool("get_themes", self.get_themes,
            "List Shopify themes and their assets")
        self.register_tool("update_theme_asset", self.update_theme_asset,
            "Create or update a theme asset (liquid, JSON, CSS, JS file)")
        self.register_tool("set_metafields", self.set_metafields,
            "Set metafields on any Shopify resource (product, variant, collection, page, etc.)")
        self.register_tool("update_seo_metadata", self.update_seo_metadata,
            "Update SEO title and description on products, collections, or pages")
        self.register_tool("list_discounts", self.list_discounts,
            "List all active discounts from Shopify")
        self.register_tool("create_discount_code", self.create_discount_code,
            "Create a percentage or fixed-amount discount code with optional start/end dates")
        self.register_tool("create_bogo_discount", self.create_bogo_discount,
            "Create a Buy X Get Y (BOGO) discount code")
        self.register_tool("create_automatic_discount", self.create_automatic_discount,
            "Create an automatic percentage or fixed-amount discount (no code needed)")
        self.register_tool("list_collections", self.list_collections,
            "List all collections (smart and manual) from Shopify")
        self.register_tool("create_smart_collection", self.create_smart_collection,
            "Create a smart collection with rules (tag, price, type, vendor conditions)")
        self.register_tool("create_manual_collection", self.create_manual_collection,
            "Create a manual collection and add products by ID")
        self.register_tool("update_collection_seo", self.update_collection_seo,
            "Update a collection's title, description, or SEO metadata")
        self.register_tool("get_product_catalog", self.get_product_catalog,
            "Fetch full product catalog from Shopify via GraphQL — variants, inventory, images, SEO, prices")
        self.register_tool("get_order_history", self.get_order_history,
            "Fetch order history from Shopify via GraphQL — line items, fulfillment, payment, customers")
        self.register_tool("get_customer_segments", self.get_customer_segments,
            "Fetch customer segments from Shopify via GraphQL — segment counts, customer breakdown")
        self.register_tool("manage_products", self.manage_products,
            "Add, update, and optimize product listings via Shopify Admin API")
        self.register_tool("track_inventory", self.track_inventory,
            "Calculate inventory health, turnover rates, and reorder recommendations from Shopify")
        self.register_tool("optimize_product_pages", self.optimize_product_pages,
            "Audit live product pages and score them on SEO and conversion factors")
        self.register_tool("manage_abandoned_carts", self.manage_abandoned_carts,
            "Generate recovery email sequences with timing and discount strategy")
        self.register_tool("generate_product_descriptions", self.generate_product_descriptions,
            "Generate optimized product titles, descriptions, and bullet points from features")
        self.register_tool("track_sales_metrics", self.track_sales_metrics,
            "Calculate revenue, AOV, conversion rate, LTV, and customer acquisition cost from Shopify")
        self.register_tool("create_promotions", self.create_promotions,
            "Design promotions with discount strategy, urgency mechanics, and projected ROI")
        self.register_tool("manage_reviews", self.manage_reviews,
            "Generate review request campaigns and response templates by sentiment")
        self.register_tool("analyze_customers", self.analyze_customers,
            "RFM analysis: segment customers by Recency, Frequency, and Monetary value from Shopify")
        self.register_tool("optimize_pricing", self.optimize_pricing,
            "Recommend pricing based on margins, competitor range, and psychological pricing")
        self.register_tool("create_product_bundle", self.create_product_bundle,
            "Create product bundles and cross-sell recommendations")
        self.register_tool("plan_seasonal_calendar", self.plan_seasonal_calendar,
            "Generate a seasonal marketing calendar with product recommendations")
        self.register_tool("analyze_shipping", self.analyze_shipping,
            "Shipping cost analysis and carrier recommendations for Canadian businesses")
        self.register_tool("configure_taxes", self.configure_taxes,
            "Canadian tax rate lookup by province with GST/HST/PST breakdown")
        self.register_tool("audit_store_health", self.audit_store_health,
            "Comprehensive store health audit across products, pages, and settings")

    def _get_shop(self, kwargs: dict) -> str | None:
        """Extract shop from tool kwargs."""
        return kwargs.get("shop") or kwargs.get("store")

    def _fetch_products(self, shop: str, limit: int = 50) -> list[dict]:
        """Fetch products from Shopify via GraphQL."""
        result = graphql(shop, """
            query($first: Int!) {
                products(first: $first) {
                    edges { node { id title handle status totalInventory availableForSale
                        variants(first: 5) { edges { node { id title price currencyCode inventoryQuantity } } }
                        images(first: 3) { edges { node { url } } }
                    } }
                }
            }
        """, {"first": limit})
        if not result:
            return []
        edges = result.get("data", {}).get("products", {}).get("edges", [])
        return [e["node"] for e in edges]

    def _fetch_orders(self, shop: str, limit: int = 50) -> list[dict]:
        """Fetch recent orders from Shopify via GraphQL."""
        result = graphql(shop, """
            query($first: Int!) {
                orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                    edges { node { id name totalPriceSet { shopMoney { amount currencyCode } }
                        createdAt displayFinancialStatus displayFulfillmentStatus email
                        customer { id displayName } lineItems(first: 10) { edges { node { title quantity } } } } }
                }
            }
        """, {"first": limit})
        if not result:
            return []
        edges = result.get("data", {}).get("orders", {}).get("edges", [])
        return [e["node"] for e in edges]

    # ------------------------------------------------------------------
    # GraphQL Data Access — Product Catalog, Orders, Customers
    # ------------------------------------------------------------------

    def get_product_catalog(self, **kwargs) -> dict[str, Any]:
        """Fetch full product catalog from Shopify via GraphQL."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        limit = min(kwargs.get("limit", 250), 250)
        result = graphql(shop, """
            query($first: Int!) {
                products(first: $first) {
                    edges { node {
                        id title handle descriptionHtml productType vendor
                        totalInventory availableForSale status
                        seo { title description }
                        onlineStorePreviewUrl
                        priceRangeV2 { minVariantPrice { amount currencyCode }
                                       maxVariantPrice { amount currencyCode } }
                        variants(first: 10) { edges { node {
                            id title sku price compareAtPrice currencyCode
                            inventoryQuantity inventoryItem { id tracked }
                        } } }
                        images(first: 5) { edges { node { url altText } } }
                        metafields(first: 20) { edges { node {
                            namespace key value type
                        } } }
                    } }
                }
            }
        """, {"first": limit})
        if not result:
            return {"success": False, "error": "GraphQL query failed or no token"}
        edges = result.get("data", {}).get("products", {}).get("edges", [])
        products = [e["node"] for e in edges]
        return {
            "success": True,
            "result": f"Fetched {len(products)} products",
            "total_count": len(products),
            "products": products,
        }

    def get_order_history(self, **kwargs) -> dict[str, Any]:
        """Fetch order history from Shopify via GraphQL."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        limit = min(kwargs.get("limit", 250), 250)
        result = graphql(shop, """
            query($first: Int!) {
                orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                    edges { node {
                        id name email phone
                        createdAt processedAt cancelledAt
                        displayFinancialStatus displayFulfillmentStatus
                        totalPriceSet { shopMoney { amount currencyCode } }
                        subtotalPriceSet { shopMoney { amount currencyCode } }
                        totalTaxSet { shopMoney { amount currencyCode } }
                        totalShippingPriceSet { shopMoney { amount currencyCode } }
                        customer { id displayName email }
                        shippingAddress { address1 city province country zip }
                        lineItems(first: 25) { edges { node {
                            title quantity variantTitle sku
                            originalTotalSet { shopMoney { amount currencyCode } }
                            product { id }
                        } } }
                        fulfillments(first: 10) { edges { node {
                            id status trackingCompany trackingNumbers
                        } } }
                        transactions(first: 10) { edges { node {
                            id kind status amountSet { shopMoney { amount currencyCode } }
                            gateway
                        } } }
                    } }
                }
            }
        """, {"first": limit})
        if not result:
            return {"success": False, "error": "GraphQL query failed or no token"}
        edges = result.get("data", {}).get("orders", {}).get("edges", [])
        orders = [e["node"] for e in edges]
        return {
            "success": True,
            "result": f"Fetched {len(orders)} orders",
            "total_count": len(orders),
            "orders": orders,
        }

    def get_customer_segments(self, **kwargs) -> dict[str, Any]:
        """Fetch customer segments from Shopify via GraphQL."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        limit = min(kwargs.get("limit", 50), 50)
        result = graphql(shop, """
            query($first: Int!) {
                customerSegments(first: $first) {
                    edges { node {
                        id name query
                        memberCount
                    } }
                }
                customers(first: 20) {
                    totalCount
                    edges { node {
                        id displayName email
                        numberOfOrders amountSpent { amount currencyCode }
                        createdAt
                    } }
                }
            }
        """, {"first": limit})
        if not result:
            return {"success": False, "error": "GraphQL query failed or no token"}
        segments_edges = result.get("data", {}).get("customerSegments", {}).get("edges", [])
        customers_edges = result.get("data", {}).get("customers", {}).get("edges", [])
        total_customers = result.get("data", {}).get("customers", {}).get("totalCount", 0)
        segments = [e["node"] for e in segments_edges]
        customers = [e["node"] for e in customers_edges]
        return {
            "success": True,
            "result": f"Fetched {len(segments)} segments, {total_customers} total customers",
            "segments": segments,
            "recent_customers": customers,
            "total_customers": total_customers,
        }

    # ------------------------------------------------------------------
    # Theme & Metafields — Shopify
    # ------------------------------------------------------------------

    def get_themes(self, **kwargs) -> dict[str, Any]:
        """List Shopify themes with their assets."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        themes = rest_get(shop, "themes.json")
        if not themes:
            return {"success": False, "error": "Failed to fetch themes"}
        return {"success": True, "result": f"Found {len(themes.get('themes', []))} themes",
                "themes": themes.get("themes", [])}

    def update_theme_asset(self, theme_id: str = "", asset_key: str = "",
                           value: str = "", **kwargs) -> dict[str, Any]:
        """Create or update a theme asset file (liquid, JSON, CSS, JS)."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        if not theme_id or not asset_key:
            return {"success": False, "error": "theme_id and asset_key are required"}
        payload = {"asset": {"key": asset_key, "value": value}}
        result = rest_put(shop, f"themes/{theme_id}/assets.json", payload)
        if not result:
            return {"success": False, "error": "Failed to update theme asset"}
        asset = result.get("asset", {})
        return {"success": True, "result": f"Asset '{asset_key}' updated",
                "asset": {"key": asset.get("key"), "size": asset.get("size")}}

    def set_metafields(self, owner_id: str = "", namespace: str = "custom",
                       key: str = "", value: str = "", type: str = "single_line_text_field",
                       **kwargs) -> dict[str, Any]:
        """Set a metafield on any Shopify resource via GraphQL."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        if not owner_id or not key:
            return {"success": False, "error": "owner_id and key are required"}
        result = graphql(shop, """
            mutation($input: [MetafieldsSetInput!]!) {
                metafieldsSet(metafields: $input) {
                    metafields { id namespace key value type ownerType }
                    userErrors { field message }
                }
            }
        """, {"input": [{
            "ownerId": owner_id,
            "namespace": namespace,
            "key": key,
            "value": value,
            "type": type,
        }]})
        if not result:
            return {"success": False, "error": "GraphQL mutation failed"}
        errors = result.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
        if errors:
            return {"success": False, "error": "; ".join(e["message"] for e in errors)}
        mf = result.get("data", {}).get("metafieldsSet", {}).get("metafields", [])
        return {"success": True, "result": f"Metafield '{namespace}.{key}' set",
                "metafields": mf}

    def update_seo_metadata(self, resource_type: str = "product", resource_id: str = "",
                            seo_title: str = "", seo_description: str = "",
                            **kwargs) -> dict[str, Any]:
        """Update SEO title and description on a product, collection, or page."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        if not resource_id:
            return {"success": False, "error": "resource_id is required"}
        mutations = {
            "product": ("productUpdate", "product", "ProductInput!"),
            "collection": ("collectionUpdate", "collection", "CollectionInput!"),
            "page": ("pageUpdate", "page", "PageInput!"),
        }
        entry = mutations.get(resource_type)
        if not entry:
            return {"success": False, "error": f"Unsupported resource_type: {resource_type}"}
        mutation_name, payload_key, input_type = entry
        seo_input = {}
        if seo_title:
            seo_input["title"] = seo_title
        if seo_description:
            seo_input["description"] = seo_description
        if not seo_input:
            return {"success": False, "error": "Provide at least seo_title or seo_description"}
        result = graphql(shop, f"""
            mutation($input: {input_type}) {{
                {mutation_name}(input: $input) {{
                    {payload_key} {{ id seo {{ title description }} }}
                    userErrors {{ field message }}
                }}
            }}
        """, {"input": {"id": resource_id, "seo": seo_input}})
        if not result:
            return {"success": False, "error": "GraphQL mutation failed"}
        errors = result.get("data", {}).get(mutation_name, {}).get("userErrors", [])
        if errors:
            return {"success": False, "error": "; ".join(e["message"] for e in errors)}
        updated = result.get("data", {}).get(mutation_name, {}).get(payload_key, {})
        return {"success": True, "result": f"SEO metadata updated on {resource_type}",
                "resource": updated}

    # ------------------------------------------------------------------
    # Discount & Pricing Rules — Shopify
    # ------------------------------------------------------------------

    def list_discounts(self, **kwargs) -> dict[str, Any]:
        """List all active discounts from Shopify."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        result = graphql(shop, """
            query($first: Int!) {
                discountNodes(first: $first) {
                    edges { node {
                        id
                        discount {
                            ... on DiscountCodeBasic { codes(first: 5) { edges { node { code } } }
                                title startsAt endsAt status
                                customerSelection { all }
                                appliesOn { ... on DiscountProducts { products(first: 5) { edges { node { id } } } } }
                                value { ... on DiscountPercentage { percentage } ... on DiscountAmount { amount { amount currencyCode } } }
                            }
                            ... on DiscountCodeBxgy { codes(first: 5) { edges { node { code } } }
                                title startsAt endsAt status
                                customerSelection { all }
                                value { ... on DiscountBuyXGetY { customerGets {
                                    quantity value { ... on DiscountOnQuantity { quantity { quantity } effect { ... on DiscountPercentage { percentage } } } }
                                } } }
                            }
                            ... on DiscountAutomaticBasic { title startsAt endsAt status
                                value { ... on DiscountPercentage { percentage } ... on DiscountAmount { amount { amount currencyCode } } }
                            }
                        }
                    } }
                }
            }
        """, {"first": min(kwargs.get("limit", 50), 100)})
        if not result:
            return {"success": False, "error": "GraphQL query failed"}
        edges = result.get("data", {}).get("discountNodes", {}).get("edges", [])
        discounts = []
        for e in edges:
            node = e["node"]
            disc = node.get("discount", {})
            entry = {"id": node["id"], "title": disc.get("title", ""),
                     "status": disc.get("status", ""), "starts_at": disc.get("startsAt"),
                     "ends_at": disc.get("endsAt")}
            codes = disc.get("codes", {}).get("edges", [])
            if codes:
                entry["codes"] = [c["node"]["code"] for c in codes]
            discounts.append(entry)
        return {"success": True, "result": f"Found {len(discounts)} active discounts",
                "discounts": discounts}

    def create_discount_code(self, title: str = "", code: str = "",
                              discount_type: str = "percentage", value: float = 10.0,
                              starts_at: str = "", ends_at: str = "",
                              applies_to_product_ids: str = "", **kwargs) -> dict[str, Any]:
        """Create a percentage or fixed-amount discount code."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        if not title:
            return {"success": False, "error": "title is required"}
        if not code:
            import secrets
            code = title.upper().replace(" ", "")[:20] + secrets.token_hex(3).upper()
        mutation = "discountCodeBasicCreate"
        input_type = "DiscountCodeBasicInput!"
        if discount_type == "percentage":
            discount_value = {"percentage": value / 100}
        elif discount_type == "fixed":
            discount_value = {"amount": {"amount": value, "currencyCode": "CAD"}}
        else:
            return {"success": False, "error": f"Unsupported discount_type: {discount_type}"}
        gql_input = {
            "title": title,
            "code": code,
            "startsAt": starts_at or None,
            "endsAt": ends_at or None,
            "customerGets": {"value": {"discountOnQuantity": {
                "quantity": None,
                "effect": {"percentage": value / 100 if discount_type == "percentage" else 0},
            }}},
        }
        if discount_type == "percentage":
            gql_input["customerGets"]["value"] = {"discountOnQuantity": {
                "quantity": None, "effect": {"percentage": value / 100}
            }}
        else:
            gql_input["customerGets"]["value"] = {"discountAmount": {"amount": value, "appliesOnEachItem": False}}

        result = graphql(shop, f"""
            mutation($input: {input_type}) {{
                {mutation}(input: $input) {{
                    code {{
                        discountNode {{ id }}
                        codes(first: 1) {{ edges {{ node {{ code }} }} }}
                    }}
                    userErrors {{ field message }}
                }}
            }}
        """, {"input": {
            "title": title,
            "code": code,
            "startsAt": starts_at or None,
            "endsAt": ends_at or None,
            "customerGets": {
                "value": {
                    "discountAmount" if discount_type == "fixed" else "discountOnQuantity": {
                        "quantity": None,
                        "effect": {"percentage": value / 100} if discount_type == "percentage" else None,
                    } if discount_type == "percentage" else None,
                } if discount_type == "percentage" else {
                    "discountAmount": {"amount": value, "appliesOnEachItem": False}
                }
            },
        }})
        if not result:
            return {"success": False, "error": "GraphQL mutation failed"}
        errors = result.get("data", {}).get(mutation, {}).get("userErrors", [])
        if errors:
            return {"success": False, "error": "; ".join(e["message"] for e in errors)}
        discount_node = result.get("data", {}).get(mutation, {}).get("code", {}).get("discountNode", {})
        return {"success": True, "result": f"Discount '{code}' created ({value}{'%' if discount_type == 'percentage' else '$'})",
                "discount_id": discount_node.get("id"), "code": code}

    def create_bogo_discount(self, title: str = "", code: str = "",
                              customer_gets_qty: int = 1, customer_gets_discount_pct: float = 100.0,
                              customer_buys_qty: int = 1, starts_at: str = "", ends_at: str = "",
                              **kwargs) -> dict[str, Any]:
        """Create a Buy X Get Y (BOGO) discount code."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        if not title:
            return {"success": False, "error": "title is required"}
        if not code:
            import secrets
            code = "BOGO" + secrets.token_hex(3).upper()
        result = graphql(shop, """
            mutation($input: DiscountCodeBxgyInput!) {
                discountCodeBxgyCreate(input: $input) {
                    codeNode { id }
                    userErrors { field message }
                }
            }
        """, {"input": {
            "title": title,
            "code": code,
            "startsAt": starts_at or None,
            "endsAt": ends_at or None,
            "customerBuys": {"quantity": customer_buys_qty},
            "customerGets": {
                "quantity": customer_gets_qty,
                "value": {"discountOnQuantity": {
                    "quantity": customer_gets_qty,
                    "effect": {"percentage": customer_gets_discount_pct / 100},
                }},
            },
        }})
        if not result:
            return {"success": False, "error": "GraphQL mutation failed"}
        errors = result.get("data", {}).get("discountCodeBxgyCreate", {}).get("userErrors", [])
        if errors:
            return {"success": False, "error": "; ".join(e["message"] for e in errors)}
        node = result.get("data", {}).get("discountCodeBxgyCreate", {}).get("codeNode", {})
        return {"success": True, "result": f"BOGO discount '{code}' created (buy {customer_buys_qty}, get {customer_gets_qty} at {customer_gets_discount_pct:.0f}% off)",
                "discount_id": node.get("id"), "code": code}

    def create_automatic_discount(self, title: str = "",
                                  discount_type: str = "percentage", value: float = 10.0,
                                  starts_at: str = "", ends_at: str = "",
                                  **kwargs) -> dict[str, Any]:
        """Create an automatic percentage or fixed-amount discount (no code needed)."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        if not title:
            return {"success": False, "error": "title is required"}
        mutation = "discountAutomaticBasicCreate"
        input_type = "DiscountAutomaticBasicInput!"
        result = graphql(shop, f"""
            mutation($input: {input_type}) {{
                {mutation}(input: $input) {{
                    automaticDiscountNode {{ id }}
                    userErrors {{ field message }}
                }}
            }}
        """, {"input": {
            "title": title,
            "startsAt": starts_at or None,
            "endsAt": ends_at or None,
            "customerGets": {"value": {
                "discountOnQuantity": {"quantity": None, "effect": {"percentage": value / 100}}
            }},
        }})
        if not result:
            return {"success": False, "error": "GraphQL mutation failed"}
        errors = result.get("data", {}).get(mutation, {}).get("userErrors", [])
        if errors:
            return {"success": False, "error": "; ".join(e["message"] for e in errors)}
        node = result.get("data", {}).get(mutation, {}).get("automaticDiscountNode", {})
        return {"success": True, "result": f"Automatic discount '{title}' created ({value}{'%' if discount_type == 'percentage' else '$'})",
                "discount_id": node.get("id")}

    # ------------------------------------------------------------------
    # Collection Management — Shopify
    # ------------------------------------------------------------------

    def list_collections(self, **kwargs) -> dict[str, Any]:
        """List all collections (smart and manual) from Shopify."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        result = graphql(shop, """
            query($first: Int!) {
                collections(first: $first) {
                    edges { node {
                        id title handle description
                        collectionType
                        updatedAt
                        productsCount { count }
                        ruleSet { appliedDisjunctively rules { column relation condition } }
                        seo { title description }
                    } }
                }
            }
        """, {"first": min(kwargs.get("limit", 50), 100)})
        if not result:
            return {"success": False, "error": "GraphQL query failed"}
        edges = result.get("data", {}).get("collections", {}).get("edges", [])
        collections = [e["node"] for e in edges]
        return {"success": True, "result": f"Found {len(collections)} collections",
                "collections": collections}

    def create_smart_collection(self, title: str = "", description: str = "",
                                 rule_column: str = "TAG", rule_relation: str = "EQUALS",
                                 rule_condition: str = "", combine_with: str = "AND",
                                 **kwargs) -> dict[str, Any]:
        """Create a smart collection with automatic product rules."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        if not title:
            return {"success": False, "error": "title is required"}
        if not rule_condition:
            return {"success": False, "error": "rule_condition is required"}
        result = graphql(shop, """
            mutation($input: CollectionInput!) {
                collectionCreate(input: $input) {
                    collection { id title handle collectionType productsCount { count } }
                    userErrors { field message }
                }
            }
        """, {"input": {
            "title": title,
            "descriptionHtml": description or "",
            "ruleSet": {
                "appliedDisjunctively": combine_with.upper() == "OR",
                "rules": [{"column": rule_column.upper(), "relation": rule_relation.upper(), "condition": rule_condition}],
            },
            "sortOrder": "ALPHA_ASC",
        }})
        if not result:
            return {"success": False, "error": "GraphQL mutation failed"}
        errors = result.get("data", {}).get("collectionCreate", {}).get("userErrors", [])
        if errors:
            return {"success": False, "error": "; ".join(e["message"] for e in errors)}
        col = result.get("data", {}).get("collectionCreate", {}).get("collection", {})
        return {"success": True, "result": f"Smart collection '{title}' created",
                "collection": col}

    def create_manual_collection(self, title: str = "", description: str = "",
                                  product_ids: str = "", **kwargs) -> dict[str, Any]:
        """Create a manual collection and add products by ID."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        if not title:
            return {"success": False, "error": "title is required"}
        # Create the collection first (no ruleSet = manual)
        result = graphql(shop, """
            mutation($input: CollectionInput!) {
                collectionCreate(input: $input) {
                    collection { id title handle }
                    userErrors { field message }
                }
            }
        """, {"input": {"title": title, "descriptionHtml": description or "",
                        "sortOrder": "ALPHA_ASC"}})
        if not result:
            return {"success": False, "error": "GraphQL mutation failed"}
        errors = result.get("data", {}).get("collectionCreate", {}).get("userErrors", [])
        if errors:
            return {"success": False, "error": "; ".join(e["message"] for e in errors)}
        col = result.get("data", {}).get("collectionCreate", {}).get("collection", {})
        col_id = col.get("id", "")
        # Add products if provided
        ids = [p.strip() for p in product_ids.split(",") if p.strip()] if product_ids else []
        added = []
        if col_id and ids:
            add_result = graphql(shop, """
                mutation($collectionId: ID!, $productIds: [ID!]!) {
                    collectionAddProductsV2(id: $collectionId, productIds: $productIds) {
                        job { id }
                        userErrors { field message }
                    }
                }
            """, {"collectionId": col_id, "productIds": ids})
            if add_result:
                add_errors = add_result.get("data", {}).get("collectionAddProductsV2", {}).get("userErrors", [])
                if not add_errors:
                    added = ids
        return {"success": True, "result": f"Manual collection '{title}' created with {len(added)} products",
                "collection": col, "products_added": added}

    def update_collection_seo(self, collection_id: str = "",
                               title: str = "", description: str = "",
                               seo_title: str = "", seo_description: str = "",
                               **kwargs) -> dict[str, Any]:
        """Update a collection's title, description, or SEO metadata."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}
        if not collection_id:
            return {"success": False, "error": "collection_id is required"}
        input_data: dict[str, Any] = {"id": collection_id}
        if title: input_data["title"] = title
        if description: input_data["descriptionHtml"] = description
        seo = {}
        if seo_title: seo["title"] = seo_title
        if seo_description: seo["description"] = seo_description
        if seo: input_data["seo"] = seo
        result = graphql(shop, """
            mutation($input: CollectionInput!) {
                collectionUpdate(input: $input) {
                    collection { id title handle collectionType seo { title description } }
                    userErrors { field message }
                }
            }
        """, {"input": input_data})
        if not result:
            return {"success": False, "error": "GraphQL mutation failed"}
        errors = result.get("data", {}).get("collectionUpdate", {}).get("userErrors", [])
        if errors:
            return {"success": False, "error": "; ".join(e["message"] for e in errors)}
        col = result.get("data", {}).get("collectionUpdate", {}).get("collection", {})
        return {"success": True, "result": f"Collection '{col.get('title', collection_id)}' updated",
                "collection": col}

    # ------------------------------------------------------------------
    # Product Management — Shopify-native
    # ------------------------------------------------------------------

    def manage_products(self, product_name: str = "", action: str = "add", price: float = 0.0,
                        **kwargs) -> dict[str, Any]:
        """Add or update a product on Shopify using the stored OAuth token."""
        shop = self._get_shop(kwargs)
        product = {
            "name": product_name or "New Product",
            "price": price,
            "status": "draft" if action == "add" else "updated",
            "platform": "shopify",
            "optimization_score": 0,
        }

        score = 0
        checks = []
        if product_name and len(product_name) > 10:
            score += 20; checks.append("Good product name length")
        else:
            checks.append("Product name too short — aim for 10+ characters")
        if price > 0:
            score += 15; checks.append("Price set")
        else:
            checks.append("No price set")
        if kwargs.get("description") and len(kwargs.get("description", "")) > 100:
            score += 25; checks.append("Good description length")
        else:
            checks.append("Add a detailed product description (100+ words)")
        if kwargs.get("images"): score += 20; checks.append("Images included")
        else: checks.append("Add at least 3-5 high-quality product images")
        if kwargs.get("sku"): score += 10; checks.append("SKU assigned")
        else: checks.append("Assign a unique SKU for inventory tracking")
        if kwargs.get("category"): score += 10; checks.append("Category assigned")
        else: checks.append("Assign to at least one category/collection")

        product["optimization_score"] = score
        product["checks"] = checks

        if shop and action == "add":
            result = graphql(shop, """
                mutation($input: ProductInput!) {
                    productCreate(input: $input) {
                        product { id title }
                        userErrors { field message }
                    }
                }
            """, {
                "input": {
                    "title": product_name,
                    "descriptionHtml": kwargs.get("description", ""),
                    "vendor": kwargs.get("vendor", ""),
                    "productType": kwargs.get("category", ""),
                    "status": "DRAFT",
                    "variants": [{"price": str(price), "sku": kwargs.get("sku", "")}],
                }
            })
            if result:
                created = result.get("data", {}).get("productCreate", {}).get("product")
                errors = result.get("data", {}).get("productCreate", {}).get("userErrors", [])
                if created:
                    product["platform_id"] = created["id"]
                    product["platform_status"] = "Created on Shopify via GraphQL"
                if errors:
                    product["platform_error"] = "; ".join(e["message"] for e in errors)

        return {"success": True, "result": f"Product '{product_name}' {action}ed (score: {score}/100)", "product": product}

    # ------------------------------------------------------------------
    # Inventory — Shopify-native
    # ------------------------------------------------------------------

    def track_inventory(self, **kwargs) -> dict[str, Any]:
        """Calculate inventory health metrics from Shopify product data."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}

        products = self._fetch_products(shop)
        if not products:
            return {"success": True, "result": "No products found in Shopify store",
                    "metrics": {"total_products": 0}}

        low_stock_threshold = kwargs.get("low_stock_threshold", 10)
        analysis = []
        total_value = 0
        low_stock = []
        overstock = []
        out_of_stock = []

        for p in products:
            qty = p.get("totalInventory", 0)
            price = 0
            variants = p.get("variants", {}).get("edges", [])
            if variants:
                price = float(variants[0]["node"].get("price", 0))
            value = qty * price
            total_value += value

            status = "healthy"
            if qty == 0: status = "out_of_stock"; out_of_stock.append(p.get("title", "Unknown"))
            elif qty <= low_stock_threshold: status = "low_stock"; low_stock.append({"name": p.get("title", "Unknown"), "quantity": qty, "reorder": max(int(qty * 2), 10)})
            elif qty > 100: status = "overstock"; overstock.append(p.get("title", "Unknown"))

            analysis.append({"name": p.get("title", "Unknown"), "quantity": qty, "value": value, "status": status})

        return {"success": True, "result": f"Inventory: {len(low_stock)} low, {len(out_of_stock)} OOS, {len(overstock)} overstock",
                "total_inventory_value": round(total_value, 2), "product_count": len(products),
                "low_stock_items": low_stock, "out_of_stock": out_of_stock, "overstock_items": overstock}

    # ------------------------------------------------------------------
    # Product Page Optimization
    # ------------------------------------------------------------------

    def optimize_product_pages(self, product_url: str = "", **kwargs) -> dict[str, Any]:
        """Audit a live product page and score it on SEO and conversion factors."""
        url = product_url or kwargs.get("url", "")
        if not url:
            return {"success": True, "result": "Product page optimization checklist. Provide a URL to audit.",
                    "checklist": ["Title tag (50-60 chars)", "Meta description (150-160 chars)",
                                  "H1 tag (single, product name)", "Product images (5-7 high-quality)",
                                  "Price displayed prominently", "Add to Cart button above the fold",
                                  "Product description 300+ words", "Bullet points (3-5)",
                                  "Customer reviews visible", "Trust badges", "Related products",
                                  "FAQ section", "Schema markup"]}

        if not url.startswith('http'): url = 'https://' + url
        if not _is_safe_url(url):
            return {"success": False, "error": "Blocked request to private IP"}
        try:
            resp = requests.get(url, headers={'User-Agent': 'AI-Ecom/1.0'}, timeout=10, allow_redirects=False)
            content = resp.text
            score = 0; checks = []

            title_m = re.search(r'<title>(.*?)</title>', content, re.I | re.S)
            if title_m and 30 <= len(title_m.group(1).strip()) <= 70:
                score += 15; checks.append({"check": "Title", "status": "pass"})
            else: checks.append({"check": "Title", "status": "fail"})

            if re.search(r'<h1[^>]*>', content) and len(re.findall(r'<h1[^>]*>', content)) == 1:
                score += 10; checks.append({"check": "H1", "status": "pass"})
            else: checks.append({"check": "H1", "status": "fail"})

            images = len(re.findall(r'<img[^>]+src=', content, re.I))
            if images >= 3: score += 15; checks.append({"check": "Images", "status": "pass", "detail": f"{images}"})
            else: checks.append({"check": "Images", "status": "fail", "detail": f"{images}"})

            if re.search(r'(?i)(add.to.cart|buy.now)', content): score += 15; checks.append({"check": "Add to Cart", "status": "pass"})
            else: checks.append({"check": "Add to Cart", "status": "fail"})

            if 'application/ld+json' in content: score += 10; checks.append({"check": "Schema", "status": "pass"})
            else: checks.append({"check": "Schema", "status": "fail"})

            if re.search(r'(?i)(review|rating)', content): score += 10; checks.append({"check": "Reviews", "status": "pass"})
            else: checks.append({"check": "Reviews", "status": "fail"})

            return {"success": True, "result": f"Product page score: {score}/100", "url": url, "score": score, "checks": checks}
        except Exception as e:
            return {"success": False, "error": f"Failed to audit: {_safe_error(e)}"}

    # ------------------------------------------------------------------
    # Sales Metrics — Shopify-native
    # ------------------------------------------------------------------

    def track_sales_metrics(self, **kwargs) -> dict[str, Any]:
        """Calculate sales metrics from Shopify order data."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}

        orders = self._fetch_orders(shop, 200)
        if not orders:
            return {"success": True, "result": "No orders found",
                    "metrics_available": ["total_revenue", "aov", "ltv", "cac", "repeat_rate"]}

        total_revenue = 0
        customers: dict[str, dict] = {}
        products: dict[str, int] = {}

        for o in orders:
            amount = float(o.get("totalPriceSet", {}).get("shopMoney", {}).get("amount", 0))
            total_revenue += amount
            email = o.get("email", "unknown")
            if email not in customers:
                customers[email] = {"orders": 0, "total_spent": 0, "name": o.get("customer", {}).get("displayName", "")}
            customers[email]["orders"] += 1
            customers[email]["total_spent"] += amount

            for item in o.get("lineItems", {}).get("edges", []):
                title = item["node"]["title"]
                products[title] = products.get(title, 0) + item["node"].get("quantity", 1)

        aov = total_revenue / len(orders) if orders else 0
        repeat = sum(1 for c in customers.values() if c["orders"] > 1)
        repeat_rate = (repeat / len(customers) * 100) if customers else 0
        top_products = sorted(products.items(), key=lambda x: x[1], reverse=True)[:5]

        return {"success": True, "result": f"Sales: ${total_revenue:.2f} rev, {len(orders)} orders, AOV ${aov:.2f}",
                "total_revenue": round(total_revenue, 2), "order_count": len(orders), "aov": round(aov, 2),
                "unique_customers": len(customers), "repeat_purchase_rate": round(repeat_rate, 1),
                "top_products": [{"name": p[0], "quantity": p[1]} for p in top_products]}

    # ------------------------------------------------------------------
    # Customer Analysis (RFM) — Shopify-native
    # ------------------------------------------------------------------

    def analyze_customers(self, **kwargs) -> dict[str, Any]:
        """RFM analysis from Shopify order data."""
        shop = self._get_shop(kwargs)
        if not shop:
            return {"success": False, "error": "Shop is required"}

        orders = self._fetch_orders(shop, 250)
        if not orders:
            return {"success": True, "result": "No order data for RFM analysis",
                    "segments": {"champions": "Reward and retain", "loyal": "Upsell and cross-sell",
                                 "at_risk": "Re-engage", "lost": "Win-back", "new": "Nurture"}}

        now = datetime.now(UTC)
        customers: dict[str, dict] = {}
        for o in orders:
            email = o.get("email", "unknown")
            amount = float(o.get("totalPriceSet", {}).get("shopMoney", {}).get("amount", 0))
            try: order_date = datetime.fromisoformat(o.get("createdAt", "").replace('Z', '+00:00'))
            except: order_date = now

            if email not in customers:
                customers[email] = {"orders": 0, "total_spent": 0, "last_order": order_date, "name": o.get("customer", {}).get("displayName", "")}
            customers[email]["orders"] += 1
            customers[email]["total_spent"] += amount
            if order_date > customers[email]["last_order"]: customers[email]["last_order"] = order_date

        segments: dict[str, list[str]] = {"champions": [], "loyal": [], "at_risk": [], "lost": [], "new": []}
        for email, data in customers.items():
            days_since = (now - data["last_order"]).days
            if days_since <= 30 and data["orders"] >= 3: segments["champions"].append(email)
            elif days_since <= 60 and data["orders"] >= 2: segments["loyal"].append(email)
            elif days_since > 60 and days_since <= 90: segments["at_risk"].append(email)
            elif days_since > 90: segments["lost"].append(email)
            else: segments["new"].append(email)

        return {"success": True, "result": f"Customer analysis: {len(customers)} customers segmented",
                "total_customers": len(customers), "segments": {k: len(v) for k, v in segments.items()},
                "recommendations": {"champions": "VIP program, early access", "loyal": "Cross-sell, bundles",
                                    "at_risk": "Re-engagement email", "lost": "Win-back campaign (20%+ off)",
                                    "new": "Welcome sequence"}}

    # ------------------------------------------------------------------
    # Abandoned Carts
    # ------------------------------------------------------------------

    def manage_abandoned_carts(self, cart_value: float = 0.0, **kwargs) -> dict[str, Any]:
        """Generate an abandoned cart recovery strategy."""
        if cart_value < 50:
            discount_tiers = [
                {"delay": "1 hour", "discount": "0%", "message": "Friendly reminder"},
                {"delay": "24 hours", "discount": "5%", "message": "Social proof + small nudge"},
                {"delay": "72 hours", "discount": "10%", "message": "Final offer with urgency"}
            ]
        elif cart_value < 150:
            discount_tiers = [
                {"delay": "1 hour", "discount": "0%", "message": "Reminder with cart contents"},
                {"delay": "24 hours", "discount": "10%", "message": "Testimonial + discount"},
                {"delay": "48 hours", "discount": "15%", "message": "Last chance countdown"}
            ]
        else:
            discount_tiers = [
                {"delay": "30 min", "discount": "0%", "message": "High-value cart follow-up"},
                {"delay": "6 hours", "discount": "10%", "message": "Personalized offer"},
                {"delay": "24 hours", "discount": "15%", "message": "Phone follow-up recommended"}
            ]

        return {"success": True, "result": f"Cart recovery for ${cart_value:.2f}",
                "recovery_sequence": discount_tiers, "expected_recovery_rate": "5-15%"}

    # ------------------------------------------------------------------
    # Product Descriptions
    # ------------------------------------------------------------------

    def generate_product_descriptions(self, product_name: str = "", features: str = "",
                                       benefits: str = "", **kwargs) -> dict[str, Any]:
        """Generate optimized product content from features and benefits."""
        feature_list = [f.strip() for f in features.split(',') if f.strip()]
        benefit_list = [b.strip() for b in benefits.split(',') if b.strip()]

        titles = []
        if product_name:
            titles.append(f"{product_name} — {feature_list[0] if feature_list else 'Premium'}")
            titles.append(f"{product_name} | {feature_list[0] if feature_list else ''} & {feature_list[1] if len(feature_list) > 1 else 'Quality'}")

        bullets = []
        for i, f in enumerate(feature_list[:6]):
            b = benefit_list[i] if i < len(benefit_list) else "Enhances your experience"
            bullets.append(f"• {f} — {b}")

        description = f"""**{product_name or 'Product'}**

{'. '.join(benefit_list[:2]) if benefit_list else 'Experience the difference today.'}

**Key Features:**
{chr(10).join(bullets[:4])}

**Why You'll Love It:**
{' '.join(benefit_list) if benefit_list else 'Built to exceed expectations.'}"""

        return {"success": True, "result": f"Generated content for '{product_name}'",
                "titles": titles, "bullets": bullets, "description": description.strip()}

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    def optimize_pricing(self, cost: float = 0.0, current_price: float = 0.0, competitor_price: float = 0.0, **kwargs) -> dict[str, Any]:
        if cost <= 0:
            return {"success": False, "error": "Cost is required"}
        margin_targets = {"minimum": round(cost * 1.3, 2), "healthy": round(cost * 2.0, 2), "premium": round(cost * 3.0, 2)}
        recommendations = []
        if current_price > 0:
            margin = ((current_price - cost) / current_price * 100)
            recommendations.append(f"Current margin: {margin:.0f}%")
            if margin < 40: recommendations.append("Raise price or reduce costs")
            elif margin > 70: recommendations.append("Healthy margin — focus on volume")
        if competitor_price > 0 and current_price > 0:
            if current_price > competitor_price: recommendations.append(f"Priced {((current_price/competitor_price)-1)*100:.0f}% above competitor")
            else: recommendations.append(f"Priced {((competitor_price/current_price)-1)*100:.0f}% below competitor")
        return {"success": True, "result": f"Pricing (cost: ${cost:.2f})", "margin_targets": margin_targets, "recommendations": recommendations}

    # ------------------------------------------------------------------
    # Bundles, Promotions, Reviews, Seasonal, Shipping, Taxes — unchanged helpers
    # ------------------------------------------------------------------

    def create_product_bundle(self, main_product: str = "", complementary_products: str = "", **kwargs) -> dict[str, Any]:
        comp_list = [c.strip() for c in complementary_products.split(',') if c.strip()]
        bundle = {"name": f"{main_product} Bundle", "main_product": main_product, "complementary": comp_list,
                  "suggested_discount": "10-15% off", "marketing_angle": "Save X% when you buy together",
                  "placement": ["Product page", "Cart page", "Post-purchase"]}
        return {"success": True, "result": f"Bundle: {bundle['name']} ({len(comp_list)} products)", "bundle": bundle}

    def create_promotions(self, promotion_type: str = "discount", discount_pct: int = 15, **kwargs) -> dict[str, Any]:
        return {"success": True, "result": f"{promotion_type.title()} ({discount_pct}% off)",
                "promotion": {"type": promotion_type, "discount": f"{discount_pct}%", "status": "draft"},
                "projected_uplift": f"{15 if promotion_type == 'flash_sale' else 10}% conversion rate"}

    def manage_reviews(self, action: str = "generate_request", **kwargs) -> dict[str, Any]:
        return {"success": True, "result": "Review strategy ready",
                "strategy": {"timing": "3-7 days after delivery", "channel": "Email + SMS for VIP",
                             "incentive": "Monthly draw for $50 gift card", "negative": "Respond within 24h"}}

    def plan_seasonal_calendar(self, year: int = 2026, **kwargs) -> dict[str, Any]:
        seasons = {"January": ["New Year", "Winter clearance", "Fitness"], "February": ["Valentine's Day", "Winter sale"],
                   "March": ["Spring preview", "St. Patrick's Day"], "April": ["Spring collection", "Easter"],
                   "May": ["Mother's Day", "Spring sale"], "June": ["Father's Day", "Summer launch"],
                   "July": ["Canada Day", "Summer sale"], "August": ["Back to school", "Fall preview"],
                   "September": ["Fall collection", "New arrivals"], "October": ["Thanksgiving (CA)", "Halloween"],
                   "November": ["Black Friday", "Cyber Monday"], "December": ["Holiday gifting", "Boxing Day"]}
        return {"success": True, "result": f"Seasonal calendar {year}", "calendar": seasons}

    def analyze_shipping(self, origin_province: str = "QC", **kwargs) -> dict[str, Any]:
        carriers = {"Canada Post": {"best_for": "Small packages, rural", "tracking": "Yes"},
                    "UPS": {"best_for": "Medium-large, US", "tracking": "Yes"},
                    "FedEx": {"best_for": "Express, international", "tracking": "Yes"},
                    "Purolator": {"best_for": "Canadian business", "tracking": "Yes"}}
        strategies = {"free_shipping": "Free over $75-$100 (AOV +15-30%)", "flat_rate": "$8.99-$14.99",
                      "real_time": "Carrier-calculated", "local": "Local delivery 25km radius"}
        return {"success": True, "result": "Shipping analysis (Canada)", "carriers": carriers, "strategies": strategies}

    def configure_taxes(self, province: str = "QC", **kwargs) -> dict[str, Any]:
        rates = {"AB": 5.0, "BC": 12.0, "MB": 12.0, "NB": 15.0, "NL": 15.0, "NS": 15.0, "ON": 13.0, "PE": 15.0, "QC": 14.975, "SK": 11.0}
        total = rates.get(province.upper(), 14.975)
        return {"success": True, "result": f"Tax rate for {province.upper()}: {total}%",
                "province": province.upper(), "total_tax": total}

    def audit_store_health(self, **kwargs) -> dict[str, Any]:
        checks = [
            {"category": "Products", "check": "Product count", "target": "10+ products", "priority": "high"},
            {"category": "Trust", "check": "Contact page", "target": "Phone, email, address", "priority": "critical"},
            {"category": "Conversion", "check": "Mobile experience", "target": "Responsive", "priority": "critical"},
            {"category": "Marketing", "check": "Email capture", "target": "Newsletter signup", "priority": "medium"},
        ]
        return {"success": True, "result": f"Store health: {len(checks)} checks", "checks": checks}
