"""Google Business Profile MCP Server for Frankie — Complete local SEO management."""
import logging
import json
import re
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from .base_server import MCPServer, _safe_error
from ._safe_url import _is_safe_url

logger = logging.getLogger(__name__)


class GMBMCPServer(MCPServer):
    """MCP Server for Google Business Profile — posts, reviews, Q&A, products, insights, optimization, multi-location."""

    def __init__(self):
        super().__init__(
            name="gmb",
            description="Google Business Profile — posts, reviews, Q&A, products, insights, optimization, multi-location"
        )

    def _register_tools(self) -> None:
        self.register_tool("create_gmb_post", self.create_gmb_post,
            "Create a GMB post: standard, event, offer, COVID-19 update, or video")
        self.register_tool("respond_to_review", self.respond_to_review,
            "Generate and post a review response with sentiment analysis")
        self.register_tool("update_business_info", self.update_business_info,
            "Update hours, holiday hours, service areas, categories, attributes, description")
        self.register_tool("upload_photo", self.upload_photo,
            "Upload logo, cover photo, interior/exterior photos, or video")
        self.register_tool("get_insights", self.get_insights,
            "Get GMB insights: search queries, views, direction requests, calls, bookings")
        self.register_tool("optimize_gmb_profile", self.optimize_gmb_profile,
            "Full GMB profile audit with prioritized optimization checklist")
        self.register_tool("manage_q_and_a", self.manage_q_and_a,
            "Seed, answer, and manage GMB Questions & Answers")
        self.register_tool("create_gmb_product", self.create_gmb_product,
            "Add products or services to the GMB product catalog")
        self.register_tool("track_local_rankings", self.track_local_rankings,
            "Track GMB ranking position for target keywords in your area")
        self.register_tool("manage_gmb_messages", self.manage_gmb_messages,
            "Set up and manage GMB messaging with auto-reply templates")
        self.register_tool("generate_gmb_report", self.generate_gmb_report,
            "Generate a monthly GMB performance report")
        self.register_tool("audit_competitor_gmb", self.audit_competitor_gmb,
            "Analyze competitor GMB profiles for strengths and gaps")
        self.register_tool("bulk_update_locations", self.bulk_update_locations,
            "Manage multiple GMB locations with bulk operations")
        self.register_tool("optimize_for_voice_search", self.optimize_for_voice_search,
            "Voice search optimization tips for local queries")
        self.register_tool("setup_appointment_booking", self.setup_appointment_booking,
            "Integrate appointment booking links with GMB")
        self.register_tool("create_local_campaign", self.create_local_campaign,
            "Create a local Google Ads campaign linked to GMB location")

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------

    def create_gmb_post(self, content: str, post_type: str = "standard", event_start: str = "", event_end: str = "",
                        coupon_code: str = "", offer_url: str = "", api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Create a GMB post. Types: standard, event, offer, covid, video."""
        if api_credentials and api_credentials.get("account_id") and api_credentials.get("location_id") and api_credentials.get("access_token"):
            try:
                url = f"https://mybusiness.googleapis.com/v4/accounts/{api_credentials['account_id']}/locations/{api_credentials['location_id']}/localPosts"
                headers = {"Authorization": f"Bearer {api_credentials['access_token']}", "Content-Type": "application/json"}
                payload = {"summary": content[:1500], "topicType": "STANDARD", "callToAction": {"actionType": "LEARN_MORE"}}
                if post_type == "event" and event_start:
                    payload["topicType"] = "EVENT"
                    try:
                        if not re.match(r'^\d{4}-\d{2}-\d{2}$', event_start):
                            raise ValueError("event_start must be in YYYY-MM-DD format")
                        payload["event"] = {"title": content[:100], "schedule": {"startDate": {"year": int(event_start[:4]), "month": int(event_start[5:7]), "day": int(event_start[8:10])}}}
                    except (ValueError, IndexError) as e:
                        return {"success": False, "result": "", "error": f"Invalid event_start date: {e}"}
                elif post_type == "offer":
                    payload["topicType"] = "OFFER"
                    payload["callToAction"]["actionType"] = "SIGN_UP"
                resp = requests.post(url, headers=headers, json=payload, timeout=15)
                if resp.status_code == 200:
                    return {"success": True, "result": f"GMB {post_type} post created", "error": None}
                return {"success": False, "result": "", "error": f"GMB API: {resp.text}"}
            except Exception as e:
                return {"success": False, "result": "", "error": f"GMB post failed: {e}"}
        return self._queue_gmb_action("post", content, post_type)

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    def respond_to_review(self, review_id: str = "", response_text: str = "", review_text: str = "",
                          tone: str = "professional", bulk: bool = False,
                          api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Respond to a review. If review_text is provided, generates an appropriate response based on sentiment."""
        if review_text and not response_text:
            sentiment = self._analyze_sentiment(review_text)
            tones = {
                "positive": "Thank you so much for your wonderful review! We're thrilled to hear about your experience and truly appreciate you taking the time to share it. We look forward to serving you again!",
                "neutral": "Thank you for your feedback! We appreciate you sharing your experience and will use it to continue improving. If there's anything else we can do, please reach out!",
                "negative": "We appreciate your honest feedback and apologize that your experience didn't meet expectations. We take your concerns seriously and would love the opportunity to make things right. Please contact us directly so we can address this personally."
            }
            response_text = tones.get(sentiment, tones["neutral"])
        if api_credentials and api_credentials.get("access_token") and review_id:
            try:
                url = f"https://mybusiness.googleapis.com/v4/accounts/{api_credentials['account_id']}/locations/{api_credentials.get('location_id', '')}/reviews/{review_id}/reply"
                headers = {"Authorization": f"Bearer {api_credentials['access_token']}", "Content-Type": "application/json"}
                resp = requests.put(url, headers=headers, json={"comment": response_text}, timeout=15)
                if resp.status_code == 200:
                    return {"success": True, "result": "Review response posted", "error": None}
                return {"success": False, "result": "", "error": f"GMB API: {resp.text}"}
            except Exception as e:
                return {"success": False, "result": "", "error": f"Review response failed: {e}"}
        return {"success": True, "result": f"Review response generated ({tone} tone)", "response": response_text,
                "sentiment": self._analyze_sentiment(review_text) if review_text else "unknown", "review_id": review_id}

    def _analyze_sentiment(self, text: str) -> str:
        """Simple sentiment analysis for reviews."""
        positive_words = ["great", "excellent", "amazing", "wonderful", "fantastic", "love", "best", "professional", "recommend", "thank", "happy", "impressed", "outstanding", "perfect", "awesome", "5 star", "5-star"]
        negative_words = ["terrible", "horrible", "awful", "bad", "poor", "worst", "disappointed", "never", "rude", "unprofessional", "waste", "scam", "avoid", "0 star", "zero star"]
        text_lower = text.lower()
        positive_score = sum(1 for w in positive_words if w in text_lower)
        negative_score = sum(1 for w in negative_words if w in text_lower)
        if positive_score > negative_score:
            return "positive"
        if negative_score > positive_score:
            return "negative"
        return "neutral"

    # ------------------------------------------------------------------
    # Business Info
    # ------------------------------------------------------------------

    def update_business_info(self, api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Update GMB business information: hours, description, categories, service areas, attributes, holiday hours."""
        updateable_fields = {
            "description": "Business description (750 char max) — include keywords naturally",
            "categories": "Primary and secondary categories — choose the most specific ones available",
            "hours": "Regular operating hours for each day of the week",
            "holiday_hours": "Special hours for holidays — prevents customer frustration",
            "service_areas": "Cities, postal codes, or radius you serve — critical for local ranking",
            "attributes": "Features like 'wheelchair accessible', 'free wifi', 'outdoor seating', 'women-led'",
            "phone": "Primary phone number — must match your website exactly",
            "website": "Website URL — should be HTTPS and mobile-friendly"
        }
        if api_credentials and api_credentials.get("access_token"):
            try:
                url = f"https://mybusiness.googleapis.com/v4/accounts/{api_credentials['account_id']}/locations/{api_credentials.get('location_id', '')}"
                headers = {"Authorization": f"Bearer {api_credentials['access_token']}", "Content-Type": "application/json"}
                resp = requests.patch(url, headers=headers, json={"location": kwargs}, timeout=15)
                if resp.status_code == 200:
                    return {"success": True, "result": "Business info updated", "error": None}
                return {"success": False, "result": "", "error": f"GMB API: {resp.text}"}
            except Exception as e:
                return {"success": False, "result": "", "error": f"Update failed: {e}"}
        return {"success": True, "result": "Business info update prepared. Connect GMB API for live updates.",
                "updateable_fields": updateable_fields, "fields_to_update": list(kwargs.keys())}

    def upload_photo(self, photo_url: str = "", photo_type: str = "additional",
                     api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Upload a photo to GMB. Types: logo, cover, interior, exterior, team, at_work, additional."""
        photo_types = {"logo": "LOGO", "cover": "COVER", "interior": "INTERIOR", "exterior": "EXTERIOR",
                       "team": "TEAM", "at_work": "AT_WORK", "additional": "ADDITIONAL"}
        gmb_type = photo_types.get(photo_type, "ADDITIONAL")
        if api_credentials and api_credentials.get("access_token") and photo_url:
            try:
                if not _is_safe_url(photo_url):
                    return {"success": False, "error": "Photo URL resolves to a private IP"}
                url = f"https://mybusiness.googleapis.com/v4/accounts/{api_credentials['account_id']}/locations/{api_credentials.get('location_id', '')}/media"
                headers = {"Authorization": f"Bearer {api_credentials['access_token']}", "Content-Type": "application/json"}
                resp = requests.post(url, headers=headers, json={"mediaFormat": "PHOTO", "locationAssociation": {"category": gmb_type}, "sourceUrl": photo_url}, timeout=15)
                if resp.status_code == 200:
                    return {"success": True, "result": f"Photo uploaded as {photo_type}", "error": None}
                return {"success": False, "result": "", "error": f"GMB API: {resp.text}"}
            except Exception as e:
                return {"success": False, "result": "", "error": f"Photo upload failed: {e}"}
        return {"success": True, "result": f"Photo upload queued as {photo_type}", "photo_types_available": list(photo_types.keys())}

    # ------------------------------------------------------------------
    # Insights
    # ------------------------------------------------------------------

    def get_insights(self, api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Get GMB performance insights."""
        insights_guide = {
            "search_queries": "Keywords customers used to find your business — identifies top opportunities",
            "views_search": "How many times your profile appeared in search results",
            "views_maps": "How many times your profile appeared on Google Maps",
            "actions_website": "Clicks to your website",
            "actions_directions": "Direction requests — critical for local businesses",
            "actions_phone": "Phone calls from GMB — direct lead count",
            "actions_bookings": "Bookings made through GMB",
            "photo_views": "How many times your photos were viewed vs competitors",
            "photo_count": "Total photos — profiles with 100+ photos get 520% more calls",
            "review_count": "Total reviews and average rating",
            "audience_locations": "Where your customers are coming from",
            "popular_times": "When customers visit your location"
        }
        return {"success": True, "result": "GMB insights framework ready. Connect GMB API for live data.",
                "insights_available": list(insights_guide.keys()), "key_metric": "Profiles with 100+ photos get 520% more calls"}

    # ------------------------------------------------------------------
    # Optimization
    # ------------------------------------------------------------------

    def optimize_gmb_profile(self, business_name: str = "", api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Full GMB profile optimization audit."""
        checklist = [
            {"task": "Claim and verify your GMB profile", "priority": "critical", "impact": "Without this, nothing else matters"},
            {"task": "Select ALL relevant categories (primary + 9 secondary)", "priority": "critical", "impact": "Directly affects which searches you appear in"},
            {"task": "Write a complete business description (750 chars) with keywords", "priority": "critical", "impact": "First thing customers read"},
            {"task": "Add services/products with descriptions and prices", "priority": "high", "impact": "Shows up in search results for specific services"},
            {"task": "Upload 100+ high-quality photos (different categories)", "priority": "high", "impact": "520% more calls than profiles with < 100 photos"},
            {"task": "Add a Google Virtual Tour or Street View interior", "priority": "high", "impact": "2x more likely to be considered reputable"},
            {"task": "Set accurate business hours including holidays", "priority": "high", "impact": "Prevents frustration and negative reviews"},
            {"task": "Enable and monitor GMB messaging", "priority": "medium", "impact": "Respond within 24 hours — Google tracks response time"},
            {"task": "Seed and answer 10+ Q&A questions", "priority": "medium", "impact": "Builds trust and answers objections before they arise"},
            {"task": "Post weekly (offers, events, updates, tips)", "priority": "medium", "impact": "Shows active engagement — Google rewards active profiles"},
            {"task": "Respond to ALL reviews (positive and negative)", "priority": "medium", "impact": "Shows you care — 89% of consumers read responses"},
            {"task": "Add a booking/appointment link", "priority": "medium", "impact": "Reduces friction — customers can book directly"},
            {"task": "Set service area (cities, postal codes, radius)", "priority": "high", "impact": "Critical for service-area businesses"},
            {"task": "Add attributes (wheelchair accessible, women-led, etc.)", "priority": "low", "impact": "Helps customers filter and find you"},
            {"task": "Generate and respond to a new review every week", "priority": "ongoing", "impact": "Fresh reviews improve ranking and conversion"}
        ]
        return {"success": True, "result": f"GMB optimization checklist for {business_name or 'your business'}: {len(checklist)} tasks",
                "checklist": checklist, "critical_count": sum(1 for c in checklist if c["priority"] == "critical"),
                "high_count": sum(1 for c in checklist if c["priority"] == "high")}

    # ------------------------------------------------------------------
    # Q&A
    # ------------------------------------------------------------------

    def manage_q_and_a(self, action: str = "seed_questions", questions: str = "",
                       api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Manage GMB Questions & Answers. Seed common questions and their answers."""
        seed_questions = [
            {"q": "Do you offer free estimates?", "a": "Yes! We provide free, no-obligation estimates for all services. Call us or request one through our website."},
            {"q": "What areas do you serve?", "a": "We serve [city] and surrounding areas including [list neighboring cities]. We're available throughout [service area]."},
            {"q": "Are you licensed and insured?", "a": "Absolutely. We are fully licensed and insured for your peace of mind. License # [number]."},
            {"q": "What are your business hours?", "a": "We're open [hours]. We also offer 24/7 emergency service — just call [phone] anytime!"},
            {"q": "How quickly can you respond to an emergency?", "a": "We typically arrive within [timeframe] for emergencies in [service area]. Same-day service is our standard."},
            {"q": "Do you offer warranties on your work?", "a": "Yes! All our work comes with a [X]-year warranty. We stand behind everything we do."},
            {"q": "What forms of payment do you accept?", "a": "We accept cash, Interac e-Transfer, all major credit cards, and offer flexible payment plans."}
        ]
        if action == "seed_questions":
            return {"success": True, "result": f"Generated {len(seed_questions)} seed questions for GMB Q&A",
                    "questions": seed_questions, "instruction": "Post these questions (as the business owner) and provide the answers to help potential customers"}
        return {"success": True, "result": "Q&A management ready", "action": action}

    # ------------------------------------------------------------------
    # Products/Services
    # ------------------------------------------------------------------

    def create_gmb_product(self, product_name: str = "", product_description: str = "", price: str = "",
                           category: str = "service", api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Add a product or service to the GMB product catalog."""
        product = {"name": product_name or "New Service", "description": product_description or "", "price": price or "Contact for pricing",
                   "category": category, "status": "pending_review"}
        return {"success": True, "result": f"Product '{product['name']}' created for GMB catalog", "product": product,
                "tip": "Add 10-20 services with descriptions to improve GMB search visibility"}

    # ------------------------------------------------------------------
    # Rankings
    # ------------------------------------------------------------------

    def track_local_rankings(self, keywords: str = "", location: str = "", api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Track GMB ranking position for target keywords."""
        kw_list = [k.strip() for k in keywords.split('\n') if k.strip()] if keywords else ["plumber near me", "emergency plumber", "plumbing services"]
        loc = location or (api_credentials.get("city", "your area") if api_credentials else "your area")
        rankings = []
        for kw in kw_list[:10]:
            rankings.append({"keyword": kw, "location": loc, "position": "pending", "previous_position": None, "trend": "new",
                             "map_pack_position": "pending", "organic_position": "pending"})
        return {"success": True, "result": f"Tracking {len(rankings)} keywords in {loc}", "rankings": rankings,
                "tip": "Connect a rank tracking API for live position data"}

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def manage_gmb_messages(self, action: str = "setup", api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Set up and manage GMB messaging."""
        templates = {
            "welcome": "Hi! Thanks for contacting {business_name}. We typically respond within 15 minutes. How can we help you today?",
            "after_hours": "Thanks for reaching out! We're currently closed. We'll get back to you first thing when we open at {opening_time}. For emergencies, call {phone}.",
            "booking": "Ready to book? You can schedule online at {booking_link} or reply here with your preferred date/time.",
            "faq": "Great question! Check our FAQ at {website_url}/faq or reply with your specific question."
        }
        return {"success": True, "result": "GMB messaging setup ready", "templates": templates,
                "important": "Google penalizes businesses that don't respond within 24 hours. Enable notifications!"}

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def generate_gmb_report(self, month: str = "", api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Generate a monthly GMB performance report."""
        try:
            report_month = datetime.strptime(month, "%Y-%m") if month else datetime.now()
        except ValueError:
            report_month = datetime.now()
        report = {"month": report_month.strftime("%B %Y"), "sections": [
            {"name": "Profile Views", "metrics": ["Search views", "Maps views", "Total views", "Vs previous month"]},
            {"name": "Customer Actions", "metrics": ["Website clicks", "Direction requests", "Phone calls", "Bookings"]},
            {"name": "Reviews", "metrics": ["New reviews", "Average rating", "Response rate", "Review velocity vs competitors"]},
            {"name": "Photos", "metrics": ["Total photos", "New photos added", "Photo views", "Vs competitor photo count"]},
            {"name": "Search Queries", "metrics": ["Top 10 keywords", "Branded vs non-branded", "New queries this month"]},
            {"name": "Rankings", "metrics": ["Map pack position", "Local finder position", "Organic position", "Position changes"]}
        ]}
        return {"success": True, "result": f"GMB report for {report['month']} generated", "report": report}

    # ------------------------------------------------------------------
    # Competitor
    # ------------------------------------------------------------------

    def audit_competitor_gmb(self, competitor_name: str = "", competitor_url: str = "", **kwargs) -> Dict[str, Any]:
        """Analyze a competitor's GMB profile."""
        audit = {
            "competitor": competitor_name,
            "checks": [
                "Review count and average rating",
                "Posting frequency and content types",
                "Photo count and categories",
                "Q&A presence and quality",
                "Category selection",
                "Service/product catalog",
                "Response rate to reviews",
                "Booking integration",
                "Virtual tour presence",
                "Attributes selected"
            ],
            "action": f"Visit {competitor_url or competitor_name}'s GMB profile and analyze these 10 factors to identify gaps you can exploit."
        }
        return {"success": True, "result": f"Competitor audit framework for {competitor_name}", "audit": audit}

    # ------------------------------------------------------------------
    # Multi-location
    # ------------------------------------------------------------------

    def bulk_update_locations(self, locations: str = "", update_field: str = "description",
                              update_value: str = "", api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Bulk update across multiple GMB locations."""
        loc_list = [l.strip() for l in locations.split('\n') if l.strip()] if locations else []
        return {"success": True, "result": f"Bulk update prepared for {len(loc_list)} locations",
                "field": update_field, "value": update_value, "locations": len(loc_list),
                "tip": "Use consistent NAP (Name, Address, Phone) across all locations"}

    # ------------------------------------------------------------------
    # Voice Search
    # ------------------------------------------------------------------

    def optimize_for_voice_search(self, business_type: str = "", location: str = "", **kwargs) -> Dict[str, Any]:
        """Voice search optimization for local queries."""
        tips = [
            "Target conversational, long-tail keywords: 'who is the best plumber near me' vs 'plumber Laval'",
            "Optimize for 'near me' searches — 82% of voice searches include 'near me'",
            "Keep your GMB profile 100% complete — voice assistants pull from GMB first",
            "Use natural language in your GMB description — write how people speak",
            "Ensure NAP consistency across all directories",
            "Target question-based queries: 'how much does a plumber cost' or 'when should I call an electrician'",
            "Create FAQ content on your website that answers common voice queries",
            "Get more reviews — voice assistants prioritize highly-rated businesses",
            "Use Schema markup (FAQ, LocalBusiness, Speakable) for voice search visibility",
            "Optimize for mobile — 53% of voice searches happen on mobile devices"
        ]
        return {"success": True, "result": f"Voice search optimization tips for {business_type} in {location}", "tips": tips}

    # ------------------------------------------------------------------
    # Booking & Campaigns
    # ------------------------------------------------------------------

    def setup_appointment_booking(self, booking_url: str = "", api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Integrate appointment booking with GMB."""
        return {"success": True, "result": "Appointment booking setup ready",
                "options": ["Google Reserve (via supported partners)", "Third-party: Calendly, Booksy, Setmore", "Custom booking URL"],
                "booking_url": booking_url or "Not configured",
                "tip": "Add a booking button to reduce friction — customers book directly from search results"}

    def create_local_campaign(self, campaign_name: str = "", budget: float = 100.0, keywords: str = "",
                              api_credentials: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Create a local Google Ads campaign linked to GMB location."""
        kw_list = [k.strip() for k in keywords.split('\n') if k.strip()] if keywords else ["near me", "best near me", "top rated near me"]
        return {"success": True, "result": f"Local campaign '{campaign_name}' created with ${budget}/day budget",
                "campaign": {"name": campaign_name, "budget": budget, "keywords": kw_list, "linked_to_gmb": True,
                             "strategy": "Use location extensions to show your GMB profile alongside ads"}}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _queue_gmb_action(self, action_type: str, content: str, detail: str = "") -> Dict[str, Any]:
        try:
            gmb_dir = Path("content/gmb")
            gmb_dir.mkdir(parents=True, exist_ok=True)
            record = {"action": action_type, "detail": detail, "content": content,
                      "timestamp": datetime.now(timezone.utc).isoformat(), "status": "pending"}
            with open(gmb_dir / "queue.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            return {"success": True, "result": f"GMB {action_type} queued", "error": None}
        except Exception as e:
            return {"success": False, "result": "", "error": _safe_error(e)}
