"""Speech providers (network): TTS in media.tts, STT in media.stt."""

from __future__ import annotations

from media.common import SpeechError, SpeechProviderError, SpeechTimeout, select_provider

__all__ = ["SpeechError", "SpeechProviderError", "SpeechTimeout", "speech_status"]


def speech_status() -> dict[str, str]:
    """Configured providers for /api/health (both sides share SPEECH_PROVIDER)."""
    provider = select_provider()
    return {"speech_provider": provider, "tts_provider": provider}
