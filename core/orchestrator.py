import json
import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from core.llm_adapter import LLMAdapter
from core.base_agent import BaseAgent
from core.location_injector import LocationInjector

logger = logging.getLogger(__name__)


class OrchestratorState(TypedDict):
    """State for the Orchestrator's LangGraph workflow."""
    user_request: str
    routed_agent: str
    agent_task: str
    agent_draft: Optional[str]
    approved: Optional[bool]
    feedback: Optional[str]
    final_result: Optional[str]
    messages: List[Dict]


class Orchestrator:
    """Central Orchestrator for the Laval Digital multi-agent system.

    Receives high-level natural language requests from small business owners
    and routes tasks to specialized agents (Local SEO, Social Media, Lead Conversion).
    Presents agent outputs for human approval before execution.
    """

    ROUTING_PROMPT = """You are the Orchestrator for Laval Digital's AI marketing automation system.
You receive requests from small business owners and must route them to the correct specialized agent.

Available agents:
- backlinks: Handles link building, guest post prospecting, citation building, backlink gap analysis, broken link building, directory submissions
- email_marketing: Handles newsletter campaigns, promotional emails, lead nurture sequences, reactivation campaigns, post-service follow-ups
- growth_hacker: Handles growth audits, viral loops, conversion rate optimization, partnership strategies, data-driven experiments, creative low-cost tactics
- lead_conversion: Handles lead follow-up sequences, CRM integration, conversion optimization, email campaigns
- local_seo: Handles Google Business Profile optimization, local citations, local keyword content, review management
- outreach: Handles prospecting emails, lead finding, campaign sequences, follow-up automation, personalized outreach at scale
- paid_ads: Handles Google & Meta ad campaigns, ad copy creation, keyword strategy, budget allocation, A/B testing, audience targeting
- reputation: Handles online review monitoring, review response generation, review generation campaigns, reputation audits, crisis response
- social_media: Handles social media posts, content creation, content calendars, engagement strategies
- tiktok: Handles short-form video content for TikTok, Instagram Reels, YouTube Shorts, content calendars, video scripts, trend adaptation

Analyze the user's request and respond in JSON format:
{
    "agent": "agent_name",
    "task": "specific task description for the agent",
    "reasoning": "brief explanation of why this agent was chosen"
}

User request: {user_request}

Respond only with the JSON, no other text."""

    def __init__(
        self,
        llm_adapter: LLMAdapter,
        agent_registry: Dict[str, BaseAgent]
    ) -> None:
        """Initialize the Orchestrator.

        Args:
            llm_adapter: An instance of LLMAdapter for routing decisions.
            agent_registry: Dict mapping agent names to BaseAgent instances.
        """
        self._llm_adapter = llm_adapter
        self._agent_registry = agent_registry
        self._checkpointer = MemorySaver()
        self._location_injector = LocationInjector()
        self._graph = None
        logger.info(f"Orchestrator initialized with {len(agent_registry)} agents")

    def _parse_request(self, state: OrchestratorState) -> OrchestratorState:
        """Parse the user request and determine which agent should handle it.

        Args:
            state: Current orchestrator state with user_request.

        Returns:
            Updated state with routed_agent and agent_task.
        """
        user_request = state["user_request"]
        logger.info(f"Parsing request: {user_request}")

        try:
            prompt = self.ROUTING_PROMPT.format(user_request=user_request)
            response = self._llm_adapter.invoke(
                system_prompt="You are a helpful routing assistant.",
                user_message=prompt
            )

            routing_decision = json.loads(response)

            state["routed_agent"] = routing_decision["agent"]
            state["agent_task"] = routing_decision["task"]

            # Inject location context for location-aware agents
            enhanced_task = self._location_injector.inject(
                state["agent_task"],
                state["routed_agent"]
            )
            state["agent_task"] = enhanced_task

            state["messages"].append({
                "role": "orchestrator",
                "content": f"Routed to {routing_decision['agent']}: {routing_decision['reasoning']}"
            })

            logger.info(f"Routed to agent: {state['routed_agent']}")

        except Exception as e:
            logger.error(f"Failed to parse request: {e}")
            state["routed_agent"] = "unknown"
            state["agent_task"] = user_request
            state["messages"].append({
                "role": "orchestrator",
                "content": f"Routing failed, using default: {str(e)}"
            })

        return state

    def _route_to_agent(self, state: OrchestratorState) -> OrchestratorState:
        """Route the task to the selected agent and produce a draft via LLM.

        Does NOT invoke the agent's full graph (draft→approval→execute).
        Instead, calls the LLM directly with the agent's system prompt to
        produce a draft. Approval and execution happen separately via the
        orchestrator's approval node and the admin panel.

        Args:
            state: Current state with routed_agent and agent_task.

        Returns:
            Updated state with agent_draft (but NOT final_result).
        """
        agent_name = state["routed_agent"]
        task = state["agent_task"]

        if agent_name not in self._agent_registry:
            logger.error(f"Agent '{agent_name}' not found in registry")
            state["agent_draft"] = f"Error: Agent '{agent_name}' not available"
            return state

        agent = self._agent_registry[agent_name]

        if not agent.enabled:
            logger.warning(f"Agent '{agent_name}' is disabled")
            state["agent_draft"] = f"Agent '{agent_name}' is currently disabled"
            return state

        logger.info(f"Producing draft via agent: {agent_name}")

        try:
            response = self._llm_adapter.invoke(
                system_prompt=agent.system_prompt,
                user_message=task
            )
            state["agent_draft"] = response
            state["messages"].append({
                "role": "agent",
                "agent": agent_name,
                "content": response
            })

        except Exception as e:
            logger.error(f"Draft generation failed: {e}")
            state["agent_draft"] = f"Draft generation error: {str(e)}"

        return state

    def _approval_node(self, state: OrchestratorState) -> OrchestratorState:
        """Present the agent's draft for human approval.

        Args:
            state: Current state with agent_draft.

        Returns:
            Updated state with approved flag and feedback.
        """
        draft = state.get("agent_draft", "")

        logger.info("Requesting human approval for agent output")

        from langgraph.types import interrupt

        human_input = interrupt({
            "type": "orchestrator_approval",
            "agent": state.get("routed_agent", "unknown"),
            "draft": draft,
            "message": "Orchestrator requests approval for agent output."
        })

        state["approved"] = human_input.get("approved", False)
        state["feedback"] = human_input.get("feedback", "")

        return state

    def _finalize(self, state: OrchestratorState) -> OrchestratorState:
        """Finalize the workflow based on approval decision.

        Args:
            state: Current state with approved flag.

        Returns:
            Updated state with final_result.
        """
        if state.get("approved"):
            state["final_result"] = state.get("agent_draft", "Task completed")
            state["messages"].append({
                "role": "orchestrator",
                "content": "Task approved and completed successfully."
            })
            logger.info("Task approved and finalized")
        else:
            feedback = state.get("feedback", "No feedback provided")
            state["final_result"] = f"Task rejected. Feedback: {feedback}"
            state["messages"].append({
                "role": "orchestrator",
                "content": f"Task rejected. Feedback: {feedback}"
            })
            logger.info(f"Task rejected. Feedback: {feedback}")

        return state

    def build_graph(self) -> StateGraph:
        """Build and compile the Orchestrator's LangGraph workflow.

        Returns:
            Compiled StateGraph for the orchestrator.
        """
        if self._graph is not None:
            return self._graph

        builder = StateGraph(OrchestratorState)

        builder.add_node("parse_request", self._parse_request)
        builder.add_node("route_to_agent", self._route_to_agent)
        builder.add_node("approval", self._approval_node)
        builder.add_node("finalize", self._finalize)

        builder.add_edge(START, "parse_request")
        builder.add_edge("parse_request", "route_to_agent")
        builder.add_edge("route_to_agent", "approval")
        builder.add_edge("approval", "finalize")
        builder.add_edge("finalize", END)

        self._graph = builder.compile(checkpointer=self._checkpointer)
        logger.info("Orchestrator graph built and compiled")

        return self._graph
