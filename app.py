import os
import re
import sys
import uuid
import secrets
import warnings
import json
import logging
import logging.handlers

_PII_PATTERNS = [
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'), '[EMAIL]'),
    (re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'), '[PHONE]'),
    (re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'), '[CCARD]'),
]


class PIIRedactFilter(logging.Filter):
    def filter(self, record):
        if record.getMessage():
            msg = record.getMessage()
            for pattern, replacement in _PII_PATTERNS:
                msg = pattern.sub(replacement, msg)
            record.msg = msg
            record.args = ()
        if record.exc_text:
            for pattern, replacement in _PII_PATTERNS:
                record.exc_text = pattern.sub(replacement, record.exc_text)
        return True
import ssl
import threading
import requests
from functools import wraps
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

from mcp._safe_url import is_safe_url as _is_safe_url


def _safe_url(url: str, timeout: int = 10) -> requests.Response:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Blocked URL scheme: {parsed.scheme}")
    if not _is_safe_url(url):
        raise ValueError(f"Blocked request to private/reserved IP: {parsed.hostname}")
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "LavalDigital/1.0 (Security Scanner)"}, allow_redirects=False)
    try:
        return resp
    finally:
        resp.close()


def _safe_error(e: Exception, status: int = 500):
    logger.error("Internal error: %s", e, exc_info=True)
    return api_error("An internal error occurred.", status)


def _safe_int(val, default=0):
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


warnings.filterwarnings("ignore", module="langgraph")
warnings.filterwarnings("ignore", module="langchain")

from flask import (Flask, render_template, jsonify, request,
                   redirect, url_for, session, flash, g, abort,
                   Response, stream_with_context)
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
from core.api_helpers import api_success, api_error
from core.auth import admin_required
from core.blog_articles import ARTICLES_EN, ARTICLES_FR, ARTICLES_BY_SLUG_EN, ARTICLES_BY_SLUG_FR

from mcp import init_mcp_servers, get_all_mcp_servers, get_mcp_server, get_all_mcp_tools, AGENT_MCP_ROUTING

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64 as _b64

from core.orchestrator import Orchestrator
from core.llm_adapter import LLMAdapter
from core.events import get_event_bus
from core.push import PushManager
from core.memory import AgentMemory
from core.monitor import monitor as proactive_monitor
from core.email_bridge import EmailBridge
from core.base_agent import BaseAgent
from agents.executioner_agent import ExecutionerAgent

AGENT_CLASSES = dict.fromkeys(
    ["local_seo", "social_media", "lead_conversion", "paid_ads",
     "growth_hacker", "reputation", "email_marketing", "tiktok",
     "outreach", "backlinks", "content_strategy", "technical_seo",
     "reporting", "cro", "video", "sms_marketing"],
    BaseAgent,
)

from core.auth import (
    init_auth, User, find_user_by_email, add_user_to_tenant,
    client_required, SESSION_TIMEOUT,
    validate_password, _check_rate_limit, _record_attempt,
)

from core import database
from core.affiliates import AffiliateManager
from core.speech import SpeechEngine
from core.scheduler import SchedulerManager
from core.analytics import AnalyticsEngine


def _derive_fernet_key() -> Fernet:
    secret = os.getenv("FLASK_SECRET_KEY", "").encode()
    salt_str = os.getenv("CREDENTIAL_SALT")
    if salt_str:
        salt = salt_str.encode()[:16].ljust(16, b'\0')
        kdf: Any = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100_000)
    else:
        kdf = HKDF(algorithm=hashes.SHA256(), length=32, info=b"laval-credential-encryption-v2", salt=None)
    key = _b64.urlsafe_b64encode(kdf.derive(secret))
    return Fernet(key)


def _encrypt_credential(plaintext: str) -> str:
    from core.app_state import get_credential_cipher
    return get_credential_cipher().encrypt(plaintext.encode()).decode()


def _decrypt_credential(ciphertext: str) -> str:
    from core.app_state import get_credential_cipher
    return get_credential_cipher().decrypt(ciphertext.encode()).decode()


def create_app(config_name: Optional[str] = None):
    load_dotenv()

    import sentry_sdk
    sentry_dsn = os.getenv("SENTRY_DSN")
    if sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            enable_tracing=True,
            traces_sample_rate=0.1,
            profiles_sample_rate=0.1,
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
    if len(pw) < 8:
        raise RuntimeError(
            "ADMIN_PASSWORD must be at least 8 characters."
        )
    if not any(c.isupper() for c in pw):
        raise RuntimeError(
            "ADMIN_PASSWORD must include at least one uppercase letter."
        )
    if not any(c.islower() for c in pw):
        raise RuntimeError(
            "ADMIN_PASSWORD must include at least one lowercase letter."
        )
    if not any(c.isdigit() for c in pw):
        raise RuntimeError(
            "ADMIN_PASSWORD must include at least one digit."
        )
    if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?`~" for c in pw):
        raise RuntimeError(
            "ADMIN_PASSWORD must include at least one special character."
        )
    if not os.getenv("CREDENTIAL_SALT"):
        logger.warning(
            "CREDENTIAL_SALT not set — using HKDF domain separation (recommended). "
            "To use a legacy custom salt, set CREDENTIAL_SALT in .env."
        )

    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY")
    app.permanent_session_lifetime = timedelta(hours=8)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
    if os.getenv("DEV_MODE", "").lower() not in ("true", "1"):
        app.config["SESSION_COOKIE_SECURE"] = True

    app.config["CONTACT_PHONE"] = os.getenv("CONTACT_PHONE", "(514) 243-1580")
    app.config["CONTACT_EMAIL"] = os.getenv("CONTACT_EMAIL", "lavaldigital@gmail.com")
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

    _API_PUBLIC: set = {
        "/api/affiliate/status",
        "/api/affiliate/signup",
        "/api/contact",
        "/api/push/vapid-key",
        "/api/personalities",
        "/api/models",
        "/api/signup",
        "/api/leads",
        "/api/orchestrator/welcome",
        "/api/orchestrator/suggestions",
        "/api/push/subscribe",
        "/api/push/unsubscribe",
        "/api/training/articles",
        "/api/training/feedback",
        "/api/health",
    }

    csrf = CSRFProtect(app)

    _log_handler = logging.handlers.RotatingFileHandler(
        "logs/app.log", maxBytes=10 * 1024 * 1024, backupCount=5,
    )
    _log_handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(name)s: %(message)s"
    ))
    _log_handler.setLevel(logging.INFO)
    _log_handler.addFilter(PIIRedactFilter())
    logging.getLogger().addHandler(_log_handler)

    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
    ))
    _console_handler.setLevel(logging.WARNING)
    _console_handler.addFilter(PIIRedactFilter())
    logging.getLogger().addHandler(_console_handler)

    logging.getLogger().setLevel(logging.INFO)

    database.init_db()

    affiliate_manager = AffiliateManager()
    push_manager = PushManager()
    agent_memory = AgentMemory()

    login_manager = init_auth(app)

    from blueprints.admin_bp import admin_bp, admin_fr_bp
    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_fr_bp)

    from blueprints.affiliate_bp import affiliate_bp
    app.register_blueprint(affiliate_bp)
    from blueprints.mcp_bp import mcp_bp
    app.register_blueprint(mcp_bp)
    from blueprints.training_bp import training_bp
    app.register_blueprint(training_bp)
    from blueprints.client_bp import client_bp
    app.register_blueprint(client_bp)
    from blueprints.executioner_bp import executioner_bp
    app.register_blueprint(executioner_bp)
    from blueprints.analytics_bp import analytics_bp
    app.register_blueprint(analytics_bp)
    from blueprints.managed_bp import managed_bp
    app.register_blueprint(managed_bp)
    from blueprints.public_bp import public_bp
    app.register_blueprint(public_bp)
    from blueprints.agents_bp import agents_bp
    app.register_blueprint(agents_bp)
    from blueprints.orchestrator_bp import orchestrator_bp
    app.register_blueprint(orchestrator_bp)
    from blueprints.speech_bp import speech_bp
    app.register_blueprint(speech_bp)
    from blueprints.schedules_bp import schedules_bp
    app.register_blueprint(schedules_bp)
    from blueprints.actions_bp import actions_bp
    app.register_blueprint(actions_bp)
    from blueprints.users_bp import users_bp
    app.register_blueprint(users_bp)

    for rule in app.url_map.iter_rules():
        if rule.rule in _API_PUBLIC and rule.methods and not {'GET', 'HEAD', 'OPTIONS'}.issuperset(rule.methods):
            csrf._exempt_views.add(rule.endpoint)

    @app.context_processor
    def inject_csrf_token():
        return dict(csrf_token=lambda: generate_csrf())

    @app.before_request
    def generate_request_id():
        g.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def inject_csp_nonce():
        return dict(csp_nonce=getattr(g, "csp_nonce", ""))

    @app.context_processor
    def inject_static_versions():
        import os as _os
        _static_dir = _os.path.join(app.root_path, "static")
        versions = {}
        for _f in ("admin.js", "admin.css"):
            _path = _os.path.join(_static_dir, _f)
            try:
                versions[_f] = int(_os.path.getmtime(_path))
            except OSError:
                versions[_f] = "0"
        return dict(static_versions=versions)

    @app.after_request
    def add_security_headers(response):
        if response.content_type and response.content_type.startswith("application/json"):
            response.content_type = "application/json; charset=utf-8"
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        nonce = getattr(g, "csp_nonce", "")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net; "
            f"style-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "style-src-attr 'unsafe-inline'; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self' https://api.deepseek.com; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "upgrade-insecure-requests"
        )
        ALLOWED_ORIGINS = {"https://lavaldigital.ca", "https://www.lavaldigital.ca", "http://127.0.0.1:5000", "http://localhost:5000"}
        origin = request.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-CSRFToken, Authorization"
            response.headers["Vary"] = "Origin"
        return response

    @app.route("/api/health")
    def health_check():
        try:
            conn = database._get_conn()
            conn.execute("SELECT 1")
            return jsonify({"status": "healthy", "database": "ok"})
        except Exception as e:
            logger.error("Health check failed: %s", e)
            return jsonify({"status": "unhealthy", "database": "error"}), 503

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not found"}), 404
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        logger.error("Internal server error: %s", e, exc_info=True)
        if request.path.startswith("/api/"):
            return jsonify({"error": "Internal server error"}), 500
        return render_template("500.html"), 500

    @app.route("/favicon.ico")
    def favicon():
        return redirect(url_for("static", filename="favicon.svg"))

    @app.before_request
    def require_api_auth():
        if not request.path.startswith("/api/"):
            return
        if request.path in _API_PUBLIC:
            return
        if current_user.is_authenticated and current_user.role == "admin":
            return
        if current_user.is_authenticated:
            return
        if request.method == "OPTIONS":
            return
        return api_error("Authentication required", 401)

    def get_tenant_agent_activity(user_id: str) -> dict:
        try:
            uid = _safe_int(user_id)
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
            logger.error("Failed to get agent activity for user %s: %s", user_id, e)
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
            uid = _safe_int(user_id)
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
                "Failed to update agent activity for %s for user %s: %s", agent_id, user_id, e
            )

    def get_current_user_id() -> Optional[str]:
        if current_user.is_authenticated and current_user.role == "admin":
            active = session.get("active_user_id")
            if active:
                logger.info("Admin acting on behalf of user %s", active)
            return active
        if current_user.is_authenticated:
            return str(current_user.id)
        return None

    @app.before_request
    def capture_affiliate_referral():
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
        return None

    @app.before_request
    def check_session_timeout():
        last_active = session.get("last_active")
        if last_active:
            try:
                last = datetime.fromisoformat(last_active)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - last > SESSION_TIMEOUT:
                    session.clear()
                    flash("Session expired. Please log in again.", "error")
                    if current_user.is_authenticated:
                        user_role = current_user.role if hasattr(current_user, 'role') else None
                        logout_user()
                        if user_role in ("client", "user"):
                            return redirect(url_for("client.client_login"))
                        elif user_role == "affiliate":
                            return redirect(url_for("affiliate.affiliate_login"))
                        elif user_role == "admin":
                            return redirect(url_for("admin.login"))
            except Exception as e:
                logger.debug("Session timeout check failed: %s", e)
        session["last_active"] = datetime.now(timezone.utc).isoformat()

    @app.before_request
    def check_trial_expiry():
        if current_user.is_authenticated and hasattr(current_user, "is_trial_expired") and current_user.is_trial_expired:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Trial expired. Subscribe to continue.", "redirect": "/trial-expired"}), 403
            if request.path not in ("/trial-expired", "/logout", "/static/bookmarklet.js"):
                from flask import flash as _flash
                _flash("Your free trial has ended. Subscribe to regain access.", "error")
                return redirect(url_for("trial_expired"))

    _AGENTS = [
        ("local_seo", "local_seo.md", "Local SEO", "Google Business Profile optimization, local citations, local keyword content, review management"),
        ("social_media", "social_media.md", "Social Media", "Social media posts, content creation, content calendars, engagement strategies"),
        ("lead_conversion", "lead_conversion.md", "Lead Conversion", "Lead follow-up sequences, CRM integration, conversion optimization, email campaigns"),
        ("paid_ads", "paid_ads_v2.md", "Paid Ads", "Google & Meta ad campaigns, ad copy creation, keyword strategy, budget allocation, A/B testing, audience targeting"),
        ("growth_hacker", "growth_hacker.md", "Growth Hacker", "Growth audits, viral loops, conversion rate optimization, partnership strategies, data-driven experiments, creative low-cost tactics"),
        ("reputation", "reputation.md", "Reputation", "Online review monitoring, review response generation, review generation campaigns, reputation audits, crisis response"),
        ("email_marketing", "email_marketing.md", "Email Marketing", "Newsletter campaigns, promotional emails, lead nurture sequences, reactivation campaigns, post-service follow-ups"),
        ("tiktok", "tiktok_agent.md", "TikTok", "Short-form video content for TikTok, Instagram Reels, YouTube Shorts, content calendars, video scripts, trend adaptation"),
        ("outreach", "outreach.md", "Outreach", "Prospecting emails, lead finding, campaign sequences, follow-up automation, personalized outreach at scale"),
        ("backlinks", "backlinks.md", "Backlinks", "Link building, guest post prospecting, citation building, backlink gap analysis, broken link building, directory submissions"),
        ("content_strategy", "content_strategy.md", "Content Strategist", "Editorial calendars, multi-channel content repurposing, content briefs, topic clusters, seasonal planning, voice and tone guidelines"),
        ("technical_seo", "technical_seo.md", "Technical SEO", "Schema markup, site speed optimization, crawl audits, XML sitemaps, core web vitals, mobile optimization, hreflang tags"),
        ("reporting", "reporting.md", "Analytics & Reports", "Cross-channel performance summaries, trend analysis, ROI calculations, executive briefs, monthly client reports"),
        ("cro", "cro.md", "CRO & Landing Pages", "Conversion rate optimization, A/B testing analysis, funnel optimization, landing page copy, heatmap interpretation, CTA strategy"),
        ("video", "video.md", "Video Production", "YouTube scripts, explainer videos, ad video scripts, video SEO, content series planning, thumbnail strategy"),
        ("sms_marketing", "sms_marketing.md", "SMS Marketing", "SMS campaign planning, sequence design, CASL compliance, concise copywriting, timing strategy, list segmentation"),
    ]
    _BASE_AGENT_CONFIG = {
        "enabled": True,
        "model": "deepseek-chat",
        "credentials": {"api_key": "", "api_base": "https://api.deepseek.com/v1"},
    }
    AGENT_CONFIGS = {aid: {**_BASE_AGENT_CONFIG, "agent_id": aid, "system_prompt_file": f"prompts/{pf}"} for aid, pf, _, _ in _AGENTS}
    AGENT_META: Dict[str, Dict[str, str]] = {aid: {"name": nm, "desc": dc} for aid, _, nm, dc in _AGENTS}

    llm_adapter = LLMAdapter(
        model="deepseek-chat",
        api_key="",
        api_base="https://api.deepseek.com/v1",
    )

    agent_registry = {}
    for agent_id, config in AGENT_CONFIGS.items():
        cls = AGENT_CLASSES.get(agent_id)
        if cls:
            agent_registry[agent_id] = cls(agent_id, config)

    mcp_servers = init_mcp_servers()
    logger.info("MCP servers ready: %s", list(mcp_servers.keys()))

    executioner = ExecutionerAgent({
        "execution_log_path": "logs/executions.jsonl",
        "max_retries": 3,
        "retry_delay": 5,
    })

    speech_engine = SpeechEngine()

    import core.app_state as _app_state
    _app_state.init_credential_cipher(_derive_fernet_key())

    orchestrator = None
    _orchestrator_lock = threading.Lock()

    def get_orchestrator():
        nonlocal orchestrator
        if orchestrator is not None:
            return orchestrator
        with _orchestrator_lock:
            if orchestrator is not None:
                return orchestrator
            logger.info("Building orchestrator")
            orchestrator = Orchestrator(llm_adapter, agent_registry, executioner=executioner, push_manager=push_manager, memory=agent_memory)
        return orchestrator

    @app.route("/")
    def home():
        return render_template("home.html")

    @app.route("/fr/")
    def home_fr():
        return render_template("home_fr.html")

    @app.route("/demo")
    def demo():
        return render_template("demo.html")

    @app.route("/fr/demo")
    def demo_fr():
        return render_template("demo_fr.html")

    @app.route("/blog")
    def blog():
        return render_template("blog.html", articles=ARTICLES_EN)

    @app.route("/blog/<slug>")
    def blog_article(slug):
        article = ARTICLES_BY_SLUG_EN.get(slug)
        if not article:
            abort(404)
        return render_template("blog_article.html",
            article=article, lang="en",
            home_route="home", demo_route="demo", blog_route="blog",
            home_label="Home", demo_label="Live Demo", blog_label="Blog",
            training_label="Training Hub",
            other_lang_route="blog_fr", other_lang_label="FR",
            back_label="Back to Blog")

    @app.route("/fr/blogue")
    def blog_fr():
        return render_template("blog_fr.html", articles=ARTICLES_FR)

    @app.route("/fr/blogue/<slug>")
    def blog_article_fr(slug):
        article = ARTICLES_BY_SLUG_FR.get(slug)
        if not article:
            abort(404)
        return render_template("blog_article.html",
            article=article, lang="fr",
            home_route="home_fr", demo_route="demo_fr", blog_route="blog_fr",
            home_label="Accueil", demo_label="Démo", blog_label="Blogue",
            training_label="Formation",
            other_lang_route="blog", other_lang_label="EN",
            back_label="Retour au blogue")

    @app.route("/free-trial")
    def free_trial():
        if current_user.is_authenticated:
            return redirect(url_for("client.client_dashboard"))
        return render_template("free_trial.html")

    @app.route("/fr/essai-gratuit")
    def free_trial_fr():
        if current_user.is_authenticated:
            return redirect(url_for("client.client_dashboard"))
        return render_template("free_trial_fr.html")

    @app.route("/contact")
    def contact():
        return render_template("contact.html")

    @app.route("/fr/contact")
    def contact_fr():
        return render_template("contact_fr.html")

    @app.route("/trial-expired")
    def trial_expired():
        return render_template("trial_expired.html")

    @app.route("/logout")
    def logout():
        logout_user()
        session.clear()
        return redirect(url_for("home"))

    @app.context_processor
    def inject_globals():
        phone = app.config["CONTACT_PHONE"]
        return dict(
            logo_file="logo.svg",
            CONTACT_PHONE=phone,
            CONTACT_PHONE_CLEAN=phone.replace("(", "").replace(")", "").replace(" ", "").replace("-", ""),
            CONTACT_EMAIL=app.config["CONTACT_EMAIL"],
        )

    @app.route("/api/agents/<agent_id>/config", methods=["POST"])
    @admin_required
    def update_agent_config(agent_id):
        nonlocal orchestrator
        if agent_id not in AGENT_CONFIGS:
            return api_error("Agent not found", 404)
        data = request.json
        config = AGENT_CONFIGS[agent_id]
        if "model" in data and data["model"]:
            if not LLMAdapter.is_valid_model(data["model"]):
                return api_error(f"Invalid model '{data['model']}'", 400)
            config["model"] = data["model"]
        if "api_key" in data:
            config["credentials"]["api_key"] = data["api_key"]
        if "api_base" in data:
            config["credentials"]["api_base"] = data["api_base"]
        _reinitialize_agent(agent_id, config)
        with _orchestrator_lock:
            orchestrator = Orchestrator(llm_adapter, agent_registry, executioner=executioner, push_manager=push_manager, memory=agent_memory)
        return api_success({
            "agent_id": agent_id,
            "model": config["model"],
            "message": "Configuration updated and agent reinitialized",
        })

    @app.route("/api/agents/bulk/config", methods=["POST"])
    @admin_required
    def update_all_agents_config():
        nonlocal orchestrator
        data = request.json
        if not data:
            return api_error("No data provided", 400)
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
        nonlocal llm_adapter
        if api_key:
            llm_adapter = LLMAdapter(
                model=model if model and model != "__keep__" and LLMAdapter.is_valid_model(model) else llm_adapter.model,
                api_key=api_key,
                api_base=api_base or llm_adapter._api_base,
                temperature=llm_adapter._temperature,
            )
        with _orchestrator_lock:
            orchestrator = Orchestrator(llm_adapter, agent_registry, executioner=executioner, push_manager=push_manager, memory=agent_memory)
        return api_success({
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

    from blueprints._shared import _email_bridge_handler
    if os.getenv("EMAIL_BRIDGE_USER") and os.getenv("EMAIL_BRIDGE_PASS"):
        tenant_for_bridge = os.getenv("EMAIL_BRIDGE_TENANT_ID", "")
        if not tenant_for_bridge:
            logger.warning("EMAIL_BRIDGE_TENANT_ID not set — email bridge not started (no tenant context)")
        else:
            _bridge = EmailBridge(
                imap_host=os.getenv("EMAIL_BRIDGE_HOST", "imap.gmail.com"),
                imap_port=int(os.getenv("EMAIL_BRIDGE_PORT", "993")),
                username=os.getenv("EMAIL_BRIDGE_USER"),
                password=_decrypt_credential(os.getenv("EMAIL_BRIDGE_PASS", "")),
            )
            _bridge.set_handler(lambda a, s, b: _email_bridge_handler(a, s, b, tenant_for_bridge))
            threading.Thread(target=_bridge.start, daemon=True).start()

    proactive_monitor.start(get_orchestrator, lambda: push_manager)

    scheduler_manager = SchedulerManager(get_orchestrator)
    scheduler_manager.start()

    import core.app_state as _app_state
    _app_state.init_agent_registry(agent_registry)
    _app_state.init_llm_adapter(llm_adapter)
    _app_state.init_orchestrator_fn(get_orchestrator)
    _app_state.init_executioner(executioner)
    _app_state.init_push_manager(push_manager)
    _app_state.init_agent_memory(agent_memory)
    _app_state.init_speech_engine(speech_engine)
    _app_state.init_affiliate_manager(affiliate_manager)
    _app_state.init_scheduler_manager(scheduler_manager)
    _app_state.init_agent_meta(AGENT_META)
    _app_state.init_agent_configs(AGENT_CONFIGS)
    _app_state.init_credential_cipher(_derive_fernet_key())
    _app_state.init_current_user_id_fn(get_current_user_id)
    _app_state.init_safe_int_fn(_safe_int)
    _app_state.init_safe_error_fn(_safe_error)
    _app_state.init_safe_url_fn(_safe_url)
    _app_state.init_encrypt_credential_fn(_encrypt_credential)
    _app_state.init_get_tenant_agent_activity_fn(get_tenant_agent_activity)
    _app_state.init_update_agent_activity_fn(update_tenant_agent_activity)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
