import os
import re
import sys
import uuid
import secrets
import warnings
import json
import logging
import logging.handlers
import requests
import socket
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def _safe_url(url: str, timeout: int = 10) -> requests.Response:
    """Fetch a URL with SSRF protection: http/https only, no private IPs."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got '{parsed.scheme}'")
    hostname = parsed.hostname or ""
    try:
        ip = socket.gethostbyname(hostname)
    except socket.gaierror:
        raise ValueError(f"Could not resolve hostname: {hostname}")
    # Block private / loopback / link-local IPs
    parts = [int(x) for x in ip.split(".")]
    if parts[0] == 127 or parts[0] == 10 or parts[0] == 0:
        raise ValueError(f"Blocked request to private IP: {ip}")
    if parts[0] == 169 and parts[1] == 254:
        raise ValueError(f"Blocked request to link-local IP: {ip}")
    if parts[0] == 192 and parts[1] == 168:
        raise ValueError(f"Blocked request to private IP: {ip}")
    if parts[0] == 172 and 16 <= parts[1] <= 31:
        raise ValueError(f"Blocked request to private IP: {ip}")
    return requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})


# Suppress warnings before any imports that might trigger them
warnings.filterwarnings("ignore", module="langgraph")
warnings.filterwarnings("ignore", module="langchain")

from flask import (Flask, render_template, jsonify, request,
                   redirect, url_for, session, flash, g)
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv


def _safe_error(e: Exception, status: int = 500):
    """Log the real error and return a generic response to the client."""
    logger.error("Internal error: %s", e, exc_info=True)
    return jsonify({"error": "An internal error occurred."}), status


load_dotenv()

# MCP Server imports
from mcp import init_mcp_servers, get_all_mcp_servers, get_mcp_server, get_all_mcp_tools, AGENT_MCP_ROUTING

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
if os.getenv("FLASK_SECRET_KEY", "").startswith("laval-digital-secret"):
    raise RuntimeError(
        "FLASK_SECRET_KEY contains the default value. "
        "Generate a secure key: python3 -c \"import secrets; print(secrets.token_hex(32))\""
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
pw = os.getenv("ADMIN_PASSWORD", "")
if len(pw) < 8 or not any(c.isdigit() for c in pw) or not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?`~" for c in pw):
    raise RuntimeError(
        "ADMIN_PASSWORD must be at least 8 characters, include at least one "
        "digit and one special character."
    )

# Hash admin password for constant-time comparison
_admin_password_hash = generate_password_hash(os.getenv("ADMIN_PASSWORD", ""))

# Credential encryption helpers (Fernet symmetric encryption)
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64 as _b64

def _derive_fernet_key() -> Fernet:
    """Derive a Fernet key from FLASK_SECRET_KEY for credential encryption."""
    secret = os.getenv("FLASK_SECRET_KEY", "").encode()
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b"laval-digital-cred", iterations=100_000)
    key = _b64.urlsafe_b64encode(kdf.derive(secret))
    return Fernet(key)

_credential_cipher = _derive_fernet_key()

def _encrypt_credential(plaintext: str) -> str:
    return _credential_cipher.encrypt(plaintext.encode()).decode()

def _decrypt_credential(ciphertext: str) -> str:
    return _credential_cipher.decrypt(ciphertext.encode()).decode()

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.orchestrator import Orchestrator
from core.llm_adapter import LLMAdapter
from core.events import get_event_bus
from core.push import PushManager
from core.memory import AgentMemory
from core.monitor import monitor as proactive_monitor
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
from agents.cro_agent import CROAgent
from agents.video_agent import VideoAgent
from agents.sms_marketing_agent import SMSMarketingAgent
from agents.executioner_agent import ExecutionerAgent

AGENT_CLASSES = {
    "local_seo": LocalSEOAgent, "social_media": SocialMediaAgent,
    "lead_conversion": LeadConversionAgent, "paid_ads": PaidAdsAgent,
    "growth_hacker": GrowthHackerAgent, "reputation": ReputationManagementAgent,
    "email_marketing": EmailMarketingAgent, "tiktok": TikTokAgent,
    "outreach": OutreachAgent, "backlinks": BacklinksAgent,
    "content_strategy": ContentStrategyAgent, "technical_seo": TechnicalSEOAgent,
    "reporting": ReportingAgent, "cro": CROAgent, "video": VideoAgent,
    "sms_marketing": SMSMarketingAgent,
}
from core.auth import (
    init_auth, User, find_user_by_email, add_user_to_tenant,
    client_required,
    validate_password, _check_rate_limit, _record_attempt,
)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
app.permanent_session_lifetime = timedelta(days=30)
app.session_cookie_httponly = True
app.session_cookie_samesite = "Lax"
if os.getenv("DEV_MODE", "").lower() not in ("true", "1"):
    app.session_cookie_secure = True

# Public API routes that don't require authentication
_API_PUBLIC: set = {
    "/api/affiliate/status",
    "/api/affiliate/signup",
}

# CSRF protection
csrf = CSRFProtect(app)


@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)


@app.after_request
def add_security_headers(response):
    """Add security headers to every response."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self' https://api.deepseek.com; "
        "frame-ancestors 'none'"
    )
    ALLOWED_ORIGINS = {"https://lavaldigital.ca", "https://www.lavaldigital.ca", "http://127.0.0.1:5000", "http://localhost:5000"}
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-CSRFToken, Authorization"
    return response


@app.before_request
def require_api_auth():
    """Require authentication on all /api/* routes except public ones."""
    if not request.path.startswith("/api/"):
        return
    if request.path in _API_PUBLIC:
        return
    if session.get("admin_logged_in"):
        return
    if current_user.is_authenticated:
        return
    if request.method == "OPTIONS":
        return
    return jsonify({"error": "Authentication required"}), 401


# Configure logging with rotation (10 MB per file, keep 5 backups)
# Also send WARNING+ to stderr for Docker/container environments
_log_handler = logging.handlers.RotatingFileHandler(
    "logs/app.log", maxBytes=10 * 1024 * 1024, backupCount=5,
)
_log_handler.setFormatter(logging.Formatter(
    "[%(asctime)s] %(levelname)s in %(name)s: %(message)s"
))
_log_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(_log_handler)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter(
    "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
))
_console_handler.setLevel(logging.WARNING)
logging.getLogger().addHandler(_console_handler)

logging.getLogger().setLevel(logging.INFO)

# Initialize the single Frankie database
from core import database
database.init_db()

# Initialize Affiliate Manager
from core.affiliates import AffiliateManager
affiliate_manager = AffiliateManager()

# Initialize Push Manager (PWA push notifications)
push_manager = PushManager()
agent_memory = AgentMemory()

# Initialize Flask-Login auth
login_manager = init_auth(app)

# Store active threads and their states (in-memory cache for orchestrator resume)
active_threads: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# Tenant helpers
# ---------------------------------------------------------------------------

def get_tenant_agent_activity(user_id: str) -> dict:
    try:
        uid = int(user_id)
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT agent_id, status, last_invoked, task_count, "
            "success_count, failure_count, last_draft_preview "
            "FROM agent_configs WHERE user_id = ?",
            (uid,),
        )
        rows = cursor.fetchall()
        return {row["agent_id"]: dict(row) for row in rows}
    except Exception as e:
        logger.error(f"Failed to get agent activity for user {user_id}: {e}")
        return {}


def update_tenant_agent_activity(
    user_id: str, agent_id: str, **kwargs
) -> None:
    _COLUMN_UPDATES = {
        "status": "UPDATE agent_configs SET status = ? WHERE agent_id = ? AND user_id = ?",
        "last_invoked": "UPDATE agent_configs SET last_invoked = ? WHERE agent_id = ? AND user_id = ?",
        "task_count": "UPDATE agent_configs SET task_count = ? WHERE agent_id = ? AND user_id = ?",
        "success_count": "UPDATE agent_configs SET success_count = ? WHERE agent_id = ? AND user_id = ?",
        "failure_count": "UPDATE agent_configs SET failure_count = ? WHERE agent_id = ? AND user_id = ?",
        "last_draft_preview": "UPDATE agent_configs SET last_draft_preview = ? WHERE agent_id = ? AND user_id = ?",
        "enabled": "UPDATE agent_configs SET enabled = ? WHERE agent_id = ? AND user_id = ?",
        "model": "UPDATE agent_configs SET model = ? WHERE agent_id = ? AND user_id = ?",
        "autonomy": "UPDATE agent_configs SET autonomy = ? WHERE agent_id = ? AND user_id = ?",
        "confidence_threshold": "UPDATE agent_configs SET confidence_threshold = ? WHERE agent_id = ? AND user_id = ?",
    }
    try:
        uid = int(user_id)
        conn = database._get_conn()
        cursor = conn.cursor()
        for key, value in kwargs.items():
            sql = _COLUMN_UPDATES.get(key)
            if sql is None:
                raise ValueError(f"Invalid column name: {key}")
            cursor.execute(sql, (value, agent_id, uid))
        conn.commit()
    except Exception as e:
        logger.error(
            f"Failed to update agent activity for {agent_id} for user {user_id}: {e}"
        )


def get_current_user_id() -> Optional[str]:
    if current_user.is_authenticated:
        return str(current_user.id)
    if session.get("admin_logged_in"):
        return session.get("active_user_id")
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
                    if current_user.role in ("client", "user"):
                        return redirect(url_for("client_login"))
                    elif current_user.role == "affiliate":
                        return redirect(url_for("affiliate_login"))

            except Exception:
                logger.warning("Session timeout check failed", exc_info=True)
        session["last_active"] = datetime.now().isoformat()
    elif session.get("admin_logged_in"):
        last_active = session.get("last_active")
        if last_active:
            try:
                last = datetime.fromisoformat(last_active)
                if datetime.now() - last > timedelta(hours=2):
                    session.pop("admin_logged_in", None)
                    session.clear()
                    flash("Session expired. Please log in again.", "error")
                    return redirect(url_for("admin_login"))
            except Exception:
                logger.warning("Admin session timeout check failed", exc_info=True)
        session["last_active"] = datetime.now().isoformat()


@app.before_request
def check_trial_expiry():
    """Redirect trial users to /trial-expired if their 7 days are up."""
    if current_user.is_authenticated and hasattr(current_user, "is_trial_expired") and current_user.is_trial_expired:
        if request.path.startswith("/api/"):
            return jsonify({"error": "Trial expired. Subscribe to continue.", "redirect": "/trial-expired"}), 403
        if request.path not in ("/trial-expired", "/logout", "/static/bookmarklet.js"):
            from flask import flash as _flash
            _flash("Your free trial has ended. Subscribe to regain access.", "error")
            return redirect(url_for("trial_expired"))


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
        "system_prompt_file": "prompts/paid_ads_v2.md",
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
    "cro": {
        "agent_id": "cro",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/cro.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
    "video": {
        "agent_id": "video",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/video.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1",
        },
    },
    "sms_marketing": {
        "agent_id": "sms_marketing",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/sms_marketing.md",
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
    cls = AGENT_CLASSES.get(agent_id)
    if cls:
        agent_registry[agent_id] = cls(agent_id, config)

# Initialize MCP Servers for execution
mcp_servers = init_mcp_servers()
logger.info(f"MCP servers ready: {list(mcp_servers.keys())}")

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
    "cro": {"name": "CRO & Landing Pages", "desc": "Conversion rate optimization, A/B testing analysis, funnel optimization, landing page copy, heatmap interpretation, CTA strategy"},
    "video": {"name": "Video Production", "desc": "YouTube scripts, explainer videos, ad video scripts, video SEO, content series planning, thumbnail strategy"},
    "sms_marketing": {"name": "SMS Marketing", "desc": "SMS campaign planning, sequence design, CASL compliance, concise copywriting, timing strategy, list segmentation"},
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


def get_orchestrator():
    """Return the cached orchestrator singleton.

    Keeps the same instance across requests so in-memory state
    (_pending_drafts) persists. Rebuilds only if the API key changes.
    """
    global llm_adapter, agent_registry, orchestrator

    if orchestrator is not None:
        return orchestrator

    logger.info("Building orchestrator")

    orchestrator = Orchestrator(llm_adapter, agent_registry, executioner=executioner, push_manager=push_manager, memory=agent_memory)
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


@app.route("/health")
def health():
    """Health check endpoint for Docker/K8s probes."""
    status = {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
    # Check DB connectivity
    try:
        conn = database._get_conn()
        conn.execute("SELECT 1")
        conn.close()
        status["database"] = "ok"
    except Exception as e:
        status["database"] = f"error: {e}"
        status["status"] = "degraded"
    # Check LLM adapter (lightweight model list call)
    try:
        models = llm_adapter.get_available_models()
        status["llm"] = "ok" if models else "no_models"
    except Exception as e:
        status["llm"] = f"error: {e}"
        status["status"] = "degraded"
    http_code = 200 if status["status"] == "ok" else 503
    return jsonify(status), http_code


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


@app.route("/free-trial")
def free_trial():
    """Serve the 7-day free trial signup page."""
    if current_user.is_authenticated:
        return redirect(url_for("client_dashboard"))
    return render_template("free_trial.html")


@app.route("/fr/essai-gratuit")
def free_trial_fr():
    """Serve the French 7-day free trial signup page."""
    if current_user.is_authenticated:
        return redirect(url_for("client_dashboard"))
    return render_template("free_trial_fr.html")


@app.route("/trial-expired")
def trial_expired():
    """Serve the trial expired / subscribe page."""
    return render_template("trial_expired.html")


@app.route("/api/signup", methods=["POST"])
def api_signup():
    """Create a new trial user account and log them in."""
    data = request.json
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password", "")

    if not name or not email or not password:
        return jsonify({"success": False, "error": "Name, email, and password are required."}), 400

    is_valid, err_msg = validate_password(password)
    if not is_valid:
        return jsonify({"success": False, "error": err_msg}), 400

    try:
        now = datetime.now(timezone.utc)
        trial_ends = (now + timedelta(days=7)).isoformat()
        uid = database.create_user(
            email=email,
            password_hash=generate_password_hash(password),
            role="user",
            display_name=name,
        )
        conn = database._get_conn()
        conn.execute(
            "UPDATE users SET status = 'trial', trial_ends_at = ? WHERE id = ?",
            (trial_ends, uid),
        )
        conn.commit()

        user_row = database.get_user_by_id(uid)
        temp_user = User(
            row_id=user_row["id"], email=user_row["email"],
            password_hash=user_row["password_hash"], role=user_row["role"],
            display_name=user_row["display_name"],
            status="trial", trial_ends_at=trial_ends,
        )
        login_user(temp_user)
        session["last_active"] = datetime.now().isoformat()

        logger.info("New trial user created: %s (id=%s)", email, uid)
        return jsonify({"success": True, "redirect": url_for("client_dashboard")}), 201

    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except RuntimeError as e:
        logger.error("Signup failed: %s", e, exc_info=True)
        return jsonify({"success": False, "error": "Account creation failed. Please try again later."}), 500


# ---------------------------------------------------------------------------
# Client auth routes
# ---------------------------------------------------------------------------

@app.route("/client/login", methods=["GET", "POST"])
def client_login():
    """Serve client login page and authenticate."""
    if current_user.is_authenticated and current_user.role in ("client", "user"):
        return redirect(url_for("client_dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not _check_rate_limit():
            flash("Too many login attempts. Try again later.", "error")
            return render_template("client/login.html")

        user_row = find_user_by_email(email)
        if not user_row or user_row["role"] not in ("client", "user"):
            _record_attempt(False)
            flash("Invalid email or password.", "error")
            return render_template("client/login.html")

        temp_user = User(
            row_id=user_row["id"], email=user_row["email"],
            password_hash=user_row["password_hash"], role=user_row["role"],
            display_name=user_row["display_name"],
        )
        if not temp_user.check_password(password):
            _record_attempt(False)
            flash("Invalid email or password.", "error")
            return render_template("client/login.html")

        login_user(temp_user)
        _record_attempt(True)
        session["tenant_id"] = str(user_row["id"])
        session["user_role"] = "client"
        session["last_active"] = datetime.now().isoformat()

        # Update last_login
        try:
            conn = database._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.now().isoformat(), user_row["id"]),
            )
            conn.commit()
        except Exception:
            logger.warning("Failed to update login timestamp for client", exc_info=True)

        return redirect(url_for("client_dashboard"))

    return render_template("client/login.html")


@app.route("/client/logout")
def client_logout():
    """Log out client and redirect to login."""
    logout_user()
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("client_login"))


@app.route("/logout")
def logout():
    """Generic logout for any authenticated user."""
    logout_user()
    session.clear()
    return redirect(url_for("home"))


@app.route("/login")
def login_redirect():
    """Redirect to the client login page."""
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
    tenant_id = current_user.id

    # Gather payment info from tenant database
    payments = []
    total_paid = 0
    total_owed = 0
    try:
        conn = database._get_conn()
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
        logger.warning("Failed to load payment data for client dashboard", exc_info=True)

    # Gather site URL from client_details
    site_url = None
    managed = False
    managed_since = None
    try:
        conn = database._get_conn()
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

        user_row = find_user_by_email(email)
        if not user_row or user_row["role"] != "affiliate":
            _record_attempt(False)
            flash("Invalid email or password.", "error")
            return render_template("affiliate/login.html")

        temp_user = User(
            row_id=user_row["id"], email=user_row["email"],
            password_hash=user_row["password_hash"], role=user_row["role"],
            display_name=user_row["display_name"],
        )
        if not temp_user.check_password(password):
            _record_attempt(False)
            flash("Invalid email or password.", "error")
            return render_template("affiliate/login.html")

        login_user(temp_user)
        _record_attempt(True)
        session["tenant_id"] = str(user_row["id"])
        session["user_role"] = "affiliate"
        session["last_active"] = datetime.now().isoformat()

        try:
            conn = database._get_conn()
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
@login_required
def affiliate_dashboard():
    """Serve the affiliate referral dashboard."""
    tenant_id = current_user.id

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
# API: User management (admin only)
# ---------------------------------------------------------------------------

@app.route("/api/users", methods=["GET"])
def api_list_users():
    """List all users for the active tenant (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    tenant_id = session.get("active_user_id")
    if not tenant_id:
        return jsonify({"error": "No client selected"}), 400

    role_filter = request.args.get("role", "").strip().lower()

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        if role_filter in ("client", "affiliate"):
            cursor.execute(
                "SELECT id, email, display_name, role, created_at, last_login "
                "FROM users WHERE id = ? AND role = ? ORDER BY created_at DESC",
                (int(tenant_id), role_filter),
            )
        else:
            cursor.execute(
                "SELECT id, email, display_name, role, created_at, last_login "
                "FROM users WHERE id = ? ORDER BY created_at DESC",
                (int(tenant_id),),
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

    tenant_id = session.get("active_user_id")
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

    tenant_id = session.get("active_user_id")
    if not tenant_id:
        return jsonify({"error": "No client selected"}), 400

    if str(user_id) == str(tenant_id):
        return jsonify({"error": "Cannot delete the currently selected client"}), 400

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = ? AND id != ?", (user_id, int(tenant_id)))
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
        if not _check_rate_limit():
            return render_template(
                "login.html", error="Too many attempts. Please try again later.", now=datetime.now()
            )
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        expected_user = os.getenv("ADMIN_USERNAME")
        if username == expected_user and check_password_hash(_admin_password_hash, password):
            _record_attempt(True)
            session["admin_logged_in"] = True
            return redirect(url_for("admin_panel_redirect"))
        _record_attempt(False)
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
        "direct_clients": database.list_users(role='user'),
    }
    active_tenant = session.get("active_user_id")
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
        if not _check_rate_limit():
            return render_template(
                "login_fr.html", error="Trop de tentatives. Veuillez réessayer plus tard.", now=datetime.now()
            )
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        expected_user = os.getenv("ADMIN_USERNAME")
        if username == expected_user and check_password_hash(_admin_password_hash, password):
            _record_attempt(True)
            session["admin_logged_in"] = True
            return redirect(url_for("admin_panel_redirect_fr"))
        _record_attempt(False)
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
        "direct_clients": database.list_users(role='user'),
    }
    active_tenant = session.get("active_user_id")
    return render_template(
        "admin_fr.html",
        logo_uploaded=logo_status,
        tenants=tenants,
        active_tenant=active_tenant,
    )


@app.context_processor
def inject_logo():
    """Always use the SVG logo from the repo."""
    return dict(logo_file="logo.svg")


# ---------------------------------------------------------------------------
# API: affiliate
# ---------------------------------------------------------------------------

@app.route("/api/affiliate/status")
@csrf.exempt
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
@csrf.exempt
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
@login_required
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
@login_required
def api_affiliate_payouts():
    """Return the current affiliate's payout history."""
    tenant_id = current_user.tenant_id
    return jsonify({"payouts": affiliate_manager.get_payouts(tenant_id)})


@app.route("/api/affiliate/payouts", methods=["POST"])
@login_required
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
# API: leads
# ---------------------------------------------------------------------------

@app.route("/api/leads", methods=["GET", "POST"])
def handle_leads():
    """Capture and list lead form submissions."""
    conn = database._get_conn()
    if request.method == "POST":
        data = request.json
        name = data.get("name", "")
        phone = data.get("phone", "")
        if not name or not phone:
            return jsonify({"error": "Name and phone are required"}), 400
        lead_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO leads (id, user_id, name, phone, service, urgency, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (lead_id, 0, name, phone, data.get("service", ""), data.get("urgency", ""), now),
        )
        conn.commit()
        return jsonify({"status": "ok", "lead": {"id": lead_id, "name": name, "phone": phone}}), 201
    rows = conn.execute("SELECT * FROM leads ORDER BY created_at DESC LIMIT 100").fetchall()
    return jsonify({"leads": [dict(r) for r in rows]})


# ---------------------------------------------------------------------------
# API: agents (tenant-aware)
# ---------------------------------------------------------------------------

@app.route("/api/agents", methods=["GET"])
def get_agents():
    """Get status and activity telemetry of all agents."""
    tenant_id = str(current_user.id) if not current_user.is_anonymous else None

    agents_status = []

    if tenant_id:
        activity = get_tenant_agent_activity(tenant_id)
        for agent_id, agent in agent_registry.items():
            act = activity.get(agent_id, {})
            agents_status.append({
                "agent_id": agent_id,
                "enabled": agent.enabled,
                "model": agent.model,
                "api_key": "",
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
                "api_key": "",
                "status": "idle",
                "last_invoked": None,
                "task_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "last_draft_preview": None,
            })

    return jsonify({"agents": agents_status})


@app.route("/api/agents/<agent_id>", methods=["GET"])
def get_agent_stats(agent_id):
    """Get stats for a specific agent (for the agent chat panel)."""
    if agent_id not in agent_registry:
        return jsonify({"error": "Agent not found"}), 404
    tenant_id = str(current_user.id) if not current_user.is_anonymous else None
    stats = {"agent_id": agent_id, "task_count": 0, "success_count": 0, "failure_count": 0, "enabled": agent_registry[agent_id].enabled, "model": agent_registry[agent_id].model}
    if tenant_id:
        try:
            conn = database._get_conn()
            row = conn.execute(
                "SELECT task_count, success_count, failure_count FROM agent_configs WHERE agent_id = ? AND user_id = ?",
                (agent_id, int(tenant_id)),
            ).fetchone()
            if row:
                stats.update(dict(row))
        except Exception:
            pass
    return jsonify(stats)


@app.route("/api/agents/<agent_id>/toggle", methods=["POST"])
def toggle_agent(agent_id):
    """Toggle agent on/off."""
    if agent_id not in agent_registry:
        return jsonify({"error": "Agent not found"}), 404

    agent = agent_registry[agent_id]
    agent.enabled = not agent.enabled

    # Persist toggle to tenant database only if a tenant is selected
    tenant_id = str(current_user.id) if not current_user.is_anonymous else None
    if tenant_id:
        try:
            conn = database._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE agent_configs SET enabled = ? WHERE agent_id = ? AND user_id = ?",
                (int(agent.enabled), agent_id, int(tenant_id)),
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
    api_key = config.get("credentials", {}).get("api_key", "")
    masked_key = ("****" + api_key[-4:]) if api_key and len(api_key) > 4 else ""
    return jsonify({
        "agent_id": agent_id,
        "model": config.get("model", "deepseek-chat"),
        "api_key": masked_key,
        "api_base": config.get("credentials", {}).get("api_base", ""),
    })


@app.route("/api/agents/<agent_id>/config", methods=["POST"])
def update_agent_config(agent_id):
    """Update configuration for a specific agent."""
    if agent_id not in AGENT_CONFIGS:
        return jsonify({"error": "Agent not found"}), 404

    data = request.json
    config = AGENT_CONFIGS[agent_id]

    if "model" in data and data["model"]:
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
    global orchestrator
    orchestrator = Orchestrator(llm_adapter, agent_registry, executioner=executioner, push_manager=push_manager, memory=agent_memory)

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
    global llm_adapter, orchestrator
    if api_key:
        llm_adapter = LLMAdapter(
            model=model if model and model != "__keep__" and LLMAdapter.is_valid_model(model) else llm_adapter.model,
            api_key=api_key,
            api_base=api_base or llm_adapter._api_base,
            temperature=llm_adapter._temperature,
        )

    orchestrator = Orchestrator(llm_adapter, agent_registry, executioner=executioner, push_manager=push_manager, memory=agent_memory)

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
    cls = AGENT_CLASSES.get(agent_id)
    if cls:
        agent_registry[agent_id] = cls(agent_id, config)


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
        global orchestrator
        orchestrator = Orchestrator(llm_adapter, agent_registry, executioner=executioner, push_manager=push_manager, memory=agent_memory)

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

        smtp_host = data.get("smtp_host", "smtp.gmail.com")
        # SSRF prevention: reject private/reserved SMTP hosts
        try:
            smtp_ip = socket.gethostbyname(smtp_host)
            ip_parts = [int(x) for x in smtp_ip.split(".")]
            if (ip_parts[0] == 127 or ip_parts[0] == 10 or ip_parts[0] == 0 or
                ip_parts[0] == 169 and ip_parts[1] == 254 or
                ip_parts[0] == 192 and ip_parts[1] == 168 or
                ip_parts[0] == 172 and 16 <= ip_parts[1] <= 31):
                return jsonify({"error": "SMTP host resolves to a private IP address"}), 400
        except socket.gaierror:
            return jsonify({"error": f"Could not resolve SMTP host: {smtp_host}"}), 400

        server = smtplib.SMTP(smtp_host,
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

        user_id = get_current_user_id()
        autonomy_config = None
        if user_id:
            conn = database._get_conn()
            rows = conn.execute(
                "SELECT agent_id, autonomy, confidence_threshold FROM agent_configs WHERE user_id = ?",
                (int(user_id),),
            ).fetchall()
            autonomy_config = {
                r["agent_id"]: {"autonomy": r["autonomy"], "confidence_threshold": r["confidence_threshold"]}
                for r in rows
            }

        result = orch.process_message(
            user_request, thread_id,
            language=language or None,
            autonomy_config=autonomy_config,
            user_id=int(user_id) if user_id else 0,
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
    for thread_id, draft_info in orch.get_pending_drafts().items():
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
        "pending_drafts": len(orch.get_pending_drafts()),
        "activity_count": len(orch.get_activity_feed(200)),
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


# ---------------------------------------------------------------------------
# API: Frankie features (inbox, undo, personalities, dashboard query)
# ---------------------------------------------------------------------------


@app.route("/api/inbox", methods=["GET"])
def api_inbox():
    """Unified inbox: merges pending approvals, activity, and agent messages."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    limit = request.args.get("limit", 50, type=int)
    orch = get_orchestrator()
    items = []

    # Pending approvals
    for tid, info in orch.get_pending_drafts().items():
        items.append({
            "type": "approval",
            "agent": info.get("agent", "?"),
            "summary": (info.get("draft", "") or "")[:120],
            "thread_id": tid,
            "created_at": info.get("created_at", ""),
            "icon": "🤔",
        })

    # Activity feed
    for a in orch.get_activity_feed(limit):
        items.append({
            "type": "activity",
            "agent": a.get("agent", "?"),
            "summary": a.get("draft_preview", "")[:120],
            "action": a.get("action", ""),
            "created_at": a.get("timestamp", ""),
            "icon": "✅" if a.get("success") else "❌",
        })

    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jsonify({"items": items[:limit]})


@app.route("/api/orchestrator/undo", methods=["POST"])
def api_undo():
    """Undo the last execution."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    orch = get_orchestrator()
    result = orch.undo_last()
    return jsonify(result if result else {"success": False, "action": "nothing_to_undo"})


@app.route("/api/frankie/inspect", methods=["GET"])
def api_frankie_inspect():
    """Frankie inspects the client's live website and returns actionable suggestions."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"suggestions": [], "error": "No user"})
    try:
        conn = database._get_conn()
        row = conn.execute("SELECT site_url, business_name, city, niche FROM client_details WHERE user_id = ? LIMIT 1", (int(user_id),)).fetchone()
    except Exception:
        row = None
    if not row or not row.get("site_url"):
        return jsonify({"suggestions": [], "site": None})

    site_url = row["site_url"]
    business = row.get("business_name", "")
    city = row.get("city", "")
    niche = row.get("niche", "")

    suggestions = []
    try:
        resp = _safe_url(site_url)
        html = resp.text.lower()
        title = ""
        meta_desc = ""
        m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m: title = m.group(1).strip()
        m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE | re.DOTALL)
        if m: meta_desc = m.group(1).strip()
        has_h1 = bool(re.search(r"<h1[^>]*>", html))
        h1_count = len(re.findall(r"<h1[^>]*>", html))
        has_schema = "schema.org" in html or "application/ld+json" in html
        has_og = "og:title" in html
        has_whatsapp = "whatsapp" in html
        has_phone = bool(re.search(r"tel:|\(\d{3}\)\s*\d{3}-\d{4}|\d{3}-\d{3}-\d{4}", html))
        word_count = len(html.split())

        if not title:
            suggestions.append("Your homepage is missing a <title> tag. Add one with your business name and city.")
        else:
            suggestions.append(f"Your site title is: \"{title[:80]}\" — keep it under 60 chars for Google.")

        if not meta_desc:
            suggestions.append("No meta description found. Add one summarizing your services for better click-through rates.")

        if h1_count > 1:
            suggestions.append(f"You have {h1_count} H1 tags. Use only one H1 per page for SEO best practices.")
        elif not has_h1:
            suggestions.append("No H1 heading found. Add one that includes your main service keyword.")

        if not has_schema:
            suggestions.append("No schema.org markup detected. LocalBusiness schema helps you show up in rich results.")

        if not has_og:
            suggestions.append("No Open Graph tags found. These control how your site looks when shared on Facebook and LinkedIn.")

        if not has_phone:
            suggestions.append("No click-to-call phone number detected. Add your phone number prominently for mobile users.")

        if word_count < 100:
            suggestions.append(f"Your homepage only has about {word_count} words. Add more content describing your services for better SEO.")

        if not has_whatsapp:
            pass  # optional

        return jsonify({
            "site": {"url": site_url, "title": title[:80], "meta_desc": meta_desc[:120], "business": business, "city": city, "niche": niche},
            "suggestions": suggestions[:5],
        })
    except Exception as e:
        return jsonify({"suggestions": [f"Could not reach {site_url}. Make sure the site is live."], "site": None})


@app.route("/api/dashboard/ask", methods=["POST"])
def api_dashboard_ask():
    """Frankie: processes both questions AND actions through the orchestrator."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    query = (data or {}).get("query", "").strip()
    if not query:
        return jsonify({"error": "No query provided"}), 400
    lang = "fr" if (session.get("lang") == "fr" or (request.accept_languages and request.accept_languages.best and request.accept_languages.best.startswith("fr"))) else "en"
    try:
        orch = get_orchestrator()
        user_id = get_current_user_id()
        autonomy_config = None
        if user_id:
            conn = database._get_conn()
            rows = conn.execute(
                "SELECT agent_id, autonomy, confidence_threshold FROM agent_configs WHERE user_id = ?",
                (int(user_id),),
            ).fetchall()
            autonomy_config = {
                r["agent_id"]: {"autonomy": r["autonomy"], "confidence_threshold": r["confidence_threshold"]}
                for r in rows
            }

        result = orch.process_message(
            user_message=query,
            thread_id="frankie-" + uuid.uuid4().hex[:8],
            language=lang if lang else None,
            autonomy_config=autonomy_config,
            user_id=int(user_id) if user_id else 0,
            source="frankie",
        )

        status = result.get("status", "error")
        response = result.get("response", "")

        # Format Frankie's response based on what happened
        if status == "pending_approval":
            agent = result.get("agent", "agent")
            p = AGENT_PERSONALITIES.get(agent, {})
            emoji = p.get("emoji", "🤖")
            color = p.get("color", "#6b7280")
            draft_preview = (response or "")[:200]
            en = f"{emoji} I asked **{p.get('short', agent)}** to handle this. Here's the draft:\n\n{draft_preview}\n\n---\n\nYou can **approve** or **reject** it in the Tasks tab."
            fr = f"{emoji} J'ai demandé à **{p.get('short_fr', agent)}** de s'en occuper. Voici le projet :\n\n{draft_preview}\n\n---\n\nVous pouvez **approuver** ou **rejeter** dans l'onglet Tâches."
            return jsonify({"response": fr if lang == "fr" else en, "pending_approval": True, "agent": agent, "thread_id": result.get("thread_id")})
        elif status == "auto_executed":
            agent = result.get("agent", "agent")
            p = AGENT_PERSONALITIES.get(agent, {})
            emoji = p.get("emoji", "✅")
            en = f"{emoji} Done! **{p.get('short', agent)}** handled it automatically."
            fr = f"{emoji} Terminé ! **{p.get('short_fr', agent)}** s'en est occupé automatiquement."
            return jsonify({"response": fr if lang == "fr" else en})
        elif status == "executed_silent":
            return jsonify({"response": "✅ Done."})
        elif status == "error":
            return jsonify({"response": response or "I couldn't process that."})
        else:
            return jsonify({"response": response or "Done."})
    except Exception as e:
        logger.error("Frankie query failed: %s", e, exc_info=True)
        fallback = "Je n'ai pas pu traiter ça. Essayez de me parler des agents, des approbations ou de l'activité récente." if lang == "fr" else "I couldn't process that. Try asking about agents, approvals, or recent activity."
        return jsonify({"response": fallback})


AGENT_PERSONALITIES = {
    "local_seo": {"emoji": "📍", "color": "#10b981", "short": "Local SEO", "short_fr": "SEO Local"},
    "social_media": {"emoji": "📱", "color": "#3b82f6", "short": "Social", "short_fr": "Sociaux"},
    "lead_conversion": {"emoji": "🎯", "color": "#f59e0b", "short": "Leads", "short_fr": "Prospects"},
    "paid_ads": {"emoji": "📢", "color": "#ef4444", "short": "Ads", "short_fr": "Annonces"},
    "growth_hacker": {"emoji": "🚀", "color": "#8b5cf6", "short": "Growth", "short_fr": "Croissance"},
    "reputation": {"emoji": "⭐", "color": "#06b6d4", "short": "Reputation", "short_fr": "Réputation"},
    "email_marketing": {"emoji": "✉️", "color": "#ec4899", "short": "Email", "short_fr": "Courriel"},
    "tiktok": {"emoji": "🎬", "color": "#14b8a6", "short": "TikTok", "short_fr": "TikTok"},
    "outreach": {"emoji": "🤝", "color": "#f97316", "short": "Outreach", "short_fr": "Prospection"},
    "backlinks": {"emoji": "🔗", "color": "#6366f1", "short": "Backlinks", "short_fr": "Liens"},
    "content_strategy": {"emoji": "📝", "color": "#84cc16", "short": "Content", "short_fr": "Contenu"},
    "technical_seo": {"emoji": "⚙️", "color": "#06b6d4", "short": "Tech SEO", "short_fr": "SEO Tech"},
    "reporting": {"emoji": "📊", "color": "#a855f7", "short": "Reports", "short_fr": "Rapports"},
    "cro": {"emoji": "📐", "color": "#f43f5e", "short": "CRO", "short_fr": "CRO"},
    "video": {"emoji": "🎥", "color": "#eab308", "short": "Video", "short_fr": "Vidéo"},
    "sms_marketing": {"emoji": "💬", "color": "#06b6d4", "short": "SMS", "short_fr": "SMS"},
    "executioner": {"emoji": "⚡", "color": "#64748b", "short": "Execute", "short_fr": "Exécution"},
}


@app.route("/api/personalities", methods=["GET"])
def api_personalities():
    """Return agent personalities (emoji, color, short name).
    Supports ``?lang=fr`` for French names."""
    lang = request.args.get("lang", "en")
    data = {}
    for aid, p in AGENT_PERSONALITIES.items():
        entry = dict(p)
        entry["short"] = p.get("short_fr", p["short"]) if lang == "fr" else p["short"]
        data[aid] = entry
    return jsonify({"personalities": data})


# ---------------------------------------------------------------------------
# API: Onboarding wizard
# ---------------------------------------------------------------------------


@app.route("/api/onboarding/status", methods=["GET"])
def api_onboarding_status():
    """Return onboarding completion status for the current user."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"onboarded": False, "error": "No user"}), 400
    return jsonify({"onboarded": True, "steps": {"welcome": True, "agents": True, "autonomy": True, "done": True}})


@app.route("/api/onboarding/step", methods=["POST"])
def api_onboarding_step():
    """Stub — onboarding was removed. Always returns success."""
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# API: Scheduler (scheduled agent tasks)
# ---------------------------------------------------------------------------


@app.route("/api/schedules", methods=["GET"])
def api_list_schedules():
    """List all scheduled tasks (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    tenant_id = request.args.get("tenant_id", "")
    schedules = scheduler_manager.get_schedules(user_id=int(tenant_id) if tenant_id else None)
    return jsonify({"schedules": schedules, "enabled": scheduler_manager.enabled})


@app.route("/api/schedules", methods=["POST"])
def api_create_schedule():
    """Create a new scheduled task (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
    tenant_id = data.get("tenant_id", "")
    agent_id = data.get("agent_id", "")
    task = data.get("task", "")
    cron = data.get("cron", "")
    lang = data.get("language", "en")
    if not all([tenant_id, agent_id, task, cron]):
        return jsonify({"error": "tenant_id, agent_id, task, and cron are required"}), 400
    sid = scheduler_manager.create_schedule(int(tenant_id), agent_id, task, cron, lang)
    return jsonify({"id": sid, "success": True}), 201


@app.route("/api/schedules/<schedule_id>", methods=["DELETE"])
def api_delete_schedule(schedule_id):
    """Delete a scheduled task (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    ok = scheduler_manager.delete_schedule(schedule_id)
    return jsonify({"success": ok})


@app.route("/api/schedules/<schedule_id>/toggle", methods=["POST"])
def api_toggle_schedule(schedule_id):
    """Enable or disable a scheduled task (admin only)."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    enabled = (data or {}).get("enabled", True)
    ok = scheduler_manager.toggle_schedule(schedule_id, enabled)
    return jsonify({"success": ok})


@app.route("/admin/dashboard")
def admin_dashboard():
    """Serve the real-time agent dashboard."""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    return render_template(
        "admin/dashboard.html",
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
    tenant_id = session.get("active_user_id", "your-tenant")
    base_url = request.url_root.rstrip("/")
    bookmarklet_code = (
        'javascript:(function(){var s=document.createElement("script");'
        f's.src="{base_url}/static/bookmarklet.js";'
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
        conn = database._get_conn()
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
        conn = database._get_conn()
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
        conn = database._get_conn()
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
    tenant_id = session.get("active_user_id") or getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return jsonify({"actions": []})
    actions = _get_pending_actions(tenant_id)
    return jsonify({"actions": actions})


@app.route("/api/actions/sms-pending", methods=["GET"])
def api_sms_pending():
    """Return pending SMS messages from the executioner's JSONL queue."""
    sms_file = Path(__file__).parent / "content" / "sms" / "sms.jsonl"
    if not sms_file.exists():
        return jsonify({"messages": []})
    messages = []
    for line in sms_file.read_text().strip().split("\n"):
        if line.strip():
            try:
                msg = json.loads(line)
                if msg.get("status") == "queued":
                    messages.append(msg)
            except json.JSONDecodeError:
                continue
    return jsonify({"messages": messages[::-1]})


@app.route("/api/actions/<action_id>/confirm", methods=["POST"])
def api_confirm_action(action_id):
    """Confirm and execute a pending action (called by bookmarklet or email bridge)."""
    tenant_id = session.get("active_user_id") or getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return jsonify({"error": "No tenant context"}), 400
    result = _confirm_pending_action(tenant_id, action_id)
    return jsonify(result)


@app.route("/api/actions/sms-sent", methods=["POST"])
def api_sms_mark_sent():
    """Mark an SMS as sent so it doesn't show up in pending again."""
    data = request.json
    timestamp = (data or {}).get("timestamp", "")
    if not timestamp:
        return jsonify({"error": "timestamp required"}), 400
    sms_file = Path(__file__).parent / "content" / "sms" / "sms.jsonl"
    if not sms_file.exists():
        return jsonify({"success": True})
    try:
        lines = sms_file.read_text().strip().split("\n")
        new_lines = []
        for line in lines:
            if line.strip():
                try:
                    msg = json.loads(line)
                    if msg.get("timestamp") == timestamp:
                        msg["status"] = "sent"
                    new_lines.append(json.dumps(msg))
                except json.JSONDecodeError:
                    new_lines.append(line)
        sms_file.write_text("\n".join(new_lines) + "\n")
    except Exception:
        pass
    return jsonify({"success": True})


@app.route("/api/actions/<action_id>/skip", methods=["POST"])
def api_skip_action(action_id):
    """Skip/discard a pending action without executing."""
    tenant_id = session.get("active_user_id") or getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return jsonify({"error": "No tenant context"}), 400
    try:
        conn = database._get_conn()
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
    if not current_user.is_authenticated and not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
    tenant_id = current_user.tenant_id
    settings = {
        "imap_host": data.get("imap_host", "imap.gmail.com"),
        "imap_port": int(data.get("imap_port", 993)),
        "username": data.get("email", ""),
        "password": _encrypt_credential(data.get("password", "")),
    }
    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO client_details (user_id, email, services) "
            "VALUES (?, COALESCE((SELECT email FROM client_details WHERE user_id=?), ?), ?)",
            (int(tenant_id), int(tenant_id), settings["username"], json.dumps({"email_bridge": settings})),
        )
        conn.commit()
        decrypted_pw = _decrypt_credential(settings["password"])
        bridge = _get_email_bridge()
        bridge.stop()
        bridge2 = EmailBridge(
            imap_host=settings["imap_host"],
            imap_port=settings["imap_port"],
            username=settings["username"],
            password=decrypted_pw,
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
                conn = database._get_conn()
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

# Start proactive monitor
proactive_monitor.start(get_orchestrator, lambda: push_manager)

# Start scheduler
from core.scheduler import SchedulerManager
scheduler_manager = SchedulerManager(get_orchestrator)
scheduler_manager.start()


@app.route("/api/agents/<agent_id>/autonomy", methods=["GET", "PUT"])
def api_agent_autonomy(agent_id):
    """Get or update autonomy settings for an agent in the current user."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "No user selected"}), 400

    conn = database._get_conn()
    uid = int(user_id)

    if request.method == "PUT":
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400

        autonomy = data.get("autonomy", "manual")
        threshold = float(data.get("confidence_threshold", 0.7))

        if autonomy not in ("manual", "suggest", "auto", "silent"):
            return jsonify({"error": f"Invalid autonomy '{autonomy}'. Must be one of: manual, suggest, auto, silent"}), 400

        conn.execute(
            "UPDATE agent_configs SET autonomy = ?, confidence_threshold = ? WHERE user_id = ? AND agent_id = ?",
            (autonomy, threshold, uid, agent_id),
        )
        conn.commit()
        return jsonify({"agent_id": agent_id, "autonomy": autonomy, "confidence_threshold": threshold})

    rows = conn.execute(
        "SELECT agent_id, autonomy, confidence_threshold FROM agent_configs WHERE user_id = ?",
        (uid,),
    ).fetchall()
    configs = {r["agent_id"]: {"autonomy": r["autonomy"], "confidence_threshold": r["confidence_threshold"]} for r in rows}
    cfg = configs.get(agent_id, {"autonomy": "manual", "confidence_threshold": 0.7})
    return jsonify({"agent_id": agent_id, **cfg})


@app.route("/api/agents/autonomy/bulk", methods=["GET"])
def api_all_agent_autonomy():
    """Get autonomy settings for all agents in the current user."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "No user selected"}), 400
    conn = database._get_conn()
    rows = conn.execute(
        "SELECT agent_id, autonomy, confidence_threshold FROM agent_configs WHERE user_id = ?",
        (int(user_id),),
    ).fetchall()
    configs = {r["agent_id"]: {"autonomy": r["autonomy"], "confidence_threshold": r["confidence_threshold"]} for r in rows}
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
    tenant_id = get_current_user_id()

    orch = get_orchestrator()

    # Delegate to orchestrator which now handles execution internally
    drafts = orch.get_pending_drafts()
    if thread_id in drafts:
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
            conn = database._get_conn()
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
                # Try MCP execution first, fall back to Executioner
                exec_result = None
                mcp_mapping = AGENT_MCP_ROUTING

                mapping = mcp_mapping.get(agent_name)
                if mapping:
                    server_name, tool_name = mapping
                    mcp_server = get_mcp_server(server_name)
                    if mcp_server:
                        try:
                            mcp_result = mcp_server.call_tool(tool_name, content=draft)
                            exec_result = {
                                "success": mcp_result.get("success", False),
                                "result": mcp_result.get("result", ""),
                                "error": mcp_result.get("error"),
                                "execution_id": f"mcp-{server_name}-{tool_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                            }
                            logger.info(f"MCP execution: {server_name}/{tool_name} → success={exec_result['success']}")
                        except Exception as e:
                            logger.warning(f"MCP execution failed, falling back to Executioner: {e}")

                # Fall back to old Executioner if MCP failed or no mapping
                if not exec_result:
                    try:
                        exec_result = executioner.execute(agent_name, draft)
                    except Exception as exec_err:
                        exec_result = {"success": False, "error": str(exec_err)}

                execution_result = {
                    "success": exec_result.get("success", False),
                    "result": exec_result.get("result", "")
                }

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

    tenant_id = get_current_user_id()
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

    tenant_id = str(current_user.id) if not current_user.is_anonymous else None
    now_iso = datetime.now().isoformat()

    # Build conversation context from previous messages in this thread
    conversation_context = ""
    if tenant_id:
        try:
            uid = int(tenant_id)
            conn = database._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT agent_task, agent_draft FROM threads WHERE thread_id = ? AND user_id = ? ORDER BY created_at ASC LIMIT 20",
                (thread_id, uid)
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
                uid = int(tenant_id)
                conn = database._get_conn()
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO threads
                       (thread_id, routed_agent, agent_task, agent_draft, status, created_at, updated_at, user_id)
                       VALUES (?, ?, ?, ?, 'chat', ?, ?, ?)""",
                    (thread_id, agent_id, message, draft, now_iso, now_iso, uid)
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

    tenant_id = get_current_user_id()
    if not tenant_id:
        return jsonify({"threads": []})

    try:
        conn = database._get_conn()
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

    tenant_id = get_current_user_id()
    if not tenant_id:
        return jsonify({"messages": []})

    try:
        conn = database._get_conn()
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
        tenant_id = session.get("active_user_id")
    else:
        tenant_id = getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return jsonify({"threads": []})

    agent_filter = request.args.get("agent", "")
    try:
        conn = database._get_conn()
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
        tenant_id = session.get("active_user_id")
    else:
        tenant_id = getattr(current_user, "tenant_id", None) if not current_user.is_anonymous else None
    if not tenant_id:
        return jsonify({"messages": []})

    try:
        conn = database._get_conn()
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
        conn = database._get_conn()
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
        conn = database._get_conn()
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

    direct = [str(u["id"]) for u in database.list_users(role='user')]

    return jsonify({
        "direct_clients": direct,
        "active_tenant": session.get("active_user_id"),
    })


@app.route("/api/tenants/switch", methods=["POST"])
def switch_tenant():
    """Switch the admin's active tenant context."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    tenant_id = data.get("tenant_id")

    if tenant_id:
        session["active_user_id"] = tenant_id
        return jsonify({
            "active_tenant": tenant_id,
            "message": f"Switched to {tenant_id}",
        })
    else:
        session.pop("active_user_id", None)
        return jsonify({
            "active_tenant": None,
            "message": "Client cleared",
        })


# ---------------------------------------------------------------------------
# Analytics routes
# ---------------------------------------------------------------------------

from core.analytics import AnalyticsEngine


@app.route("/api/analytics/summary")
def api_analytics_summary():
    """Return summary analytics for a user or all users (admin)."""
    user_id = request.args.get("client", "").strip()
    days = int(request.args.get("days", 30))
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    is_admin = session.get("admin_logged_in", False)
    session_user = session.get("active_user_id") or getattr(current_user, "id", None)

    if user_id and is_admin:
        engine = AnalyticsEngine(int(user_id))
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
                "user_id": user_id,
                "leads": perf.get("leads_this_month", 0),
                "tasks": perf.get("tasks_this_month", 0),
                "success_rate": perf.get("success_rate", 0),
                "active_agents": perf.get("active_agents", 0),
            }],
        })

    if is_admin:
        all_users = database.list_users(role='user')
        all_user_ids = [str(u["id"]) for u in all_users]
        total_leads = 0
        total_tasks = 0
        total_success = 0
        total_fail = 0
        all_tasks_per_agent = {}
        all_failures_by_tool = {}
        all_leads_by_month = {}
        all_recent_leads = []
        all_recent_execs = []
        for uid in all_user_ids:
            e = AnalyticsEngine(int(uid))
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
        total_clients = len(all_user_ids)
        avg_sr = round((total_success / (total_success + total_fail) * 100) if (total_success + total_fail) else 0, 1)
        return jsonify({
            "total_clients": total_clients,
            "total_leads": total_leads,
            "total_tasks": total_tasks,
            "success_count": total_success,
            "fail_count": total_fail,
            "avg_success_rate": avg_sr,
            "active_agents": len(all_tasks_per_agent),
            "total_agents": len(database.DEFAULT_AGENTS),
            "leads_this_month": total_leads,
            "tasks_this_month": total_tasks,
            "leads_by_month": leads_by_month,
            "tasks_per_agent": list(all_tasks_per_agent.values()),
            "failures_by_tool": all_failures_by_tool,
            "recent_leads": sorted(all_recent_leads, key=lambda x: x.get("name", ""))[:20],
            "recent_executions": sorted(all_recent_execs, key=lambda x: x.get("timestamp", ""), reverse=True)[:20],
        })

    if not is_admin and session_user:
        engine = AnalyticsEngine(int(session_user))
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
    user_id = request.args.get("client", "").strip() or session.get("active_user_id") or getattr(current_user, "id", None)
    start = request.args.get("start")
    end = request.args.get("end")
    if not user_id:
        return jsonify({"error": "No user context"}), 400
    engine = AnalyticsEngine(int(user_id))
    return jsonify(engine.get_lead_metrics(start, end))


@app.route("/api/analytics/agents")
def api_analytics_agents():
    """Return agent performance metrics."""
    user_id = request.args.get("client", "").strip() or session.get("active_user_id") or getattr(current_user, "id", None)
    start = request.args.get("start")
    end = request.args.get("end")
    if not user_id:
        return jsonify({"error": "No user context"}), 400
    engine = AnalyticsEngine(int(user_id))
    return jsonify(engine.get_agent_metrics(start, end))


@app.route("/api/analytics/executions")
def api_analytics_executions():
    """Return execution metrics."""
    user_id = request.args.get("client", "").strip() or session.get("active_user_id") or getattr(current_user, "id", None)
    start = request.args.get("start")
    end = request.args.get("end")
    if not user_id:
        return jsonify({"error": "No user context"}), 400
    engine = AnalyticsEngine(int(user_id))
    return jsonify(engine.get_execution_metrics(start, end))


@app.route("/api/analytics/report/generate", methods=["POST"])
def api_analytics_generate_report():
    """Generate a monthly report HTML for a tenant."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    user_id = data.get("user_id") or session.get("active_user_id")
    month = data.get("month")
    year = data.get("year")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    engine = AnalyticsEngine(int(user_id))
    html = engine.generate_monthly_report(year, month)
    return jsonify({"html": html})


# In-memory report history store (survives within a process lifetime)
_report_history: list = []


@app.route("/api/analytics/report/save", methods=["POST"])
def api_analytics_save_report():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    report_id = uuid.uuid4().hex[:12]
    entry = {
        "id": report_id,
        "user_id": data.get("user_id", ""),
        "month": data.get("month"),
        "year": data.get("year"),
        "html": data.get("html", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _report_history.insert(0, entry)
    _report_history[:] = _report_history[:100]
    return jsonify({"success": True, "id": report_id})


@app.route("/api/analytics/reports/history", methods=["GET"])
def api_analytics_report_history():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    user_id = request.args.get("user_id", "")
    reports = [r for r in _report_history if not user_id or r.get("user_id") == user_id]
    safe = [{"id": r["id"], "month": r["month"], "year": r["year"], "created_at": r["created_at"]} for r in reports]
    return jsonify({"reports": safe})


@app.route("/api/analytics/report/<report_id>", methods=["GET"])
def api_analytics_get_report(report_id):
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    for r in _report_history:
        if r["id"] == report_id:
            return jsonify({"html": r["html"]})
    return jsonify({"error": "Report not found"}), 404


@app.route("/api/analytics/report/<report_id>/email", methods=["POST"])
def api_analytics_email_saved_report(report_id):
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    report = None
    for r in _report_history:
        if r["id"] == report_id:
            report = r
            break
    if not report:
        return jsonify({"error": "Report not found"}), 404
    # Forward to the existing email endpoint
    from flask import request as _flask_req
    with app.test_request_context(json={"html": report["html"], "user_id": report["user_id"]}):
        try:
            return api_analytics_email_report()
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/analytics/report/email", methods=["POST"])
def api_analytics_email_report():
    """Email a monthly report to the client."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    user_id = data.get("user_id")
    month = data.get("month")
    year = data.get("year")
    html = data.get("html")
    if not user_id or not html:
        return jsonify({"error": "user_id and html are required"}), 400
    try:
        engine = AnalyticsEngine(int(user_id))
        biz_row = engine._fetchone("SELECT business_name, email FROM client_details LIMIT 1")
        business_name = biz_row["business_name"] if biz_row else user_id
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
        "direct_clients": [str(u["id"]) for u in database.list_users(role='user')],
    }
    active_tenant = session.get("active_user_id")
    return render_template("admin.html", tenants=tenants, active_tenant=active_tenant)


@app.route("/admin/reports")
def admin_reports_page():
    """Serve the report generation page."""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    tenants = {
        "direct_clients": [str(u["id"]) for u in database.list_users(role='user')],
    }
    active_tenant = session.get("active_user_id")
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
    user_id = current_user.id
    engine = AnalyticsEngine(user_id)
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
        conn = database._get_conn()
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
        conn = database._get_conn()
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
        conn = database._get_conn()
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
    all_tenants = [str(u["id"]) for u in database.list_users(role='user')]
    clients = []
    total_mrr = 0
    total_pending = 0
    past_due_count = 0

    for tid in all_tenants:
        try:
            conn = database._get_conn()
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
        conn = database._get_conn()
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
        conn = database._get_conn()
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
        conn = database._get_conn()
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
    all_tenants = [str(u["id"]) for u in database.list_users(role='user')]
    active_count = 0
    for tid in all_tenants:
        try:
            conn = database._get_conn()
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
        "direct_clients": [str(u["id"]) for u in database.list_users(role='user')],
    }
    active_tenant = session.get("active_user_id")
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
# MCP Server API routes
# ---------------------------------------------------------------------------

@app.route("/api/mcp/servers", methods=["GET"])
def list_mcp_servers():
    """List all available MCP servers and their status."""
    servers = {}
    for name, server in get_all_mcp_servers().items():
        servers[name] = server.get_status()
    return jsonify({"servers": servers})


@app.route("/api/mcp/servers/<server_name>/tools", methods=["GET"])
def list_mcp_tools(server_name):
    """List all tools for a specific MCP server."""
    server = get_mcp_server(server_name)
    if not server:
        return jsonify({"error": f"MCP server '{server_name}' not found"}), 404
    return jsonify({"server": server_name, "tools": server.list_tools()})


@app.route("/api/mcp/call", methods=["POST"])
def call_mcp_tool():
    """Call a tool on an MCP server.

    Request body:
    {
        "server": "seo",
        "tool": "publish_blog_post",
        "params": {
            "content": "Blog post content...",
            "title": "My Blog Post",
            "cms_type": "wordpress",
            "api_credentials": {...}
        }
    }
    """
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    server_name = data.get("server", "")
    tool_name = data.get("tool", "")
    params = data.get("params", {})

    if not server_name or not tool_name:
        return jsonify({"error": "server and tool are required"}), 400

    server = get_mcp_server(server_name)
    if not server:
        return jsonify({"error": f"MCP server '{server_name}' not found"}), 404

    result = server.call_tool(tool_name, **params)
    return jsonify(result)


@app.route("/api/mcp/credentials", methods=["GET"])
def get_mcp_credentials():
    """Get stored MCP credentials for the current tenant."""
    tenant_id = get_current_user_id()
    if not tenant_id:
        return jsonify({"credentials": {}, "error": "No tenant selected"}), 400

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT server_name, platform, credential_key, credential_value FROM mcp_credentials WHERE user_id = ?", (int(tenant_id),))
        creds = {}
        for row in cursor.fetchall():
            key = f"{row['server_name']}.{row['platform']}.{row['credential_key']}"
            try:
                creds[key] = _decrypt_credential(row["credential_value"])
            except Exception:
                creds[key] = row["credential_value"]
        return jsonify({"credentials": creds})
    except Exception as e:
        return jsonify({"credentials": {}, "error": str(e)})


@app.route("/api/mcp/credentials", methods=["POST"])
def save_mcp_credentials():
    """Save MCP credentials for the current tenant."""
    tenant_id = get_current_user_id()
    if not tenant_id:
        return jsonify({"error": "No tenant selected"}), 400

    data = request.json
    server_name = data.get("server_name", "")
    platform = data.get("platform", "")
    credentials = data.get("credentials", {})

    if not server_name:
        return jsonify({"error": "server_name is required"}), 400

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        for key, value in credentials.items():
            encrypted = _encrypt_credential(str(value))
            cursor.execute("""
                INSERT OR REPLACE INTO mcp_credentials
                (user_id, server_name, platform, credential_key, credential_value, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM mcp_credentials WHERE server_name=? AND platform=? AND credential_key=?), ?), ?)
            """, (int(tenant_id), server_name, platform, key, encrypted, server_name, platform, key, now, now))

        conn.commit()
        return jsonify({"success": True, "message": f"Credentials saved for {server_name}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/mcp/credentials/<server_name>", methods=["DELETE"])
def delete_mcp_credentials(server_name):
    """Delete all credentials for an MCP server."""
    tenant_id = get_current_user_id()
    if not tenant_id:
        return jsonify({"error": "No tenant selected"}), 400

    try:
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM mcp_credentials WHERE user_id = ? AND server_name = ?", (int(tenant_id), server_name))
        conn.commit()
        return jsonify({"success": True, "message": f"Credentials deleted for {server_name}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/mcp/execute", methods=["POST"])
def execute_via_mcp():
    """Execute an approved agent draft via the appropriate MCP server.
    Auto-selects the correct MCP server based on the agent that generated the content.
    """
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    agent_id = data.get("agent_id", "")
    content = data.get("content", "")

    if not agent_id or not content:
        return jsonify({"error": "agent_id and content are required"}), 400

    mapping = AGENT_MCP_ROUTING.get(agent_id)
    if not mapping:
        return jsonify({"error": f"No MCP mapping for agent '{agent_id}'"}), 400

    server_name, tool_name = mapping
    server = get_mcp_server(server_name)
    if not server:
        return jsonify({"error": f"MCP server '{server_name}' not found"}), 404

    result = server.call_tool(tool_name, content=content)
    return jsonify(result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
