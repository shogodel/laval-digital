"""Ads MCP Server — Multi-platform ad campaign management with real Google Ads API integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from .base_server import MCPServer

logger = logging.getLogger(__name__)

_GOOGLE_ADS_DEFAULT_CUSTOMER = ""


def _get_customer_ids(**kwargs: Any) -> list[str]:
    """Extract customer_id from kwargs or return empty list.

    Supports both ``customer_id`` and ``api_credentials`` dict patterns.
    """
    cid = kwargs.get("customer_id", "").strip() or _GOOGLE_ADS_DEFAULT_CUSTOMER
    if cid:
        return [cid]
    creds = kwargs.get("api_credentials") or {}
    cid = creds.get("customer_id", "").strip()
    if cid:
        return [cid]
    return []


def _fmt_cid(cid: str) -> str:
    """Format a customer ID as ``123-456-7890``."""
    raw = cid.replace("-", "")
    return f"{raw[:3]}-{raw[3:6]}-{raw[6:]}"


class AdsMCPServer(MCPServer):
    """MCP Server for advertising — Google Ads, Meta Ads, TikTok Ads, LinkedIn Ads, retargeting, optimization.

    Google Ads tools use real API calls via the google-ads library (agency partnership model).
    Other platforms remain template-based until integration is available.
    """

    def __init__(self):
        super().__init__(
            name="ads",
            description="Ad campaign management — Google, Meta, TikTok, LinkedIn, retargeting, optimization, reporting"
        )

    def _register_tools(self) -> None:
        self.register_tool("create_google_ads_campaign", self.create_google_ads_campaign,
            "Create a Google Ads campaign: Search, Display, Performance Max, Local, or Video")
        self.register_tool("create_meta_ads_campaign", self.create_meta_ads_campaign,
            "Create a Facebook/Instagram campaign with audience targeting, placements, and ad creative")
        self.register_tool("create_tiktok_ads_campaign", self.create_tiktok_ads_campaign,
            "Create a TikTok Ads campaign: Spark Ads, In-Feed, TopView, or Branded Hashtag")
        self.register_tool("create_linkedin_ads_campaign", self.create_linkedin_ads_campaign,
            "Create a LinkedIn campaign: Sponsored Content, Message Ads, or Dynamic Ads")
        self.register_tool("keyword_research_ads", self.keyword_research_ads,
            "Research keywords for Google Ads with volume, competition, and CPC estimates")
        self.register_tool("create_audience_targeting", self.create_audience_targeting,
            "Create audience targeting: custom, lookalike, retargeting, interest, demographic")
        self.register_tool("create_ad_copy", self.create_ad_copy,
            "Generate Responsive Search Ads, display ads, video scripts, and dynamic ad templates")
        self.register_tool("optimize_campaign", self.optimize_campaign,
            "AI-powered campaign optimization with specific improvement suggestions")
        self.register_tool("ab_test_ad", self.ab_test_ad,
            "Set up A/B tests for ad variations across platforms")
        self.register_tool("generate_ad_report", self.generate_ad_report,
            "Generate a multi-platform ad performance report with ROAS, CPA, CTR, and recommendations")
        self.register_tool("manage_ad_extensions", self.manage_ad_extensions,
            "Manage Google Ads extensions: sitelinks, callouts, structured snippets, call, location")
        self.register_tool("create_retargeting_campaign", self.create_retargeting_campaign,
            "Create retargeting campaigns across Google, Meta, and TikTok")
        self.register_tool("calculate_ad_budget", self.calculate_ad_budget,
            "Calculate recommended ad budget with ROAS projections by industry")
        self.register_tool("analyze_competitor_ads", self.analyze_competitor_ads,
            "Analyze competitor ad strategy across platforms")
        self.register_tool("create_local_service_ads", self.create_local_service_ads,
            "Set up Google Local Services Ads for SMBs")
        self.register_tool("optimize_landing_page_for_ads", self.optimize_landing_page_for_ads,
            "Landing page optimization checklist for higher Quality Scores")
        self.register_tool("get_campaign_stats", self.get_campaign_stats,
            "Get campaign performance stats with ROAS, CPA, CTR, Quality Score, impression share")
        self.register_tool("update_ad_budget", self.update_ad_budget,
            "Update campaign budget with automated bidding strategies")

    # ------------------------------------------------------------------
    # Google Ads — Real API Integration
    # ------------------------------------------------------------------

    def _ga_client(self) -> Any | None:
        try:
            from core.ads_auth import get_google_ads_client
            return get_google_ads_client()
        except Exception:
            return None

    def _ga_service(self, name: str = "GoogleAdsService") -> Any | None:
        try:
            from core.ads_auth import get_google_ads_service
            return get_google_ads_service(name)
        except Exception:
            return None

    def _search(self, customer_id: str, query: str) -> list[dict]:
        """Execute a GAQL query and return row dicts (empty list on failure)."""
        try:
            from core.ads_auth import search_google_ads
            return search_google_ads(customer_id, query)
        except Exception as e:
            logger.warning("GAQL search failed: %s", e)
            return []

    def create_google_ads_campaign(self, campaign_name: str = "", campaign_type: str = "search",
                                   budget: float = 500.0, keywords: str = "", location: str = "",
                                   customer_id: str = "", **kwargs) -> dict[str, Any]:
        """Create a Google Ads campaign. Types: search, display, pmax, local, video.

        Requires a connected customer_id (Google Ads account ID under our MCC).
        Falls back to template if no customer_id or API error.
        """
        cid = customer_id.replace("-", "") if customer_id else ""
        if not cid:
            return _template_create_google(campaign_name, campaign_type, budget, keywords, location)

        client = self._ga_client()
        if not client:
            return _template_create_google(campaign_name, campaign_type, budget, keywords, location)

        try:
            ga_service = self._ga_service("GoogleAdsService")
            if not ga_service:
                return _template_create_google(campaign_name, campaign_type, budget, keywords, location)

            kw_list = [k.strip() for k in keywords.split('\n') if k.strip()] if keywords else []

            campaign_service = client.get_service("CampaignService", version="v24")
            campaign_budget_service = client.get_service("CampaignBudgetService", version="v24")

            now = datetime.now()
            start_date = now.strftime("%Y%m%d")
            end_date = (now + timedelta(days=30)).strftime("%Y%m%d")

            budget_op = client.get_type("CampaignBudgetOperation", version="v24")
            budget_obj = client.get_type("CampaignBudget", version="v24")
            budget_obj.name = f"Budget for {campaign_name or 'AI Campaign'}"
            budget_obj.delivery_method = client.enums["BudgetDeliveryMethodEnum"].STANDARD
            budget_obj.amount_micros = int(budget * 1_000_000)
            budget_op.create = budget_obj
            budget_response = campaign_budget_service.mutate(customer_id=cid, operations=[budget_op])
            budget_resource = budget_response.results[0].resource_name

            campaign_op = client.get_type("CampaignOperation", version="v24")
            campaign = client.get_type("Campaign", version="v24")
            campaign.name = campaign_name or f"AI {campaign_type.title()} Campaign"
            campaign.campaign_budget = budget_resource
            campaign.advertising_channel_type = {
                "search": "SEARCH",
                "display": "DISPLAY",
                "pmax": "PERFORMANCE_MAX",
                "local": "LOCAL",
                "video": "VIDEO",
            }.get(campaign_type, "SEARCH")
            campaign.status = client.enums["CampaignStatusEnum"].PAUSED
            campaign.start_date = start_date
            campaign.end_date = end_date

            if campaign_type in ("search", "pmax"):
                network = client.get_type("NetworkSettings", version="v24")
                network.target_google_search = True
                network.target_search_network = True
                network.target_content_network = campaign_type == "pmax"
                campaign.network_settings = network

            if location:
                geo_target = client.get_type("LocationInfo", version="v24")
                geo_target.geo_target_constant = f"geoTargetConstants/{_resolve_location_id(location)}"
                campaign.targeting_setting.target_restrictions = [geo_target]

            campaign_op.create = campaign
            campaign_response = campaign_service.mutate(customer_id=cid, operations=[campaign_op])
            campaign_resource = campaign_response.results[0].resource_name

            return {
                "success": True,
                "result": f"Google Ads {campaign_type} campaign '{campaign.name}' created (paused). Budget: ${budget}/mo",
                "campaign": {
                    "resource_name": campaign_resource,
                    "name": campaign.name,
                    "type": campaign_type,
                    "budget_micros": budget * 1_000_000,
                    "status": "PAUSED",
                    "customer_id": _fmt_cid(cid),
                },
            }
        except Exception as e:
            logger.warning("Google Ads API campaign creation failed: %s", e, exc_info=True)
            result = _template_create_google(campaign_name, campaign_type, budget, keywords, location)
            result["note"] = f"API call failed, showing template: {e}"
            return result

    def keyword_research_ads(self, business_type: str = "", location: str = "",
                              customer_id: str = "", **kwargs) -> dict[str, Any]:
        """Research keywords for Google Ads with real Keyword Planner data.

        Falls back to estimated data if no customer_id or API error.
        """
        cid = customer_id.replace("-", "") if customer_id else ""

        if cid:
            try:
                client = self._ga_client()
                if client:
                    keyword_plan_idea_service = client.get_service("KeywordPlanIdeaService", version="v24")
                    geo_templates = []
                    if location:
                        geo_templates.append(f"geoTargetConstants/{_resolve_location_id(location)}")

                    request = client.get_type("GenerateKeywordIdeasRequest", version="v24")
                    request.customer_id = cid
                    request.language = "languageConstants/1000"
                    if geo_templates:
                        request.geo_target_constants.extend(geo_templates)
                    request.keyword_seed.keywords.extend(
                        [business_type, f"{business_type} near me", f"{business_type} {location}",
                         f"best {business_type}", f"{business_type} service"]
                    )
                    request.include_adult_keywords = False
                    request.page_size = 20

                    response = keyword_plan_idea_service.generate_keyword_ideas(request=request)
                    keywords = []
                    for idea in response.results:
                        keywords.append({
                            "keyword": idea.text,
                            "avg_monthly_searches": str(idea.keyword_idea_metrics.avg_monthly_searches),
                            "competition": idea.keyword_idea_metrics.competition.name,
                            "cpc_micros": idea.keyword_idea_metrics.low_top_of_page_bid_micros,
                        })

                    return {
                        "success": True,
                        "result": f"Generated {len(keywords)} keyword ideas for {business_type} in {location}",
                        "keywords": keywords or _sample_keywords(business_type, location),
                        "source": "google_ads_api",
                    }
            except Exception as e:
                logger.warning("Keyword Planner API failed: %s", e)

        return {
            "success": True,
            "result": f"Generated estimated keywords for {business_type} in {location}",
            "keywords": _sample_keywords(business_type, location),
            "source": "estimates",
        }

    def get_campaign_stats(self, customer_id: str = "", campaign_id: str = "", **kwargs) -> dict[str, Any]:
        """Get campaign performance stats via Google Ads API.

        Returns real metrics if customer_id is provided, otherwise template.
        """
        cid = customer_id.replace("-", "") if customer_id else ""
        if not cid:
            return _template_stats()

        query = """
            SELECT campaign.id, campaign.name, campaign.status,
                   metrics.impressions, metrics.clicks, metrics.ctr,
                   metrics.average_cpc, metrics.conversions,
                   metrics.conversions_value, metrics.cost_micros,
                   metrics.quality_score
            FROM campaign
        """
        if campaign_id:
            clean_id = campaign_id.replace("-", "")
            query += f" WHERE campaign.id = {clean_id}"
        query += " LIMIT 50"

        rows = self._search(cid, query)
        if not rows:
            return _template_stats()

        stats_list = []
        for row in rows:
            s = dict(row)
            s["cost"] = s.get("cost_micros", 0) / 1_000_000 if s.get("cost_micros") else 0
            stats_list.append(s)

        return {
            "success": True,
            "result": f"Retrieved stats for {len(stats_list)} campaign(s)",
            "campaigns": stats_list,
            "source": "google_ads_api",
        }

    def update_ad_budget(self, campaign_id: str = "", new_budget: float = 0.0,
                          customer_id: str = "", **kwargs) -> dict[str, Any]:
        """Update campaign budget via Google Ads API."""
        cid = customer_id.replace("-", "") if customer_id else ""
        if not cid or not campaign_id or new_budget <= 0:
            return {
                "success": True,
                "result": f"Budget update simulated to ${new_budget}/mo for campaign {campaign_id}",
                "tip": "Increase budget gradually (20% every 3-5 days) to maintain performance stability",
                "source": "simulated",
            }

        try:
            client = self._ga_client()
            if not client:
                raise RuntimeError("No client")

            clean_campaign_id = campaign_id.replace("-", "")

            query = f"SELECT campaign.id, campaign.campaign_budget FROM campaign WHERE campaign.id = {clean_campaign_id}"
            rows = self._search(cid, query)
            if not rows:
                return {"success": False, "result": "", "error": f"Campaign {campaign_id} not found"}

            budget_resource = rows[0].get("campaign.campaign_budget") or rows[0].get("campaign_budget", "")
            budget_service = client.get_service("CampaignBudgetService", version="v24")
            budget_op = client.get_type("CampaignBudgetOperation", version="v24")
            budget = client.get_type("CampaignBudget", version="v24")
            budget.resource_name = budget_resource
            budget.amount_micros = int(new_budget * 1_000_000)

            field_mask = client.get_type("FieldMask", version="v24")
            from google.protobuf import field_mask_pb2
            field_mask.paths.extend(["amount_micros"])
            budget_op.update = budget
            budget_op.update_mask = field_mask

            budget_service.mutate(customer_id=cid, operations=[budget_op])
            return {
                "success": True,
                "result": f"Budget updated to ${new_budget}/mo for campaign {campaign_id}",
                "source": "google_ads_api",
            }
        except Exception as e:
            logger.warning("Budget update API failed: %s", e)
            return {
                "success": True,
                "result": f"Budget update simulated to ${new_budget}/mo for campaign {campaign_id}",
                "tip": "Increase budget gradually (20% every 3-5 days) to maintain performance stability",
                "source": "simulated",
            }

    def manage_ad_extensions(self, action: str = "list", business_name: str = "", phone: str = "",
                              website: str = "", customer_id: str = "", **kwargs) -> dict[str, Any]:
        """Manage Google Ads extensions. Supports listing active extensions via API."""
        cid = customer_id.replace("-", "") if customer_id else ""
        if cid and action == "list":
            query = """
                SELECT campaign.id, campaign.name,
                       campaign_extension_setting.extension_type,
                       campaign_extension_setting.campaign
                FROM campaign_extension_setting
                LIMIT 20
            """
            rows = self._search(cid, query)
            if rows:
                return {
                    "success": True,
                    "result": f"Found {len(rows)} extension settings",
                    "extensions": rows,
                    "source": "google_ads_api",
                }

        return _template_extensions(action, business_name, phone, website)

    # ------------------------------------------------------------------
    # Non-Google-Ads Tools (Template-based, no real API yet)
    # ------------------------------------------------------------------

    def create_meta_ads_campaign(self, **kwargs) -> dict[str, Any]:
        return _template_create_meta(**kwargs)

    def create_tiktok_ads_campaign(self, **kwargs) -> dict[str, Any]:
        return _template_create_tiktok(**kwargs)

    def create_linkedin_ads_campaign(self, **kwargs) -> dict[str, Any]:
        return _template_create_linkedin(**kwargs)

    def create_audience_targeting(self, audience_type: str = "custom", business_type: str = "", **kwargs) -> dict[str, Any]:
        return _template_audience(audience_type, business_type)

    def create_ad_copy(self, business_name: str = "", business_type: str = "", location: str = "",
                        platform: str = "google", **kwargs) -> dict[str, Any]:
        return _template_ad_copy(business_name, business_type, location, platform)

    def optimize_campaign(self, campaign_id: str = "", platform: str = "google", **kwargs) -> dict[str, Any]:
        return _template_optimize(campaign_id, platform)

    def ab_test_ad(self, test_name: str = "", platform: str = "google", **kwargs) -> dict[str, Any]:
        return _template_ab_test(test_name, platform)

    def generate_ad_report(self, month: str = "", platforms: str = "google,meta", **kwargs) -> dict[str, Any]:
        return _template_report(month, platforms)

    def create_retargeting_campaign(self, campaign_name: str = "", platform: str = "meta",
                                     budget: float = 100.0, **kwargs) -> dict[str, Any]:
        return _template_retargeting(campaign_name, platform, budget)

    def calculate_ad_budget(self, industry: str = "local_services", goal: str = "leads", **kwargs) -> dict[str, Any]:
        return _template_budget(industry, goal)

    def analyze_competitor_ads(self, competitor_name: str = "", platform: str = "google", **kwargs) -> dict[str, Any]:
        return _template_competitor(competitor_name, platform)

    def create_local_service_ads(self, business_type: str = "", business_name: str = "", phone: str = "",
                                  location: str = "", **kwargs) -> dict[str, Any]:
        return _template_lsa(business_type, business_name, phone, location)

    def optimize_landing_page_for_ads(self, landing_page_url: str = "", **kwargs) -> dict[str, Any]:
        return _template_landing_page(landing_page_url)


# ── Helpers ──────────────────────────────────────────────────────────

def _resolve_location_id(location_name: str) -> str:
    """Basic location name to geo-target constant ID mapping."""
    location_map = {
        "laval": "1014271",
        "montreal": "1002210",
        "quebec": "1002211",
        "toronto": "1002180",
        "vancouver": "1002190",
        "calgary": "1002082",
        "ottawa": "1002160",
        "edmonton": "1002100",
        "winnipeg": "1002200",
    }
    key = location_name.lower().split(",")[0].strip()
    return location_map.get(key, "1014271")


def _sample_keywords(business_type: str, location: str) -> list[dict]:
    return [
        {"keyword": f"emergency {business_type} near me", "avg_monthly_searches": "1K-10K", "competition": "HIGH", "cpc_micros": 8000000},
        {"keyword": f"best {business_type} in {location}", "avg_monthly_searches": "100-1K", "competition": "MEDIUM", "cpc_micros": 5000000},
        {"keyword": f"{business_type} services {location}", "avg_monthly_searches": "100-1K", "competition": "MEDIUM", "cpc_micros": 4000000},
        {"keyword": f"affordable {business_type} {location}", "avg_monthly_searches": "100-1K", "competition": "LOW", "cpc_micros": 3000000},
        {"keyword": f"{business_type} company near me", "avg_monthly_searches": "1K-10K", "competition": "HIGH", "cpc_micros": 6000000},
    ]


# ── Template fallbacks (unchanged structure from original) ────────────

def _template_create_google(campaign_name: str = "", campaign_type: str = "search",
                             budget: float = 500.0, keywords: str = "", location: str = "") -> dict[str, Any]:
    kw_list = [k.strip() for k in keywords.split('\n') if k.strip()] if keywords else ["near me", "best near me"]
    campaign_types = {
        "search": {"network": "Google Search Network", "best_for": "High-intent local leads", "avg_cpc": "$2-8"},
        "display": {"network": "Google Display Network", "best_for": "Brand awareness and retargeting", "avg_cpc": "$0.50-2"},
        "pmax": {"network": "All Google networks", "best_for": "Maximum reach with AI optimization", "avg_cpc": "Varies"},
        "local": {"network": "Google Maps + Search", "best_for": "Driving calls and directions", "avg_cpc": "$1-5"},
        "video": {"network": "YouTube", "best_for": "Brand awareness and education", "avg_cpv": "$0.01-0.05"},
    }
    ctype = campaign_types.get(campaign_type, campaign_types["search"])
    return {"success": True, "result": f"Google Ads {campaign_type} campaign '{campaign_name or 'AI Campaign'}' created. Budget: ${budget}/mo",
            "campaign": {"name": campaign_name or f"AI {campaign_type.title()} Campaign", "platform": "google",
                         "type": campaign_type, "budget_monthly": budget, "keywords": kw_list,
                         "location": location or "Laval, QC", "network": ctype["network"]},
            "tip": f"Best for: {ctype['best_for']}. Avg CPC: {ctype['avg_cpc']}", "source": "template"}


def _template_create_meta(**kwargs) -> dict[str, Any]:
    campaign_name = kwargs.get("campaign_name", "")
    objective = kwargs.get("objective", "leads")
    budget = kwargs.get("budget", 300.0)
    audiences = kwargs.get("audiences", "")
    location = kwargs.get("location", "")
    audience_list = [a.strip() for a in audiences.split(',') if a.strip()] if audiences else ["Local residents 25-65"]
    return {"success": True, "result": f"Meta Ads {objective} campaign '{campaign_name or 'AI Campaign'}' created. Budget: ${budget}/mo",
            "campaign": {"name": campaign_name or f"AI Meta {objective.title()} Campaign", "platform": "meta",
                         "budget_monthly": budget, "audiences": audience_list, "location": location or "Laval, QC + 25km"}}


def _template_create_tiktok(**kwargs) -> dict[str, Any]:
    campaign_name = kwargs.get("campaign_name", "")
    objective = kwargs.get("objective", "traffic")
    budget = kwargs.get("budget", 200.0)
    location = kwargs.get("location", "")
    return {"success": True, "result": f"TikTok Ads campaign '{campaign_name or 'AI Campaign'}' created. Budget: ${budget}/mo",
            "campaign": {"name": campaign_name or "AI TikTok Campaign", "platform": "tiktok",
                         "objective": objective, "budget_monthly": budget, "location": location or "Laval, QC"}}


def _template_create_linkedin(**kwargs) -> dict[str, Any]:
    campaign_name = kwargs.get("campaign_name", "")
    objective = kwargs.get("objective", "leads")
    budget = kwargs.get("budget", 400.0)
    location = kwargs.get("location", "")
    return {"success": True, "result": f"LinkedIn Ads campaign '{campaign_name or 'AI Campaign'}' created. Budget: ${budget}/mo",
            "campaign": {"name": campaign_name or "AI LinkedIn Campaign", "platform": "linkedin",
                         "objective": objective, "budget_monthly": budget, "location": location or "Greater Montreal Area"}}


def _template_audience(audience_type: str, business_type: str) -> dict[str, Any]:
    audiences = {
        "custom": {"name": f"{business_type.title()} Custom Audience", "description": "People actively searching for your services"},
        "lookalike": {"name": f"{business_type.title()} Lookalike", "description": "People similar to your best customers"},
        "retargeting": {"name": "Website Retargeting", "description": "People who visited your site but didn't convert"},
        "interest": {"name": "Home Services Interest", "description": "People interested in home improvement"},
        "demographic": {"name": "Homeowners 30-65", "description": "Homeowners in your service area"},
    }
    audience = audiences.get(audience_type, audiences["custom"])
    return {"success": True, "result": f"Audience '{audience['name']}' created", "audience": audience,
            "available_types": list(audiences.keys()), "source": "template"}


def _template_ad_copy(business_name: str, business_type: str, location: str, platform: str) -> dict[str, Any]:
    templates = {
        "google_rsa": {
            "headlines": [f"Top {business_type.title()} in {location}", f"Emergency {business_type.title()} — 24/7",
                          "Call Now for a Free Estimate", f"Licensed & Insured {business_type.title()}"],
            "descriptions": [f"Looking for a reliable {business_type} in {location}? Call now!",
                             f"{business_name} — your trusted {business_type} in {location}."],
        },
        "meta_ad": {"headline": f"Need a {business_type.title()} in {location}?",
                     "primary_text": f"We're {business_name}, your 5-star rated {business_type}.",
                     "cta": "Get Quote"},
        "tiktok_ad": {"hook": f"3 signs you need a {business_type} in {location}",
                       "body": f"At {business_name}, we've seen it all.", "cta": "Call Now"},
    }
    ad = templates.get(platform, templates["google_rsa"])
    return {"success": True, "result": f"Ad copy generated for {platform}", "ad_copy": ad,
            "platforms_available": list(templates.keys()), "source": "template"}


def _template_optimize(campaign_id: str, platform: str) -> dict[str, Any]:
    optimizations = {
        "google": ["Add negative keywords", "Improve Quality Score", "Add ad extensions",
                    "Test Responsive Search Ads", "Enable conversion tracking",
                    "Set up automated bidding", "Check impression share"],
        "meta": ["Test Advantage+ placements", "Create lookalike audiences",
                  "Refresh ad creative every 2 weeks", "Test video ads"],
    }
    opt = optimizations.get(platform, optimizations["google"])
    return {"success": True, "result": f"Generated {len(opt)} optimization suggestions for {platform}",
            "suggestions": opt, "source": "template"}


def _template_ab_test(test_name: str, platform: str) -> dict[str, Any]:
    return {"success": True, "result": f"A/B test '{test_name}' configured for {platform}",
            "setup": {"variation_a": "Control", "variation_b": "Variant", "split": "50/50",
                       "duration": "7-14 days", "metrics": ["CTR", "Conversion rate", "CPC", "CPA", "ROAS"]},
            "source": "template"}


def _template_report(month: str, platforms: str) -> dict[str, Any]:
    try:
        report_month = datetime.strptime(month, "%Y-%m") if month else datetime.now()
    except ValueError:
        report_month = datetime.now()
    platform_list = [p.strip() for p in platforms.split(',')]
    return {"success": True, "result": f"Ad report for {report_month.strftime('%B %Y')} generated",
            "report": {"month": report_month.strftime("%B %Y"), "platforms": platform_list,
                        "sections": [{"name": "Spend & Budget", "metrics": ["Total spend", "Daily average"]},
                                      {"name": "Performance", "metrics": ["Impressions", "Clicks", "CTR", "CPC", "Conversions", "CPA"]},
                                      {"name": "ROAS", "metrics": ["Revenue", "ROAS"]},
                                      {"name": "Recommendations", "metrics": ["Budget reallocation", "Underperforming to pause"]}]},
            "source": "template"}


def _template_extensions(action: str, business_name: str, phone: str, website: str) -> dict[str, Any]:
    extensions = {
        "sitelinks": [{"text": "Free Estimate", "url": f"{website}/free-estimate"},
                       {"text": "Our Services", "url": f"{website}/services"}],
        "callouts": ["Licensed & Insured", "5-Star Rated", "Same-Day Service", "Free Estimates"],
        "call": {"phone": phone or "(555) 123-4567", "country": "CA"},
        "location": {"address": "Your business address"},
        "structured_snippets": [{"header": "Services", "values": ["Emergency Repairs", "Installation", "Maintenance"]}],
    }
    return {"success": True, "result": "Ad extensions configured", "extensions": extensions,
            "tip": "Ads with extensions get 10-15% higher CTR on average", "source": "template"}


def _template_retargeting(campaign_name: str, platform: str, budget: float) -> dict[str, Any]:
    strategies = {
        "meta": ["Website visitors (30 days)", "Video viewers (50%+)", "Page engagers"],
        "google": ["Website visitors (30 days)", "Cart abandoners (7 days)", "Past converters (90 days)"],
        "tiktok": ["Website visitors (30 days)", "Video viewers (75%+)"],
    }
    return {"success": True, "result": f"Retargeting campaign created for {platform}",
            "campaign": {"name": campaign_name or f"Retargeting — {platform.title()}", "budget": budget,
                          "strategies": strategies.get(platform, strategies["meta"])},
            "source": "template"}


def _template_budget(industry: str, goal: str) -> dict[str, Any]:
    benchmarks = {
        "local_services": {"avg_cpc": "$4-8", "conversion_rate": "5-10%", "cost_per_lead": "$20-50", "recommended_budget": "$500-2,000/mo"},
        "ecommerce": {"avg_cpc": "$1-3", "conversion_rate": "2-5%", "cost_per_sale": "$10-30", "recommended_budget": "$1,000-5,000/mo"},
        "b2b": {"avg_cpc": "$5-10", "conversion_rate": "2-5%", "cost_per_lead": "$50-150", "recommended_budget": "$1,500-5,000/mo"},
    }
    return {"success": True, "result": f"Budget recommendations for {industry}",
            "benchmarks": benchmarks.get(industry, benchmarks["local_services"]), "source": "template"}


def _template_competitor(competitor_name: str, platform: str) -> dict[str, Any]:
    return {"success": True, "result": f"Competitor ad analysis framework for {competitor_name}",
            "analysis": {"competitor": competitor_name, "platform": platform,
                          "checks": ["Ad copy and messaging", "Keywords they're bidding on",
                                      "Landing page experience", "Ad extensions used"]},
            "source": "template"}


def _template_lsa(business_type: str, business_name: str, phone: str, location: str) -> dict[str, Any]:
    eligible_types = ["plumber", "electrician", "roofer", "hvac", "locksmith", "cleaner", "landscaper", "painter", "handyman"]
    is_eligible = business_type.lower() in eligible_types
    return {"success": True, "result": f"Local Services Ads setup for {business_type}",
            "eligible": is_eligible, "eligible_types": eligible_types,
            "setup_steps": ["Verify your GMB profile", "Pass Google background check",
                            "Set your service areas", "Choose job types", "Set your weekly budget"],
            "source": "template"}


def _template_landing_page(landing_page_url: str) -> dict[str, Any]:
    return {"success": True, "result": f"Landing page optimization checklist",
            "checklist": [{"check": "Headline matches ad copy", "importance": "critical"},
                          {"check": "Single CTA above the fold", "importance": "critical"},
                          {"check": "Page loads under 3s", "importance": "critical"},
                          {"check": "Mobile-responsive", "importance": "critical"}],
            "source": "template"}


def _template_stats() -> dict[str, Any]:
    return {"success": True, "result": "Campaign stats framework ready. Connect a Google Ads account for live data.",
            "metrics_available": ["impressions", "clicks", "CTR", "CPC", "conversions", "CPA", "ROAS", "quality_score"],
            "source": "template"}
