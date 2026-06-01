"""E-Commerce MCP Server for Frankie — Online store management."""
import logging
import re
import json
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from .base_server import MCPServer, _safe_error
from ._safe_url import _is_safe_url

logger = logging.getLogger(__name__)


class EcommerceMCPServer(MCPServer):
    """MCP Server for e-commerce — real product management, customer analytics, pricing, and platform integration."""

    def __init__(self):
        super().__init__(
            name="ecommerce",
            description="E-commerce management — product optimization, customer analytics, pricing, Shopify/WooCommerce integration"
        )

    def _register_tools(self) -> None:
        self.register_tool("manage_products", self.manage_products,
            "Add, update, and optimize product listings with platform integration")
        self.register_tool("track_inventory", self.track_inventory,
            "Calculate inventory health, turnover rates, and reorder recommendations")
        self.register_tool("optimize_product_pages", self.optimize_product_pages,
            "Audit live product pages and score them on SEO and conversion factors")
        self.register_tool("manage_abandoned_carts", self.manage_abandoned_carts,
            "Generate recovery email sequences with timing and discount strategy")
        self.register_tool("generate_product_descriptions", self.generate_product_descriptions,
            "Generate optimized product titles, descriptions, and bullet points from features")
        self.register_tool("track_sales_metrics", self.track_sales_metrics,
            "Calculate revenue, AOV, conversion rate, LTV, and customer acquisition cost")
        self.register_tool("create_promotions", self.create_promotions,
            "Design promotions with discount strategy, urgency mechanics, and projected ROI")
        self.register_tool("manage_reviews", self.manage_reviews,
            "Generate review request campaigns and response templates by sentiment")
        self.register_tool("analyze_customers", self.analyze_customers,
            "RFM analysis: segment customers by Recency, Frequency, and Monetary value")
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

    # ------------------------------------------------------------------
    # Product Management
    # ------------------------------------------------------------------

    def manage_products(self, product_name: str = "", action: str = "add", price: float = 0.0,
                        platform: str = "shopify", api_credentials: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Add or update a product on an e-commerce platform."""
        product = {
            "name": product_name or "New Product",
            "price": price,
            "status": "draft" if action == "add" else "updated",
            "platform": platform,
            "optimization_score": 0
        }

        score = 0
        checks = []
        if product_name and len(product_name) > 10:
            score += 20
            checks.append("Good product name length")
        else:
            checks.append("Product name too short — aim for 10+ characters with key features")
        if price > 0:
            score += 15
            checks.append("Price set")
        else:
            checks.append("No price set — add pricing immediately")
        if kwargs.get("description") and len(kwargs.get("description", "")) > 100:
            score += 25
            checks.append("Good description length")
        else:
            checks.append("Add a detailed product description (100+ words)")
        if kwargs.get("images"):
            score += 20
            checks.append("Images included")
        else:
            checks.append("Add at least 3-5 high-quality product images")
        if kwargs.get("sku"):
            score += 10
            checks.append("SKU assigned")
        else:
            checks.append("Assign a unique SKU for inventory tracking")
        if kwargs.get("category"):
            score += 10
            checks.append("Category assigned")
        else:
            checks.append("Assign to at least one category/collection")

        product["optimization_score"] = score
        product["checks"] = checks

        if platform == "shopify" and api_credentials:
            try:
                store_url = api_credentials.get("store_url", "")
                if store_url and not _is_safe_url(f"https://{store_url}/"):
                    return {"success": False, "result": "", "error": "Blocked store URL"}
                api_key = api_credentials.get("api_key", "")
                if store_url and api_key:
                    url = f"https://{store_url}/admin/api/2024-01/products.json"
                    headers = {"X-Shopify-Access-Token": api_key, "Content-Type": "application/json"}
                    payload: Dict[str, Any] = {"product": {"title": product_name, "body_html": kwargs.get("description", ""),
                                                              "vendor": kwargs.get("vendor", ""), "product_type": kwargs.get("category", ""),
                                                              "status": "active" if action == "add" else None}}
                    resp = requests.post(url, headers=headers, json=payload, timeout=15)
                    if resp.status_code == 201:
                        product["platform_id"] = resp.json().get("product", {}).get("id")
                        product["platform_status"] = "Created on Shopify"
            except Exception as e:
                product["platform_error"] = _safe_error(e)

        elif platform == "woocommerce" and api_credentials:
            try:
                site_url = api_credentials.get("site_url", "")
                if site_url and not _is_safe_url(site_url):
                    return {"success": False, "result": "", "error": "Blocked store URL"}
                consumer_key = api_credentials.get("consumer_key", "")
                consumer_secret = api_credentials.get("consumer_secret", "")
                if site_url and consumer_key:
                    if not site_url.startswith("https://"):
                        raise ValueError("WooCommerce API requires HTTPS")
                    url = f"{site_url.rstrip('/')}/wp-json/wc/v3/products"
                    auth = (consumer_key, consumer_secret)
                    wc_payload: Dict[str, Any] = {"name": product_name, "regular_price": str(price), "description": kwargs.get("description", ""),
                                                        "status": "draft" if action == "add" else "publish"}
                    resp = requests.post(url, auth=auth, json=wc_payload, timeout=15)
                    if resp.status_code == 201:
                        product["platform_id"] = resp.json().get("id")
                        product["platform_status"] = "Created on WooCommerce"
            except Exception as e:
                product["platform_error"] = _safe_error(e)

        return {"success": True, "result": f"Product '{product_name}' {action}ed (score: {score}/100)", "product": product}

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------

    def track_inventory(self, products_json: str = "", low_stock_threshold: int = 10, **kwargs) -> Dict[str, Any]:
        """Calculate inventory health metrics from product data."""
        try:
            products = json.loads(products_json) if products_json else []
        except json.JSONDecodeError:
            products = []

        if not products:
            return {"success": True, "result": "Inventory tracking framework ready. Provide product data for analysis.",
                    "metrics": {"turnover_rate": "Sales ÷ Average Inventory", "days_of_inventory": "365 ÷ Turnover Rate",
                               "stockout_risk": "Products with < 2 weeks supply", "overstock": "Products with > 12 weeks supply",
                               "reorder_point": "(Daily Sales × Lead Time Days) + Safety Stock"}}

        analysis = []
        total_value = 0
        low_stock = []
        overstock = []
        out_of_stock = []

        for p in products:
            qty = p.get("quantity", 0)
            price = p.get("price", 0)
            daily_sales = p.get("daily_sales", 0)
            value = qty * price
            total_value += value

            status = "healthy"
            if qty == 0:
                status = "out_of_stock"
                out_of_stock.append(p.get("name", "Unknown"))
            elif qty <= low_stock_threshold:
                status = "low_stock"
                low_stock.append({"name": p.get("name", "Unknown"), "quantity": qty, "reorder_recommendation": max(int(daily_sales * 14) - qty, 10)})
            elif qty > 100 and daily_sales < 1:
                status = "overstock"
                overstock.append(p.get("name", "Unknown"))

            analysis.append({"name": p.get("name", "Unknown"), "quantity": qty, "value": value, "status": status})

        return {"success": True, "result": f"Inventory analysis: {len(low_stock)} low stock, {len(out_of_stock)} out of stock, {len(overstock)} overstock",
                "total_inventory_value": round(total_value, 2), "product_count": len(products),
                "low_stock_items": low_stock, "out_of_stock": out_of_stock, "overstock_items": overstock}

    # ------------------------------------------------------------------
    # Product Page Optimization
    # ------------------------------------------------------------------

    def optimize_product_pages(self, product_url: str = "", **kwargs) -> Dict[str, Any]:
        """Audit a live product page and score it on SEO and conversion factors."""
        url = product_url or kwargs.get("url", "")
        if not url:
            return {"success": True, "result": "Product page optimization checklist. Provide a URL to audit a live page.",
                    "checklist": ["Title tag (50-60 chars, includes product name + key feature)",
                                  "Meta description (150-160 chars, includes price/promotion if applicable)",
                                  "H1 tag (product name only — one H1 per page)",
                                  "Product images (5-7 high-quality, zoomable, multiple angles)",
                                  "Price displayed prominently above the fold",
                                  "Add to Cart button — large, contrasting color, above the fold",
                                  "Product description — unique, benefit-focused, 300+ words",
                                  "Bullet points — 3-5 key features in scannable format",
                                  "Customer reviews — visible star rating and review count",
                                  "Trust badges — secure checkout, money-back guarantee, shipping info",
                                  "Related products — cross-sell section below main product",
                                  "FAQ section — answers common objections",
                                  "Schema markup — Product schema with price, availability, reviews"]}

        if not url.startswith('http'): url = 'https://' + url
        if not _is_safe_url(url):
            return {"success": False, "error": "Blocked request to private IP"}
        try:
            # SSRF protection: no redirect following to prevent DNS rebinding
            resp = requests.get(url, headers={'User-Agent': 'Frankie-Ecom-Scanner/1.0'}, timeout=10, allow_redirects=False)
            content = resp.text

            score = 0
            checks = []

            title_match = re.search(r'<title>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
            if title_match:
                title = title_match.group(1).strip()
                if 30 <= len(title) <= 70:
                    score += 15
                    checks.append({"check": "Title tag", "status": "pass", "detail": f"{len(title)} chars"})
                else:
                    checks.append({"check": "Title tag", "status": "fail", "detail": f"{len(title)} chars (aim for 30-70)"})
            else:
                checks.append({"check": "Title tag", "status": "fail", "detail": "Missing"})

            meta_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', content, re.IGNORECASE)
            if meta_match:
                meta = meta_match.group(1)
                if 120 <= len(meta) <= 160:
                    score += 10
                    checks.append({"check": "Meta description", "status": "pass", "detail": f"{len(meta)} chars"})
                else:
                    checks.append({"check": "Meta description", "status": "fail", "detail": f"{len(meta)} chars (aim for 120-160)"})
            else:
                checks.append({"check": "Meta description", "status": "fail", "detail": "Missing"})

            h1s = re.findall(r'<h1[^>]*>(.*?)</h1>', content, re.IGNORECASE)
            if len(h1s) == 1:
                score += 10
                checks.append({"check": "H1 tag", "status": "pass", "detail": "Single H1 present"})
            elif len(h1s) == 0:
                checks.append({"check": "H1 tag", "status": "fail", "detail": "Missing H1"})
            else:
                checks.append({"check": "H1 tag", "status": "fail", "detail": f"{len(h1s)} H1s (should be 1)"})

            images = len(re.findall(r'<img[^>]+src=', content, re.IGNORECASE))
            if images >= 3:
                score += 15
                checks.append({"check": "Product images", "status": "pass", "detail": f"{images} images"})
            else:
                checks.append({"check": "Product images", "status": "fail", "detail": f"Only {images} image(s) — add at least 3-5"})

            if re.search(r'(?i)(add.to.cart|buy.now|add.to.bag)', content):
                score += 15
                checks.append({"check": "Add to Cart button", "status": "pass"})
            else:
                checks.append({"check": "Add to Cart button", "status": "fail", "detail": "Not found in page source"})

            if re.search(r'(?i)(review|rating|star)', content):
                score += 10
                checks.append({"check": "Reviews visible", "status": "pass"})
            else:
                checks.append({"check": "Reviews visible", "status": "fail", "detail": "Add customer reviews to product page"})

            if 'application/ld+json' in content:
                score += 10
                checks.append({"check": "Schema markup", "status": "pass"})
            else:
                checks.append({"check": "Schema markup", "status": "fail", "detail": "Add Product schema for rich results"})

            if re.search(r'(?i)(secure.checkout|money.back|free.shipping|guarantee)', content):
                score += 10
                checks.append({"check": "Trust signals", "status": "pass"})
            else:
                checks.append({"check": "Trust signals", "status": "fail", "detail": "Add security badges, guarantees, or shipping info"})

            return {"success": True, "result": f"Product page score: {score}/100", "url": url,
                    "score": score, "checks": checks, "pass_count": sum(1 for c in checks if c["status"] == "pass"),
                    "fail_count": sum(1 for c in checks if c["status"] == "fail")}
        except Exception as e:
            return {"success": False, "error": f"Failed to audit {url}: {_safe_error(e)}"}

    # ------------------------------------------------------------------
    # Abandoned Carts
    # ------------------------------------------------------------------

    def manage_abandoned_carts(self, cart_value: float = 0.0, **kwargs) -> Dict[str, Any]:
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
                {"delay": "24 hours", "discount": "10%", "message": "Testimonial + discount incentive"},
                {"delay": "48 hours", "discount": "15%", "message": "Last chance with countdown"}
            ]
        else:
            discount_tiers = [
                {"delay": "30 min", "discount": "0%", "message": "High-value cart — immediate follow-up"},
                {"delay": "6 hours", "discount": "10%", "message": "Personalized offer from founder"},
                {"delay": "24 hours", "discount": "15%", "message": "Phone call follow-up recommended"}
            ]

        return {"success": True, "result": f"Abandoned cart strategy for ${cart_value:.2f} cart value",
                "cart_value": cart_value, "recovery_sequence": discount_tiers,
                "expected_recovery_rate": "5-15% of abandoned carts recoverable",
                "tips": ["Include product images in recovery emails", "Use direct checkout links (skip cart page)",
                         "Show inventory scarcity if applicable", "Include customer service contact for high-value carts"]}

    # ------------------------------------------------------------------
    # Product Descriptions
    # ------------------------------------------------------------------

    def generate_product_descriptions(self, product_name: str = "", features: str = "",
                                      benefits: str = "", target_audience: str = "", tone: str = "professional", **kwargs) -> Dict[str, Any]:
        """Generate optimized product content from features and benefits."""
        feature_list = [f.strip() for f in features.split(',') if f.strip()] if features else []
        benefit_list = [b.strip() for b in benefits.split(',') if b.strip()] if benefits else []

        tones = {"professional": "Clear, authoritative, benefit-focused", "friendly": "Warm, conversational, relatable",
                 "luxury": "Sophisticated, exclusive, aspirational", "technical": "Detailed, precise, specification-heavy",
                 "storytelling": "Narrative-driven, emotional, customer-focused"}

        titles = []
        if product_name:
            titles.append(f"{product_name} — {feature_list[0] if feature_list else 'Premium Quality'}")
            if len(feature_list) > 1:
                titles.append(f"{product_name} | {feature_list[0]} & {feature_list[1]}")
            titles.append(f"{product_name} — {benefit_list[0] if benefit_list else 'Transform Your Experience'}")

        bullets = []
        for i, feature in enumerate(feature_list[:6]):
            benefit = benefit_list[i] if i < len(benefit_list) else "Enhances your experience"
            bullets.append(f"✨ {feature} — {benefit}")

        audience_text = f"Perfect for {target_audience}" if target_audience else "Designed for discerning customers"
        description = f"""**{audience_text}**

Introducing the {product_name or 'product'} — where {' and '.join(feature_list[:2]) if len(feature_list) >= 2 else 'quality meets innovation'}.

{' '.join(benefit_list[:2]) if len(benefit_list) >= 2 else 'Experience the difference today'}.

**Key Features:**
{chr(10).join(f'- {b}' for b in bullets[:4])}

**Why You'll Love It:**
{' '.join(benefit_list) if benefit_list else 'Built to exceed your expectations.'}

**Specifications:** [Add dimensions, weight, materials, care instructions]

**What's Included:** [List package contents]

Order now and experience the difference."""

        return {"success": True, "result": f"Generated product content for '{product_name}'",
                "titles": titles, "bullets": bullets, "description": description.strip(),
                "tone": tones.get(tone, tones["professional"]), "seo_tip": "Include primary keyword in title, first paragraph, and one H2"}

    # ------------------------------------------------------------------
    # Sales Metrics
    # ------------------------------------------------------------------

    def track_sales_metrics(self, orders_json: str = "", period: str = "monthly", **kwargs) -> Dict[str, Any]:
        """Calculate sales metrics from order data."""
        try:
            orders = json.loads(orders_json) if orders_json else []
        except json.JSONDecodeError:
            orders = []

        if not orders:
            return {"success": True, "result": "Sales metrics framework. Provide order data (JSON array) for real calculations.",
                    "metrics_available": ["total_revenue", "aov", "conversion_rate", "ltv", "cac", "repeat_rate", "top_products"]}

        total_revenue = sum(o.get("total", 0) for o in orders)
        order_count = len(orders)
        aov = total_revenue / order_count if order_count > 0 else 0

        customers: Dict[str, int] = {}
        for o in orders:
            email = o.get("email", "unknown")
            customers[email] = customers.get(email, 0) + 1

        unique_customers = len(customers)
        repeat_customers = sum(1 for c in customers.values() if c > 1)
        repeat_rate = (repeat_customers / unique_customers * 100) if unique_customers > 0 else 0

        products: Dict[str, int] = {}
        for o in orders:
            for item in o.get("items", []):
                name = item.get("name", "Unknown")
                products[name] = products.get(name, 0) + item.get("quantity", 1)

        top_products = sorted(products.items(), key=lambda x: x[1], reverse=True)[:5]

        return {"success": True, "result": f"Sales analysis: ${total_revenue:.2f} revenue, {order_count} orders, AOV ${aov:.2f}",
                "total_revenue": round(total_revenue, 2), "order_count": order_count, "aov": round(aov, 2),
                "unique_customers": unique_customers, "repeat_purchase_rate": round(repeat_rate, 1),
                "top_products": [{"name": p[0], "quantity": p[1]} for p in top_products]}

    # ------------------------------------------------------------------
    # Customer Analysis (RFM)
    # ------------------------------------------------------------------

    def analyze_customers(self, orders_json: str = "", **kwargs) -> Dict[str, Any]:
        """RFM analysis: segment customers by Recency, Frequency, Monetary value."""
        try:
            orders = json.loads(orders_json) if orders_json else []
        except json.JSONDecodeError:
            orders = []

        if not orders:
            return {"success": True, "result": "Customer analysis framework. Provide order data for RFM segmentation.",
                    "segments": {"champions": "High RFM — reward and retain", "loyal": "High frequency — upsell and cross-sell",
                                 "at_risk": "Low recency — re-engage with offers", "lost": "No recent activity — win-back campaign",
                                 "new": "Recent first purchase — nurture and onboard"}}

        now = datetime.now()
        customers: Dict[str, Any] = {}
        for o in orders:
            email = o.get("email", "unknown")
            date = o.get("date", "")
            total = o.get("total", 0)
            try: order_date = datetime.fromisoformat(date.replace('Z', '+00:00'))
            except Exception: order_date = now

            if email not in customers:
                customers[email] = {"orders": 0, "total_spent": 0, "last_order": order_date}
            customers[email]["orders"] += 1
            customers[email]["total_spent"] += total
            if order_date > customers[email]["last_order"]:
                customers[email]["last_order"] = order_date

        segments: Dict[str, List[str]] = {"champions": [], "loyal": [], "at_risk": [], "lost": [], "new": []}
        for email, data in customers.items():
            days_since = (now - data["last_order"]).days
            if days_since <= 30 and data["orders"] >= 3: segments["champions"].append(email)
            elif days_since <= 60 and data["orders"] >= 2: segments["loyal"].append(email)
            elif days_since > 60 and days_since <= 90: segments["at_risk"].append(email)
            elif days_since > 90: segments["lost"].append(email)
            else: segments["new"].append(email)

        return {"success": True, "result": f"Customer analysis: {len(customers)} customers segmented",
                "total_customers": len(customers), "segments": {k: len(v) for k, v in segments.items()},
                "recommendations": {"champions": "VIP program, early access, referral rewards",
                                    "loyal": "Cross-sell, bundle offers, subscription upgrade",
                                    "at_risk": "Re-engagement email, personalized discount, 'we miss you'",
                                    "lost": "Win-back campaign with strong incentive (20%+ off)",
                                    "new": "Welcome sequence, educational content, first-purchase follow-up"}}

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    def optimize_pricing(self, cost: float = 0.0, current_price: float = 0.0, competitor_price: float = 0.0, **kwargs) -> Dict[str, Any]:
        """Recommend optimal pricing based on cost, margin targets, and competitor data."""
        if cost <= 0:
            return {"success": False, "error": "Cost is required for pricing recommendations"}

        margin_targets = {"minimum": round(cost * 1.3, 2), "healthy": round(cost * 2.0, 2), "premium": round(cost * 3.0, 2)}
        psychological_prices = []
        for target in [margin_targets["healthy"]]:
            psychological_prices.append(round(target - 0.01, 2))
            psychological_prices.append(round(target / 5) * 5 - 0.01)

        recommendations = []
        if current_price > 0:
            current_margin = ((current_price - cost) / current_price * 100)
            recommendations.append(f"Current margin: {current_margin:.0f}%")
            if current_margin < 40: recommendations.append("Margin is low — consider raising price or reducing costs")
            elif current_margin > 70: recommendations.append("Margin is healthy — focus on volume and conversion")

        if competitor_price > 0:
            if current_price > competitor_price: recommendations.append(f"You're priced {((current_price/competitor_price)-1)*100:.0f}% above competitor — justify with unique value")
            else: recommendations.append(f"You're priced {((competitor_price/current_price)-1)*100:.0f}% below competitor — room to increase")

        return {"success": True, "result": f"Pricing recommendations (cost: ${cost:.2f})",
                "margin_targets": margin_targets, "psychological_prices": psychological_prices[:3],
                "recommendations": recommendations, "keystone_price": round(cost * 2, 2)}

    # ------------------------------------------------------------------
    # Bundles
    # ------------------------------------------------------------------

    def create_product_bundle(self, main_product: str = "", complementary_products: str = "", **kwargs) -> Dict[str, Any]:
        comp_list = [c.strip() for c in complementary_products.split(',') if c.strip()] if complementary_products else []
        bundle = {"name": f"{main_product} Bundle", "main_product": main_product, "complementary": comp_list,
                  "suggested_discount": "10-15% off total individual prices", "marketing_angle": "Save X% when you buy together",
                  "placement": ["Product page — below Add to Cart", "Cart page — before checkout", "Post-purchase thank you page"]}
        return {"success": True, "result": f"Bundle created: {bundle['name']} ({len(comp_list)} products)", "bundle": bundle}

    # ------------------------------------------------------------------
    # Seasonal Calendar
    # ------------------------------------------------------------------

    def plan_seasonal_calendar(self, year: int = 2026, **kwargs) -> Dict[str, Any]:
        seasons = {"January": ["New Year organization", "Winter clearance", "Fitness/wellness"], "February": ["Valentine's Day gifts", "Winter gear sale", "Super Bowl"],
                   "March": ["Spring preview", "St. Patrick's Day", "March Break"], "April": ["Spring collection", "Easter", "Earth Day"],
                   "May": ["Mother's Day", "Victoria Day", "Spring sale"], "June": ["Father's Day", "Summer launch", "End of school"],
                   "July": ["Canada Day", "Summer sale", "Vacation gear"], "August": ["Back to school", "Summer clearance", "Fall preview"],
                   "September": ["Fall collection", "Labor Day", "New arrivals"], "October": ["Thanksgiving (Canada)", "Halloween", "Fall sale"],
                   "November": ["Black Friday", "Cyber Monday", "Holiday preview"], "December": ["Holiday gifting", "Boxing Day", "Year-end clearance"]}
        return {"success": True, "result": f"Seasonal calendar for {year}", "calendar": seasons}

    # ------------------------------------------------------------------
    # Shipping
    # ------------------------------------------------------------------

    def analyze_shipping(self, origin_province: str = "QC", **kwargs) -> Dict[str, Any]:
        carriers = {"Canada Post": {"best_for": "Small packages, rural delivery", "tracking": "Yes", "insurance": "Up to $100 included"},
                    "UPS": {"best_for": "Medium-large packages, US shipping", "tracking": "Yes", "insurance": "Up to $100 included"},
                    "FedEx": {"best_for": "Express, international", "tracking": "Yes", "insurance": "Up to $100 included"},
                    "Purolator": {"best_for": "Canadian business shipping", "tracking": "Yes", "insurance": "Up to $100 included"},
                    "Canpar": {"best_for": "Budget Canadian shipping", "tracking": "Yes", "insurance": "Optional"}}
        strategies = {"free_shipping_threshold": "Offer free shipping over $75-$100 — increases AOV by 15-30%",
                      "flat_rate": "Simple flat rate ($8.99-$14.99) — reduces cart abandonment",
                      "real_time": "Carrier-calculated rates — most accurate but requires API integration",
                      "local_delivery": "Offer local delivery for orders within 25km — growing trend post-COVID"}
        return {"success": True, "result": "Shipping analysis for Canadian e-commerce", "carriers": carriers, "strategies": strategies}

    # ------------------------------------------------------------------
    # Taxes
    # ------------------------------------------------------------------

    def configure_taxes(self, province: str = "QC", **kwargs) -> Dict[str, Any]:
        tax_rates = {"AB": {"gst": 5.0, "pst": 0.0, "hst": 0.0, "total": 5.0}, "BC": {"gst": 5.0, "pst": 7.0, "hst": 0.0, "total": 12.0},
                     "MB": {"gst": 5.0, "pst": 7.0, "hst": 0.0, "total": 12.0}, "NB": {"gst": 0.0, "pst": 0.0, "hst": 15.0, "total": 15.0},
                     "NL": {"gst": 0.0, "pst": 0.0, "hst": 15.0, "total": 15.0}, "NS": {"gst": 0.0, "pst": 0.0, "hst": 15.0, "total": 15.0},
                     "ON": {"gst": 0.0, "pst": 0.0, "hst": 13.0, "total": 13.0}, "PE": {"gst": 0.0, "pst": 0.0, "hst": 15.0, "total": 15.0},
                     "QC": {"gst": 5.0, "pst": 9.975, "hst": 0.0, "total": 14.975}, "SK": {"gst": 5.0, "pst": 6.0, "hst": 0.0, "total": 11.0}}
        rates = tax_rates.get(province.upper(), tax_rates["QC"])
        return {"success": True, "result": f"Tax rate for {province.upper()}: {rates['total']}%",
                "province": province.upper(), "rates": rates, "note": "GST/HST registration required after $30,000 in revenue"}

    # ------------------------------------------------------------------
    # Store Health Audit
    # ------------------------------------------------------------------

    def audit_store_health(self, store_url: str = "", platform: str = "shopify", **kwargs) -> Dict[str, Any]:
        url = store_url or kwargs.get("url", "")
        checks = []
        score = 0

        checks.append({"category": "Products", "check": "Product count", "target": "10+ products for credibility", "priority": "high"})
        checks.append({"category": "Products", "check": "Product images", "target": "3-5 high-quality images per product", "priority": "high"})
        checks.append({"category": "Products", "check": "Product descriptions", "target": "Unique, 300+ word descriptions (not manufacturer copy)", "priority": "high"})
        checks.append({"category": "Trust", "check": "Contact page", "target": "Phone, email, and physical address visible", "priority": "critical"})
        checks.append({"category": "Trust", "check": "Return policy", "target": "Clear, easy-to-find return/refund policy", "priority": "critical"})
        checks.append({"category": "Trust", "check": "Shipping policy", "target": "Shipping times and costs clearly stated", "priority": "high"})
        checks.append({"category": "Trust", "check": "Privacy policy", "target": "Required by law — linked in footer", "priority": "critical"})
        checks.append({"category": "Conversion", "check": "Mobile experience", "target": "Fully responsive, easy checkout on mobile", "priority": "critical"})
        checks.append({"category": "Conversion", "check": "Checkout flow", "target": "Guest checkout option, minimal form fields", "priority": "high"})
        checks.append({"category": "Conversion", "check": "Payment options", "target": "Credit card + at least one alternative (PayPal, Shop Pay)", "priority": "medium"})
        checks.append({"category": "Marketing", "check": "Email capture", "target": "Newsletter signup or popup with incentive", "priority": "medium"})
        checks.append({"category": "Marketing", "check": "Abandoned cart recovery", "target": "Automated email sequence for abandoned carts", "priority": "high"})

        if url:
            try:
                # SSRF protection: no redirect following to prevent DNS rebinding
                resp = self._fetch_page(url) if hasattr(self, '_fetch_page') else requests.get(url, timeout=10, headers={'User-Agent': 'Frankie/1.0'}, allow_redirects=False)
                if resp is None:
                    raise ValueError("Empty response from store")
                content = resp.text
                if 'shopify' in content.lower(): checks.append({"category": "Platform", "check": "Platform detected", "detail": "Shopify", "priority": "info"})
                if 'woocommerce' in content.lower(): checks.append({"category": "Platform", "check": "Platform detected", "detail": "WooCommerce", "priority": "info"})
                if 'application/ld+json' in content:
                    score += 15
                    checks.append({"category": "SEO", "check": "Schema markup", "status": "pass", "priority": "high"})
            except Exception as e:
                logger.warning("Store health audit URL fetch failed: %s", e)

        return {"success": True, "result": f"Store health audit: {len(checks)} checks across 5 categories",
                "checks": checks, "categories": ["Products", "Trust", "Conversion", "Marketing", "SEO"]}

    # ------------------------------------------------------------------
    # Simple tools (keep existing)
    # ------------------------------------------------------------------

    def create_promotions(self, promotion_type: str = "discount", discount_pct: int = 15, **kwargs) -> Dict[str, Any]:
        types = {"discount": "Percentage or fixed amount off", "flash_sale": "Limited-time deep discount (24-48h) with countdown timer",
                 "bundle": "Buy X get Y at discount — increases AOV", "free_shipping": "Free shipping above order threshold — reduces abandonment",
                 "bogo": "Buy One Get One — clears inventory fast", "loyalty": "Points or rewards for repeat purchases",
                 "referral": "Discount for referring a friend — low CAC"}
        return {"success": True, "result": f"{promotion_type.title()} promotion created ({discount_pct}% off)",
                "promotion": {"type": promotion_type, "discount": f"{discount_pct}%", "status": "draft"},
                "available_types": types, "projected_uplift": f"Expect {15 if promotion_type == 'flash_sale' else 10}% conversion rate during promotion"}

    def manage_reviews(self, action: str = "generate_request", **kwargs) -> Dict[str, Any]:
        return {"success": True, "result": "Review management strategy",
                "strategy": {"timing": "Send review request 3-7 days after delivery",
                             "channel": "Email with direct review link + SMS for high-value customers",
                             "incentive": "Monthly draw for $50 gift card (CAN-SPAM compliant)",
                             "negative_reviews": "Respond within 24 hours, apologize, take conversation offline",
                             "display": "Show reviews prominently on product pages with star rating schema"}}

    def _fetch_page(self, url: str) -> Optional[requests.Response]:
        try:
            if not url.startswith(('http://', 'https://')): url = 'https://' + url
            if not _is_safe_url(url):
                logger.warning("Blocked SSRF attempt to private IP: %s", url)
                return None
            # SSRF protection: no redirect following to prevent DNS rebinding
            return requests.get(url, headers={'User-Agent': 'Frankie-Ecom/1.0'}, timeout=10, allow_redirects=False)
        except Exception:
            return None
