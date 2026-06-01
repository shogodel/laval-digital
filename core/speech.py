import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_SPEECH_SETTINGS: dict[str, Any] = {
    "speech_enabled": False,
    "stt_provider": "browser",
    "tts_provider": "browser",
    "openai_api_key": "",
    "elevenlabs_api_key": "",
    "elevenlabs_voice_id": "21m00Tcm4TlvDq8ikWAM",
    "tts_voice": "alloy",
    "auto_speak": False,
}

OPENAI_TTS_VOICES = ["alloy", "echo", "fable", "nova", "shimmer"]
OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"
OPENAI_STT_URL = "https://api.openai.com/v1/audio/transcriptions"
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

LANG_TO_OPENAI_VOICE = {
    "fr": "nova",
    "en": "alloy",
}

LANG_TO_ELEVENLABS_VOICE = {
    "fr": "21m00Tcm4TlvDq8ikWAM",
    "en": "21m00Tcm4TlvDq8ikWAM",
}


class SpeechEngine:
    def __init__(self, settings: dict[str, Any] | None = None):
        self._settings = dict(DEFAULT_SPEECH_SETTINGS)
        if settings:
            self._settings.update(settings)

    @property
    def enabled(self) -> bool:
        return self._settings.get("speech_enabled", False)

    def update_settings(self, updates: dict[str, Any]) -> None:
        self._settings.update(updates)
        logger.debug("Speech settings updated: %s", list(updates))

    def get_settings(self) -> dict[str, Any]:
        return dict(self._settings)

    def get_public_settings(self) -> dict[str, Any]:
        public = dict(self._settings)
        public.pop("openai_api_key", None)
        public.pop("elevenlabs_api_key", None)
        return public

    def transcribe(self, audio_bytes: bytes, language: str = "en") -> str:
        provider = self._settings.get("stt_provider", "browser")
        if provider == "openai":
            return self._transcribe_openai(audio_bytes, language)
        raise ValueError(f"Unknown STT provider: '{provider}'. Supported: openai")

    def synthesize(self, text: str, language: str = "en") -> bytes:
        provider = self._settings.get("tts_provider", "browser")
        if provider == "openai":
            return self._synthesize_openai(text, language)
        elif provider == "elevenlabs":
            return self._synthesize_elevenlabs(text, language)
        raise ValueError(f"Unknown TTS provider: '{provider}'. Supported: openai, elevenlabs")

    def _transcribe_openai(self, audio_bytes: bytes, language: str) -> str:
        api_key = self._settings.get("openai_api_key", "")
        if not api_key:
            raise ValueError("OpenAI API key not configured for speech-to-text")

        files = {"file": ("audio.webm", audio_bytes, "audio/webm")}
        data = {"model": "whisper-1", "language": language}

        try:
            resp = requests.post(
                OPENAI_STT_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                data=data,
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()
            text = result.get("text", "").strip()
            logger.info("Whisper transcribed %d bytes in '%s'", len(audio_bytes), language)
            return text
        except requests.RequestException as e:
            logger.error("Whisper STT failed: %s", e)
            raise

    def _synthesize_openai(self, text: str, language: str) -> bytes:
        api_key = self._settings.get("openai_api_key", "")
        if not api_key:
            raise ValueError("OpenAI API key not configured for text-to-speech")

        voice = self._settings.get("tts_voice", "") or LANG_TO_OPENAI_VOICE.get(language, "alloy")

        try:
            resp = requests.post(
                OPENAI_TTS_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": "tts-1", "input": text, "voice": voice, "response_format": "mp3"},
                timeout=30,
            )
            resp.raise_for_status()
            logger.info("OpenAI TTS synthesized %d chars in '%s' (voice=%s)", len(text), language, voice)
            return resp.content
        except requests.RequestException as e:
            logger.error("OpenAI TTS failed: %s", e)
            raise

    def _synthesize_elevenlabs(self, text: str, language: str) -> bytes:
        api_key = self._settings.get("elevenlabs_api_key", "")
        if not api_key:
            raise ValueError("ElevenLabs API key not configured for text-to-speech")

        voice_id = (
            self._settings.get("elevenlabs_voice_id", "")
            or LANG_TO_ELEVENLABS_VOICE.get(language, "21m00Tcm4TlvDq8ikWAM")
        )

        # Validate voice_id to prevent path traversal/SSRF
        import re
        if not re.match(r'^[a-zA-Z0-9]{1,50}$', voice_id):
            raise ValueError("Invalid ElevenLabs voice_id format")

        try:
            resp = requests.post(
                ELEVENLABS_TTS_URL.format(voice_id=voice_id),
                headers={
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                    "xi-api-key": api_key,
                },
                json={"text": text, "model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
                timeout=30,
            )
            resp.raise_for_status()
            logger.info("ElevenLabs TTS synthesized %d chars in '%s'", len(text), language)
            return resp.content
        except requests.RequestException as e:
            logger.error("ElevenLabs TTS failed: %s", e)
            raise
