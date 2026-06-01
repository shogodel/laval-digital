"""Blueprint for speech-to-text and text-to-speech endpoints."""
import logging

import requests
from flask import Blueprint, request

from core.api_helpers import api_error, api_success
from core.app_state import get_speech_engine
from core.auth import admin_required

logger = logging.getLogger(__name__)
speech_bp = Blueprint("speech", __name__)


@speech_bp.route("/api/speech/settings", methods=["GET"])
@admin_required
def get_speech_settings():
    return api_success(get_speech_engine().get_public_settings())


@speech_bp.route("/api/speech/settings", methods=["PUT"])
@admin_required
def update_speech_settings():
    data = request.json
    if not data:
        return api_error("No data provided", 400)
    get_speech_engine().update_settings(data)
    return api_success(get_speech_engine().get_public_settings())


@speech_bp.route("/api/speech/stt", methods=["POST"])
@admin_required
def speech_to_text():
    if "audio" not in request.files:
        return api_error("No audio file provided", 400)

    audio_file = request.files["audio"]
    language = request.form.get("language", "en")

    try:
        text = get_speech_engine().transcribe(audio_file.read(), language)
        return api_success({"text": text, "language": language})
    except Exception as e:
        logger.error("Speech-to-text failed: %s", e)
        from core.app_state import safe_error
        return safe_error(e, 500)


@speech_bp.route("/api/speech/tts", methods=["POST"])
@admin_required
def text_to_speech():
    data = request.json
    if not data or not data.get("text"):
        return api_error("No text provided", 400)

    text = data["text"]
    language = data.get("language", "en")

    try:
        audio_bytes = get_speech_engine().synthesize(text, language)
        return (audio_bytes, 200, {"Content-Type": "audio/mpeg"})
    except Exception as e:
        logger.error("Text-to-speech failed: %s", e)
        from core.app_state import safe_error
        return safe_error(e, 500)


@speech_bp.route("/api/speech/voices", methods=["GET"])
@admin_required
def get_speech_voices():
    provider = get_speech_engine().get_settings().get("tts_provider", "browser")
    if provider == "openai":
        return api_success({"voices": ["alloy", "echo", "fable", "nova", "shimmer"]})
    elif provider == "elevenlabs":
        api_key = get_speech_engine().get_settings().get("elevenlabs_api_key", "")
        if not api_key:
            return api_success({"voices": []})
        try:
            resp = requests.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            voices = [{"id": v["voice_id"], "name": v["name"]} for v in resp.json().get("voices", [])]
            return api_success({"voices": voices})
        except Exception:
            logger.warning("Failed to fetch ElevenLabs voices", exc_info=True)
            return api_success({"voices": []})
    return api_success({"voices": []})
