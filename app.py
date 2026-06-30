# Monkey-patch gevent before any other imports
try:
    import gevent.monkey
    gevent.monkey.patch_all()
except ImportError:
    pass

# Make psycopg2 gevent-compatible via psycogreen
try:
    from psycogreen.gevent import patch_psycopg
    patch_psycopg()
except ImportError:
    pass

import logging
import logging.handlers
import os
import sys
import threading
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, logout_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.middleware.proxy_fix import ProxyFix

from agents.executioner_agent import ExecutionerAgent
from core import database
from core.api_helpers import api_error, api_success
from core.auth import SESSION_TIMEOUT, init_auth
from core.email_bridge import EmailBridge
from core.llm_adapter import LLMAdapter
from core.memory import AgentMemory
from core.monitor import monitor as proactive_monitor
from core.orchestrator import Orchestrator
from core.push import PushManager
from core.scheduler import SchedulerManager
from core.settings import (
    AGENTS_META, AGENT_CLASSES, API_PUBLIC, BASE_AGENT_CONFIG,
    CorrelationIDFilter, PIIRedactFormatter, PIIRedactJSONFormatter,
    decrypt_credential, derive_fernet_key,
    encrypt_credential, safe_error, safe_int, safe_url,
)
from core.speech import SpeechEngine
from mcp import init_mcp_servers

logger = logging.getLogger(__name__)


def create_app():
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
    if not os.getenv("CREDENTIAL_SALT"):
        logger.warning(
            "CREDENTIAL_SALT not set \u2014 using HKDF domain separation (recommended). "
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
    else:
        app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["CONTACT_PHONE"] = os.getenv("CONTACT_PHONE", "(514) 243-1580")
    app.config["CONTACT_EMAIL"] = os.getenv("CONTACT_EMAIL", "lavaldigital@gmail.com")
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

    csrf = CSRFProtect(app)

    _log_handler = logging.handlers.RotatingFileHandler(
        "logs/app.log", maxBytes=10 * 1024 * 1024, backupCount=5,
    )
    _log_handler.setLevel(logging.INFO)
    _log_handler.addFilter(CorrelationIDFilter())
    _log_handler.setFormatter(PIIRedactJSONFormatter())
    logging.getLogger().addHandler(_log_handler)

    _console_handler = logging.StreamHandler()
    _console_handler.addFilter(CorrelationIDFilter())
    _console_handler.setFormatter(PIIRedactFormatter(
        "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
    ))
    logging.getLogger().addHandler(_console_handler)

    logging.getLogger().setLevel(logging.INFO)

    database.init_db()

    push_manager = PushManager()
    agent_memory = AgentMemory()

    login_manager = init_auth(app)

    from blueprints.admin_bp import admin_bp, admin_fr_bp
    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_fr_bp)
    from blueprints.mcp_bp import mcp_bp
    app.register_blueprint(mcp_bp)
    from blueprints.training_bp import training_bp
    app.register_blueprint(training_bp)
    from blueprints.executioner_bp import executioner_bp
    app.register_blueprint(executioner_bp)
    from blueprints.analytics_bp import analytics_bp
    app.register_blueprint(analytics_bp)
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
    from blueprints.shopify_bp import shopify_bp
    app.register_blueprint(shopify_bp)

    for rule in app.url_map.iter_rules():
        if rule.rule in API_PUBLIC and rule.methods and not {'GET', 'HEAD', 'OPTIONS'}.issuperset(rule.methods):
            csrf._exempt_views.add(rule.endpoint)

    # ── Context processors ──────────────────────────────────────────

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": generate_csrf}

    @app.before_request
    def generate_request_id():
        import uuid
        g.request_id = uuid.uuid4().hex[:12]
        g.csp_nonce = uuid.uuid4().hex[:16]

    @app.context_processor
    def inject_csp_nonce():
        return {"csp_nonce": getattr(g, "csp_nonce", "")}

    @app.context_processor
    def inject_static_versions():
        import hashlib, os as _os
        versions = {}
        static_dir = _os.path.join(app.root_path, "static")
        for fname in ("app.css", "app.js", "admin.css", "admin.js"):
            fpath = _os.path.join(static_dir, fname)
            try:
                with open(fpath, "rb") as f:
                    versions[fname] = hashlib.md5(f.read()).hexdigest()[:8]
            except FileNotFoundError:
                versions[fname] = "0"
        return {"static_versions": versions}

    # ── Security headers ────────────────────────────────────────────

    @app.after_request
    def add_security_headers(response):
        nonce = getattr(g, "csp_nonce", "")
        script_src = f"'self' 'nonce-{nonce}' https://cdn.jsdelivr.net https://cdn.shopify.com"
        style_src = "'self' https://cdn.shopify.com https://fonts.googleapis.com https://cdn.jsdelivr.net"
        style_src_attr = "'unsafe-inline'"
        img_src = "'self' data: blob: https://cdn.shopify.com https://*.shopify.com https://cdn.jsdelivr.net"
        font_src = "'self' https://fonts.gstatic.com data:"
        frame_src = "'self' https://*.shopify.com https://admin.shopify.com"
        connect_src = "'self' https://*.shopify.com https://admin.shopify.com https://cdn.shopify.com"
        csp = (
            f"default-src 'self';"
            f"script-src {script_src};"
            f"style-src {style_src};"
            f"style-src-attr {style_src_attr};"
            f"img-src {img_src};"
            f"font-src {font_src};"
            f"frame-src {frame_src};"
            f"connect-src {connect_src};"
            f"object-src 'none';"
            f"base-uri 'self'"
        )
        response.headers["Content-Security-Policy"] = csp
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        allowed_origins = {
            "https://lavaldigital.ca", "https://www.lavaldigital.ca",
            "http://127.0.0.1:5000", "http://localhost:5000",
            "https://admin.shopify.com",
        }
        origin = request.headers.get("Origin")
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-CSRFToken, Authorization"
            response.headers["Vary"] = "Origin"
        return response

    # ── Error handlers ──────────────────────────────────────────────

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

    # ── API auth middleware ─────────────────────────────────────────

    @app.before_request
    def require_api_auth():
        if not request.path.startswith("/api/"):
            return
        if request.path in API_PUBLIC:
            return
        if current_user.is_authenticated and current_user.role == "admin":
            return
        shop = session.get("shop") or request.args.get("shop") or request.headers.get("X-Shopify-Shop-Domain")
        if shop:
            from core.shopify_auth import get_shop_by_domain, verify_session_token
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                payload = verify_session_token(auth_header[7:])
                if payload and shop in payload.get("dest", ""):
                    g.shop = shop
                    return
            session_shop = session.get("shop")
            if session_shop and session_shop == shop:
                g.shop = shop
                return
            shop_data = get_shop_by_domain(shop)
            if shop_data and shop_data.get("is_active"):
                g.shop = shop
                return
        if request.method == "OPTIONS":
            return
        return api_error("Authentication required", 401)

    # ── Session timeout ─────────────────────────────────────────────

    @app.before_request
    def check_session_timeout():
        last_active = session.get("last_active")
        if last_active:
            try:
                last = datetime.fromisoformat(last_active)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                if datetime.now(UTC) - last > SESSION_TIMEOUT:
                    session.clear()
                    flash("Session expired. Please log in again.", "error")
                    if current_user.is_authenticated:
                        logout_user()
                        return redirect(url_for("admin.login"))
            except Exception as e:
                logger.debug("Session timeout check failed: %s", e)
        session["last_active"] = datetime.now(UTC).isoformat()

    @app.before_request
    def check_trial_expiry():
        if current_user.is_authenticated and hasattr(current_user, "is_trial_expired") and current_user.is_trial_expired:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Trial expired. Subscribe to continue.", "redirect": "/trial-expired"}), 403
            if request.path not in ("/trial-expired", "/logout", "/static/bookmarklet.js"):
                from flask import flash as _flash
                _flash("Your free trial has ended. Subscribe to regain access.", "error")
                return redirect(url_for("public.trial_expired"))

    # ── Agent configuration ─────────────────────────────────────────

    _base_agent_config = dict(BASE_AGENT_CONFIG)
    agent_configs = {
        aid: {**_base_agent_config, "agent_id": aid, "system_prompt_file": f"prompts/{pf}"}
        for aid, pf, _, _ in AGENTS_META
    }
    agent_meta: dict[str, dict[str, str]] = {aid: {"name": nm, "desc": dc} for aid, _, nm, dc in AGENTS_META}

    llm_adapter = LLMAdapter(
        model="deepseek-chat",
        api_key="",
        api_base="https://api.deepseek.com/v1",
    )

    agent_registry = {}
    for agent_id, config in agent_configs.items():
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
    _app_state.init_credential_cipher(derive_fernet_key())

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

    # ── Agent config API routes ─────────────────────────────────────

    @app.route("/api/agents/<agent_id>/config", methods=["POST"])
    def update_agent_config(agent_id):
        nonlocal orchestrator
        if agent_id not in agent_configs:
            return api_error("Agent not found", 404)
        data = request.json
        config = agent_configs[agent_id]
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
    def update_all_agents_config():
        nonlocal orchestrator
        data = request.json
        if not data:
            return api_error("No data provided", 400)
        model = data.get("model")
        api_key = data.get("api_key")
        api_base = data.get("api_base")
        updated_count = 0
        for agent_id, config in agent_configs.items():
            changed = False
            if model and model != "__keep__" and LLMAdapter.is_valid_model(model):
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

    # ── Email bridge ────────────────────────────────────────────────

    from blueprints._shared import _email_bridge_handler
    if os.getenv("EMAIL_BRIDGE_USER") and os.getenv("EMAIL_BRIDGE_PASS"):
        tenant_for_bridge = os.getenv("EMAIL_BRIDGE_TENANT_ID", "")
        if not tenant_for_bridge:
            logger.warning("EMAIL_BRIDGE_TENANT_ID not set \u2014 email bridge not started (no tenant context)")
        else:
            _bridge = EmailBridge(
                imap_host=os.getenv("EMAIL_BRIDGE_HOST", "imap.gmail.com"),
                imap_port=int(os.getenv("EMAIL_BRIDGE_PORT", "993")),
                username=os.getenv("EMAIL_BRIDGE_USER", ""),
                password=decrypt_credential(os.getenv("EMAIL_BRIDGE_PASS", "")),
            )
            _bridge.set_handler(lambda a, s, b: _email_bridge_handler(a, s, b, tenant_for_bridge))
            threading.Thread(target=_bridge.start, daemon=True).start()

    proactive_monitor.start(get_orchestrator, lambda: push_manager)

    scheduler_manager = SchedulerManager(get_orchestrator)
    scheduler_manager.start()

    # ── Page routes ────────────────────────────────────────────────

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

    @app.route("/free-trial")
    def free_trial():
        return render_template("free_trial.html")

    @app.route("/fr/essai-gratuit")
    def free_trial_fr():
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

    @app.route("/favicon.ico")
    def favicon():
        return redirect(url_for("static", filename="favicon.svg"))

    # ── Context processor for globals ──────────────────────────────

    @app.context_processor
    def inject_globals():
        phone = app.config["CONTACT_PHONE"]
        return dict(
            logo_file="logo.svg",
            CONTACT_PHONE=phone,
            CONTACT_PHONE_CLEAN=phone.replace("(", "").replace(")", "").replace(" ", "").replace("-", ""),
            CONTACT_EMAIL=app.config["CONTACT_EMAIL"],
        )

    # ── Inject singletons into app_state ────────────────────────────

    _app_state.init_agent_registry(agent_registry)
    _app_state.init_llm_adapter(llm_adapter)
    _app_state.init_orchestrator_fn(get_orchestrator)
    _app_state.init_executioner(executioner)
    _app_state.init_push_manager(push_manager)
    _app_state.init_agent_memory(agent_memory)
    _app_state.init_speech_engine(speech_engine)
    _app_state.init_scheduler_manager(scheduler_manager)
    _app_state.init_agent_meta(agent_meta)
    _app_state.init_agent_configs(agent_configs)
    _app_state.init_credential_cipher(derive_fernet_key())
    _app_state.init_current_user_id_fn(get_current_user_id)
    _app_state.init_safe_int_fn(safe_int)
    _app_state.init_safe_error_fn(safe_error)
    _app_state.init_safe_url_fn(safe_url)
    _app_state.init_encrypt_credential_fn(encrypt_credential)
    _app_state.init_get_tenant_agent_activity_fn(get_tenant_agent_activity)
    _app_state.init_update_agent_activity_fn(update_tenant_agent_activity)

    return app


def get_tenant_agent_activity(user_id: str) -> dict:
    try:
        uid = safe_int(user_id)
        conn = database._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT agent_id, enabled, status, last_invoked, task_count, "
            "success_count, failure_count, last_draft_preview "
            "FROM agent_configs WHERE user_id = ?",
            (uid,),
        )
        rows = cursor.fetchall()
        return {row["agent_id"]: dict(row) for row in rows}
    except Exception as e:
        logger.error("Failed to get agent activity for user %s: %s", user_id, e)
        return {}


def update_tenant_agent_activity(user_id: str, agent_id: str, **kwargs) -> None:
    _column_updates = {
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
        uid = safe_int(user_id)
        conn = database._get_conn()
        cursor = conn.cursor()
        for key, value in kwargs.items():
            sql = _column_updates.get(key)
            if sql is None:
                raise ValueError(f"Invalid column name: {key}")
            cursor.execute(sql, (value, agent_id, uid))
        conn.commit()
    except Exception as e:
        logger.error(
            "Failed to update agent activity for %s for user %s: %s", agent_id, user_id, e,
        )


def get_current_user_id() -> str | None:
    if current_user.is_authenticated and current_user.role == "admin":
        active = session.get("active_user_id")
        if active:
            logger.info("Admin acting on behalf of user %s", active)
        return active
    if current_user.is_authenticated:
        return str(current_user.id)
    shop = getattr(g, "shop", None)
    if shop:
        from core.shopify_auth import get_shop_by_domain
        shop_data = get_shop_by_domain(shop)
        if shop_data and shop_data.get("user_id"):
            return str(shop_data["user_id"])
    return None


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)