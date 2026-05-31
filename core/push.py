"""Push notification manager — sends Web Push notifications to PWA subscribers.

Uses the ``pywebpush`` library for encrypted push delivery via browser's
native push service. Falls back gracefully if the library is not installed.

Subscriptions are persisted to ``data/push_subscriptions.jsonl`` so they
survive server restarts.
VAPID keys are auto-generated on first startup and cached to
``data/vapid_keys.json`` — no environment configuration needed.
"""

import base64
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

logger = logging.getLogger(__name__)

_base_dir = Path(__file__).parent.parent
SUBSCRIPTIONS_FILE = _base_dir / "data" / "push_subscriptions.jsonl"
VAPID_KEYS_FILE = _base_dir / "data" / "vapid_keys.json"

try:
    from pywebpush import webpush, WebPushException
    HAS_PYWEBPUSH = True
except ImportError:
    HAS_PYWEBPUSH = False
    logger.info("pywebpush not installed — push disabled. Install: pip install pywebpush")


def _vapid_fernet() -> Fernet:
    secret = os.getenv("FLASK_SECRET_KEY", "").encode()
    salt = b"vapid-key-encryption-salt"
    kdf = hashlib.pbkdf2_hmac("sha256", secret, salt, 100_000, dklen=32)
    return Fernet(base64.urlsafe_b64encode(kdf))


def _encrypt_vapid_keys(keys: Dict[str, str]) -> str:
    return _vapid_fernet().encrypt(json.dumps(keys).encode()).decode()


def _decrypt_vapid_keys(token: str) -> Dict[str, str]:
    return json.loads(_vapid_fernet().decrypt(token.encode()))


def _ensure_vapid_keys() -> Dict[str, str]:
    """Load VAPID keys from env vars, encrypted cache, or generate fresh."""
    pub = os.getenv("VAPID_PUBLIC_KEY", "")
    priv = os.getenv("VAPID_PRIVATE_KEY", "")
    if pub and priv:
        return {"public_key": pub, "private_key": priv}

    if VAPID_KEYS_FILE.exists():
        try:
            return _decrypt_vapid_keys(VAPID_KEYS_FILE.read_text())
        except Exception as e:
            logger.debug("Failed to decrypt VAPID keys cache: %s", e)

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
        VAPID_KEYS_FILE.write_text(_encrypt_vapid_keys(keys))
    except Exception as e:
        logger.warning("Failed to cache VAPID keys: %s", e)
    return keys


class PushManager:
    """Manages Web Push subscriptions and sends push notifications.

    Thread-safe. Degrades gracefully if ``pywebpush`` is not installed.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscriptions: List[Dict[str, Any]] = []
        self._vapid = _ensure_vapid_keys()
        vapid_sub = os.getenv("VAPID_SUBSCRIPTION", "mailto:admin@lavaldigital.ca")
        self._vapid_claims = {"sub": vapid_sub}
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

    def send_event(self, event_type: str, agent: str, data: Optional[Dict[str, Any]] = None) -> None:
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
