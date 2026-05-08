import os
import sys
import uuid
import warnings
from datetime import datetime
from typing import Dict, Any

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
from agents.local_seo_agent import LocalSEOAgent
from agents.social_media_agent import SocialMediaAgent
from agents.lead_conversion_agent import LeadConversionAgent
from agents.paid_ads_agent import PaidAdsAgent
from agents.growth_hacker_agent import GrowthHackerAgent
from agents.executioner_agent import ExecutionerAgent

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# Store active threads and their states
active_threads: Dict[str, Dict[str, Any]] = {}

# In-memory lead storage (replace with database in production)
leads: list[Dict[str, Any]] = []

# Per-agent activity telemetry for admin panel
agent_activity: Dict[str, Dict[str, Any]] = {
    agent_id: {
        "status": "idle",
        "last_invoked": None,
        "task_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "last_draft_preview": None,
    }
    for agent_id in ["local_seo", "social_media", "lead_conversion", "paid_ads", "growth_hacker"]
}

def _update_activity(agent_id: str, **kwargs) -> None:
    """Update activity fields for a given agent."""
    if agent_id in agent_activity:
        agent_activity[agent_id].update(kwargs)

# Agent configurations - in production, load from config files
AGENT_CONFIGS = {
    "local_seo": {
        "agent_id": "local_seo",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/local_seo.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1"
        }
    },
    "social_media": {
        "agent_id": "social_media",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/social_media.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1"
        }
    },
    "lead_conversion": {
        "agent_id": "lead_conversion",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/lead_conversion.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1"
        }
    },
    "paid_ads": {
        "agent_id": "paid_ads",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/paid_ads.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1"
        }
    },
    "growth_hacker": {
        "agent_id": "growth_hacker",
        "enabled": True,
        "model": "deepseek-chat",
        "system_prompt_file": "prompts/growth_hacker.md",
        "credentials": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "api_base": "https://api.deepseek.com/v1"
        }
    }
}

# Initialize LLM Adapter for Orchestrator
llm_adapter = LLMAdapter(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    api_base="https://api.deepseek.com/v1"
)

# Initialize agents
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
        return render_template("login.html", error="Invalid username or password.", now=datetime.now())
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
    return render_template("admin.html", logo_uploaded=logo_status)


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
        return render_template("login_fr.html", error="Nom d'utilisateur ou mot de passe invalide.", now=datetime.now())
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
    return render_template("admin_fr.html", logo_uploaded=logo_status)


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
    if file and (file.filename.lower().endswith(".png") or file.filename.lower().endswith(".svg")):
        ext = file.filename.rsplit(".", 1)[1].lower()
        save_path = os.path.join(app.root_path, "static", f"logo_custom.{ext}")
        file.save(save_path)
        other_ext = "svg" if ext == "png" else "png"
        other_path = os.path.join(app.root_path, "static", f"logo_custom.{other_ext}")
        if os.path.exists(other_path):
            os.remove(other_path)
        session["logo_ext"] = ext
        return redirect(url_for("admin_panel_redirect", logo_uploaded="success"))
    return redirect(url_for("admin_panel_redirect", logo_uploaded="invalid"))


@app.context_processor
def inject_logo():
    """Inject the current logo filename into all templates."""
    for ext in ("png", "svg"):
        path = os.path.join(app.root_path, "static", f"logo_custom.{ext}")
        if os.path.exists(path):
            return dict(logo_file=f"logo_custom.{ext}")
    return dict(logo_file="logo.svg")


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
            "created_at": __import__("datetime").datetime.now().isoformat()
        }
        if not lead["name"] or not lead["phone"]:
            return jsonify({"error": "Name and phone are required"}), 400
        leads.append(lead)
        return jsonify({"status": "ok", "lead": lead}), 201

    # GET: return all leads (for admin panel)
    return jsonify({"leads": leads})


@app.route("/api/agents", methods=["GET"])
def get_agents():
    """Get status and activity telemetry of all agents."""
    agents_status = []
    for agent_id, agent in agent_registry.items():
        act = agent_activity.get(agent_id, {})
        agents_status.append({
            "agent_id": agent.agent_id,
            "enabled": agent.enabled,
            "model": agent.model,
            "status": act.get("status", "idle"),
            "last_invoked": act.get("last_invoked"),
            "task_count": act.get("task_count", 0),
            "success_count": act.get("success_count", 0),
            "failure_count": act.get("failure_count", 0),
            "last_draft_preview": act.get("last_draft_preview"),
        })
    return jsonify({"agents": agents_status})


@app.route("/api/models", methods=["GET"])
def get_available_models():
    """Return list of all available LLM models via litellm."""
    try:
        models = LLMAdapter.get_available_models()
        return jsonify({"models": models})
    except Exception as e:
        return jsonify({"models": ["deepseek-chat", "gpt-4o", "claude-3.5-sonnet"]})


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
        return jsonify({"provider": "unknown", "models": [], "error": str(e)}), 500


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


@app.route("/api/agents/<agent_id>/toggle", methods=["POST"])
def toggle_agent(agent_id):
    """Toggle agent on/off."""
    if agent_id not in agent_registry:
        return jsonify({"error": "Agent not found"}), 404
    
    agent = agent_registry[agent_id]
    agent.enabled = not agent.enabled
    
    return jsonify({
        "agent_id": agent_id,
        "enabled": agent.enabled
    })


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
        "api_base": config.get("credentials", {}).get("api_base", "")
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
    
    # Rebuild orchestrator with updated agent
    global orchestrator, orchestrator_graph
    orchestrator = Orchestrator(llm_adapter, agent_registry)
    orchestrator_graph = orchestrator.build_graph()
    
    return jsonify({
        "agent_id": agent_id,
        "model": config["model"],
        "message": "Configuration updated and agent reinitialized"
    })



@app.route("/api/tasks", methods=["POST"])
def submit_task():
    """Submit a task to the orchestrator."""
    data = request.json
    user_request = data.get("request")
    
    if not user_request:
        return jsonify({"error": "No request provided"}), 400
    
    thread_id = str(uuid.uuid4())
    
    initial_state = {
        "user_request": user_request,
        "routed_agent": "",
        "agent_task": "",
        "agent_draft": None,
        "approved": None,
        "feedback": None,
        "final_result": None,
        "messages": []
    }
    
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        graph = get_orchestrator()
        result = graph.invoke(initial_state, config)
        
        has_draft = bool(result.get("agent_draft"))
        has_final = bool(result.get("final_result"))
        status = "completed" if has_final else ("pending_approval" if has_draft else "error")
        
        active_threads[thread_id] = {
            "state": result,
            "config": config,
            "status": status
        }
        
        agent_name = result.get("routed_agent", "")
        if agent_name and agent_name in agent_activity:
            draft_preview = None
            if has_draft:
                draft = result.get("agent_draft", "")
                draft_preview = (draft[:120] + "...") if len(draft) > 120 else draft
            _update_activity(agent_name,
                status="idle" if status == "completed" else "pending_approval",
                last_invoked=datetime.now().isoformat(),
                task_count=agent_activity[agent_name]["task_count"] + 1,
                last_draft_preview=draft_preview,
            )
        
        return jsonify({
            "thread_id": thread_id,
            "status": status,
            "result": result
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/approvals", methods=["GET"])
def get_approvals():
    """Get pending approvals."""
    approvals = []
    for thread_id, thread_data in active_threads.items():
        state = thread_data["state"]
        if thread_data["status"] == "pending_approval" and state.get("agent_draft"):
            approvals.append({
                "thread_id": thread_id,
                "agent": state.get("routed_agent"),
                "draft": state.get("agent_draft"),
                "task": state.get("agent_task")
            })
    return jsonify({"approvals": approvals})


@app.route("/api/approvals/<thread_id>/respond", methods=["POST"])
def respond_approval(thread_id):
    """Respond to an approval request and execute agent if approved."""
    if thread_id not in active_threads:
        return jsonify({"error": "Thread not found"}), 404
    
    data = request.json
    approved = data.get("approved", False)
    feedback = data.get("feedback", "")
    
    thread_data = active_threads[thread_id]
    
    human_response = {
        "approved": approved,
        "feedback": feedback
    }
    
    try:
        graph = get_orchestrator()
        result = graph.invoke(human_response, thread_data["config"])
        
        thread_data["state"] = result
        thread_data["status"] = "completed"
        
        # If approved, execute via the ExecutionerAgent
        if approved:
            state = result
            agent_name = state.get("routed_agent")
            draft = state.get("agent_draft", "")
            if agent_name and agent_name in agent_registry:
                try:
                    exec_result = executioner.execute(agent_name, draft)
                    thread_data["state"]["final_result"] = exec_result.get("result", str(exec_result))
                    thread_data["state"]["execution_id"] = exec_result.get("execution_id")

                    if exec_result.get("status") == "pending_confirmation":
                        _update_activity(agent_name,
                            status="pending_confirmation",
                            last_invoked=datetime.now().isoformat(),
                            last_draft_preview=(draft[:120] + "...") if len(draft) > 120 else draft,
                        )
                    elif exec_result.get("success"):
                        _update_activity(agent_name,
                            success_count=agent_activity[agent_name]["success_count"] + 1,
                            status="idle",
                        )
                    else:
                        _update_activity(agent_name,
                            failure_count=agent_activity[agent_name]["failure_count"] + 1,
                            status="idle",
                        )
                except Exception as exec_err:
                    thread_data["state"]["final_result"] = f"Execution error: {str(exec_err)}"
                    _update_activity(agent_name,
                        failure_count=agent_activity[agent_name]["failure_count"] + 1,
                        status="idle",
                    )
        else:
            agent_name = thread_data["state"].get("routed_agent")
            if agent_name and agent_name in agent_activity:
                _update_activity(agent_name,
                    failure_count=agent_activity[agent_name]["failure_count"] + 1,
                    status="idle",
                )
        
        return jsonify({
            "thread_id": thread_id,
            "status": "completed",
            "result": thread_data["state"].get("final_result")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
    
    try:
        _update_activity(agent_id, status="processing")
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
        _update_activity(agent_id,
            status="idle",
            last_invoked=datetime.now().isoformat(),
            task_count=agent_activity[agent_id]["task_count"] + 1,
            success_count=agent_activity[agent_id]["success_count"] + 1,
            last_draft_preview=draft_preview,
        )
        
        return jsonify({
            "agent_id": agent_id,
            "result": result
        })
    except Exception as e:
        _update_activity(agent_id,
            status="idle",
            failure_count=agent_activity[agent_id]["failure_count"] + 1,
        )
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
