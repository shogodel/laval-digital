"""Push notification manager — sends Web Push notifications to PWA subscribers.

Uses the ``pywebpush`` library for encrypted push delivery via browser's
native push service. Falls back gracefully if the library is not installed.

Subscriptions are persisted to ``data/push_subscriptions.jsonl`` so they
survive server restarts.
VAPID keys are auto-generated on first startup and cached to
``data/vapid_keys.json`` — no environment configuration needed.
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

logger = logging.getLogger(__name__)

SUBSCRIPTIONS_FILE = Path("data/push_subscriptions.jsonl")
VAPID_KEYS_FILE = Path("data/vapid_keys.json")

try:
    from pywebpush import webpush, WebPushException
    HAS_PYWEBPUSH = True
except ImportError:
    HAS_PYWEBPUSH = False
    logger.info("pywebpush not installed — push disabled. Install: pip install pywebpush")


def _ensure_vapid_keys() -> Dict[str, str]:
    """Load VAPID keys from env vars, cached file, or generate fresh."""
    pub = os.getenv("VAPID_PUBLIC_KEY", "")
    priv = os.getenv("VAPID_PRIVATE_KEY", "")
    if pub and priv:
        return {"public_key": pub, "private_key": priv}

    if VAPID_KEYS_FILE.exists():
        try:
            return json.loads(VAPID_KEYS_FILE.read_text())
        except Exception:
            pass

    key = ec.generate_private_key(ec.SECP256R1())
    keys = {
        "private_key": key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode(),
        "public_key": key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode(),
    }
    try:
        VAPID_KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
        VAPID_KEYS_FILE.write_text(json.dumps(keys))
    except Exception as e:
        logger.warning("Failed to cache VAPID keys: %s", e)
    return keys


class PushManager:
    """Manages Web Push subscriptions and sends push notifications.

    Thread-safe. Degrades gracefully if ``pywebpush`` is not installed.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscriptions: List[Dict[str, Any]] = []
        self._vapid = _ensure_vapid_keys()
        self._vapid_claims = {"sub": "mailto:lavaldigital@gmail.com"}
        self._load_subscriptions()

    @property
    def public_key(self) -> str:
        return self._vapid.get("public_key", "")

    @property
    def enabled(self) -> bool:
        return HAS_PYWEBPUSH and bool(self._vapid.get("private_key"))

    def _load_subscriptions(self) -> None:
        if not SUBSCRIPTIONS_FILE.exists():
            return
        with self._lock:
            self._subscriptions = []
            try:
                SUBSCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
                for line in SUBSCRIPTIONS_FILE.read_text().strip().split("\n"):
                    if line.strip():
                        try:
                            self._subscriptions.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                logger.warning("Failed to load push subscriptions: %s", e)

    def _save_subscriptions(self) -> None:
        try:
            SUBSCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                SUBSCRIPTIONS_FILE.write_text(
                    "\n".join(json.dumps(s) for s in self._subscriptions)
                )
        except Exception as e:
            logger.warning("Failed to save push subscriptions: %s", e)

    def subscribe(self, subscription: Dict[str, Any]) -> bool:
        endpoint = subscription.get("endpoint", "")
        if not endpoint:
            return False
        with self._lock:
            if not any(s.get("endpoint") == endpoint for s in self._subscriptions):
                self._subscriptions.append(subscription)
                self._save_subscriptions()
        return True

    def unsubscribe(self, endpoint: str) -> bool:
        with self._lock:
            before = len(self._subscriptions)
            self._subscriptions = [s for s in self._subscriptions if s.get("endpoint") != endpoint]
            if len(self._subscriptions) < before:
                self._save_subscriptions()
            return len(self._subscriptions) < before

    def send(self, title: str, body: str, icon: str = "/static/logo.svg", url: str = "/admin/dashboard") -> int:
        if not self.enabled:
            return 0
        payload = json.dumps({"title": title, "body": body, "icon": icon, "url": url, "badge": "/static/logo.svg"})
        with self._lock:
            subs = list(self._subscriptions)
        success = 0
        expired = []
        for sub in subs:
            try:
                webpush(
                    subscription_info=sub,
                    data=payload,
                    vapid_private_key=self._vapid["private_key"],
                    vapid_claims=self._vapid_claims,
                )
                success += 1
            except WebPushException as e:
                if e.response and e.response.status_code in (404, 410):
                    expired.append(sub.get("endpoint", ""))
                else:
                    logger.warning("Push send failed: %s", e)
            except Exception as e:
                logger.warning("Push send error: %s", e)
        if expired:
            with self._lock:
                for ep in expired:
                    self._subscriptions = [s for s in self._subscriptions if s.get("endpoint") != ep]
                self._save_subscriptions()
        return success

    def send_event(self, event_type: str, agent: str, data: Dict[str, Any] = None) -> None:
        data = data or {}
        lang = data.get("lang", "en")
        if lang == "fr":
            if event_type == "agent_executed":
                self.send(title=f"✅ {agent} terminé", body=(data.get("draft_preview") or "Tâche exécutée.")[:120])
            elif event_type == "agent_failed":
                self.send(title=f"❌ {agent} a échoué", body=(data.get("error") or "Tâche échouée.")[:120])
            elif event_type == "approval_needed":
                self.send(title=f"🤔 {agent} nécessite approbation", body=(data.get("draft_preview") or "Nouveau projet prêt.")[:120], url="/admin")
            elif event_type == "approval_responded":
                self.send(title=f"📋 {agent} traité", body="Votre réponse d'approbation a été reçue.")
        else:
            if event_type == "agent_executed":
                self.send(title=f"✅ {agent} completed", body=(data.get("draft_preview") or "Task executed.")[:120])
            elif event_type == "agent_failed":
                self.send(title=f"❌ {agent} failed", body=(data.get("error") or "Task failed.")[:120])
            elif event_type == "approval_needed":
                self.send(title=f"🤔 {agent} needs approval", body=(data.get("draft_preview") or "New draft ready.")[:120], url="/admin")
            elif event_type == "approval_responded":
                self.send(title=f"📋 {agent} processed", body="Your approval response was received.")
