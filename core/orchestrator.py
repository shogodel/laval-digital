import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.llm_adapter import LLMAdapter
from core.base_agent import BaseAgent
from core.location_injector import LocationInjector

logger = logging.getLogger(__name__)

ROUTING_PROMPT = """You are the Orchestrator for Laval Digital's AI marketing automation system.
You receive requests from small business owners and must route them to the correct specialized agent.

Available agents:
- backlinks: Link building, guest post prospecting, citation building, backlink gap analysis
- email_marketing: Newsletter campaigns, promotional emails, lead nurture sequences
- growth_hacker: Growth audits, viral loops, conversion rate optimization, partnership strategies
- lead_conversion: Lead follow-up sequences, CRM integration, conversion optimization
- local_seo: Google Business Profile optimization, local citations, local keyword content
- outreach: Prospecting emails, lead finding, campaign sequences, follow-up automation
- paid_ads: Google & Meta ad campaigns, ad copy creation, keyword strategy, budget allocation
- reputation: Online review monitoring, review response generation, reputation audits
- social_media: Social media posts, content creation, content calendars, engagement strategies
- tiktok: Short-form video content for TikTok, Instagram Reels, YouTube Shorts

When a user sends a request, you must:
1. Analyze their request and determine which agent should handle it
2. Generate the agent's response yourself by adopting that agent's expertise
3. Return your response in a friendly, conversational format
4. END EVERY RESPONSE with this exact text:

---

**Agent:** [agent_name] | **Status:** Pending Approval
Type **"approve"** to execute this content or **"reject"** to discard it.

User request: {user_request}

Respond as if you are the selected agent. Be helpful, specific, and actionable.
Always include the approval prompt at the end."""


class Orchestrator:
    """Conversational orchestrator that routes tasks to agents and manages chat-based approval.

    Unlike the previous version, this orchestrator does NOT use LangGraph interrupts.
    It responds directly in the chat and uses text commands (approve/reject) for execution.
    """

    def __init__(self, llm_adapter: LLMAdapter, agent_registry: Dict[str, BaseAgent]):
        self._llm_adapter = llm_adapter
        self._agent_registry = agent_registry
        self._location_injector = LocationInjector()
        self._pending_drafts: Dict[str, Dict[str, Any]] = {}
        logger.info(f"Chat Orchestrator initialized with {len(agent_registry)} agents")

    def process_message(self, user_message: str, thread_id: str) -> Dict[str, Any]:
        """Process a user message and return an immediate response.

        If the user says "approve" or "reject", handle the pending draft.
        Otherwise, route to the appropriate agent and generate a response.

        Returns:
            Dict with keys: response, agent, status, thread_id, pending_approval (bool)
        """
        message_lower = user_message.strip().lower()

        if message_lower in ("approve", "approved", "yes", "execute", "run it"):
            return self._handle_approval(thread_id, approved=True)
        elif message_lower in ("reject", "rejected", "no", "discard", "cancel"):
            return self._handle_approval(thread_id, approved=False)

        return self._route_and_respond(user_message, thread_id)

    def _route_and_respond(self, user_message: str, thread_id: str) -> Dict[str, Any]:
        """Route the message to the appropriate agent and return a response."""
        try:
            prompt = ROUTING_PROMPT.format(user_request=user_message)
            response = self._llm_adapter.invoke(
                system_prompt="You are a helpful AI orchestrator for local business marketing.",
                user_message=prompt
            )

            agent_name = self._extract_agent_from_response(response)

            self._pending_drafts[thread_id] = {
                "agent": agent_name,
                "draft": response,
                "task": user_message,
                "created_at": datetime.now(timezone.utc).isoformat()
            }

            return {
                "response": response,
                "agent": agent_name,
                "status": "pending_approval",
                "thread_id": thread_id,
                "pending_approval": True
            }

        except Exception as e:
            logger.error(f"Orchestrator routing failed: {e}")
            return {
                "response": f"I had trouble processing that request. Could you rephrase it? Error: {str(e)}",
                "agent": "unknown",
                "status": "error",
                "thread_id": thread_id,
                "pending_approval": False
            }

    def _handle_approval(self, thread_id: str, approved: bool) -> Dict[str, Any]:
        """Handle an approval or rejection command."""
        if thread_id not in self._pending_drafts:
            return {
                "response": "I don't have any pending content to approve or reject. Send me a new request and I'll generate something for you!",
                "agent": "orchestrator",
                "status": "no_pending",
                "thread_id": thread_id,
                "pending_approval": False
            }

        draft_info = self._pending_drafts.pop(thread_id)

        if approved:
            return {
                "response": f"✅ Approved! The content from **{draft_info['agent']}** has been sent to the Executioner for publishing.\n\nYou can now ask me for something else.",
                "agent": draft_info["agent"],
                "status": "approved",
                "thread_id": thread_id,
                "pending_approval": False,
                "approved_draft": draft_info["draft"],
                "agent_for_execution": draft_info["agent"]
            }
        else:
            return {
                "response": f"❌ Rejected. The content from **{draft_info['agent']}** has been discarded. Send me a new request and I'll try again!",
                "agent": draft_info["agent"],
                "status": "rejected",
                "thread_id": thread_id,
                "pending_approval": False
            }

    def _extract_agent_from_response(self, response: str) -> str:
        """Extract the agent name from the orchestrator's response."""
        match = re.search(r'\*\*Agent:\*\*\s*(\w+)', response)
        if match:
            return match.group(1)
        return "local_seo"
