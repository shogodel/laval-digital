import os
import sys
import uuid
import warnings
from typing import Dict, Any

# Suppress warnings before any imports that might trigger them
warnings.filterwarnings("ignore", module="langgraph")
warnings.filterwarnings("ignore", module="langchain")

from flask import Flask, render_template, jsonify, request, redirect, url_for
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

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# Store active threads and their states
active_threads: Dict[str, Dict[str, Any]] = {}

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
def lead_site():
    """Serve the client-facing lead generation site."""
    return render_template("lead_site.html",
        business_name="Laval 24/7 Plumbing",
        city="Laval",
        service="Plumbing",
        phone="(450) 555-0199",
        services=["Emergency Repairs", "Pipe Installation", "Water Heater Service", "Drain Cleaning", "Bathroom Remodeling"]
    )


@app.route("/admin")
def admin_panel_redirect():
    """Redirect to admin panel."""
    return render_template("admin.html")


@app.route("/api/agents", methods=["GET"])
def get_agents():
    """Get status of all agents."""
    agents_status = []
    for agent_id, agent in agent_registry.items():
        agents_status.append({
            "agent_id": agent.agent_id,
            "enabled": agent.enabled,
            "model": agent.model,
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
        
        active_threads[thread_id] = {
            "state": result,
            "config": config,
            "status": "completed" if result.get("final_result") else "pending_approval"
        }
        
        return jsonify({
            "thread_id": thread_id,
            "status": active_threads[thread_id]["status"],
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
    """Respond to an approval request."""
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
        
        return jsonify({
            "thread_id": thread_id,
            "status": "completed",
            "result": result.get("final_result")
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
        graph = agent.build_graph()
        result = graph.invoke({
            "task": task,
            "draft_output": None,
            "approved": None,
            "feedback": None,
            "result": None,
        })
        
        return jsonify({
            "agent_id": agent_id,
            "result": result
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
