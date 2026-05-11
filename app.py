import os
import sys
import uuid
import warnings
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Suppress warnings before any imports that might trigger them
warnings.filterwarnings("ignore", module="langgraph")
warnings.filterwarnings("ignore", module="langchain")

from flask import Flask, render_template, jsonify, request, redirect, url_for, session
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

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.orchestrator import Orchestrator, OrchestratorState
from core.llm_adapter import LLMAdapter
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
from agents.executioner_agent import ExecutionerAgent
from client_factory import ClientFactory

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
app.permanent_session_lifetime = timedelta(days=30)

# Initialize Tenant Manager for multi-tenant database isolation
tenant_manager = TenantManager()

# Store active threads and their states (in-memory cache for orchestrator resume)
active_threads: Dict[str, Dict[str, Any]] = {}

# In-memory lead storage (replace with database in production)
leads: list[Dict[str, Any]] = []

# In-memory affiliate store (replace with DB later)
AFFILIATES = {
    "MIKE15": {"name": "Mike", "code": "MIKE15", "earnings": 0},
    "SARAH10": {"name": "Sarah", "code": "SARAH10", "earnings": 0},
}

VALID_AFFILIATE_CODES = set(AFFILIATES.keys())

# In-memory lead tracking for affiliates
affiliate_leads: list[dict] = []

# In-memory reseller applications (replace with DB later)
reseller_applications: list[dict] = []


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
    if ref_code and ref_code in VALID_AFFILIATE_CODES:
        session.permanent = True
        session["affiliate_ref"] = ref_code
        session["affiliate_discount"] = 500

        if not any(
            lead.get("ref_code") == ref_code
            and lead.get("ip") == request.remote_addr
            for lead in affiliate_leads
        ):
            affiliate_leads.append({
                "ref_code": ref_code,
                "ip": request.remote_addr,
                "user_agent": request.headers.get("User-Agent"),
                "landing_page": request.path,
                "timestamp": datetime.now().isoformat(),
            })


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

# Initialize ExecutionerAgent for approved draft execution
executioner = ExecutionerAgent({
    "execution_log_path": "logs/executions.jsonl",
    "max_retries": 3,
    "retry_delay": 5,
})

# Initialize Orchestrator (deferred to first use)
orchestrator = None
orchestrator_graph = None


def get_orchestrator():
    global orchestrator, orchestrator_graph
    if orchestrator is None:
        orchestrator = Orchestrator(llm_adapter, agent_registry)
        orchestrator_graph = orchestrator.build_graph()
    return orchestrator_graph


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
# Admin auth routes
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Serve the admin login page and handle authentication."""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        expected_user = os.getenv("ADMIN_USERNAME", "laval")
        expected_pass = os.getenv("ADMIN_PASSWORD", "digital2026!")
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


@app.route("/fr/admin/login", methods=["GET", "POST"])
def admin_login_fr():
    """Serve the French admin login page."""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        expected_user = os.getenv("ADMIN_USERNAME", "laval")
        expected_pass = os.getenv("ADMIN_PASSWORD", "digital2026!")
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
    if ref_code and ref_code in VALID_AFFILIATE_CODES:
        return jsonify({
            "active": True,
            "code": ref_code,
            "discount": 500,
            "affiliate_name": AFFILIATES.get(ref_code, {}).get("name", "Partner"),
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

    code = "REF" + uuid.uuid4().hex[:6].upper()
    AFFILIATES[code] = {"name": name, "code": code, "earnings": 0}
    VALID_AFFILIATE_CODES.add(code)

    affiliate_leads.append({
        "ref_code": code,
        "name": name,
        "email": email,
        "phone": phone,
        "timestamp": datetime.now().isoformat(),
    })

    return jsonify({
        "success": True,
        "code": code,
        "referral_link": f"https://lavaldigital.ca/?ref={code}",
    }), 201


@app.route("/api/contract/submit", methods=["POST"])
def contract_submit():
    """Submit a signed agreement."""
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

    logger.info("Contract submitted by %s (%s) — package: %s", name, email, contract_data["package"])
    return jsonify({"success": True, "contract_id": contract_data["id"]}), 201


@app.route("/api/reseller/apply", methods=["POST"])
def reseller_apply():
    """Submit a reseller application."""
    data = request.json
    agency = (data.get("agencyName") or "").strip()
    contact = (data.get("contactName") or "").strip()
    email = (data.get("email") or "").strip()

    if not agency or not contact or not email:
        return jsonify({"error": "Agency name, contact name, and email are required"}), 400

    application = {
        "id": str(uuid.uuid4()),
        "agencyName": agency,
        "contactName": contact,
        "email": email,
        "phone": data.get("phone", ""),
        "clientCount": data.get("clientCount", ""),
        "created_at": datetime.now().isoformat(),
    }
    reseller_applications.append(application)

    logger.info("Reseller application received — %s (%s)", agency, email)
    return jsonify({"success": True, "application_id": application["id"]}), 201


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
    orchestrator = Orchestrator(llm_adapter, agent_registry)
    orchestrator_graph = orchestrator.build_graph()

    return jsonify({
        "agent_id": agent_id,
        "model": config["model"],
        "message": "Configuration updated and agent reinitialized",
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
        orchestrator = Orchestrator(llm_adapter, agent_registry)
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
        return jsonify({
            "provider": "unknown", "models": [], "error": str(e)
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
        return jsonify(executioner.get_settings())
    return jsonify(executioner.get_settings())


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
        return jsonify({"error": str(e)}), 400


@app.route("/api/executioner/reject/<execution_id>", methods=["POST"])
def reject_execution(execution_id):
    """Reject a queued execution without running it."""
    try:
        result = executioner.reject_execution(execution_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/executions", methods=["GET"])
def get_executions():
    """Get recent execution history."""
    limit = request.args.get("limit", 50, type=int)
    history = executioner.get_execution_history(limit)
    return jsonify({"executions": history})


# ---------------------------------------------------------------------------
# API: tasks & approvals (tenant-aware)
# ---------------------------------------------------------------------------

@app.route("/api/tasks", methods=["POST"])
def submit_task():
    """Submit a task to the orchestrator.

    Stores the agent draft and thread in both the in-memory cache
    (for orchestrator resume) and the tenant database (for persistence).
    """
    data = request.json
    user_request = data.get("request")

    if not user_request:
        return jsonify({"error": "No request provided"}), 400

    thread_id = str(uuid.uuid4())
    now_iso = datetime.now().isoformat()

    initial_state = {
        "user_request": user_request,
        "routed_agent": "",
        "agent_task": "",
        "agent_draft": None,
        "approved": None,
        "feedback": None,
        "final_result": None,
        "messages": [],
    }

    config = {"configurable": {"thread_id": thread_id}}

    try:
        graph = get_orchestrator()
        result = graph.invoke(initial_state, config)

        has_draft = bool(result.get("agent_draft"))
        has_final = bool(result.get("final_result"))
        status = (
            "completed"
            if has_final
            else ("pending_approval" if has_draft else "error")
        )

        # Cache in memory for orchestrator resume
        active_threads[thread_id] = {
            "state": result,
            "config": config,
            "status": status,
        }

        # Persist to tenant database
        tenant_id = get_current_tenant()
        if tenant_id:
            try:
                conn = tenant_manager.get_connection(tenant_id)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO threads
                        (thread_id, routed_agent, agent_task, agent_draft,
                         status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        thread_id,
                        result.get("routed_agent", ""),
                        result.get("agent_task", ""),
                        result.get("agent_draft", ""),
                        status,
                        now_iso,
                        now_iso,
                    ),
                )
                conn.commit()
            except Exception:
                pass

        # Persist agent activity
        agent_name = result.get("routed_agent", "")
        if agent_name and tenant_id:
            try:
                draft_preview = None
                if has_draft:
                    draft = result.get("agent_draft", "")
                    draft_preview = (
                        (draft[:120] + "...") if len(draft) > 120 else draft
                    )
                update_tenant_agent_activity(
                    tenant_id,
                    agent_name,
                    status="idle" if status == "completed" else "pending_approval",
                    last_invoked=now_iso,
                    last_draft_preview=draft_preview,
                )
            except Exception:
                pass

        return jsonify({
            "thread_id": thread_id,
            "status": status,
            "result": result,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/approvals", methods=["GET"])
def get_approvals():
    """Get pending approvals from the tenant database."""
    tenant_id = get_current_tenant()
    approvals = []

    if tenant_id:
        try:
            conn = tenant_manager.get_connection(tenant_id)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT thread_id, routed_agent, agent_draft, agent_task
                FROM threads
                WHERE status = 'pending_approval'
                  AND agent_draft IS NOT NULL
                  AND agent_draft != ''
                """
            )
            rows = cursor.fetchall()
            for row in rows:
                approvals.append({
                    "thread_id": row["thread_id"],
                    "agent": row["routed_agent"],
                    "draft": row["agent_draft"],
                    "task": row["agent_task"],
                })
        except Exception:
            pass

    return jsonify({"approvals": approvals})


@app.route("/api/approvals/<thread_id>/respond", methods=["POST"])
def respond_approval(thread_id):
    """Respond to an approval request and execute agent if approved."""
    data = request.json
    approved = data.get("approved", False)
    feedback = data.get("feedback", "")
    now_iso = datetime.now().isoformat()
    tenant_id = get_current_tenant()

    # Check if we have the thread in the in-memory orchestrator cache
    if thread_id in active_threads:
        thread_data = active_threads[thread_id]
        human_response = {"approved": approved, "feedback": feedback}

        try:
            graph = get_orchestrator()
            result = graph.invoke(human_response, thread_data["config"])

            thread_data["state"] = result
            thread_data["status"] = "completed"

            # Update the threads table in the tenant database
            if tenant_id:
                try:
                    conn = tenant_manager.get_connection(tenant_id)
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        UPDATE threads
                        SET approved = ?, feedback = ?, final_result = ?,
                            status = 'completed', updated_at = ?
                        WHERE thread_id = ?
                        """,
                        (
                            int(approved),
                            feedback,
                            result.get("final_result", ""),
                            now_iso,
                            thread_id,
                        ),
                    )
                    conn.commit()
                except Exception:
                    pass

            # If approved, execute via the ExecutionerAgent
            if approved:
                state = result
                agent_name = state.get("routed_agent")
                draft = state.get("agent_draft", "")
                if agent_name and agent_name in agent_registry:
                    try:
                        exec_result = executioner.execute(agent_name, draft)

                        thread_data["state"]["final_result"] = exec_result.get(
                            "result", str(exec_result)
                        )
                        thread_data["state"]["execution_id"] = exec_result.get(
                            "execution_id"
                        )

                        # Persist activity to tenant database
                        if tenant_id:
                            try:
                                if exec_result.get("status") == "pending_confirmation":
                                    update_tenant_agent_activity(
                                        tenant_id,
                                        agent_name,
                                        status="pending_confirmation",
                                        last_invoked=now_iso,
                                        last_draft_preview=(
                                            (draft[:120] + "...") if len(draft) > 120 else draft
                                        ),
                                    )
                                elif exec_result.get("success"):
                                    update_tenant_agent_activity(
                                        tenant_id, agent_name, status="idle"
                                    )
                                else:
                                    update_tenant_agent_activity(
                                        tenant_id, agent_name, status="idle"
                                    )

                                # Log to execution_log table
                                cursor = tenant_manager.get_connection(
                                    tenant_id
                                ).cursor()
                                cursor.execute(
                                    """
                                    INSERT INTO execution_log
                                        (execution_id, agent_name, draft_preview,
                                         success, result, timestamp)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        exec_result.get("execution_id", ""),
                                        agent_name,
                                        (draft[:120] + "...") if len(draft) > 120 else draft,
                                        int(exec_result.get("success", False)),
                                        str(exec_result.get("result", "")),
                                        now_iso,
                                    ),
                                )
                                cursor.connection.commit()
                            except Exception:
                                pass
                    except Exception as exec_err:
                        thread_data["state"][
                            "final_result"
                        ] = f"Execution error: {str(exec_err)}"
                        if tenant_id:
                            try:
                                update_tenant_agent_activity(
                                    tenant_id, agent_name, status="idle"
                                )
                            except Exception:
                                pass
            else:
                agent_name = thread_data["state"].get("routed_agent")
                if agent_name and tenant_id:
                    try:
                        update_tenant_agent_activity(
                            tenant_id, agent_name, status="idle"
                        )
                    except Exception:
                        pass

            return jsonify({
                "thread_id": thread_id,
                "status": "completed",
                "result": thread_data["state"].get("final_result"),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Not in memory cache — try DB-only response (orchestrator resume unavailable)
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

            cursor.execute(
                """
                UPDATE threads
                SET approved = ?, feedback = ?, status = 'completed', updated_at = ?
                WHERE thread_id = ?
                """,
                (int(approved), feedback, now_iso, thread_id),
            )
            conn.commit()

            agent_name = row["routed_agent"]
            draft = row["agent_draft"] or ""

            if approved and agent_name and agent_name in agent_registry:
                try:
                    exec_result = executioner.execute(agent_name, draft)
                    if tenant_id:
                        update_tenant_agent_activity(
                            tenant_id, agent_name, status="idle",
                        )
                        cursor = tenant_manager.get_connection(tenant_id).cursor()
                        cursor.execute(
                            """
                            INSERT INTO execution_log
                                (execution_id, agent_name, draft_preview,
                                 success, result, timestamp)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                exec_result.get("execution_id", ""),
                                agent_name,
                                (draft[:120] + "...") if len(draft) > 120 else draft,
                                int(exec_result.get("success", False)),
                                str(exec_result.get("result", "")),
                                now_iso,
                            ),
                        )
                        cursor.connection.commit()
                    return jsonify({
                        "thread_id": thread_id,
                        "status": "completed",
                        "result": exec_result.get("result", "Task executed"),
                    })
                except Exception as exec_err:
                    if tenant_id:
                        update_tenant_agent_activity(
                            tenant_id, agent_name, status="idle"
                        )
                    return jsonify({
                        "thread_id": thread_id,
                        "status": "completed",
                        "result": f"Execution error: {str(exec_err)}",
                    })
            else:
                if agent_name and tenant_id:
                    update_tenant_agent_activity(
                        tenant_id, agent_name, status="idle"
                    )
                return jsonify({
                    "thread_id": thread_id,
                    "status": "completed",
                    "result": "Task rejected." if not approved else "No agent assigned.",
                })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({"error": "Thread not found and no tenant context"}), 404


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
        return jsonify({"error": str(e)}), 500


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
    if not tenant_id:
        return jsonify({"error": "tenant_id required"}), 400

    session["active_tenant_id"] = tenant_id
    return jsonify({
        "active_tenant": tenant_id,
        "message": f"Switched to tenant {tenant_id}",
    })


# ---------------------------------------------------------------------------
# API: client deployment via Client Factory
# ---------------------------------------------------------------------------

@app.route("/api/clients/deploy", methods=["POST"])
def deploy_client():
    """Deploy a new client website via the Client Factory.

    Requires admin login. Creates tenant database, clones template,
    injects brand, deploys to subdomain, and sends welcome email.
    """
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    config = request.json
    if not config:
        return jsonify({"success": False, "error": "No configuration provided"}), 400

    try:
        factory = ClientFactory()
        result = factory.deploy(config)
        return jsonify(result), 200 if result.get("success") else 500
    except Exception as e:
        logger.error(f"Client deployment failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
