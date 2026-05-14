import json
import logging
import re
import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional

from core.llm_adapter import LLMAdapter
from core.base_agent import BaseAgent
from core.events import get_event_bus

logger = logging.getLogger(__name__)

FRENCH_KEYWORDS = [
    'bonjour', 'salut', 'bjr', 'couci', 'allo',
    'je', 'tu', 'il', 'elle', 'on', 'nous', 'vous', 'ils', 'elles',
    'le', 'la', 'les', 'un', 'une', 'des', 'du', 'de', 'ce', 'ces',
    'mon', 'ton', 'son', 'ma', 'ta', 'sa', 'mes', 'tes', 'ses',
    'est', 'sont', 'dans', 'avec', 'pour', 'sur', 'par', 'pas',
    'comment', 'français', 'french', 'parle', 'parler', 'parlez',
    'aide', 'aidez', 'aider', 'merci', 'svp', 's\'il vous plaît',
    'peux', 'peut', 'veux', 'veut', 'fait', 'faire', 'avoir', 'être',
    'quoi', 'qui', 'où', 'quand', 'pourquoi', 'combien', 'quel',
    'ça', 'cela', 'cet', 'cette', 'notre', 'votre', 'leur',
]

VALID_AUTONOMY_LEVELS = ("manual", "suggest", "auto", "silent")

ROUTING_PROMPT = """You are the Orchestrator for Laval Digital's AI marketing automation platform.
You receive requests from local business owners and must route them to the correct specialized agent.

Available agents:
- **local_seo**: Google Business Profile optimization, local citations, local keyword content, review management
- **social_media**: Social media posts, content creation, content calendars, engagement strategies
- **lead_conversion**: Lead follow-up sequences, CRM integration, conversion optimization, email campaigns
- **paid_ads**: Google & Meta ad campaigns, ad copy creation, keyword strategy, budget allocation, A/B testing
- **growth_hacker**: Growth audits, viral loops, conversion rate optimization, partnership strategies, data-driven experiments
- **reputation**: Online review monitoring, review response generation, review generation campaigns, reputation audits
- **email_marketing**: Newsletter campaigns, promotional emails, lead nurture sequences, reactivation campaigns
- **tiktok**: Short-form video content for TikTok, Instagram Reels, YouTube Shorts, video scripts, trend adaptation
- **outreach**: Prospecting emails, lead finding, campaign sequences, follow-up automation, personalized outreach
- **backlinks**: Link building, guest post prospecting, citation building, backlink gap analysis, directory submissions

Your job:
1. Analyze the user's request and determine which agent should handle it
2. Generate the agent's response yourself by adopting that agent's expertise
3. Be proactive — if the user seems new, offer suggestions for what you can help with
4. If the request is vague, ask clarifying questions and suggest specific services
5. End EVERY response with the approval prompt:

---

**Agent:** [agent_name] | **Status:** Pending Approval
Type **"approve"** to execute this content or **"reject"** to discard it.

User request: {user_request}

Respond in {language}. Be helpful, specific, and actionable.
Always include the approval prompt at the end."""

WELCOME_PROMPT = """You are the Orchestrator for Laval Digital's AI marketing automation platform.
A new user has just opened a conversation with you. Greet them warmly and explain what you can do.

You have 10 specialized agents that can help with:
- Local SEO (Google Business Profile, local rankings)
- Social Media management (content creation, scheduling)
- Lead Conversion (follow-up sequences, CRM)
- Paid Ads (Google & Meta campaigns)
- Growth Hacking (viral strategies, CRO)
- Reputation Management (reviews, monitoring)
- Email Marketing (newsletters, campaigns)
- TikTok content (short-form video)
- Outreach & Prospecting
- Backlinks & Link Building

Your response should:
1. Welcome the user in a friendly way
2. Briefly explain what you can do for their business
3. Ask about their business type and biggest marketing challenge
4. Suggest 2-3 specific things you could help with right away
5. Be conversational and encouraging

Respond in {language}."""

SUGGESTIONS_PROMPT = """You are a proactive AI marketing assistant. Based on typical small business needs,
suggest 3-5 specific marketing actions the user could take right now.

For each suggestion, include:
- A clear title
- A brief explanation of why it matters
- Which agent would handle it

Be practical and actionable. Focus on high-impact, low-effort wins first.

Respond in {language}."""


class Orchestrator:
    def __init__(self, llm_adapter: LLMAdapter, agent_registry: Dict[str, BaseAgent], executioner=None, push_manager=None):
        self._llm_adapter = llm_adapter
        self._agent_registry = agent_registry
        self._executioner = executioner
        self._push_manager = push_manager
        self._pending_drafts: Dict[str, Dict[str, Any]] = {}
        self._activity_feed: List[Dict[str, Any]] = []
        self._panicked = False
        self._panic_lock = Lock()
        logger.info(
            "Orchestrator initialized with %d agents (executioner=%s, push=%s)",
            len(agent_registry),
            "connected" if executioner else "not connected",
            "connected" if push_manager else "not connected",
        )

    # ------------------------------------------------------------------
    # Panic
    # ------------------------------------------------------------------

    def panic(self) -> None:
        with self._panic_lock:
            self._panicked = True
        logger.warning("PANIC engaged — all auto-executions blocked")

    def clear_panic(self) -> None:
        with self._panic_lock:
            self._panicked = False
        logger.info("Panic cleared — auto-executions resumed")

    @property
    def is_panicked(self) -> bool:
        with self._panic_lock:
            return self._panicked

    # ------------------------------------------------------------------
    # Activity feed
    # ------------------------------------------------------------------

    def _push_activity(self, entry: Dict[str, Any]) -> None:
        self._activity_feed.insert(0, entry)
        self._activity_feed[:] = self._activity_feed[:200]

    def get_activity_feed(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._activity_feed[:limit]

    # ------------------------------------------------------------------
    # Welcome / Suggestions
    # ------------------------------------------------------------------

    def get_welcome(self, language: str = "en") -> Dict[str, Any]:
        lang_label = "français" if language == "fr" else "english"
        try:
            response = self._llm_adapter.invoke(
                system_prompt=f"You are a friendly AI orchestrator for local business marketing. Respond in {lang_label}.",
                user_message=WELCOME_PROMPT.format(language=lang_label),
            )
            return {"response": response, "agent": "orchestrator", "status": "welcome"}
        except Exception as e:
            logger.error("Welcome message failed: %s", e)
            fallback_en = "Hi! I'm your AI marketing team. I have 10 specialized agents ready to help with SEO, social media, ads, email, and more. What's your business and what would you like help with?"
            fallback_fr = "Bonjour ! Je suis votre équipe marketing IA. J'ai 10 agents spécialisés prêts à vous aider avec le SEO, les réseaux sociaux, les annonces, les courriels et plus encore. Parlez-moi de votre entreprise et de ce que vous aimeriez améliorer."
            return {"response": fallback_fr if language == "fr" else fallback_en, "agent": "orchestrator", "status": "welcome"}

    def _send_push(self, event_type: str, agent: str, data: Dict[str, Any]) -> None:
        if self._push_manager and hasattr(self._push_manager, "send_event"):
            try:
                self._push_manager.send_event(event_type, agent, data)
            except Exception:
                pass

    def get_suggestions(self, language: str = "en") -> Dict[str, Any]:
        lang_label = "français" if language == "fr" else "english"
        try:
            response = self._llm_adapter.invoke(
                system_prompt=f"You are a proactive AI marketing assistant. Respond in {lang_label}.",
                user_message=SUGGESTIONS_PROMPT.format(language=lang_label),
            )
            return {"response": response, "agent": "orchestrator", "status": "suggestions"}
        except Exception as e:
            logger.error("Suggestions failed: %s", e)
            return {"response": "", "agent": "orchestrator", "status": "suggestions"}

    # ------------------------------------------------------------------
    # Main message processing with autonomy policy
    # ------------------------------------------------------------------

    def process_message(
        self,
        user_message: str,
        thread_id: str,
        language: Optional[str] = None,
        autonomy_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Process a user message, applying the autonomy policy if configured.

        Args:
            user_message: The user's text input.
            thread_id: Conversation thread identifier.
            language: Detected or provided language code.
            autonomy_config: Per-agent autonomy settings keyed by agent_id.
                Each value: ``{autonomy: str, confidence_threshold: float}``.

        Returns:
            Dict with response + status.
        """
        message_lower = user_message.strip().lower()

        if self.is_panicked:
            return {
                "response": "⚠️ All agents are stopped. Click Resume to continue.",
                "agent": "orchestrator",
                "status": "panicked",
                "thread_id": thread_id,
                "pending_approval": False,
            }

        if language is None:
            language = self._detect_language(user_message)

        if message_lower in (
            "approve", "approved", "yes", "execute", "run it", "go ahead", "confirm",
            "approuvé", "approuve", "oui", "exécute", "exécuter", "confirmer",
        ):
            return self._handle_approval(thread_id, approved=True)
        elif message_lower in (
            "reject", "rejected", "no", "discard", "cancel", "stop",
            "non", "rejeté", "rejeter", "annuler", "supprimer",
        ):
            return self._handle_approval(thread_id, approved=False)

        return self._route_and_respond(user_message, thread_id, language, autonomy_config)

    def _route_and_respond(
        self,
        user_message: str,
        thread_id: str,
        language: str,
        autonomy_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        lang_label = "français" if language == "fr" else "english"
        try:
            prompt = ROUTING_PROMPT.format(user_request=user_message, language=lang_label)
            response = self._llm_adapter.invoke(
                system_prompt=f"You are a helpful AI orchestrator for local business marketing. Respond in {lang_label}.",
                user_message=prompt,
            )

            agent_name = self._extract_agent_from_response(response)
            now_iso = datetime.now(timezone.utc).isoformat()

            event_data_processing = {"task": user_message[:200], "language": language}
            get_event_bus().publish("agent_processing", agent_name, event_data_processing)
            self._send_push("agent_processing", agent_name, event_data_processing)

            # Check autonomy policy for this agent
            autonomy_level = "manual"
            threshold = 0.7
            confidence = 0.0

            if autonomy_config and agent_name in autonomy_config:
                ac = autonomy_config[agent_name]
                autonomy_level = ac.get("autonomy", "manual")
                threshold = float(ac.get("confidence_threshold", 0.7))

            # Parse confidence from agent response if suggest/auto
            if autonomy_level in ("suggest", "auto", "silent"):
                confidence = BaseAgent._parse_confidence(response)

            # ------ AUTONOMY POLICY GATE ------
            exec_decision = None  # None = pending, True = approved, False = rejected

            if autonomy_level == "auto":
                exec_decision = True
            elif autonomy_level == "silent":
                exec_decision = True
            elif autonomy_level == "suggest" and confidence >= threshold:
                exec_decision = True
            elif autonomy_level == "suggest" and confidence < threshold:
                exec_decision = None  # needs human
            # manual: stays None (needs human)

            clean_draft = BaseAgent._strip_confidence_metadata(response)

            if exec_decision is True:
                # Execute immediately
                execution_result = None
                if self._executioner:
                    try:
                        exec_result = self._executioner.execute(agent_name, clean_draft)
                        execution_result = {
                            "success": exec_result.get("success", False),
                            "result": exec_result.get("result", ""),
                            "execution_id": exec_result.get("execution_id"),
                        }
                    except Exception as e:
                        logger.error("Auto-execution failed for %s: %s", agent_name, e, exc_info=True)
                        execution_result = {"success": False, "error": "Execution failed."}

                # Activity feed entry
                success_flag = execution_result.get("success") if execution_result else None
                self._push_activity({
                    "id": uuid.uuid4().hex[:12],
                    "agent": agent_name,
                    "action": "auto_executed",
                    "autonomy": autonomy_level,
                    "confidence": confidence,
                    "draft_preview": clean_draft[:120],
                    "success": success_flag,
                    "timestamp": now_iso,
                })

                # Publish event
                event_type = "agent_executed" if success_flag else "agent_failed"
                event_data_exec = {
                    "autonomy": autonomy_level,
                    "confidence": confidence,
                    "draft_preview": clean_draft[:200],
                    "success": success_flag,
                    "result": execution_result.get("result") if execution_result else None,
                }
                get_event_bus().publish(event_type, agent_name, event_data_exec)
                self._send_push(event_type, agent_name, event_data_exec)

                if autonomy_level == "silent":
                    return {
                        "response": f"✔️ Task handled by **{agent_name}** (silent mode).",
                        "agent": agent_name,
                        "status": "executed_silent",
                        "thread_id": thread_id,
                        "pending_approval": False,
                        "confidence": confidence,
                        "autonomy": autonomy_level,
                    }

                msg_en = f"✅ **{agent_name}** completed this automatically (confidence {confidence:.0%})."
                msg_fr = f"✅ **{agent_name}** a terminé cela automatiquement (confiance {confidence:.0%})."
                if execution_result:
                    if execution_result.get("success"):
                        msg_en += f"\n\n**Result:** {execution_result.get('result', 'Done.')}"
                        msg_fr += f"\n\n**Résultat :** {execution_result.get('result', 'Terminé.')}"
                    elif execution_result.get("error"):
                        msg_en += f"\n\n**Error:** {execution_result['error']}"
                        msg_fr += f"\n\n**Erreur :** {execution_result['error']}"

                return {
                    "response": msg_fr if language == "fr" else msg_en,
                    "agent": agent_name,
                    "status": "auto_executed",
                    "thread_id": thread_id,
                    "pending_approval": False,
                    "approved_draft": clean_draft,
                    "execution": execution_result,
                    "confidence": confidence,
                    "autonomy": autonomy_level,
                }

            # Publish approval_needed event
            event_data_approval = {
                "thread_id": thread_id,
                "confidence": confidence,
                "autonomy": autonomy_level,
                "task": user_message[:200],
                "draft_preview": clean_draft[:200],
            }
            get_event_bus().publish("approval_needed", agent_name, event_data_approval)
            self._send_push("approval_needed", agent_name, event_data_approval)

            # Store draft for human approval (manual mode or low-confidence suggest)
            self._pending_drafts[thread_id] = {
                "agent": agent_name,
                "draft": clean_draft,
                "raw_draft": response,
                "task": user_message,
                "language": language,
                "confidence": confidence,
                "autonomy": autonomy_level,
                "created_at": now_iso,
            }

            result: Dict[str, Any] = {
                "response": clean_draft,
                "agent": agent_name,
                "status": "pending_approval",
                "thread_id": thread_id,
                "pending_approval": True,
                "confidence": confidence,
                "autonomy": autonomy_level,
            }

            if autonomy_level == "suggest" and confidence < threshold:
                msg_en = f"\n\n---\n⚠️ I'm only {confidence:.0%} confident about this. Please review and approve or reject."
                msg_fr = f"\n\n---\n⚠️ Je ne suis sûr qu'à {confidence:.0%} à propos de cela. Veuillez vérifier et approuver ou rejeter."
                result["response"] += msg_fr if language == "fr" else msg_en

            return result

        except Exception as e:
            logger.error("Orchestrator routing failed: %s", e, exc_info=True)
            return {
                "response": "I had trouble processing that request. Please try again.",
                "agent": "unknown",
                "status": "error",
                "thread_id": thread_id,
                "pending_approval": False,
            }

    def _handle_approval(self, thread_id: str, approved: bool) -> Dict[str, Any]:
        if thread_id not in self._pending_drafts:
            return {
                "response": "I don't have any pending content to approve or reject. Send me a new request and I'll generate something for you!",
                "agent": "orchestrator",
                "status": "no_pending",
                "thread_id": thread_id,
                "pending_approval": False,
            }

        draft_info = self._pending_drafts.pop(thread_id)
        language = draft_info.get("language", "en")

        if approved:
            execution_result = None
            agent_name = draft_info["agent"]
            draft = draft_info["draft"]
            now_iso = datetime.now(timezone.utc).isoformat()

            if self._executioner:
                try:
                    exec_result = self._executioner.execute(agent_name, draft)
                    execution_result = {
                        "success": exec_result.get("success", False),
                        "result": exec_result.get("result", ""),
                        "execution_id": exec_result.get("execution_id"),
                    }
                    logger.info(
                        "Orchestrator executed draft via %s (success=%s)",
                        agent_name,
                        execution_result["success"],
                    )
                except Exception as e:
                    logger.error("Orchestrator execution failed for %s: %s", agent_name, e, exc_info=True)
                    execution_result = {"success": False, "error": "Execution failed."}

            success_flag = execution_result.get("success") if execution_result else None
            self._push_activity({
                "id": uuid.uuid4().hex[:12],
                "agent": agent_name,
                "action": "approved",
                "autonomy": draft_info.get("autonomy", "manual"),
                "confidence": draft_info.get("confidence", 0.0),
                "draft_preview": draft[:120],
                "success": success_flag,
                "timestamp": now_iso,
            })

            # Publish event
            event_type = "agent_executed" if success_flag else "agent_failed"
            event_data_approve = {
                "autonomy": draft_info.get("autonomy", "manual"),
                "confidence": draft_info.get("confidence", 0.0),
                "draft_preview": draft[:200],
                "success": success_flag,
                "source": "human_approval",
            }
            get_event_bus().publish(event_type, agent_name, event_data_approve)
            self._send_push(event_type, agent_name, event_data_approve)

            msg_en = f"✅ Approved! The content from **{agent_name}** has been executed."
            msg_fr = f"✅ Approuvé ! Le contenu de **{agent_name}** a été exécuté."
            if execution_result:
                if execution_result.get("success"):
                    msg_en += f"\n\n**Result:** {execution_result.get('result', 'Done.')}"
                    msg_fr += f"\n\n**Résultat :** {execution_result.get('result', 'Terminé.')}"
                elif execution_result.get("error"):
                    msg_en += f"\n\n**Error:** {execution_result['error']}"
                    msg_fr += f"\n\n**Erreur :** {execution_result['error']}"

            return {
                "response": msg_fr if language == "fr" else msg_en,
                "agent": agent_name,
                "status": "approved",
                "thread_id": thread_id,
                "pending_approval": False,
                "approved_draft": draft,
                "agent_for_execution": agent_name,
                "execution": execution_result,
            }

        event_data_reject = {
            "thread_id": thread_id,
            "approved": False,
            "task": draft_info.get("task", "")[:200],
        }
        get_event_bus().publish("approval_responded", draft_info["agent"], event_data_reject)
        self._send_push("approval_responded", draft_info["agent"], event_data_reject)

        msg_en = f"❌ Rejected. The content from **{draft_info['agent']}** has been discarded. Send me a new request and I'll try again!"
        msg_fr = f"❌ Rejeté. Le contenu de **{draft_info['agent']}** a été supprimé. Envoyez-moi une nouvelle demande et je réessaierai !"
        return {
            "response": msg_fr if language == "fr" else msg_en,
            "agent": draft_info["agent"],
            "status": "rejected",
            "thread_id": thread_id,
            "pending_approval": False,
        }

    def _extract_agent_from_response(self, response: str) -> str:
        match = re.search(r'\*\*Agent:\*\*\s*(\w+)', response)
        if match:
            return match.group(1)
        return "local_seo"

    def _detect_language(self, text: str) -> str:
        text_lower = text.lower()
        count = sum(1 for kw in FRENCH_KEYWORDS if kw in text_lower)
        return "fr" if count >= 3 else "en"
