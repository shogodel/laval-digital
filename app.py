import os
import sys
import uuid
import secrets
import warnings
import logging
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def _safe_error(e: Exception, status: int = 500):
    """Log the real error and return a generic response to the client."""
    logger.error("Internal error: %s", e, exc_info=True)
    return jsonify({"error": "An internal error occurred."}), status


# Suppress warnings before any imports that might trigger them
warnings.filterwarnings("ignore", module="langgraph")
warnings.filterwarnings("ignore", module="langchain")

from flask import Flask, render_template, jsonify, request, redirect, url_for, session, flash
from flask_login import login_user, logout_user, login_required, current_user
from dotenv import load_dotenv

load_dotenv()

if not os.getenv("DEEPSEEK_API_KEY"):
    raise RuntimeError(
        "DEEPSEEK_API_KEY environment variable is required. "
        "Create a .env file with DEEPSEEK_API_KEY=your-key-here"
    )
if not os.getenv("FLASK_SECRET_KEY"):
    raise RuntimeError(
        "FLASK_SECRET_KEY environment variable is required. "
        "Create a .env file with FLASK_SECRET_KEY=your-random-secret"
    )
if not os.getenv("ADMIN_USERNAME"):
    raise RuntimeError(
        "ADMIN_USERNAME environment variable is required. "
        "Create a .env file with ADMIN_USERNAME=your-admin-username"
    )
if not os.getenv("ADMIN_PASSWORD"):
    raise RuntimeError(
        "ADMIN_PASSWORD environment variable is required. "
        "Create a .env file with ADMIN_PASSWORD=your-secure-password"
    )

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.orchestrator import Orchestrator
from core.llm_adapter import LLMAdapter
from core.events import get_event_bus
from core.push import PushManager
from core.tenant_manager import TenantManager
from agents.local_seo_agent import LocalSEOAgent
from agents.social_media_agent import SocialMediaAgent
from agents.lead_conversion_agent import LeadConversionAgent
from agents.paid_ads_agent import PaidAdsAgent
from agents.growth_hacker_agent import GrowthHackerAgent
from agents.reputation_agent import ReputationManagementAgent
from agents.email_marketing_agent import EmailMarketingAgent
from agents.tiktok_agent import TikTokAgent
from agents.outreach_agent import OutreachAgent
from agents.backlinks_agent import BacklinksAgent
from agents.content_strategy_agent import ContentStrategyAgent
from agents.technical_seo_agent import TechnicalSEOAgent
from agents.reporting_agent import ReportingAgent
from agents.executioner_agent import ExecutionerAgent
from client_factory import ClientFactory, deploy as client_factory_deploy, deploy_async as client_factory_deploy_async, get_deploy_status as client_factory_get_deploy_status
from core.auth import (
    init_auth, User, find_user_by_email, add_user_to_tenant,
    client_required, affiliate_required, reseller_required,
    validate_password, _check_rate_limit, _record_attempt,
)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
app.permanent_session_lifetime = timedelta(days=30)

# Initialize Tenant Manager for multi-tenant database isolation
tenant_manager = TenantManager()

# Initialize Affiliate Manager (persistent DB-backed affiliate system)
from core.affiliates import AffiliateManager
affiliate_manager = AffiliateManager(tenant_manager)

# Initialize Reseller Manager (persistent DB-backed reseller system)
from core.resellers import ResellerManager
reseller_manager = ResellerManager(tenant_manager)

# Initialize Push Manager (PWA push notifications)
push_manager = PushManager()

# Initialize Flask-Login auth with tenant manager reference
login_manager = init_auth(app, tenant_manager)

# Store active threads and their states (in-memory cache for orchestrator resume)
active_threads: Dict[str, Dict[str, Any]] = {}

# In-memory lead storage (replace with database in production)
leads: list[Dict[str, Any]] = []

RESELLER_MAP_POLICY = """
Resellers agree to the following:
1. Minimum Advertised Price (MAP): All advertised prices must be at or above the MAP.
2. Resellers may sell at any price they choose in private quotes, phone calls, and
   one-on-one negotiations. MAP applies only to publicly advertised prices.
3. Violations will result in a warning, then suspension of reseller privileges.
4. Resellers keep 100% of their markup above the wholesale price.
"""


# ---------------------------------------------------------------------------
# Tenant helpers
# ---------------------------------------------------------------------------

def get_tenant_agent_activity(tenant_id: str) -> dict:
    """Get agent activity telemetry from a tenant's database.

    Args:
        tenant_id: The tenant identifier.

    Returns:
        Dict mapping agent_id to its activity row from the agents table.
    """
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT agent_id, status, last_invoked, task_count, "
            "success_count, failure_count, last_draft_preview FROM agents"
        )
        rows = cursor.fetchall()
        return {row["agent_id"]: dict(row) for row in rows}
    except Exception as e:
        logger.error(f"Failed to get agent activity for tenant {tenant_id}: {e}")
        return {}


def update_tenant_agent_activity(
    tenant_id: str, agent_id: str, **kwargs
) -> None:
    """Update agent activity fields in a tenant's database.

    Args:
        tenant_id: The tenant identifier.
        agent_id: The agent identifier to update.
        **kwargs: Column-value pairs to set on the agents row.
    """
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        for key, value in kwargs.items():
            cursor.execute(
                f"UPDATE agents SET {key} = ? WHERE agent_id = ?",
                (value, agent_id),
            )
        conn.commit()
    except Exception as e:
        logger.error(
            f"Failed to update agent activity for {agent_id} in tenant {tenant_id}: {e}"
        )


def get_current_tenant() -> Optional[str]:
    """Resolve the current tenant from the admin session.

    Returns:
        Tenant ID string, or None if no tenant context is active.
    """
    if session.get("admin_logged_in"):
        return session.get("active_tenant_id", None)
    return None


# ---------------------------------------------------------------------------
# Affiliate referral capture
# ---------------------------------------------------------------------------

@app.before_request
def capture_affiliate_referral():
    """Capture ?ref= parameter into a cookie and store lead info."""
    ref_code = request.args.get("ref")
    if ref_code and affiliate_manager.is_valid_code(ref_code):
        session.permanent = True
        session["affiliate_ref"] = ref_code
        session["affiliate_discount"] = 500
        affiliate_manager.track_lead(
            ref_code=ref_code,
            ip=request.remote_addr or "",
            user_agent=request.headers.get("User-Agent", ""),
            landing_page=request.path,
        )


@login_manager.request_loader
def load_user_from_request(request):
    """Support session-based auth via Flask-Login's request loader."""
    return None


@app.before_request
def check_session_timeout():
    """Log out users after 2 hours of inactivity."""
    if current_user.is_authenticated:
        last_active = session.get("last_active")
        if last_active:
            try:
                last = datetime.fromisoformat(last_active)
                if datetime.now() - last > timedelta(hours=2):
                    logout_user()
                    session.clear()
                    flash("Session expired. Please log in again.", "error")
                    if current_user.role == "client":
                        return redirect(url_for("client_login"))
                    elif current_user.role == "affiliate":
                        return redirect(url_for("affiliate_login"))
                    elif current_user.role == "reseller":
                        return redirect(url_for("reseller_login"))
            except Exception:
                pass
        session["last_active"] = datetime.now().isoformat()


# ---------------------------------------------------------------------------
# Agent configurations
# ---------------------------------------------------------------------------

AGENT_CONFIGS = {
    "local_seo": {
        "agent_id": "local_seo",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/local_seo.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
    "social_media": {
        "agent_id": "social_media",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/social_media.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
    "lead_conversion": {
        "agent_id": "lead_conversion",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/lead_conversion.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
    "paid_ads": {
        "agent_id": "paid_ads",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/paid_ads.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
    "growth_hacker": {
        "agent_id": "growth_hacker",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/growth_hacker.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
    "reputation": {
        "agent_id": "reputation",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/reputation.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
    "email_marketing": {
        "agent_id": "email_marketing",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/email_marketing.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
    "tiktok": {
        "agent_id": "tiktok",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/tiktok_agent.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
    "outreach": {
        "agent_id": "outreach",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/outreach.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
    "backlinks": {
        "agent_id": "backlinks",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/backlinks.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
    "content_strategy": {
        "agent_id": "content_strategy",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/content_strategy.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
    "technical_seo": {
        "agent_id": "technical_seo",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/technical_seo.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
    "reporting": {
        "agent_id": "reporting",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/reporting.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
}

# Initialize LLM Adapter for Orchestrator
llm_adapter = LLMAdapter(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    api_base="https://api.deepseek.com/v1",
)

# Initialize agents (stateless registry — no per-client data)
agent_registry = {}
for agent_id, config in AGENT_CONFIGS.items():
    if agent_id == "local_seo":
        agent_registry[agent_id] = LocalSEOAgent(agent_id, config)
    elif agent_id == "social_media":
        agent_registry[agent_id] = SocialMediaAgent(agent_id, config)
    elif agent_id == "lead_conversion":
        agent_registry[agent_id] = LeadConversionAgent(agent_id, config)
    elif agent_id == "paid_ads":
        agent_registry[agent_id] = PaidAdsAgent(agent_id, config)
    elif agent_id == "growth_hacker":
        agent_registry[agent_id] = GrowthHackerAgent(agent_id, config)
    elif agent_id == "reputation":
        agent_registry[agent_id] = ReputationManagementAgent(agent_id, config)
    elif agent_id == "email_marketing":
        agent_registry[agent_id] = EmailMarketingAgent(agent_id, config)
    elif agent_id == "tiktok":
        agent_registry[agent_id] = TikTokAgent(agent_id, config)
    elif agent_id == "outreach":
        agent_registry[agent_id] = OutreachAgent(agent_id, config)
    elif agent_id == "backlinks":
        agent_registry[agent_id] = BacklinksAgent(agent_id, config)
    elif agent_id == "content_strategy":
        agent_registry[agent_id] = ContentStrategyAgent(agent_id, config)
    elif agent_id == "technical_seo":
        agent_registry[agent_id] = TechnicalSEOAgent(agent_id, config)
    elif agent_id == "reporting":
        agent_registry[agent_id] = ReportingAgent(agent_id, config)

# Agent display metadata for chat interfaces
AGENT_META: Dict[str, Dict[str, str]] = {
    "local_seo": {"name": "Local SEO", "desc": "Google Business Profile optimization, local citations, local keyword content, review management"},
    "social_media": {"name": "Social Media", "desc": "Social media posts, content creation, content calendars, engagement strategies"},
    "lead_conversion": {"name": "Lead Conversion", "desc": "Lead follow-up sequences, CRM integration, conversion optimization, email campaigns"},
    "paid_ads": {"name": "Paid Ads", "desc": "Google & Meta ad campaigns, ad copy creation, keyword strategy, budget allocation, A/B testing, audience targeting"},
    "growth_hacker": {"name": "Growth Hacker", "desc": "Growth audits, viral loops, conversion rate optimization, partnership strategies, data-driven experiments, creative low-cost tactics"},
    "reputation": {"name": "Reputation", "desc": "Online review monitoring, review response generation, review generation campaigns, reputation audits, crisis response"},
    "email_marketing": {"name": "Email Marketing", "desc": "Newsletter campaigns, promotional emails, lead nurture sequences, reactivation campaigns, post-service follow-ups"},
    "tiktok": {"name": "TikTok", "desc": "Short-form video content for TikTok, Instagram Reels, YouTube Shorts, content calendars, video scripts, trend adaptation"},
    "outreach": {"name": "Outreach", "desc": "Prospecting emails, lead finding, campaign sequences, follow-up automation, personalized outreach at scale"},
    "backlinks": {"name": "Backlinks", "desc": "Link building, guest post prospecting, citation building, backlink gap analysis, broken link building, directory submissions"},
    "content_strategy": {"name": "Content Strategist", "desc": "Editorial calendars, multi-channel content repurposing, content briefs, topic clusters, seasonal planning, voice and tone guidelines"},
    "technical_seo": {"name": "Technical SEO", "desc": "Schema markup, site speed optimization, crawl audits, XML sitemaps, core web vitals, mobile optimization, hreflang tags"},
    "reporting": {"name": "Analytics & Reports", "desc": "Cross-channel performance summaries, trend analysis, ROI calculations, executive briefs, monthly client reports"},
}

# Initialize ExecutionerAgent for approved draft execution
executioner = ExecutionerAgent({
    "execution_log_path": "logs/executions.jsonl",
    "max_retries": 3,
    "retry_delay": 5,
})

# Initialize SpeechEngine for optional speech-to-text and text-to-speech
from core.speech import SpeechEngine
speech_engine = SpeechEngine()


# Initialize Orchestrator (cached singleton — shared pending_drafts)
orchestrator = None
orchestrator_graph = None


def get_orchestrator():
    """Return the cached orchestrator singleton.

    Keeps the same instance across requests so in-memory state
    (_pending_drafts) persists. Rebuilds only if the API key changes.
    """
    global llm_adapter, agent_registry, orchestrator, orchestrator_graph

    if orchestrator is not None:
        return orchestrator

    key_preview = llm_adapter._api_key[:10] + "..." if llm_adapter._api_key else "None"
    logger.info(f"Building orchestrator with API key: {key_preview}")

    orchestrator = Orchestrator(llm_adapter, agent_registry, executioner=executioner, push_manager=push_manager)
    return orchestrator


# ---------------------------------------------------------------------------
# Public page routes
# ---------------------------------------------------------------------------

@app.route("/affiliate")
def affiliate_signup():
    """Serve the affiliate program signup page."""
    has_ref = "affiliate_ref" in session
    return render_template("affiliate.html", has_ref=has_ref)


@app.route("/fr/affiliate")
def affiliate_signup_fr():
    """Serve the French affiliate program signup page."""
    has_ref = "affiliate_ref" in session
    return render_template("affiliate_fr.html", has_ref=has_ref)


@app.route("/reseller")
def reseller_program():
    """Serve the white-label reseller program page."""
    return render_template("reseller.html")


@app.route("/fr/reseller")
def reseller_program_fr():
    """Serve the French white-label reseller program page."""
    return render_template("reseller_fr.html")


@app.route("/contract")
def contract():
    """Serve the contract/signup page."""
    return render_template("contract.html")


@app.route("/fr/contract")
def contract_fr():
    """Serve the French contract/signup page."""
    return render_template("contract_fr.html")


@app.route("/")
def home():
    """Serve the new marketing home page."""
    return render_template("home.html")


@app.route("/fr/")
def home_fr():
    """Serve the French marketing home page."""
    return render_template("home_fr.html")


@app.route("/demo")
def demo():
    """Serve the interactive agent demo page."""
    return render_template("demo.html")


@app.route("/fr/demo")
def demo_fr():
    """Serve the French interactive agent demo page."""
    return render_template("demo_fr.html")


@app.route("/blog")
def blog():
    """Serve the blog page."""
    return render_template("blog.html")


@app.route("/fr/blogue")
def blog_fr():
    """Serve the French blog page."""
    return render_template("blog_fr.html")


# ---------------------------------------------------------------------------
# Client auth routes
# ---------------------------------------------------------------------------

@app.route("/client/login", methods=["GET", "POST"])
def client_login():
    """Serve client login page and authenticate."""
    if current_user.is_authenticated and current_user.role == "client":
        return redirect(url_for("client_dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not _check_rate_limit():
            flash("Too many login attempts. Try again later.", "error")
            return render_template("client/login.html")

        user_row, tenant_id, tenant_type = find_user_by_email(email)
        if not user_row or user_row["role"] != "client":
            _record_attempt(False)
            flash("Invalid email or password.", "error")
            return render_template("client/login.html")

        temp_user = User(
            row_id=user_row["id"], email=user_row["email"],
            password_hash=user_row["password_hash"], role=user_row["role"],
            display_name=user_row["display_name"], tenant_id=tenant_id,
        )
        if not temp_user.check_password(password):
            _record_attempt(False)
            flash("Invalid email or password.", "error")
            return render_template("client/login.html")

        login_user(temp_user)
        _record_attempt(True)
        session["tenant_id"] = tenant_id
        session["user_role"] = "client"
        session["last_active"] = datetime.now().isoformat()

        # Update last_login
        try:
            conn = tenant_manager.get_connection(tenant_id, tenant_type)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.now().isoformat(), user_row["id"]),
            )
            conn.commit()
        except Exception:
            pass

        return redirect(url_for("client_dashboard"))

    return render_template("client/login.html")


@app.route("/client/logout")
def client_logout():
    """Log out client and redirect to login."""
    logout_user()
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("client_login"))


@app.route("/client/agent/<agent_id>/chat")
@client_required
def client_agent_chat(agent_id):
    """Serve the client agent chat interface."""
    if agent_id not in agent_registry:
        return "Agent not found", 404
    return render_template(
        "client/agent_chat.html",
        agent_id=agent_id,
        agent=agent_registry[agent_id],
        agent_name=AGENT_META.get(agent_id, {}).get("name", agent_id),
    )


@app.route("/fr/client/agent/<agent_id>/chat")
@client_required
def client_agent_chat_fr(agent_id):
    """Serve the French client agent chat interface."""
    if agent_id not in agent_registry:
        return "Agent introuvable", 404
    return render_template(
        "client/agent_chat_fr.html",
        agent_id=agent_id,
        agent=agent_registry[agent_id],
        agent_name=AGENT_META.get(agent_id, {}).get("name", agent_id),
    )


@app.route("/client/dashboard")
@client_required
def client_dashboard():
    """Serve the client project dashboard."""
    tenant_id = current_user.tenant_id

    # Gather payment info from tenant database
    payments = []
    total_paid = 0
    total_owed = 0
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM payments ORDER BY installment_number")
        for row in cursor.fetchall():
            p = dict(row)
            payments.append(p)
            if p.get("paid"):
                total_paid += p["amount"]
            else:
                total_owed += p["amount"]
    except Exception:
        pass

    # Gather site URL from client_details
    site_url = None
    managed = False
    managed_since = None
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT site_url, managed_service, managed_since FROM client_details LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            site_url = row["site_url"]
            managed = bool(row.get("managed_service", False))
            ms = row.get("managed_since")
            managed_since = ms[:10] if ms else None
    except Exception:
        pass

    return render_template(
        "client/dashboard.html",
        payments=payments,
        total_paid=total_paid,
        total_owed=total_owed,
        site_url=site_url,
        project_status="Live" if site_url else "In Progress",
        active_agents=11,
        tasks_this_month=0,
        managed=managed,
        managed_since=managed_since,
    )


# ---------------------------------------------------------------------------
# Affiliate auth routes
# ---------------------------------------------------------------------------

@app.route("/affiliate/login", methods=["GET", "POST"])
def affiliate_login():
    """Serve affiliate login page and authenticate."""
    if current_user.is_authenticated and current_user.role == "affiliate":
        return redirect(url_for("affiliate_dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not _check_rate_limit():
            flash("Too many login attempts. Try again later.", "error")
            return render_template("affiliate/login.html")

        user_row, tenant_id, tenant_type = find_user_by_email(email)
        if not user_row or user_row["role"] != "affiliate":
            _record_attempt(False)
            flash("Invalid email or password.", "error")
            return render_template("affiliate/login.html")

        temp_user = User(
            row_id=user_row["id"], email=user_row["email"],
            password_hash=user_row["password_hash"], role=user_row["role"],
            display_name=user_row["display_name"], tenant_id=tenant_id,
        )
        if not temp_user.check_password(password):
            _record_attempt(False)
            flash("Invalid email or password.", "error")
            return render_template("affiliate/login.html")

        login_user(temp_user)
        _record_attempt(True)
        session["tenant_id"] = tenant_id
        session["user_role"] = "affiliate"
        session["last_active"] = datetime.now().isoformat()

        try:
            conn = tenant_manager.get_connection(tenant_id, tenant_type)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.now().isoformat(), user_row["id"]),
            )
            conn.commit()
        except Exception:
            pass

        return redirect(url_for("affiliate_dashboard"))

    return render_template("affiliate/login.html")


@app.route("/affiliate/logout")
def affiliate_logout():
    """Log out affiliate and redirect to login."""
    logout_user()
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("affiliate_login"))


@app.route("/affiliate/dashboard")
@affiliate_required
def affiliate_dashboard():
    """Serve the affiliate referral dashboard."""
    tenant_id = current_user.tenant_id

    # Gather affiliate profile from platform DB
    aff = affiliate_manager.get_affiliate(tenant_id)
    profile = aff or {}

    # Gather leads from affiliate's tenant DB
    referrals = affiliate_manager.get_leads(tenant_id)
    stats = {"total_clicks": 0, "total_leads": 0, "total_clients": 0, "total_commissions": 0}
    for r in referrals:
        if r.get("status") == "client":
            stats["total_clients"] += 1
            stats["total_commissions"] += r.get("commission") or 0
        else:
            stats["total_leads"] += 1

    # Gather commissions from platform DB
    commissions = affiliate_manager.get_commissions(tenant_id)

    # Gather payouts
    payouts = affiliate_manager.get_payouts(tenant_id)

    # Build referral link
    referral_link = f"https://lavaldigital.ca/?ref={tenant_id}"

    return render_template(
        "affiliate/dashboard.html",
        stats=stats,
        referrals=referrals,
        payouts=payouts,
        commissions=commissions,
        profile=profile,
        referral_link=referral_link,
    )


# ---------------------------------------------------------------------------
# Reseller auth routes
# ---------------------------------------------------------------------------

@app.route("/reseller/login", methods=["GET", "POST"])
def reseller_login():
    """Serve reseller login page and authenticate."""
    if current_user.is_authenticated and current_user.role == "reseller":
        return redirect(url_for("reseller_dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not _check_rate_limit():
            flash("Too many login attempts. Try again later.", "error")
            return render_template("reseller/login.html")

        user_row, tenant_id, tenant_type = find_user_by_email(email)
        if not user_row or user_row["role"] != "reseller":
            _record_attempt(False)
            flash("Invalid email or password.", "error")
            return render_template("reseller/login.html")

        temp_user = User(
            row_id=user_row["id"], email=user_row["email"],
            password_hash=user_row["password_hash"], role=user_row["role"],
            display_name=user_row["display_name"], tenant_id=tenant_id,
        )
        if not temp_user.check_password(password):
            _record_attempt(False)
            flash("Invalid email or password.", "error")
            return render_template("reseller/login.html")

        login_user(temp_user)
        _record_attempt(True)
        session["tenant_id"] = tenant_id
        session["user_role"] = "reseller"
        session["last_active"] = datetime.now().isoformat()

        try:
            conn = tenant_manager.get_connection(tenant_id, tenant_type)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.now().isoformat(), user_row["id"]),
            )
            conn.commit()
        except Exception:
            pass

        return redirect(url_for("reseller_dashboard"))

    return render_template("reseller/login.html")


@app.route("/reseller/logout")
def reseller_logout():
    """Log out reseller and redirect to login."""
    logout_user()
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("reseller_login"))


@app.route("/reseller/dashboard")
@reseller_required
def reseller_dashboard():
    """Serve the reseller white-label dashboard."""
    tenant_id = current_user.tenant_id

    reseller_stats = reseller_manager.get_reseller_stats(tenant_id)

    agency_name = ""
    try:
        conn = tenant_manager.get_connection(tenant_id, "reseller")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT business_name FROM client_details WHERE business_name IS NOT NULL LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            agency_name = row["business_name"]
    except Exception:
        pass

    tier = reseller_stats.get("tier", "standard")
    pricing = reseller_manager.get_pricing(tier)

    return render_template(
        "reseller/dashboard.html",
        clients=reseller_stats.get("clients", []),
        stats={
            "total_clients": reseller_stats.get("total_clients", 0),
            "monthly_recurring": reseller_stats.get("monthly_recurring", 0),
            "pending_deployments": reseller_stats.get("pending_deployments", 0),
            "live_sites": reseller_stats.get("live_sites", 0),
        },
        agency_name=agency_name,
        map_pricing=pricing,
        map_policy=RESELLER_MAP_POLICY,
        tier_name=tier,
        mrr_per_client=reseller_stats.get("mrr_per_client", 1500),
    )


# ---------------------------------------------------------------------------
# API: User management (admin only)
# ---------------------------------------------------------------------------

@app.route("/api/users", methods=["GET"])
def api_list_users():
    """List all users for the active tenant (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    tenant_id = session.get("active_tenant_id")
    if not tenant_id:
        return jsonify({"error": "No client selected"}), 400

    role_filter = request.args.get("role", "").strip().lower()

    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        if role_filter in ("client", "affiliate", "reseller"):
            cursor.execute(
                "SELECT id, email, display_name, role, created_at, last_login "
                "FROM users WHERE role = ? ORDER BY created_at DESC",
                (role_filter,),
            )
        else:
            cursor.execute(
                "SELECT id, email, display_name, role, created_at, last_login "
                "FROM users ORDER BY created_at DESC"
            )
        users = [dict(row) for row in cursor.fetchall()]
        return jsonify({"users": users})
    except Exception as e:
        return _safe_error(e, 500)


@app.route("/api/users", methods=["POST"])
def api_add_user():
    """Add a user to the active tenant (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    tenant_id = session.get("active_tenant_id")
    if not tenant_id:
        return jsonify({"error": "No client selected"}), 400

    data = request.json
    email = (data.get("email") or "").strip()
    password = data.get("password", "")
    role = data.get("role", "client")
    display_name = (data.get("display_name") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    is_valid, err_msg = validate_password(password)
    if not is_valid:
        return jsonify({"error": err_msg}), 400

    try:
        result = add_user_to_tenant(email, password, role, display_name, tenant_id)
        return jsonify(result), 201
    except ValueError as e:
        return _safe_error(e, 400)
    except RuntimeError as e:
        return _safe_error(e, 500)


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
def api_delete_user(user_id):
    """Delete a user from the active tenant (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    tenant_id = session.get("active_tenant_id")
    if not tenant_id:
        return jsonify({"error": "No client selected"}), 400

    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "User not found"}), 404
        return jsonify({"success": True, "message": "User deleted"})
    except Exception as e:
        return _safe_error(e, 500)


# ---------------------------------------------------------------------------
# Admin auth routes
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Serve the admin login page and handle authentication."""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        expected_user = os.getenv("ADMIN_USERNAME")
        expected_pass = os.getenv("ADMIN_PASSWORD")
        if username == expected_user and password == expected_pass:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_panel_redirect"))
        return render_template(
            "login.html", error="Invalid username or password.", now=datetime.now()
        )
    return render_template("login.html", now=datetime.now())


@app.route("/admin/logout")
def admin_logout():
    """Log out and redirect to login."""
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
def admin_panel_redirect():
    """Serve the admin panel with session-based auth."""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    logo_status = request.args.get("logo_uploaded", "")
    tenants = {
        "direct_clients": tenant_manager.list_tenants("direct"),
        "resellers": tenant_manager.list_tenants("reseller"),
    }
    active_tenant = session.get("active_tenant_id")
    return render_template(
        "admin.html",
        logo_uploaded=logo_status,
        tenants=tenants,
        active_tenant=active_tenant,
    )


@app.route("/admin/agent/<agent_id>/chat")
def admin_agent_chat(agent_id):
    """Serve the admin agent chat interface."""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    if agent_id not in agent_registry:
        return "Agent not found", 404
    return render_template(
        "admin/agent_chat.html",
        agent_id=agent_id,
        agent=agent_registry[agent_id],
        agent_name=AGENT_META.get(agent_id, {}).get("name", agent_id),
    )


@app.route("/fr/admin/agent/<agent_id>/chat")
def admin_agent_chat_fr(agent_id):
    """Serve the French admin agent chat interface."""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login_fr"))
    if agent_id not in agent_registry:
        return "Agent introuvable", 404
    return render_template(
        "admin/agent_chat_fr.html",
        agent_id=agent_id,
        agent=agent_registry[agent_id],
        agent_name=AGENT_META.get(agent_id, {}).get("name", agent_id),
    )


@app.route("/fr/admin/login", methods=["GET", "POST"])
def admin_login_fr():
    """Serve the French admin login page."""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        expected_user = os.getenv("ADMIN_USERNAME")
        expected_pass = os.getenv("ADMIN_PASSWORD")
        if username == expected_user and password == expected_pass:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_panel_redirect_fr"))
        return render_template(
            "login_fr.html",
            error="Nom d'utilisateur ou mot de passe invalide.",
            now=datetime.now(),
        )
    return render_template("login_fr.html", now=datetime.now())


@app.route("/fr/admin/logout")
def admin_logout_fr():
    """Log out from French admin and redirect to login."""
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login_fr"))


@app.route("/fr/admin")
def admin_panel_redirect_fr():
    """Serve the French admin panel with session-based auth."""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login_fr"))
    logo_status = request.args.get("logo_uploaded", "")
    tenants = {
        "direct_clients": tenant_manager.list_tenants("direct"),
        "resellers": tenant_manager.list_tenants("reseller"),
    }
    active_tenant = session.get("active_tenant_id")
    return render_template(
        "admin_fr.html",
        logo_uploaded=logo_status,
        tenants=tenants,
        active_tenant=active_tenant,
    )


@app.route("/admin/logo", methods=["POST"])
def admin_upload_logo():
    """Upload a custom logo PNG or SVG to replace the default."""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    if "logo" not in request.files:
        return redirect(url_for("admin_panel_redirect"))
    file = request.files["logo"]
    if file.filename == "":
        return redirect(url_for("admin_panel_redirect"))
    if file and (
        file.filename.lower().endswith(".png")
        or file.filename.lower().endswith(".svg")
    ):
        ext = file.filename.rsplit(".", 1)[1].lower()
        save_path = os.path.join(app.root_path, "static", f"logo_custom.{ext}")
        file.save(save_path)
        other_ext = "svg" if ext == "png" else "png"
        other_path = os.path.join(
            app.root_path, "static", f"logo_custom.{other_ext}"
        )
        if os.path.exists(other_path):
            os.remove(other_path)
        session["logo_ext"] = ext
        return redirect(
            url_for("admin_panel_redirect", logo_uploaded="success")
        )
    return redirect(url_for("admin_panel_redirect", logo_uploaded="invalid"))


@app.context_processor
def inject_logo():
    """Inject the current logo filename into all templates."""
    for ext in ("png", "svg"):
        path = os.path.join(app.root_path, "static", f"logo_custom.{ext}")
        if os.path.exists(path):
            return dict(logo_file=f"logo_custom.{ext}")
    return dict(logo_file="logo.svg")


# ---------------------------------------------------------------------------
# API: affiliate
# ---------------------------------------------------------------------------

@app.route("/api/affiliate/status")
def affiliate_status():
    """Return current affiliate status for the visitor."""
    ref_code = session.get("affiliate_ref")
    if ref_code and affiliate_manager.is_valid_code(ref_code):
        aff = affiliate_manager.get_affiliate(ref_code)
        if aff:
            return jsonify({
                "active": True,
                "code": ref_code,
                "discount": 500,
                "affiliate_name": aff.get("name", "Partner"),
            })
    return jsonify({"active": False, "discount": 0})


@app.route("/api/affiliate/signup", methods=["POST"])
def affiliate_signup_api():
    """Register a new affiliate and return their referral code."""
    data = request.json
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()

    if not name or not email:
        return jsonify({"error": "Name and email are required"}), 400

    try:
        aff = affiliate_manager.create_affiliate(name, email, phone)
        code = aff["code"]

        password = secrets.token_urlsafe(12) + "A1!"
        try:
            add_user_to_tenant(email, password, "affiliate", name, code, "direct")
            logger.info("Affiliate user created: %s (tenant=%s)", email, code)
        except Exception as e:
            logger.error("Failed to create affiliate user for %s: %s", email, e)
            return jsonify({
                "success": False,
                "error": "Account creation failed. Please try again later.",
            }), 500

        return jsonify({
            "success": True,
            "code": code,
            "referral_link": f"https://lavaldigital.ca/?ref={code}",
            "password": password,
            "message": "Your login credentials have been created. Please check your email for your password.",
        }), 201
    except Exception as e:
        logger.error("Affiliate signup failed: %s", e, exc_info=True)
        return jsonify({"success": False, "error": "Signup failed. Please try again."}), 500


# ---------------------------------------------------------------------------
# API: affiliate payouts
# ---------------------------------------------------------------------------


@app.route("/api/affiliate/commissions", methods=["GET"])
@affiliate_required
def api_affiliate_commissions():
    """Return the current affiliate's commission history."""
    tenant_id = current_user.tenant_id
    commissions = affiliate_manager.get_commissions(tenant_id)
    total_pending = sum(c["amount"] for c in commissions if c["status"] == "pending")
    total_paid = sum(c["amount"] for c in commissions if c["status"] == "paid")
    return jsonify({
        "commissions": commissions,
        "total_pending": total_pending,
        "total_paid": total_paid,
    })


@app.route("/api/affiliate/payouts", methods=["GET"])
@affiliate_required
def api_affiliate_payouts():
    """Return the current affiliate's payout history."""
    tenant_id = current_user.tenant_id
    return jsonify({"payouts": affiliate_manager.get_payouts(tenant_id)})


@app.route("/api/affiliate/payouts", methods=["POST"])
@affiliate_required
def api_request_payout():
    """Request a payout for the current affiliate's pending commissions."""
    tenant_id = current_user.tenant_id
    commissions = affiliate_manager.get_commissions(tenant_id)
    total_pending = sum(c["amount"] for c in commissions if c["status"] == "pending")
    if total_pending < 50:
        return jsonify({"error": "Minimum payout is $50. You have $" + str(round(total_pending, 2))}), 400
    payout_id = affiliate_manager.create_payout(tenant_id, total_pending)
    if payout_id:
        return jsonify({"success": True, "payout_id": payout_id, "amount": total_pending})
    return jsonify({"error": "Failed to create payout"}), 500


@app.route("/api/admin/affiliates", methods=["GET"])
def api_admin_affiliates():
    """List all affiliates with stats (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    affiliates = affiliate_manager.get_all_affiliates()
    commissions = affiliate_manager.get_all_commissions(limit=200)
    payouts = affiliate_manager.get_payouts(limit=200)
    return jsonify({
        "affiliates": affiliates,
        "recent_commissions": commissions,
        "recent_payouts": payouts,
    })


@app.route("/api/admin/affiliates/<code>/payout", methods=["POST"])
def api_admin_process_payout(code):
    """Process (approve) a payout for an affiliate (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    payout_id = data.get("payout_id", "")
    if not payout_id:
        return jsonify({"error": "payout_id required"}), 400
    success = affiliate_manager.process_payout(payout_id)
    if success:
        return jsonify({"success": True, "message": "Payout processed"})
    return jsonify({"error": "Payout not found or already processed"}), 404


# ---------------------------------------------------------------------------
# API: reseller admin
# ---------------------------------------------------------------------------


_reseller_spots = 17


@app.route("/api/reseller/spots", methods=["GET"])
def api_reseller_spots():
    return jsonify({"spots_remaining": _reseller_spots})


@app.route("/api/admin/reseller/spots", methods=["PUT"])
def api_admin_set_spots():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if data and "spots" in data:
        global _reseller_spots
        _reseller_spots = int(data["spots"])
    return jsonify({"spots_remaining": _reseller_spots})


@app.route("/api/admin/reseller/tiers", methods=["GET"])
def api_admin_reseller_tiers():
    """Return all reseller tiers (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"tiers": reseller_manager.get_tiers()})


@app.route("/api/admin/reseller/tiers/<tier>", methods=["PUT"])
def api_admin_update_tier(tier):
    """Update a reseller tier (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
    ok = reseller_manager.update_tier(tier, **data)
    return jsonify({"success": ok})


@app.route("/api/admin/reseller/pricing", methods=["GET"])
def api_admin_reseller_pricing():
    """Return pricing for all tiers (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    tier = request.args.get("tier", "standard")
    return jsonify({"pricing": reseller_manager.get_pricing(tier)})


@app.route("/api/admin/reseller/pricing/<tier>/<package>", methods=["PUT"])
def api_admin_update_pricing(tier, package):
    """Update pricing for a specific tier + package (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
    ok = reseller_manager.update_pricing(tier, package, **data)
    return jsonify({"success": ok})


@app.route("/api/admin/reseller/applications", methods=["GET"])
def api_admin_reseller_applications():
    """Return reseller applications (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    status = request.args.get("status", "").strip() or None
    return jsonify({"applications": reseller_manager.get_applications(status)})


@app.route("/api/admin/reseller/applications/<app_id>/process", methods=["POST"])
def api_admin_process_application(app_id):
    """Approve or reject a reseller application (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    status = data.get("status", "approved") if data else "approved"
    tier = data.get("tier", "standard") if data else "standard"
    ok = reseller_manager.process_application(app_id, status, tier)
    return jsonify({"success": ok})


@app.route("/api/contract/submit", methods=["POST"])
def contract_submit():
    """Submit a signed agreement and create a user account."""
    data = request.json
    name = (data.get("name") or "").strip()
    business = (data.get("business") or "").strip()
    email = (data.get("email") or "").strip()

    if not name or not business or not email:
        return jsonify({"error": "Name, business, and email are required"}), 400

    contract_data = {
        "id": str(uuid.uuid4()),
        "name": name,
        "business": business,
        "email": email,
        "phone": data.get("phone", ""),
        "address": data.get("address", ""),
        "package": data.get("package", ""),
        "packageName": data.get("packageName", ""),
        "totalPrice": data.get("totalPrice", 0),
        "deposit": data.get("deposit", 0),
        "affiliateCode": data.get("affiliateCode", ""),
        "signedAt": data.get("signedAt", datetime.now().isoformat()),
        "created_at": datetime.now().isoformat(),
    }
    leads.append(contract_data)

    password = secrets.token_urlsafe(12) + "A1!"
    subdomain = business.lower().replace(" ", "-").replace("'", "")[:40]
    try:
        tenant_manager.create_tenant_database(subdomain, "direct")
        add_user_to_tenant(email, password, "client", name, subdomain, "direct")
        logger.info("Client user created: %s (tenant=%s)", email, subdomain)
    except Exception as e:
        logger.error("Failed to create client user for %s: %s", email, e)
        return jsonify({
            "success": False,
            "error": "Account creation failed. Please try again later.",
            "contract_id": contract_data["id"],
        }), 500

    logger.info("Contract submitted by %s (%s) — package: %s", name, email, contract_data["package"])

    # Credit affiliate if a valid referral code was attached
    affiliate_info = None
    affiliate_code = contract_data.get("affiliateCode", "")
    if affiliate_code and affiliate_manager.is_valid_code(affiliate_code):
        commission = round(float(contract_data.get("deposit", 0)) * 0.10, 2)
        try:
            commission_id = affiliate_manager.add_commission(
                affiliate_code, email, name, commission,
            )
            if commission_id:
                aff = affiliate_manager.get_affiliate(affiliate_code)
                affiliate_info = {
                    "code": affiliate_code,
                    "affiliate_name": aff.get("name", "Partner") if aff else "Partner",
                    "commission": commission,
                }
                logger.info(
                    "Affiliate %s credited $%.2f for referral %s",
                    affiliate_code, commission, email,
                )
        except Exception as e:
            logger.error(
                "Failed to credit affiliate %s for %s: %s",
                affiliate_code, email, e,
            )

    response_data = {
        "success": True,
        "contract_id": contract_data["id"],
        "password": password,
        "tenant_id": subdomain,
        "message": "Your account has been created. Please check your email for login credentials.",
    }
    if affiliate_info:
        response_data["affiliate"] = affiliate_info
    return jsonify(response_data), 201


@app.route("/api/reseller/apply", methods=["POST"])
def reseller_apply():
    """Submit a reseller application."""
    data = request.json
    agency = (data.get("agencyName") or "").strip()
    contact = (data.get("contactName") or "").strip()
    email = (data.get("email") or "").strip()

    if not agency or not contact or not email:
        return jsonify({"error": "Agency name, contact name, and email are required"}), 400

    try:
        application = reseller_manager.create_application(
            agency, contact, email,
            phone=data.get("phone", ""),
            client_count=data.get("clientCount", ""),
        )
    except Exception as e:
        logger.error("Failed to create reseller application: %s", e)
        return jsonify({"success": False, "error": "Application failed. Please try again."}), 500

    password = secrets.token_urlsafe(12) + "A1!"
    agency_slug = agency.lower().replace(" ", "-").replace("'", "")[:40]
    try:
        tenant_manager.create_tenant_database(agency_slug, "reseller")
        add_user_to_tenant(email, password, "reseller", agency, agency_slug, "reseller")
        logger.info("Reseller user created: %s (tenant=%s)", email, agency_slug)
    except Exception as e:
        logger.error("Failed to create reseller user for %s: %s", email, e)
        return jsonify({
            "success": False,
            "error": "Account creation failed. Please try again later.",
            "application_id": application["id"],
        }), 500

    logger.info("Reseller application received — %s (%s)", agency, email)
    return jsonify({
        "success": True,
        "application_id": application["id"],
        "password": password,
        "tenant_id": agency_slug,
    }), 201


# ---------------------------------------------------------------------------
# API: leads
# ---------------------------------------------------------------------------

@app.route("/api/leads", methods=["GET", "POST"])
def handle_leads():
    """Capture and list lead form submissions."""
    if request.method == "POST":
        data = request.json
        lead = {
            "id": str(uuid.uuid4()),
            "name": data.get("name", ""),
            "phone": data.get("phone", ""),
            "service": data.get("service", ""),
            "urgency": data.get("urgency", ""),
            "created_at": datetime.now().isoformat(),
        }
        if not lead["name"] or not lead["phone"]:
            return jsonify({"error": "Name and phone are required"}), 400
        leads.append(lead)
        return jsonify({"status": "ok", "lead": lead}), 201
    return jsonify({"leads": leads})


# ---------------------------------------------------------------------------
# API: agents (tenant-aware)
# ---------------------------------------------------------------------------

@app.route("/api/agents", methods=["GET"])
def get_agents():
    """Get status and activity telemetry of all agents."""
    tenant_id = get_current_tenant()

    agents_status = []

    if tenant_id:
        activity = get_tenant_agent_activity(tenant_id)
        for agent_id, agent in agent_registry.items():
            act = activity.get(agent_id, {})
            agents_status.append({
                "agent_id": agent_id,
                "enabled": agent.enabled,
                "model": agent.model,
                "status": act.get("status", "idle"),
                "last_invoked": act.get("last_invoked"),
                "task_count": act.get("task_count", 0),
                "success_count": act.get("success_count", 0),
                "failure_count": act.get("failure_count", 0),
                "last_draft_preview": act.get("last_draft_preview"),
            })
    else:
        for agent_id, agent in agent_registry.items():
            agents_status.append({
                "agent_id": agent_id,
                "enabled": agent.enabled,
                "model": agent.model,
                "status": "idle",
                "last_invoked": None,
                "task_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "last_draft_preview": None,
            })

    return jsonify({"agents": agents_status})


@app.route("/api/agents/<agent_id>/toggle", methods=["POST"])
def toggle_agent(agent_id):
    """Toggle agent on/off."""
    if agent_id not in agent_registry:
        return jsonify({"error": "Agent not found"}), 404

    agent = agent_registry[agent_id]
    agent.enabled = not agent.enabled

    # Persist toggle to tenant database only if a tenant is selected
    tenant_id = get_current_tenant()
    if tenant_id:
        try:
            conn = tenant_manager.get_connection(tenant_id)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE agents SET enabled = ? WHERE agent_id = ?",
                (int(agent.enabled), agent_id),
            )
            conn.commit()
        except Exception:
            pass

    return jsonify({"agent_id": agent_id, "enabled": agent.enabled})


# ---------------------------------------------------------------------------
# API: agent config
# ---------------------------------------------------------------------------

@app.route("/api/agents/<agent_id>/config", methods=["GET"])
def get_agent_config(agent_id):
    """Get configuration for a specific agent."""
    if agent_id not in AGENT_CONFIGS:
        return jsonify({"error": "Agent not found"}), 404
    config = AGENT_CONFIGS[agent_id]
    return jsonify({
        "agent_id": agent_id,
        "model": config.get("model", "deepseek-chat"),
        "api_key": config.get("credentials", {}).get("api_key", ""),
        "api_base": config.get("credentials", {}).get("api_base", ""),
    })


@app.route("/api/agents/<agent_id>/config", methods=["POST"])
def update_agent_config(agent_id):
    """Update configuration for a specific agent."""
    if agent_id not in AGENT_CONFIGS:
        return jsonify({"error": "Agent not found"}), 404

    data = request.json
    config = AGENT_CONFIGS[agent_id]

    if "model" in data:
        if not LLMAdapter.is_valid_model(data["model"]):
            return jsonify({"error": f"Invalid model '{data['model']}'"}), 400
        config["model"] = data["model"]

    if "api_key" in data:
        config["credentials"]["api_key"] = data["api_key"]

    if "api_base" in data:
        config["credentials"]["api_base"] = data["api_base"]

    # Re-initialize the agent with new config
    _reinitialize_agent(agent_id, config)

    # Rebuild orchestrator with updated agent
    global orchestrator, orchestrator_graph
    orchestrator = Orchestrator(llm_adapter, agent_registry, executioner=executioner, push_manager=push_manager)
    orchestrator_graph = orchestrator.build_graph()

    return jsonify({
        "agent_id": agent_id,
        "model": config["model"],
        "message": "Configuration updated and agent reinitialized",
    })


@app.route("/api/agents/bulk/config", methods=["POST"])
def update_all_agents_config():
    """Apply the same configuration to ALL agents at once."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    model = data.get("model")
    api_key = data.get("api_key")
    api_base = data.get("api_base")

    updated_count = 0

    for agent_id, config in AGENT_CONFIGS.items():
        changed = False

        if model and model != "__keep__":
            if LLMAdapter.is_valid_model(model):
                config["model"] = model
                changed = True

        if api_key:
            config["credentials"]["api_key"] = api_key
            changed = True

        if api_base:
            config["credentials"]["api_base"] = api_base
            changed = True

        if changed:
            updated_count += 1

        _reinitialize_agent(agent_id, config)

    # Also update the global llm_adapter so the orchestrator uses the new key
    global llm_adapter, orchestrator, orchestrator_graph
    if api_key:
        llm_adapter = LLMAdapter(
            model=model if model and model != "__keep__" and LLMAdapter.is_valid_model(model) else llm_adapter.model,
            api_key=api_key,
            api_base=api_base or llm_adapter._api_base,
            temperature=llm_adapter._temperature,
        )

    orchestrator = Orchestrator(llm_adapter, agent_registry, executioner=executioner, push_manager=push_manager)
    orchestrator_graph = orchestrator.build_graph()

    return jsonify({
        "success": True,
        "message": f"Updated {updated_count} agents",
        "updated": updated_count,
        "applied": {
            "model": model or "(unchanged)",
            "api_key": "****" + (api_key[-4:] if api_key and len(api_key) > 4 else "") if api_key else "(unchanged)",
            "api_base": api_base or "(unchanged)"
        }
    })


def _reinitialize_agent(agent_id: str, config: dict) -> None:
    """Re-initialize a single agent in the registry with a new config.

    Args:
        agent_id: The agent identifier.
        config: The updated configuration dict.
    """
    if agent_id == "local_seo":
        agent_registry[agent_id] = LocalSEOAgent(agent_id, config)
    elif agent_id == "social_media":
        agent_registry[agent_id] = SocialMediaAgent(agent_id, config)
    elif agent_id == "lead_conversion":
        agent_registry[agent_id] = LeadConversionAgent(agent_id, config)
    elif agent_id == "paid_ads":
        agent_registry[agent_id] = PaidAdsAgent(agent_id, config)
    elif agent_id == "growth_hacker":
        agent_registry[agent_id] = GrowthHackerAgent(agent_id, config)
    elif agent_id == "reputation":
        agent_registry[agent_id] = ReputationManagementAgent(agent_id, config)
    elif agent_id == "email_marketing":
        agent_registry[agent_id] = EmailMarketingAgent(agent_id, config)
    elif agent_id == "tiktok":
        agent_registry[agent_id] = TikTokAgent(agent_id, config)
    elif agent_id == "outreach":
        agent_registry[agent_id] = OutreachAgent(agent_id, config)
    elif agent_id == "backlinks":
        agent_registry[agent_id] = BacklinksAgent(agent_id, config)
    elif agent_id == "content_strategy":
        agent_registry[agent_id] = ContentStrategyAgent(agent_id, config)
    elif agent_id == "technical_seo":
        agent_registry[agent_id] = TechnicalSEOAgent(agent_id, config)
    elif agent_id == "reporting":
        agent_registry[agent_id] = ReportingAgent(agent_id, config)


@app.route("/api/agents/config/bulk", methods=["POST"])
def bulk_update_agent_config():
    """Update configuration for multiple agents at once.

    Accepts a JSON body with:
        agent_ids (list): List of agent IDs to update.
        model (str, optional): Model name to set on all listed agents.
        api_key (str, optional): API key to set on all listed agents.
        api_base (str, optional): API base URL to set on all listed agents.

    Returns a summary of which agents were updated and any errors.
    """
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    agent_ids = data.get("agent_ids", [])
    model = data.get("model")
    api_key = data.get("api_key")
    api_base = data.get("api_base")

    if not agent_ids:
        return jsonify({"error": "agent_ids list is required"}), 400

    results = {"updated": [], "errors": []}

    for agent_id in agent_ids:
        if agent_id not in AGENT_CONFIGS:
            results["errors"].append({"agent_id": agent_id, "error": "Agent not found"})
            continue

        config = AGENT_CONFIGS[agent_id]

        if model:
            if not LLMAdapter.is_valid_model(model):
                results["errors"].append({"agent_id": agent_id, "error": f"Invalid model '{model}'"})
                continue
            config["model"] = model

        if api_key is not None:
            config["credentials"]["api_key"] = api_key

        if api_base is not None:
            config["credentials"]["api_base"] = api_base

        # Re-initialize the agent with new config
        _reinitialize_agent(agent_id, config)
        results["updated"].append(agent_id)

    # Rebuild orchestrator if any agent was updated
    if results["updated"]:
        global orchestrator, orchestrator_graph
        orchestrator = Orchestrator(llm_adapter, agent_registry, executioner=executioner, push_manager=push_manager)
        orchestrator_graph = orchestrator.build_graph()

    return jsonify({
        "updated": results["updated"],
        "errors": results["errors"],
        "message": f"Updated {len(results['updated'])} agent(s) with {len(results['errors'])} error(s)",
    })


# ---------------------------------------------------------------------------
# API: models
# ---------------------------------------------------------------------------

@app.route("/api/models", methods=["GET"])
def get_available_models():
    """Return list of all available LLM models via litellm."""
    try:
        models = LLMAdapter.get_available_models()
        return jsonify({"models": models})
    except Exception:
        return jsonify({
            "models": ["deepseek-chat", "gpt-4o", "claude-3.5-sonnet"]
        })


@app.route("/api/models/detect", methods=["POST"])
def detect_models():
    """Detect provider from API key and return available models."""
    data = request.json
    api_key = data.get("api_key", "")
    if not api_key:
        return jsonify({"error": "API key is required"}), 400
    try:
        result = LLMAdapter.detect_models(api_key)
        return jsonify(result)
    except Exception as e:
        logger.error("Model detection failed: %s", e, exc_info=True)
        return jsonify({
            "provider": "unknown", "models": [], "error": "Model detection failed."
        }), 500


# ---------------------------------------------------------------------------
# API: executioner
# ---------------------------------------------------------------------------

@app.route("/api/executioner/settings", methods=["GET", "PUT"])
def handle_executioner_settings():
    """Get or update ExecutionerAgent settings."""
    if request.method == "PUT":
        data = request.json
        if data:
            executioner.update_settings(data)
        return jsonify(executioner.get_public_settings())
    return jsonify(executioner.get_public_settings())


@app.route("/api/executioner/test-smtp", methods=["POST"])
def test_smtp():
    """Send a test email to verify SMTP configuration."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    to_email = data.get("to_email", "")
    if not to_email:
        return jsonify({"error": "No recipient email provided"}), 400

    try:
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText("This is a test email from your Laval Digital platform. Your SMTP configuration is working correctly! 🚀")
        msg["Subject"] = "Laval Digital — SMTP Test Email"
        msg["From"] = data.get("smtp_from_email", "")
        msg["To"] = to_email

        server = smtplib.SMTP(data.get("smtp_host", "smtp.gmail.com"),
                              int(data.get("smtp_port", 587)), timeout=15)
        if data.get("smtp_use_tls", True):
            server.starttls()
        server.login(data.get("smtp_username", ""), data.get("smtp_password", ""))
        server.send_message(msg)
        server.quit()

        return jsonify({"success": True, "message": "Test email sent"})
    except Exception as e:
        logger.error("Internal error: %s", e, exc_info=True); return jsonify({"success": False, "error": "An internal error occurred."}), 500


@app.route("/api/executioner/validate-social-key", methods=["POST"])
def validate_social_key():
    """Validate a unified social media API key and return connected accounts."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    provider = data.get("provider", "socialapi")
    api_key = data.get("api_key", "")

    if not api_key:
        return jsonify({"error": "No API key provided"}), 400

    try:
        if provider == "socialapi":
            from socialapi import SocialAPI
            client = SocialAPI(api_key=api_key)
            accounts = client.accounts.list()
            return jsonify({
                "success": True,
                "accounts": [{"platform": a.platform, "account_name": a.account_name} for a in accounts]
            })
        else:
            return jsonify({"success": False, "error": f"Provider '{provider}' is not yet supported."})
    except ImportError:
        return jsonify({"success": False, "error": "socialapi package is not installed. Run: pip install socialapi"})
    except Exception as e:
        logger.error("Internal error: %s", e, exc_info=True); return jsonify({"success": False, "error": "An internal error occurred."}), 500


@app.route("/api/executioner/social-settings", methods=["POST"])
def save_social_settings():
    """Save the unified social media settings to the Executioner."""
    data = request.json
    executioner.update_settings({
        "social_api_provider": data.get("provider", "socialapi"),
        "social_api_key": data.get("api_key", ""),
    })
    return jsonify({"success": True, "message": "Social media settings saved."})


@app.route("/api/executioner/pending", methods=["GET"])
def get_pending_executions():
    """Get all executions awaiting confirmation."""
    return jsonify({"pending": executioner.get_pending_executions()})


@app.route("/api/executioner/confirm/<execution_id>", methods=["POST"])
def confirm_execution(execution_id):
    """Confirm and execute a queued execution."""
    try:
        result = executioner.confirm_execution(execution_id)
        return jsonify(result)
    except Exception as e:
        return _safe_error(e, 400)


@app.route("/api/executioner/reject/<execution_id>", methods=["POST"])
def reject_execution(execution_id):
    """Reject a queued execution without running it."""
    try:
        result = executioner.reject_execution(execution_id)
        return jsonify(result)
    except Exception as e:
        return _safe_error(e, 400)


@app.route("/api/executioner/execute-chat", methods=["POST"])
def execute_chat_response():
    """Execute an agent response directly from the chat interface."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    agent_id = data.get("agent_id", "")
    content = data.get("content", "")

    if not agent_id or not content:
        return jsonify({"error": "Agent ID and content are required"}), 400

    try:
        result = executioner.execute(agent_id, content)
        return jsonify(result)
    except Exception as e:
        return _safe_error(e, 500)


@app.route("/api/executions", methods=["GET"])
def get_executions():
    """Get recent execution history."""
    limit = request.args.get("limit", 50, type=int)
    history = executioner.get_execution_history(limit)
    return jsonify({"executions": history})


# ---------------------------------------------------------------------------
# API: speech (optional speech-to-text & text-to-speech)
# ---------------------------------------------------------------------------


@app.route("/api/speech/settings", methods=["GET"])
def get_speech_settings():
    """Get current speech engine settings (public, no secrets)."""
    return jsonify(speech_engine.get_public_settings())


@app.route("/api/speech/settings", methods=["PUT"])
def update_speech_settings():
    """Update speech engine settings."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
    speech_engine.update_settings(data)
    return jsonify(speech_engine.get_public_settings())


@app.route("/api/speech/stt", methods=["POST"])
def speech_to_text():
    """Transcribe uploaded audio to text.

    Expects multipart form with an 'audio' file field.
    Optional 'language' field (default 'en').
    """
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files["audio"]
    language = request.form.get("language", "en")

    try:
        text = speech_engine.transcribe(audio_file.read(), language)
        return jsonify({"text": text, "language": language})
    except Exception as e:
        logger.error("Speech-to-text failed: %s", e)
        return _safe_error(e, 500)


@app.route("/api/speech/tts", methods=["POST"])
def text_to_speech():
    """Synthesize speech from text and return audio.

    Expects JSON with 'text' and optional 'language' (default 'en').
    Returns audio/mpeg bytes.
    """
    data = request.json
    if not data or not data.get("text"):
        return jsonify({"error": "No text provided"}), 400

    text = data["text"]
    language = data.get("language", "en")

    try:
        audio_bytes = speech_engine.synthesize(text, language)
        return (audio_bytes, 200, {"Content-Type": "audio/mpeg"})
    except Exception as e:
        logger.error("Text-to-speech failed: %s", e)
        return _safe_error(e, 500)


@app.route("/api/speech/voices", methods=["GET"])
def get_speech_voices():
    """Return available voices for the configured TTS provider."""
    provider = speech_engine.get_settings().get("tts_provider", "browser")
    if provider == "openai":
        return jsonify({"voices": ["alloy", "echo", "fable", "nova", "shimmer"]})
    elif provider == "elevenlabs":
        api_key = speech_engine.get_settings().get("elevenlabs_api_key", "")
        if not api_key:
            return jsonify({"voices": []})
        try:
            resp = requests.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            voices = [{"id": v["voice_id"], "name": v["name"]} for v in resp.json().get("voices", [])]
            return jsonify({"voices": voices})
        except Exception:
            return jsonify({"voices": []})
    return jsonify({"voices": []})


# ---------------------------------------------------------------------------
# API: tasks & approvals (tenant-aware)
# ---------------------------------------------------------------------------

@app.route("/api/tasks", methods=["POST"])
def submit_task():
    """Submit a task to the chat orchestrator for immediate response."""
    data = request.json
    user_request = data.get("request", "").strip()

    if not user_request:
        return jsonify({"error": "No request provided"}), 400

    thread_id = data.get("thread_id", str(uuid.uuid4()))
    language = data.get("language", "")

    try:
        orch = get_orchestrator()

        # Load autonomy settings if tenant is active
        autonomy_config = None
        tenant_id = get_current_tenant()
        if tenant_id:
            autonomy_config = tenant_manager.get_agent_autonomy(tenant_id)

        result = orch.process_message(
            user_request, thread_id,
            language=language or None,
            autonomy_config=autonomy_config,
        )

        return jsonify(result)
    except Exception as e:
        logger.error("Task failed: %s", e, exc_info=True)
        return jsonify({
            "response": "I had trouble processing that request. Please try again.",
            "agent": "error",
            "status": "error",
            "thread_id": thread_id,
            "pending_approval": False
        }), 500


@app.route("/api/approvals", methods=["GET"])
def get_approvals():
    """Get pending approvals from the orchestrator's in-memory store."""
    orch = get_orchestrator()
    approvals = []
    for thread_id, draft_info in orch._pending_drafts.items():
        approvals.append({
            "thread_id": thread_id,
            "agent": draft_info.get("agent", "unknown"),
            "draft": draft_info.get("draft", ""),
            "task": draft_info.get("task", "")
        })
    logger.info(f"Returning {len(approvals)} pending approvals")
    return jsonify({"approvals": approvals})


@app.route("/api/orchestrator/welcome", methods=["POST"])
def api_orchestrator_welcome():
    """Get a welcome message from the orchestrator."""
    data = request.json or {}
    language = data.get("language", "en")
    orch = get_orchestrator()
    return jsonify(orch.get_welcome(language))


@app.route("/api/orchestrator/suggestions", methods=["POST"])
def api_orchestrator_suggestions():
    """Get proactive suggestions from the orchestrator."""
    data = request.json or {}
    language = data.get("language", "en")
    orch = get_orchestrator()
    return jsonify(orch.get_suggestions(language))


# ---------------------------------------------------------------------------
# API: autonomy & panic
# ---------------------------------------------------------------------------


@app.route("/api/orchestrator/panic", methods=["POST"])
def api_panic():
    """Stop all auto-executions immediately."""
    orch = get_orchestrator()
    orch.panic()
    return jsonify({"status": "panicked", "message": "All agents stopped."})


@app.route("/api/orchestrator/resume", methods=["POST"])
def api_resume():
    """Resume auto-executions after a panic."""
    orch = get_orchestrator()
    orch.clear_panic()
    return jsonify({"status": "active", "message": "Agents resumed."})


@app.route("/api/orchestrator/status", methods=["GET"])
def api_orchestrator_status():
    """Return orchestrator status (panicked, pending drafts, activity count)."""
    orch = get_orchestrator()
    return jsonify({
        "panicked": orch.is_panicked,
        "pending_drafts": len(orch._pending_drafts),
        "activity_count": len(orch._activity_feed),
    })


@app.route("/api/orchestrator/activity", methods=["GET"])
def api_activity():
    """Return the orchestrator's activity feed."""
    limit = request.args.get("limit", 50, type=int)
    orch = get_orchestrator()
    return jsonify({"activities": orch.get_activity_feed(limit)})


@app.route("/api/events/stream")
def api_events_stream():
    """Server-Sent Events stream for real-time agent dashboard.

    Yields SSE-formatted events as they happen. The client reconnects
    automatically on disconnect (built into EventSource API).
    """
    event_bus = get_event_bus()
    q = event_bus.subscribe()

    def generate():
        from queue import Empty as _QueueEmpty
        try:
            while True:
                try:
                    event = q.get(timeout=10)
                    yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                except _QueueEmpty:
                    yield f"event: heartbeat\ndata: {{\"ts\": \"{datetime.now(timezone.utc).isoformat()}\"}}\n\n"
        except GeneratorExit:
            event_bus.unsubscribe(q)

    return app.response_class(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/events/history", methods=["GET"])
def api_events_history():
    """Return recent event history for dashboard bootstrapping."""
    limit = request.args.get("limit", 100, type=int)
    event_type = request.args.get("type", "").strip() or None
    agent = request.args.get("agent", "").strip() or None
    events = get_event_bus().get_history(limit=limit, event_type=event_type, agent=agent)
    return jsonify({"events": events})


@app.route("/api/events/stats", methods=["GET"])
def api_events_stats():
    """Return aggregate event stats for the dashboard."""
    return jsonify(get_event_bus().get_stats())


# ---------------------------------------------------------------------------
# API: PWA push notifications
# ---------------------------------------------------------------------------


@app.route("/api/push/vapid-key", methods=["GET"])
def api_push_vapid_key():
    """Return the VAPID public key for push subscription."""
    return jsonify({"public_key": push_manager.public_key, "enabled": push_manager.enabled})


@app.route("/api/push/subscribe", methods=["POST"])
def api_push_subscribe():
    """Store a push subscription from the browser."""
    data = request.json
    if not data:
        return jsonify({"error": "No subscription data"}), 400
    ok = push_manager.subscribe(data)
    return jsonify({"success": ok})


@app.route("/api/push/unsubscribe", methods=["POST"])
def api_push_unsubscribe():
    """Remove a push subscription."""
    data = request.json
    endpoint = (data or {}).get("endpoint", "")
    if not endpoint:
        return jsonify({"error": "No endpoint"}), 400
    ok = push_manager.unsubscribe(endpoint)
    return jsonify({"success": ok})


@app.route("/admin/dashboard")
def admin_dashboard():
    """Serve the real-time agent dashboard."""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    tenants = {
        "direct_clients": tenant_manager.list_tenants("direct"),
        "resellers": tenant_manager.list_tenants("reseller"),
    }
    active_tenant = session.get("active_tenant_id")
    return render_template(
        "admin/dashboard.html",
        tenants=tenants,
        active_tenant=active_tenant,
        agents=AGENT_META,
    )


# ---------------------------------------------------------------------------
# Connector page (bookmarklet + email bridge setup)
# ---------------------------------------------------------------------------


@app.route("/admin/connector")
def admin_connector():
    """Serve the connector setup page (bookmarklet + email bridge)."""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    tenant_id = session.get("active_tenant_id", "your-tenant")
    bookmarklet_code = (
        'javascript:(function(){var s=document.createElement("script");'
        's.src="https://lavaldigital.ca/static/bookmarklet.js";'
        "document.body.appendChild(s);})()"
    )
    return render_template(
        "admin/connector.html",
        bookmarklet_code=bookmarklet_code,
        tenant_id=tenant_id,
    )


# ---------------------------------------------------------------------------
# Pending actions API (for bookmarklet + email bridge)
# ---------------------------------------------------------------------------


def _get_pending_actions(tenant_id: str, status: str = "pending") -> list:
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, agent_name, tool_name, provider, content, subject, status, created_at "
            "FROM pending_actions WHERE status = ? ORDER BY created_at DESC LIMIT 50",
            (status,),
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error("Failed to get pending actions for %s: %s", tenant_id, e)
        return []


def _add_pending_action(
    tenant_id: str, agent_name: str, tool_name: str,
    content: str, provider: str = "web", subject: str = "",
) -> str:
    action_id = uuid.uuid4().hex[:12]
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO pending_actions (id, agent_name, tool_name, provider, content, subject, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (action_id, agent_name, tool_name, provider, content, subject, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return action_id
    except Exception as e:
        logger.error("Failed to add pending action: %s", e)
        return ""


def _confirm_pending_action(tenant_id: str, action_id: str) -> Dict[str, Any]:
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, agent_name, tool_name, content FROM pending_actions WHERE id = ? AND status = 'pending'",
            (action_id,),
        )
        row = cursor.fetchone()
        if not row:
            return {"success": False, "error": "Action not found or already completed"}
        # Execute via executioner
        from agents.executioner_agent import ExecutionerError
        try:
            exec_result = executioner.execute(row["agent_name"], row["content"], tool_name=row["tool_name"])
            cursor.execute(
                "UPDATE pending_actions SET status = 'completed', completed_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), action_id),
            )
            conn.commit()
            return {"success": True, "result": exec_result.get("result", "Done"), "action_id": action_id}
        except ExecutionerError as ee:
            return {"success": False, "error": str(ee)}
    except Exception as e:
        logger.error("Failed to confirm action %s: %s", action_id, e)
        return {"success": False, "error": "Internal error"}


@app.route("/api/actions/pending", methods=["GET"])
def api_pending_actions():
    """Return pending actions for the current tenant (used by bookmarklet)."""
    tenant_id = session.get("active_tenant_id") or getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return jsonify({"actions": []})
    actions = _get_pending_actions(tenant_id)
    return jsonify({"actions": actions})


@app.route("/api/actions/<action_id>/confirm", methods=["POST"])
def api_confirm_action(action_id):
    """Confirm and execute a pending action (called by bookmarklet or email bridge)."""
    tenant_id = session.get("active_tenant_id") or getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return jsonify({"error": "No tenant context"}), 400
    result = _confirm_pending_action(tenant_id, action_id)
    return jsonify(result)


@app.route("/api/actions/<action_id>/skip", methods=["POST"])
def api_skip_action(action_id):
    """Skip/discard a pending action without executing."""
    tenant_id = session.get("active_tenant_id") or getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return jsonify({"error": "No tenant context"}), 400
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE pending_actions SET status = 'skipped', completed_at = ? WHERE id = ? AND status = 'pending'",
            (datetime.now(timezone.utc).isoformat(), action_id),
        )
        conn.commit()
        return jsonify({"success": True, "action_id": action_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/actions/bridge/email", methods=["POST"])
def api_set_email_bridge():
    """Configure the email bridge for the current user."""
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
    # Store email bridge settings in the tenant DB
    tenant_id = current_user.tenant_id
    settings = {
        "imap_host": data.get("imap_host", "imap.gmail.com"),
        "imap_port": int(data.get("imap_port", 993)),
        "username": data.get("email", ""),
        "password": data.get("password", ""),
    }
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO client_details (id, email, services) "
            "VALUES (1, COALESCE((SELECT email FROM client_details WHERE id=1), ?), ?)",
            (settings["username"], json.dumps({"email_bridge": settings})),
        )
        conn.commit()
        # Restart bridge with new settings
        bridge = _get_email_bridge()
        bridge.stop()
        bridge2 = EmailBridge(
            imap_host=settings["imap_host"],
            imap_port=settings["imap_port"],
            username=settings["username"],
            password=settings["password"],
        )
        bridge2.set_handler(lambda action, subj, body: _email_bridge_handler(action, subj, body, tenant_id))
        bridge2.start()
        _set_email_bridge(bridge2)
        return jsonify({"success": True, "message": "Email bridge configured"})
    except Exception as e:
        logger.error("Email bridge setup failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


# Email bridge handler
def _email_bridge_handler(action: str, subject: str, body: str, tenant_id: str) -> None:
    if action == "approve":
        actions = _get_pending_actions(tenant_id)
        if actions:
            _confirm_pending_action(tenant_id, actions[0]["id"])
            logger.info("Email bridge approved action %s for %s", actions[0]["id"], tenant_id)
    elif action == "reject":
        actions = _get_pending_actions(tenant_id)
        if actions:
            try:
                conn = tenant_manager.get_connection(tenant_id)
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE pending_actions SET status = 'skipped', completed_at = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), actions[0]["id"]),
                )
                conn.commit()
            except Exception:
                pass


_email_bridge_instance = None


def _get_email_bridge():
    global _email_bridge_instance
    if _email_bridge_instance is None:
        from core.email_bridge import EmailBridge
        _email_bridge_instance = EmailBridge()
        _email_bridge_instance.set_handler(lambda a, s, b: _email_bridge_handler(a, s, b, ""))
    return _email_bridge_instance


def _set_email_bridge(bridge):
    global _email_bridge_instance
    _email_bridge_instance = bridge


# Start email bridge on boot (if configured in env)
if os.getenv("EMAIL_BRIDGE_USER") and os.getenv("EMAIL_BRIDGE_PASS"):
    _bridge = EmailBridge(
        imap_host=os.getenv("EMAIL_BRIDGE_HOST", "imap.gmail.com"),
        imap_port=int(os.getenv("EMAIL_BRIDGE_PORT", "993")),
        username=os.getenv("EMAIL_BRIDGE_USER"),
        password=os.getenv("EMAIL_BRIDGE_PASS"),
    )
    _bridge.set_handler(lambda a, s, b: _email_bridge_handler(a, s, b, ""))

    import threading
    threading.Thread(target=_bridge.start, daemon=True).start()


@app.route("/api/agents/<agent_id>/autonomy", methods=["GET", "PUT"])
def api_agent_autonomy(agent_id):
    """Get or update autonomy settings for an agent in the current tenant."""
    tenant_id = get_current_tenant()
    if not tenant_id:
        return jsonify({"error": "No tenant selected"}), 400

    if request.method == "PUT":
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400

        autonomy = data.get("autonomy", "manual")
        threshold = float(data.get("confidence_threshold", 0.7))

        if autonomy not in ("manual", "suggest", "auto", "silent"):
            return jsonify({"error": f"Invalid autonomy '{autonomy}'. Must be one of: manual, suggest, auto, silent"}), 400

        tenant_manager.set_agent_autonomy(tenant_id, agent_id, autonomy, threshold)
        return jsonify({"agent_id": agent_id, "autonomy": autonomy, "confidence_threshold": threshold})

    # GET: return current settings
    configs = tenant_manager.get_agent_autonomy(tenant_id)
    cfg = configs.get(agent_id, {"autonomy": "manual", "confidence_threshold": 0.7})
    return jsonify({"agent_id": agent_id, **cfg})


@app.route("/api/agents/autonomy/bulk", methods=["GET"])
def api_all_agent_autonomy():
    """Get autonomy settings for all agents in the current tenant."""
    tenant_id = get_current_tenant()
    if not tenant_id:
        return jsonify({"error": "No tenant selected"}), 400
    configs = tenant_manager.get_agent_autonomy(tenant_id)
    return jsonify({"autonomy": configs})


# ---------------------------------------------------------------------------
# API: approvals
# ---------------------------------------------------------------------------


@app.route("/api/approvals/<thread_id>/respond", methods=["POST"])
def respond_approval(thread_id):
    """Respond to an approval request using the chat orchestrator."""
    data = request.json
    approved = data.get("approved", False)
    now_iso = datetime.now().isoformat()
    tenant_id = get_current_tenant()

    orch = get_orchestrator()

    # Delegate to orchestrator which now handles execution internally
    if thread_id in orch._pending_drafts:
        result = orch._handle_approval(thread_id, approved=approved)
        return jsonify({
            "thread_id": thread_id,
            "status": "completed" if approved else "rejected",
            "execution": result.get("execution"),
            "response": result.get("response"),
        })

    # Fallback: check tenant database if no in-memory draft found
    if tenant_id:
        try:
            conn = tenant_manager.get_connection(tenant_id)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT routed_agent, agent_draft FROM threads WHERE thread_id = ?",
                (thread_id,),
            )
            row = cursor.fetchone()
            if not row:
                return jsonify({"error": "Thread not found"}), 404

            agent_name = row["routed_agent"]
            draft = row["agent_draft"]
            execution_result = None

            cursor.execute(
                """
                UPDATE threads
                SET approved = ?, status = 'completed', updated_at = ?
                WHERE thread_id = ?
                """,
                (int(approved), now_iso, thread_id),
            )
            conn.commit()

            if approved and agent_name and agent_name in agent_registry:
                try:
                    exec_result = executioner.execute(agent_name, draft)
                    execution_result = {
                        "success": exec_result.get("success", False),
                        "result": exec_result.get("result", "")
                    }
                except Exception as exec_err:
                    execution_result = {"success": False, "error": str(exec_err)}

            return jsonify({
                "thread_id": thread_id,
                "status": "completed",
                "execution": execution_result
            })
        except Exception as e:
            return _safe_error(e, 500)

    return jsonify({"error": "Thread not found"}), 404


# ---------------------------------------------------------------------------
# API: agent direct invoke
# ---------------------------------------------------------------------------

@app.route("/api/agents/<agent_id>/invoke", methods=["POST"])
def invoke_agent(agent_id):
    """Directly invoke a specific agent (bypass orchestrator)."""
    if agent_id not in agent_registry:
        return jsonify({"error": "Agent not found"}), 404

    agent = agent_registry[agent_id]

    if not agent.enabled:
        return jsonify({"error": "Agent is disabled"}), 403

    data = request.json
    task = data.get("task")

    if not task:
        return jsonify({"error": "No task provided"}), 400

    tenant_id = get_current_tenant()
    now_iso = datetime.now().isoformat()

    try:
        if tenant_id:
            try:
                update_tenant_agent_activity(
                    tenant_id, agent_id, status="processing"
                )
            except Exception:
                pass

        graph = agent.build_graph()
        result = graph.invoke({
            "task": task,
            "draft_output": None,
            "approved": None,
            "feedback": None,
            "result": None,
        })

        draft = result.get("draft_output", "")
        draft_preview = (draft[:120] + "...") if len(draft) > 120 else draft

        if tenant_id:
            try:
                update_tenant_agent_activity(
                    tenant_id,
                    agent_id,
                    status="idle",
                    last_invoked=now_iso,
                    last_draft_preview=draft_preview,
                )
            except Exception:
                pass

        return jsonify({"agent_id": agent_id, "result": result})
    except Exception as e:
        if tenant_id:
            try:
                update_tenant_agent_activity(
                    tenant_id, agent_id, status="idle"
                )
            except Exception:
                pass
        return _safe_error(e, 500)


@app.route("/api/agents/<agent_id>/chat", methods=["POST"])
def agent_chat(agent_id):
    """
    Send a message directly to a specific agent and get its response.
    Supports conversation threading -- pass an existing thread_id to continue
    a conversation with full context.

    Request body:
    {
        "message": "Write a blog post about winter plumbing tips",
        "thread_id": "optional-existing-thread-uuid"
    }

    Response:
    {
        "agent_id": "local_seo",
        "response": "Here's your blog post...",
        "thread_id": "abc-123",
        "thinking": "[Agent processed using deepseek-chat]",
        "model": "deepseek-chat"
    }
    """
    if agent_id not in agent_registry:
        return jsonify({"error": f"Agent '{agent_id}' not found"}), 404

    agent = agent_registry[agent_id]
    if not agent.enabled:
        return jsonify({"error": "Agent is disabled"}), 403

    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    message = data.get("message", "").strip()
    thread_id = data.get("thread_id", str(uuid.uuid4()))
    language = data.get("language", "")

    if not message:
        return jsonify({"error": "No message provided"}), 400

    if not language:
        from core.base_agent import BaseAgent
        language = BaseAgent._detect_language(message)

    tenant_id = get_current_tenant()
    now_iso = datetime.now().isoformat()

    # Build conversation context from previous messages in this thread
    conversation_context = ""
    if tenant_id:
        try:
            conn = tenant_manager.get_connection(tenant_id)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT agent_task, agent_draft FROM threads WHERE thread_id = ? ORDER BY created_at ASC LIMIT 20",
                (thread_id,)
            )
            history = cursor.fetchall()
            if history:
                conversation_context = "\n\n--- Previous conversation in this thread ---\n"
                for row in history:
                    conversation_context += f"User: {row['agent_task']}\nAgent: {row['agent_draft'][:300]}...\n"
                conversation_context += "--- End of history ---\n\n"
        except Exception:
            pass

    # Build the full task with context
    full_task = f"{conversation_context}Current request: {message}" if conversation_context else message

    try:
        # Use the agent's existing graph to generate a response
        graph = agent.build_graph()
        result = graph.invoke(
            {
                "task": full_task,
                "draft_output": None,
                "approved": None,
                "feedback": None,
                "result": None,
            },
            config={"configurable": {"thread_id": thread_id}}
        )

        draft = result.get("draft_output", "")

        # Store the conversation turn in the tenant database
        if tenant_id:
            try:
                conn = tenant_manager.get_connection(tenant_id)
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO threads
                       (thread_id, routed_agent, agent_task, agent_draft, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'chat', ?, ?)""",
                    (thread_id, agent_id, message, draft, now_iso, now_iso)
                )
                conn.commit()
            except Exception:
                pass

        # Update agent activity
        if tenant_id:
            try:
                update_tenant_agent_activity(
                    tenant_id,
                    agent_id,
                    status="idle",
                    last_invoked=now_iso,
                    last_draft_preview=(draft[:120] + "...") if len(draft) > 120 else draft,
                )
            except Exception:
                pass

        return jsonify({
            "agent_id": agent_id,
            "response": draft,
            "thread_id": thread_id,
            "language": language,
            "thinking": f"Agent '{agent_id}' processed your request using model '{agent.model}'. The agent applied its specialized system prompt to generate this response.",
            "model": agent.model,
        })
    except Exception as e:
        logger.error(f"Agent chat failed for {agent_id}: {e}")
        return _safe_error(e, 500)


@app.route("/api/agents/<agent_id>/threads", methods=["GET"])
def get_agent_threads(agent_id):
    """
    Get all chat threads for a specific agent in the current tenant.
    Returns list of thread IDs with preview of the first message.
    """
    if agent_id not in agent_registry:
        return jsonify({"error": f"Agent '{agent_id}' not found"}), 404

    tenant_id = get_current_tenant()
    if not tenant_id:
        return jsonify({"threads": []})

    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            """SELECT DISTINCT thread_id,
                      MIN(created_at) as started_at,
                      (SELECT agent_task FROM threads t2 WHERE t2.thread_id = threads.thread_id ORDER BY created_at ASC LIMIT 1) as first_message
               FROM threads
               WHERE routed_agent = ? AND status = 'chat'
               GROUP BY thread_id
               ORDER BY started_at DESC LIMIT 30""",
            (agent_id,)
        )
        threads = []
        for row in cursor.fetchall():
            threads.append({
                "thread_id": row["thread_id"],
                "started_at": row["started_at"],
                "first_message": (row["first_message"] or "")[:80] + "..." if row["first_message"] and len(row["first_message"]) > 80 else (row["first_message"] or "New conversation"),
            })
        return jsonify({"threads": threads})
    except Exception as e:
        return _safe_error(e, 500)


@app.route("/api/agents/<agent_id>/threads/<thread_id>", methods=["GET"])
def get_agent_thread_history(agent_id, thread_id):
    """
    Get the full conversation history for a specific thread.
    Returns all messages in chronological order.
    """
    if agent_id not in agent_registry:
        return jsonify({"error": f"Agent '{agent_id}' not found"}), 404

    tenant_id = get_current_tenant()
    if not tenant_id:
        return jsonify({"messages": []})

    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            """SELECT agent_task, agent_draft, created_at
               FROM threads
               WHERE thread_id = ? AND routed_agent = ?
               ORDER BY created_at ASC""",
            (thread_id, agent_id)
        )
        messages = []
        for row in cursor.fetchall():
            messages.append({
                "role": "user",
                "content": row["agent_task"],
                "timestamp": row["created_at"],
            })
            messages.append({
                "role": "agent",
                "content": row["agent_draft"],
                "timestamp": row["created_at"],
            })
        return jsonify({"messages": messages, "thread_id": thread_id, "agent_id": agent_id})
    except Exception as e:
        return _safe_error(e, 500)


@app.route("/api/threads")
def api_list_threads():
    """List chat threads for the current tenant, optionally filtered by agent."""
    if session.get("admin_logged_in"):
        tenant_id = session.get("active_tenant_id")
    else:
        tenant_id = getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return jsonify({"threads": []})

    agent_filter = request.args.get("agent", "")
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        if agent_filter:
            cursor.execute(
                ("SELECT thread_id, agent_task, created_at FROM threads "
                 "WHERE status = 'chat' AND routed_agent = ? "
                 "ORDER BY created_at DESC LIMIT 50"),
                (agent_filter,),
            )
        else:
            cursor.execute(
                "SELECT thread_id, agent_task, created_at FROM threads WHERE status = 'chat' ORDER BY created_at DESC LIMIT 50"
            )
        rows = cursor.fetchall()
        return jsonify({
            "threads": [
                {"thread_id": r["thread_id"], "agent_task": r["agent_task"], "created_at": r["created_at"]}
                for r in rows
            ]
        })
    except Exception as e:
        return _safe_error(e, 500)


@app.route("/api/threads/<thread_id>/messages")
def api_get_thread_messages(thread_id):
    """Get all messages in a chat thread."""
    if session.get("admin_logged_in"):
        tenant_id = session.get("active_tenant_id")
    else:
        tenant_id = getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return jsonify({"messages": []})

    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT agent_task, agent_draft, result FROM threads WHERE thread_id = ? AND status = 'chat' ORDER BY created_at ASC",
            (thread_id,),
        )
        rows = cursor.fetchall()
        messages = []
        for r in rows:
            messages.append({"role": "user", "content": r["agent_task"]})
            messages.append({"role": "agent", "content": r["agent_draft"], "thinking": None})
        return jsonify({"messages": messages})
    except Exception as e:
        return _safe_error(e, 500)


@app.route("/api/client/threads")
@client_required
def api_client_list_threads():
    """List chat threads for the current client, optionally filtered by agent."""
    tenant_id = current_user.tenant_id
    agent_filter = request.args.get("agent", "")
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        if agent_filter:
            cursor.execute(
                ("SELECT thread_id, agent_task, created_at FROM threads "
                 "WHERE status = 'chat' AND routed_agent = ? "
                 "ORDER BY created_at DESC LIMIT 50"),
                (agent_filter,),
            )
        else:
            cursor.execute(
                "SELECT thread_id, agent_task, created_at FROM threads WHERE status = 'chat' ORDER BY created_at DESC LIMIT 50"
            )
        rows = cursor.fetchall()
        return jsonify({
            "threads": [
                {"thread_id": r["thread_id"], "agent_task": r["agent_task"], "created_at": r["created_at"]}
                for r in rows
            ]
        })
    except Exception:
        return jsonify({"threads": []})


@app.route("/api/client/threads/<thread_id>/messages")
@client_required
def api_client_get_thread_messages(thread_id):
    """Get all messages in a chat thread for the current client."""
    tenant_id = current_user.tenant_id
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT agent_task, agent_draft FROM threads WHERE thread_id = ? AND status = 'chat' ORDER BY created_at ASC",
            (thread_id,),
        )
        rows = cursor.fetchall()
        messages = []
        for r in rows:
            messages.append({"role": "user", "content": r["agent_task"]})
            messages.append({"role": "agent", "content": r["agent_draft"]})
        return jsonify({"messages": messages})
    except Exception:
        return jsonify({"messages": []})


# ---------------------------------------------------------------------------
# API: tenant management (admin only)
# ---------------------------------------------------------------------------

@app.route("/api/tenants", methods=["GET"])
def list_tenants():
    """List all tenants (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    direct = tenant_manager.list_tenants("direct")
    resellers = tenant_manager.list_tenants("reseller")

    return jsonify({
        "direct_clients": direct,
        "resellers": resellers,
        "active_tenant": session.get("active_tenant_id"),
    })


@app.route("/api/tenants/switch", methods=["POST"])
def switch_tenant():
    """Switch the admin's active tenant context."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    tenant_id = data.get("tenant_id")

    if tenant_id:
        session["active_tenant_id"] = tenant_id
        return jsonify({
            "active_tenant": tenant_id,
            "message": f"Switched to {tenant_id}",
        })
    else:
        session.pop("active_tenant_id", None)
        return jsonify({
            "active_tenant": None,
            "message": "Client cleared",
        })


# ---------------------------------------------------------------------------
# API: client deployment via Client Factory
# ---------------------------------------------------------------------------

@app.route("/api/clients/deploy", methods=["POST"])
def deploy_client():
    """Deploy a new client website via the Client Factory.

    Supports both synchronous (default) and async (``?async=1``) modes.
    In async mode returns a deployment ID for status polling.
    """
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    config = request.json
    if not config:
        return jsonify({"success": False, "error": "No configuration provided"}), 400

    async_mode = request.args.get("async", "").strip() in ("1", "true", "yes")

    try:
        if async_mode:
            deploy_id = client_factory_deploy_async(config)
            return jsonify({"deploy_id": deploy_id, "status": "running"}), 202
        result = client_factory_deploy(config)
        return jsonify(result), 200 if result.get("success") else 500
    except Exception as e:
        logger.error("Client deployment failed: %s", e, exc_info=True)
        return jsonify({"success": False, "error": "An internal error occurred."}), 500


@app.route("/api/clients/deploy/<deploy_id>/status", methods=["GET"])
def deploy_status(deploy_id):
    """Poll the status of an async deployment."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    status = client_factory_get_deploy_status(deploy_id)
    if not status:
        return jsonify({"error": "Deployment not found"}), 404
    return jsonify(status)


# ---------------------------------------------------------------------------
# Analytics routes
# ---------------------------------------------------------------------------

from core.analytics import AnalyticsEngine


@app.route("/api/analytics/summary")
def api_analytics_summary():
    """Return summary analytics for a tenant or all tenants (admin)."""
    tenant_id = request.args.get("client", "").strip()
    days = int(request.args.get("days", 30))
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    is_admin = session.get("admin_logged_in", False)
    session_tenant = session.get("active_tenant_id") or getattr(current_user, "tenant_id", None)

    if tenant_id and is_admin:
        engine = AnalyticsEngine(tenant_id, tenant_manager)
        perf = engine.get_performance_summary()
        leads = engine.get_lead_metrics(start_date, end_date)
        agents = engine.get_agent_metrics(start_date, end_date)
        execs = engine.get_execution_metrics(start_date, end_date)
        return jsonify({
            "total_clients": 1,
            "total_leads": perf.get("leads_this_month", 0),
            "total_tasks": perf.get("tasks_this_month", 0),
            "success_rate": perf.get("success_rate", 0),
            "success_count": execs.get("success_count", 0),
            "fail_count": execs.get("fail_count", 0),
            "avg_success_rate": perf.get("success_rate", 0),
            "leads_this_month": perf.get("leads_this_month", 0),
            "tasks_this_month": perf.get("tasks_this_month", 0),
            "active_agents": perf.get("active_agents", 0),
            "total_agents": perf.get("total_agents", 0),
            "avg_response_time": agents.get("avg_response_time", 0),
            "leads_by_month": _leads_by_month(engine),
            "tasks_per_agent": agents.get("tasks_per_agent", []),
            "failures_by_tool": execs.get("failures_by_tool", {}),
            "recent_leads": engine._fetchall(
                "SELECT name, service, urgency, status FROM leads ORDER BY created_at DESC LIMIT 50"
            ),
            "recent_executions": engine._fetchall(
                "SELECT agent_name, tool_name, success, timestamp FROM execution_log ORDER BY timestamp DESC LIMIT 50"
            ),
            "per_client": [{
                "tenant_id": tenant_id,
                "leads": perf.get("leads_this_month", 0),
                "tasks": perf.get("tasks_this_month", 0),
                "success_rate": perf.get("success_rate", 0),
                "active_agents": perf.get("active_agents", 0),
            }],
        })

    if is_admin:
        all_tenants = tenant_manager.list_tenants("direct")
        engine = AnalyticsEngine("_admin_", tenant_manager)
        summary = engine.get_admin_summary(all_tenants)
        total_leads = 0
        total_tasks = 0
        total_success = 0
        total_fail = 0
        all_tasks_per_agent = {}
        all_failures_by_tool = {}
        all_leads_by_month = {}
        all_recent_leads = []
        all_recent_execs = []
        for tid in all_tenants:
            e = AnalyticsEngine(tid, tenant_manager)
            perf = e.get_performance_summary()
            leads_m = e.get_lead_metrics(start_date, end_date)
            agents_m = e.get_agent_metrics(start_date, end_date)
            execs_m = e.get_execution_metrics(start_date, end_date)
            total_leads += perf.get("leads_this_month", 0)
            total_tasks += perf.get("tasks_this_month", 0)
            total_success += execs_m.get("success_count", 0)
            total_fail += execs_m.get("fail_count", 0)
            for a in agents_m.get("tasks_per_agent", []):
                name = a["agent"]
                if name not in all_tasks_per_agent:
                    all_tasks_per_agent[name] = {"agent": name, "total": 0, "success": 0, "fail": 0, "success_rate": 0}
                all_tasks_per_agent[name]["total"] += a["total"]
                all_tasks_per_agent[name]["success"] += a["success"]
                all_tasks_per_agent[name]["fail"] += a["fail"]
            for tool, cnt in execs_m.get("failures_by_tool", {}).items():
                all_failures_by_tool[tool] = all_failures_by_tool.get(tool, 0) + cnt
            for m in _leads_by_month(e):
                lbl = m["label"]
                all_leads_by_month[lbl] = all_leads_by_month.get(lbl, 0) + m["count"]
            all_recent_leads.extend(
                e._fetchall("SELECT name, service, urgency, status FROM leads ORDER BY created_at DESC LIMIT 20")
            )
            all_recent_execs.extend(
                e._fetchall("SELECT agent_name, tool_name, success, timestamp FROM execution_log ORDER BY timestamp DESC LIMIT 20")
            )
        for a in all_tasks_per_agent.values():
            a["success_rate"] = round((a["success"] / a["total"] * 100) if a["total"] else 0, 1)
        leads_by_month = [{"label": k, "count": v} for k, v in sorted(all_leads_by_month.items())]
        total_clients = len(all_tenants)
        avg_sr = round((total_success / (total_success + total_fail) * 100) if (total_success + total_fail) else 0, 1)
        return jsonify({
            "total_clients": total_clients,
            "total_leads": total_leads,
            "total_tasks": total_tasks,
            "success_count": total_success,
            "fail_count": total_fail,
            "avg_success_rate": avg_sr,
            "leads_this_month": total_leads,
            "tasks_this_month": total_tasks,
            "leads_by_month": leads_by_month,
            "tasks_per_agent": list(all_tasks_per_agent.values()),
            "failures_by_tool": all_failures_by_tool,
            "recent_leads": sorted(all_recent_leads, key=lambda x: x.get("name", ""))[:20],
            "recent_executions": sorted(all_recent_execs, key=lambda x: x.get("timestamp", ""), reverse=True)[:20],
            "per_client": summary.get("per_client", []),
        })

    if not is_admin and session_tenant:
        engine = AnalyticsEngine(session_tenant, tenant_manager)
        perf = engine.get_performance_summary()
        leads = engine.get_lead_metrics(start_date, end_date)
        agents = engine.get_agent_metrics(start_date, end_date)
        execs = engine.get_execution_metrics(start_date, end_date)
        return jsonify({
            "leads_this_month": perf.get("leads_this_month", 0),
            "tasks_this_month": perf.get("tasks_this_month", 0),
            "success_rate": perf.get("success_rate", 0),
            "active_agents": perf.get("active_agents", 0),
            "total_agents": perf.get("total_agents", 0),
            "avg_response_time": agents.get("avg_response_time", 0),
            "conversion_rate": leads.get("conversion_rate", 0),
            "leads_by_month": _leads_by_month(engine),
            "tasks_per_agent": agents.get("tasks_per_agent", []),
            "failures_by_tool": execs.get("failures_by_tool", {}),
            "recent_leads": engine._fetchall(
                "SELECT name, service, urgency, status FROM leads ORDER BY created_at DESC LIMIT 20"
            ),
            "recent_executions": engine._fetchall(
                "SELECT agent_name, tool_name, success, timestamp FROM execution_log ORDER BY timestamp DESC LIMIT 20"
            ),
        })

    return jsonify({"error": "Unauthorized"}), 401


def _leads_by_month(engine, months: int = 6) -> list:
    """Return lead counts grouped by month for chart display."""
    from datetime import date as dt_date
    import calendar
    result = []
    today = dt_date.today()
    for i in range(months - 1, -1, -1):
        m = today.month - i
        y = today.year
        while m < 1:
            m += 12
            y -= 1
        start = f"{y}-{m:02d}-01"
        last_day = calendar.monthrange(y, m)[1]
        end = f"{y}-{m:02d}-{last_day}"
        rows = engine._fetchall(
            "SELECT COUNT(*) as cnt FROM leads WHERE DATE(created_at) >= ? AND DATE(created_at) <= ?",
            (start, end),
        )
        cnt = rows[0]["cnt"] if rows else 0
        result.append({"label": f"{calendar.month_abbr[m]}", "count": cnt})
    return result


@app.route("/api/analytics/leads")
def api_analytics_leads():
    """Return lead metrics for a date range."""
    tenant_id = request.args.get("client", "").strip() or session.get("active_tenant_id") or getattr(current_user, "tenant_id", None)
    start = request.args.get("start")
    end = request.args.get("end")
    if not tenant_id:
        return jsonify({"error": "No tenant context"}), 400
    engine = AnalyticsEngine(tenant_id, tenant_manager)
    return jsonify(engine.get_lead_metrics(start, end))


@app.route("/api/analytics/agents")
def api_analytics_agents():
    """Return agent performance metrics."""
    tenant_id = request.args.get("client", "").strip() or session.get("active_tenant_id") or getattr(current_user, "tenant_id", None)
    start = request.args.get("start")
    end = request.args.get("end")
    if not tenant_id:
        return jsonify({"error": "No tenant context"}), 400
    engine = AnalyticsEngine(tenant_id, tenant_manager)
    return jsonify(engine.get_agent_metrics(start, end))


@app.route("/api/analytics/executions")
def api_analytics_executions():
    """Return execution metrics."""
    tenant_id = request.args.get("client", "").strip() or session.get("active_tenant_id") or getattr(current_user, "tenant_id", None)
    start = request.args.get("start")
    end = request.args.get("end")
    if not tenant_id:
        return jsonify({"error": "No tenant context"}), 400
    engine = AnalyticsEngine(tenant_id, tenant_manager)
    return jsonify(engine.get_execution_metrics(start, end))


@app.route("/api/analytics/report/generate", methods=["POST"])
def api_analytics_generate_report():
    """Generate a monthly report HTML for a tenant."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    tenant_id = data.get("tenant_id")
    month = data.get("month")
    year = data.get("year")
    if not tenant_id:
        return jsonify({"error": "tenant_id required"}), 400
    engine = AnalyticsEngine(tenant_id, tenant_manager)
    html = engine.generate_monthly_report(year, month)
    return jsonify({"html": html})


@app.route("/api/analytics/report/email", methods=["POST"])
def api_analytics_email_report():
    """Email a monthly report to the client."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    tenant_id = data.get("tenant_id")
    month = data.get("month")
    year = data.get("year")
    html = data.get("html")
    if not tenant_id or not html:
        return jsonify({"error": "tenant_id and html are required"}), 400
    try:
        engine = AnalyticsEngine(tenant_id, tenant_manager)
        biz_row = engine._fetchone("SELECT business_name, email FROM client_details LIMIT 1")
        business_name = biz_row["business_name"] if biz_row else tenant_id
        client_email = biz_row["email"] if biz_row else None
        if not client_email:
            return jsonify({"error": "No client email found"}), 400
        settings = executioner.get_settings()
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Monthly Performance Report — {business_name}"
        msg["From"] = settings.get("smtp_from_email", "reports@lavaldigital.ca")
        msg["To"] = client_email
        part = MIMEText(html, "html")
        msg.attach(part)
        with smtplib.SMTP(settings.get("smtp_host", "smtp.gmail.com"), settings.get("smtp_port", 587)) as server:
            if settings.get("smtp_use_tls", True):
                server.starttls()
            if settings.get("smtp_username"):
                server.login(settings["smtp_username"], settings.get("smtp_password", ""))
            server.send_message(msg)
        return jsonify({"success": True, "message": f"Report emailed to {client_email}"})
    except Exception as e:
        logger.error("Failed to email report: %s", e)
        logger.error("Internal error: %s", e, exc_info=True); return jsonify({"success": False, "error": "An internal error occurred."}), 500


@app.route("/admin/analytics")
def admin_analytics_page():
    """Serve the admin analytics dashboard page."""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    tenants = {
        "direct_clients": tenant_manager.list_tenants("direct"),
        "resellers": tenant_manager.list_tenants("reseller"),
    }
    active_tenant = session.get("active_tenant_id")
    return render_template("admin.html", tenants=tenants, active_tenant=active_tenant)


@app.route("/admin/reports")
def admin_reports_page():
    """Serve the report generation page."""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    tenants = {
        "direct_clients": tenant_manager.list_tenants("direct"),
        "resellers": tenant_manager.list_tenants("reseller"),
    }
    active_tenant = session.get("active_tenant_id")
    return render_template("admin.html", tenants=tenants, active_tenant=active_tenant)


@app.route("/client/analytics")
@client_required
def client_analytics_page():
    """Serve the client analytics view."""
    return redirect(url_for("client_dashboard"))


@app.route("/client/analytics/report")
@client_required
def client_analytics_report():
    """Generate and serve a printable monthly report for the client."""
    tenant_id = current_user.tenant_id
    engine = AnalyticsEngine(tenant_id, tenant_manager)
    html = engine.generate_monthly_report()
    return html, 200, {"Content-Type": "text/html"}


# ---------------------------------------------------------------------------
# Managed Services routes
# ---------------------------------------------------------------------------

MANAGED_MONTHLY_FEE = 499


@app.route("/client/managed-services")
@client_required
def client_managed_services():
    """Serve the managed services opt-in page."""
    tenant_id = current_user.tenant_id
    managed = False
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT managed_service FROM client_details LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            managed = bool(row.get("managed_service", False))
    except Exception:
        pass
    return render_template("client/managed_services.html", managed=managed)


@app.route("/api/managed/upgrade", methods=["POST"])
@client_required
def api_managed_upgrade():
    """Upgrade the current client to managed services."""
    tenant_id = current_user.tenant_id
    now_iso = datetime.now().isoformat()
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE client_details SET managed_service = 1, managed_since = ?",
            (now_iso,),
        )
        conn.commit()

        # Log to execution_log
        try:
            cursor.execute(
                "INSERT INTO execution_log (execution_id, agent_name, tool_name, success, draft_preview, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "system", "managed_services", 1,
                 f"Client upgraded to Managed Services (${MANAGED_MONTHLY_FEE}/mo)", now_iso),
            )
            conn.commit()
        except Exception:
            pass

        logger.info("Client %s upgraded to Managed Services", tenant_id)
        return jsonify({"success": True, "message": "Upgraded to Managed Services"})
    except Exception as e:
        logger.error("Failed to upgrade %s: %s", tenant_id, e)
        logger.error("Internal error: %s", e, exc_info=True); return jsonify({"success": False, "error": "An internal error occurred."}), 500


@app.route("/api/managed/cancel", methods=["POST"])
@client_required
def api_managed_cancel():
    """Request cancellation of managed services (30-day notice)."""
    tenant_id = current_user.tenant_id
    now_iso = datetime.now().isoformat()
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE client_details SET managed_service = 0 WHERE managed_service = 1"
        )
        conn.commit()
        logger.info("Client %s cancelled Managed Services", tenant_id)
        # Log cancellation
        try:
            cursor.execute(
                "INSERT INTO execution_log (execution_id, agent_name, tool_name, success, draft_preview, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "system", "managed_services", 1,
                 "Client cancelled Managed Services (30-day notice)", now_iso),
            )
            conn.commit()
        except Exception:
            pass
        return jsonify({"success": True, "message": "Cancellation requested"})
    except Exception as e:
        logger.error("Failed to cancel managed for %s: %s", tenant_id, e)
        logger.error("Internal error: %s", e, exc_info=True); return jsonify({"success": False, "error": "An internal error occurred."}), 500


@app.route("/api/managed/clients")
def api_managed_clients():
    """List all managed clients (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    filter_mode = request.args.get("filter", "active")
    all_tenants = tenant_manager.list_tenants("direct")
    clients = []
    total_mrr = 0
    total_pending = 0
    past_due_count = 0

    for tid in all_tenants:
        try:
            conn = tenant_manager.get_connection(tid)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT managed_service, managed_since, package FROM client_details LIMIT 1"
            )
            row = cursor.fetchone()
            if not row or not row.get("managed_service"):
                continue

            managed_since = row.get("managed_since")
            managed_since_str = managed_since[:10] if managed_since else None
            pkg = row.get("package", "")

            # Calculate billing date (30 days from managed_since)
            next_billing = None
            if managed_since:
                try:
                    from datetime import date as dt_date
                    ms_date = dt_date.fromisoformat(managed_since[:10])
                    from datetime import timedelta as td
                    next_date = ms_date + td(days=30)
                    while next_date < dt_date.today():
                        next_date += td(days=30)
                    next_billing = next_date.isoformat()
                except Exception:
                    pass

            # Determine status
            status = "active"
            if next_billing:
                try:
                    from datetime import date as dt_date
                    billing_dt = dt_date.fromisoformat(next_billing)
                    if billing_dt < dt_date.today():
                        status = "past_due"
                        past_due_count += 1
                except Exception:
                    pass

            if filter_mode != "all" and status != filter_mode:
                continue

            total_mrr += MANAGED_MONTHLY_FEE

            # Count pending approvals
            try:
                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM threads WHERE status = 'pending_approval'"
                )
                pending_row = cursor.fetchone()
                pending_count = pending_row["cnt"] if pending_row else 0
                total_pending += pending_count
            except Exception:
                pending_count = 0

            clients.append({
                "tenant_id": tid,
                "package": pkg,
                "managed_since": managed_since_str,
                "monthly_fee": MANAGED_MONTHLY_FEE,
                "next_billing": next_billing[:10] if next_billing else None,
                "status": status,
                "pending_approvals": pending_count,
            })
        except Exception:
            continue

    return jsonify({
        "clients": clients,
        "total_mrr": total_mrr,
        "total_pending_approvals": total_pending,
        "past_due_count": past_due_count,
    })


@app.route("/api/managed/pause", methods=["POST"])
def api_managed_pause():
    """Pause managed services for a client (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    tenant_id = data.get("tenant_id")
    if not tenant_id:
        return jsonify({"error": "tenant_id required"}), 400
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE client_details SET managed_service = 0 WHERE managed_service = 1"
        )
        conn.commit()
        logger.info("Admin paused Managed Services for %s", tenant_id)
        return jsonify({"success": True, "message": "Managed services paused"})
    except Exception as e:
        logger.error("Internal error: %s", e, exc_info=True); return jsonify({"success": False, "error": "An internal error occurred."}), 500


@app.route("/api/managed/resume", methods=["POST"])
def api_managed_resume():
    """Resume managed services for a client (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    tenant_id = data.get("tenant_id")
    if not tenant_id:
        return jsonify({"error": "tenant_id required"}), 400
    now_iso = datetime.now().isoformat()
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE client_details SET managed_service = 1, managed_since = ?",
            (now_iso,),
        )
        conn.commit()
        logger.info("Admin resumed Managed Services for %s", tenant_id)
        return jsonify({"success": True, "message": "Managed services resumed"})
    except Exception as e:
        logger.error("Internal error: %s", e, exc_info=True); return jsonify({"success": False, "error": "An internal error occurred."}), 500


@app.route("/api/managed/bulk-approve", methods=["POST"])
def api_managed_bulk_approve():
    """Approve all pending approvals for a managed client (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    tenant_id = data.get("tenant_id")
    if not tenant_id:
        return jsonify({"error": "tenant_id required"}), 400
    try:
        conn = tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT thread_id, routed_agent, agent_draft FROM threads WHERE status = 'pending_approval'"
        )
        pending = cursor.fetchall()
        approved_count = 0
        now_iso = datetime.now().isoformat()

        for row in pending:
            thread_id = row["thread_id"]
            agent_name = row["routed_agent"]
            draft = row["agent_draft"] or ""

            # Approve the thread
            cursor.execute(
                "UPDATE threads SET approved = 1, status = 'completed', updated_at = ? WHERE thread_id = ?",
                (now_iso, thread_id),
            )

            # Execute via executioner if agent exists and draft is not empty
            if agent_name and draft and agent_name in agent_registry:
                try:
                    exec_result = executioner.execute(agent_name, draft)
                    # Log execution
                    cursor.execute(
                        "INSERT INTO execution_log (execution_id, agent_name, tool_name, success, draft_preview, timestamp) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (str(uuid.uuid4()), agent_name, "managed_bulk_approve",
                         int(exec_result.get("success", False)),
                         (draft[:120] + "...") if len(draft) > 120 else draft, now_iso),
                    )
                except Exception:
                    pass

            approved_count += 1

        conn.commit()
        logger.info("Bulk approved %d items for %s", approved_count, tenant_id)
        return jsonify({
            "success": True,
            "approved_count": approved_count,
            "message": f"Approved {approved_count} pending item(s)",
        })
    except Exception as e:
        logger.error("Bulk approve failed for %s: %s", tenant_id, e)
        logger.error("Internal error: %s", e, exc_info=True); return jsonify({"success": False, "error": "An internal error occurred."}), 500


@app.route("/api/managed/mrr")
def api_managed_mrr():
    """Return total MRR from managed services (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    all_tenants = tenant_manager.list_tenants("direct")
    active_count = 0
    for tid in all_tenants:
        try:
            conn = tenant_manager.get_connection(tid)
            cursor = conn.cursor()
            cursor.execute("SELECT managed_service FROM client_details LIMIT 1")
            row = cursor.fetchone()
            if row and row.get("managed_service"):
                active_count += 1
        except Exception:
            continue
    total_mrr = active_count * MANAGED_MONTHLY_FEE
    return jsonify({
        "active_managed_clients": active_count,
        "monthly_fee": MANAGED_MONTHLY_FEE,
        "total_mrr": total_mrr,
    })


@app.route("/admin/managed")
def admin_managed_page():
    """Serve the managed clients admin page."""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    tenants = {
        "direct_clients": tenant_manager.list_tenants("direct"),
        "resellers": tenant_manager.list_tenants("reseller"),
    }
    active_tenant = session.get("active_tenant_id")
    return render_template("admin.html", tenants=tenants, active_tenant=active_tenant)


# ---------------------------------------------------------------------------
# Training Hub routes
# ---------------------------------------------------------------------------

from core.training_articles import ARTICLES as TRAINING_ARTICLES

# Build slug-to-article lookup
_TRAINING_BY_SLUG = {a["slug"]: a for a in TRAINING_ARTICLES}


@app.route("/training")
def training_hub():
    """Serve the training hub landing page."""
    import json
    articles_json = json.dumps(TRAINING_ARTICLES)
    return render_template("blog/training_hub.html", articles_json=articles_json)


@app.route("/training/<slug>")
def training_article(slug):
    """Serve an individual training article."""
    article = _TRAINING_BY_SLUG.get(slug)
    if not article:
        return redirect(url_for("training_hub"))

    # Find related articles (same category, exclude current)
    related = [
        a for a in TRAINING_ARTICLES
        if a["slug"] != slug and a["category"] == article["category"]
    ][:3]

    return render_template(
        "blog/training_article.html",
        article=article,
        related=related,
    )


@app.route("/api/training/articles")
def api_training_articles():
    """Return the list of training articles (for search/filter)."""
    return jsonify(TRAINING_ARTICLES)


@app.route("/api/training/feedback", methods=["POST"])
def api_training_feedback():
    """Log training article feedback."""
    data = request.json
    slug = data.get("slug", "")
    helpful = data.get("helpful")
    logger.info("Training feedback: slug=%s helpful=%s", slug, helpful)
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
