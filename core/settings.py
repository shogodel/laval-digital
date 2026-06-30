"""Application-wide configuration, constants, and utility helpers."""
import base64 as _b64
import logging
import os
import re
import warnings
from typing import Any
from urllib.parse import urlparse

import requests
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from flask import jsonify

from core.api_helpers import api_error
from core.base_agent import AnalyticalAgent, BaseAgent, CreativeAgent, SalesAgent
from mcp._safe_url import is_safe_url as _is_safe_url

logger = logging.getLogger(__name__)

# ── PII Redaction ────────────────────────────────────────────────────

_PII_PATTERNS = [
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'), '[EMAIL]'),
    (re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'), '[PHONE]'),
    (re.compile(r'\(\d{3}\)\s*\d{3}[-.]?\d{4}'), '[PHONE]'),
    (re.compile(r'\+\d{1,3}\s\d{3}[-.\s]?\d{3}[-.\s]?\d{4}'), '[PHONE]'),
    (re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'), '[CCARD]'),
    (re.compile(r'\b\d{4}[-\s]?\d{6}[-\s]?\d{5}\b'), '[CCARD]'),
    (re.compile(r'\b\d{4}[-\s]?\d{6}[-\s]?\d{4}\b'), '[CCARD]'),
]


class CorrelationIDFilter(logging.Filter):
    """Injects the current request correlation ID into each log record (as `request_id`).
    Only adds a new attribute — never mutates existing fields."""

    def filter(self, record):
        try:
            from flask import g as flask_g
            record.request_id = flask_g.request_id
        except Exception:
            record.request_id = ""
        return True


class PIIRedactFormatter(logging.Formatter):
    """Text formatter that PII-redacts the message without mutating the original LogRecord."""

    def format(self, record):
        copied = logging.LogRecord(
            record.name, record.levelno, record.pathname,
            record.lineno, record.msg, record.args,
            record.exc_info, record.funcName,
        )
        copied.__dict__.update(record.__dict__)
        copied.msg = record.msg
        copied.args = record.args
        redacted = copied.getMessage()
        for pattern, replacement in _PII_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        if copied.exc_text:
            for pattern, replacement in _PII_PATTERNS:
                copied.exc_text = pattern.sub(replacement, copied.exc_text)
        copied.msg = redacted
        copied.args = ()
        return super().format(copied)


class PIIRedactJSONFormatter(PIIRedactFormatter):
    """JSON log formatter — each line is a JSON object with timestamp, level, logger, request_id, message, etc.
    PII is redacted in the message field.  The original LogRecord is never mutated."""

    def format(self, record):
        copied = logging.LogRecord(
            record.name, record.levelno, record.pathname,
            record.lineno, record.msg, record.args,
            record.exc_info, record.funcName,
        )
        copied.__dict__.update(record.__dict__)
        copied.msg = record.msg
        copied.args = record.args
        redacted = copied.getMessage()
        for pattern, replacement in _PII_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        exc = ""
        if copied.exc_info and not copied.exc_text:
            copied.exc_text = self.formatException(copied.exc_info)
        if copied.exc_text:
            exc = copied.exc_text
            for pattern, replacement in _PII_PATTERNS:
                exc = pattern.sub(replacement, exc)
        import json, time
        from datetime import timezone
        entry = {
            "timestamp": self.formatTime(copied, self.datefmt),
            "level": copied.levelname,
            "logger": copied.name,
            "request_id": getattr(copied, "request_id", ""),
            "message": redacted,
            "module": copied.module,
            "function": copied.funcName,
            "line": copied.lineno,
        }
        if exc:
            entry["exception"] = exc
        if copied.process:
            entry["pid"] = copied.process
        return json.dumps(entry, ensure_ascii=False, default=str)


# ── Safe network / error / type helpers ──────────────────────────────

def safe_url(url: str, timeout: int = 10) -> requests.Response:
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


def safe_error(e: Exception, status: int = 500):
    logger.error("Internal error: %s", e, exc_info=True)
    return api_error("An internal error occurred.", status)


def safe_int(val, default=0):
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


# ── Warning filters ─────────────────────────────────────────────────

warnings.filterwarnings("ignore", module="langgraph")
warnings.filterwarnings("ignore", module="langchain")


# ── Agent definitions ───────────────────────────────────────────────

AGENT_CLASSES: dict[str, type] = {
    "local_seo": BaseAgent,
    "social_media": CreativeAgent,
    "lead_conversion": SalesAgent,
    "paid_ads": BaseAgent,
    "growth_hacker": CreativeAgent,
    "reputation": SalesAgent,
    "email_marketing": SalesAgent,
    "tiktok": CreativeAgent,
    "outreach": SalesAgent,
    "backlinks": AnalyticalAgent,
    "content_strategy": CreativeAgent,
    "technical_seo": AnalyticalAgent,
    "reporting": AnalyticalAgent,
    "cro": AnalyticalAgent,
    "video": CreativeAgent,
    "sms_marketing": SalesAgent,
}

# Per-agent temperature overrides (agents not listed use their class default)
AGENT_TEMPERATURES: dict[str, float] = {
    "paid_ads": 0.8,
    "local_seo": 0.6,
}

AGENTS_META = [
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
    ("video", "video.md", "Video Production", "YouTube scripts, explication videos, ad video scripts, video SEO, content series planning, thumbnail strategy"),
    ("sms_marketing", "sms_marketing.md", "SMS Marketing", "SMS campaign planning, sequence design, CASL compliance, concise copywriting, timing strategy, list segmentation"),
]

BASE_AGENT_CONFIG = {
    "enabled": True,
    "model": "deepseek-chat",
    "credentials": {"api_key": "", "api_base": "https://api.deepseek.com/v1"},
    "temperature": 0.7,
}


# ── Encryption helpers ──────────────────────────────────────────────

def derive_fernet_key() -> Fernet:
    secret = os.getenv("FLASK_SECRET_KEY", "").encode()
    salt_str = os.getenv("CREDENTIAL_SALT")
    if salt_str:
        salt = salt_str.encode()[:16].ljust(16, b'\0')
        kdf: Any = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100_000)
    else:
        kdf = HKDF(algorithm=hashes.SHA256(), length=32, info=b"laval-credential-encryption-v2", salt=None)
    key = _b64.urlsafe_b64encode(kdf.derive(secret))
    return Fernet(key)


def encrypt_credential(plaintext: str) -> str:
    from core.app_state import get_credential_cipher
    return get_credential_cipher().encrypt(plaintext.encode()).decode()


def decrypt_credential(ciphertext: str) -> str:
    from core.app_state import get_credential_cipher
    return get_credential_cipher().decrypt(ciphertext.encode()).decode()


# ── Public API routes (exempt from auth) ────────────────────────────

API_PUBLIC: set = {
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
    "/api/auth/install",
    "/api/auth/callback",
    "/api/webhooks",
    "/api/shopify/register-webhooks",
}