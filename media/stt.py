"""Speech-to-text: ElevenLabs Scribe primary, Gemini fallback. No forced language.

`transcribe()` is synchronous and thread-safe; call it from a worker thread in async code.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from media.common import (
    SpeechError,
    SpeechProviderError,
    SpeechTimeout,
    classify_exception,
    env_value,
    language_name,
    log,
    provider_chain,
    wav_loudest_frame_dbfs,
)

STT_TIMEOUT_S = 15.0
# Below this (or with no confidence at all) the client must confirm "Heard: ..." first.
CONFIRMATION_THRESHOLD = 0.6
# A WAV whose loudest 20 ms frame is quieter than this holds no speech: skip the provider.
# (Gemini hallucinates confident phrases on pure silence.) Normal speech peaks above -30 dBFS.
SILENCE_GATE_DBFS = -50.0

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
DEFAULT_ELEVENLABS_STT_MODEL = "scribe_v1"

DEFAULT_GEMINI_STT_MODEL = "gemini-3.5-flash"
DEFAULT_GEMINI_STT_FALLBACKS = "gemini-3.5-flash-lite"
DEFAULT_GEMINI_STT_THINKING = "minimal"

# ElevenLabs reports ISO 639-3; the rest of the app speaks ISO 639-1 / BCP-47 primaries.
ISO3_TO_ISO1 = {"jpn": "ja", "eng": "en", "kor": "ko", "cmn": "zh", "zho": "zh", "spa": "es",
                "fra": "fr", "deu": "de"}
_JAPANESE_SCRIPT = re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]")


@dataclass(frozen=True)
class TranscriptionResult:
    transcript: str
    romanized: str | None
    detected_languages: list[str] = field(default_factory=list)
    confidence: float | None = None
    provider: str = ""


def needs_confirmation(result: TranscriptionResult) -> bool:
    """True when the learner should confirm the transcript before it is acted on."""
    if not result.transcript.strip():
        return True
    return result.confidence is None or result.confidence < CONFIRMATION_THRESHOLD


class STTProvider(Protocol):
    name: str

    def transcribe(
        self, audio: bytes, mime: str, *, target_locale: str, support_locale: str
    ) -> TranscriptionResult: ...


def normalize_mime(mime: str) -> str:
    base = (mime or "").split(";")[0].strip().lower()
    return {"audio/x-wav": "audio/wav", "audio/wave": "audio/wav", "audio/vnd.wave": "audio/wav",
            "audio/mpeg": "audio/mp3", "audio/x-m4a": "audio/mp4"}.get(base, base or "audio/wav")


def _languages(codes: Sequence[str], transcript: str) -> list[str]:
    out: list[str] = []
    for code in codes:
        base = str(code).strip().lower().replace("_", "-").split("-")[0]
        base = ISO3_TO_ISO1.get(base, base)
        if base and base not in out:
            out.append(base)
    if _JAPANESE_SCRIPT.search(transcript) and "ja" not in out:
        out.append("ja")
    return out


def _clamp01(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return min(1.0, max(0.0, number))


class ElevenLabsSTT:
    name = "elevenlabs"

    def __init__(
        self, api_key: str, *, model: str = DEFAULT_ELEVENLABS_STT_MODEL,
        http: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.http = http or httpx.Client(timeout=httpx.Timeout(STT_TIMEOUT_S, connect=5.0))

    def transcribe(
        self, audio: bytes, mime: str, *, target_locale: str, support_locale: str
    ) -> TranscriptionResult:
        # language_code is deliberately NOT sent: code-switched attempts must survive.
        extension = normalize_mime(mime).split("/")[-1]
        try:
            response = self.http.post(
                ELEVENLABS_STT_URL,
                headers={"xi-api-key": self.api_key},
                data={"model_id": self.model, "tag_audio_events": "false", "diarize": "false"},
                files={"file": (f"attempt.{extension}", audio, mime or "audio/wav")},
                timeout=httpx.Timeout(STT_TIMEOUT_S, connect=5.0),
            )
        except Exception as exc:
            raise classify_exception(exc, self.name) from exc
        if response.status_code != 200:
            raise SpeechProviderError(
                f"elevenlabs stt HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SpeechProviderError("elevenlabs stt returned non-JSON") from exc
        transcript = str(payload.get("text") or "").strip()
        code = payload.get("language_code")
        return TranscriptionResult(
            transcript=transcript,
            romanized=None,
            detected_languages=_languages([code] if code and transcript else [], transcript),
            confidence=elevenlabs_confidence(payload) if transcript else None,
            provider=self.name,
        )


def elevenlabs_confidence(payload: Mapping[str, Any]) -> float | None:
    """Mean word probability from logprobs when present, else language_probability."""
    probs = [
        math.exp(float(word["logprob"]))
        for word in payload.get("words") or []
        if word.get("type", "word") == "word" and isinstance(word.get("logprob"), (int, float))
    ]
    if probs:
        return _clamp01(sum(probs) / len(probs))
    return _clamp01(payload.get("language_probability"))


GEMINI_STT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "transcript": {"type": "string"},
        "romanized": {"type": "string"},
        "languages": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["transcript", "romanized", "languages", "confidence"],
}


def gemini_stt_prompt(*, target_locale: str, support_locale: str) -> str:
    target = language_name(target_locale)
    support = language_name(support_locale)
    return (
        "You are the speech recognizer for a voice-first language-learning game. The speaker is "
        f"an absolute beginner in {target} whose own language is {support}. They may speak "
        f"{target}, {support}, or a mix of both in one utterance.\n"
        "Transcribe the audio VERBATIM:\n"
        f"- Keep mixed {support} and {target} exactly as spoken, in the order spoken. "
        "Never translate.\n"
        f"- Write words that are clearly {target} in normal {target} script "
        "(e.g. 鍵をください); write "
        f"{support} words in {support}.\n"
        "- Never correct grammar, word choice, particles, or pronunciation. Do not complete or "
        "tidy unfinished phrases. Transcribe what was said, not what was meant.\n"
        "- romanized: the whole utterance in lower-case Hepburn romaji, with "
        f"{support} words left as spoken (e.g. \"kagi o kudasai\", \"key... kudasai\").\n"
        "- languages: ISO 639-1 codes of the languages actually heard, e.g. [\"ja\"] or "
        "[\"en\", \"ja\"].\n"
        "- confidence: 0 to 1, how sure you are that the transcript matches the audio.\n"
        "- Never guess. If there is no clear human speech (silence, breathing, background "
        "noise, or unintelligible sounds), return an empty transcript, empty romanized, "
        "empty languages, and confidence 0."
    )


class GeminiSTT:
    name = "gemini"

    def __init__(
        self, *, model: str = DEFAULT_GEMINI_STT_MODEL,
        fallback_models: Sequence[str] = (DEFAULT_GEMINI_STT_FALLBACKS,),
        thinking_level: str = DEFAULT_GEMINI_STT_THINKING, client: Any = None,
    ) -> None:
        self.model = model
        self.models = list(dict.fromkeys(m for m in [model, *fallback_models] if m))
        self.thinking_level = thinking_level
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from core.gemini import get_client

            self._client = get_client()
        return self._client

    def transcribe(
        self, audio: bytes, mime: str, *, target_locale: str, support_locale: str
    ) -> TranscriptionResult:
        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=GEMINI_STT_SCHEMA,
            temperature=0,
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(self.thinking_level.upper())
            ),
            http_options=types.HttpOptions(timeout=int(STT_TIMEOUT_S * 1000)),
        )
        contents = [
            types.Part.from_bytes(data=audio, mime_type=normalize_mime(mime)),
            gemini_stt_prompt(target_locale=target_locale, support_locale=support_locale),
        ]
        errors: list[str] = []
        for model in self.models:
            try:
                response = self.client.models.generate_content(
                    model=model, contents=contents, config=config
                )
                return self._parse(response.text or "")
            except Exception as exc:
                error = classify_exception(exc, f"gemini stt {model}")
                if isinstance(error, SpeechTimeout):
                    raise error from exc
                errors.append(str(error))
        raise SpeechProviderError(" | ".join(errors))

    def _parse(self, text: str) -> TranscriptionResult:
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise SpeechProviderError(f"gemini stt returned non-JSON: {text[:200]!r}") from exc
        if not isinstance(payload, dict):
            raise SpeechProviderError("gemini stt returned a non-object")
        transcript = str(payload.get("transcript") or "").strip()
        romanized = str(payload.get("romanized") or "").strip()
        return TranscriptionResult(
            transcript=transcript,
            romanized=(romanized or None) if transcript else None,
            detected_languages=(
                _languages(payload.get("languages") or [], transcript) if transcript else []
            ),
            confidence=_clamp01(payload.get("confidence")) if transcript else None,
            provider=self.name,
        )


def is_empty_audio(audio: bytes, mime: str) -> bool:
    """No bytes, or a WAV with no frame above the silence gate."""
    if not audio:
        return True
    if normalize_mime(mime) == "audio/wav":
        level = wav_loudest_frame_dbfs(audio)
        return level is not None and level < SILENCE_GATE_DBFS
    return False


class STTService:
    """Tries providers in order; ElevenLabs failures fall back to Gemini."""

    def __init__(self, providers: Sequence[STTProvider]) -> None:
        if not providers:
            raise ValueError("STTService needs at least one provider")
        self.providers = list(providers)

    def transcribe(
        self, audio: bytes, mime: str, *, target_locale: str, support_locale: str
    ) -> TranscriptionResult:
        if is_empty_audio(audio, mime):
            return TranscriptionResult("", None, [], None, self.providers[0].name)
        errors: list[SpeechError] = []
        for provider in self.providers:
            try:
                result = provider.transcribe(
                    audio, mime, target_locale=target_locale, support_locale=support_locale
                )
            except SpeechError as exc:
                log.warning("STT provider %s failed: %s", provider.name, exc)
                errors.append(exc)
                continue
            if errors:
                log.warning("STT fell back to %s after: %s", provider.name, errors[-1])
            return result
        detail = " | ".join(str(error) for error in errors)
        if all(isinstance(error, SpeechTimeout) for error in errors):
            raise SpeechTimeout(detail)
        raise SpeechProviderError(detail)


def build_stt_service(env: Mapping[str, str] | None = None) -> STTService:
    values = os.environ if env is None else env
    providers: list[STTProvider] = []
    for name in provider_chain(values):
        if name == "elevenlabs":
            providers.append(
                ElevenLabsSTT(
                    values["ELEVENLABS_API_KEY"].strip(),
                    model=env_value(values, "ELEVENLABS_STT_MODEL", DEFAULT_ELEVENLABS_STT_MODEL),
                )
            )
        else:
            fallbacks = env_value(values, "GEMINI_STT_FALLBACKS", DEFAULT_GEMINI_STT_FALLBACKS)
            providers.append(
                GeminiSTT(
                    model=env_value(values, "GEMINI_STT_MODEL", DEFAULT_GEMINI_STT_MODEL),
                    fallback_models=[m.strip() for m in fallbacks.split(",") if m.strip()],
                    thinking_level=env_value(
                        values, "GEMINI_STT_THINKING_LEVEL", DEFAULT_GEMINI_STT_THINKING
                    ),
                )
            )
    return STTService(providers)


_service: STTService | None = None
_service_lock = threading.Lock()


def default_service() -> STTService:
    """Process-wide service built from the environment on first use."""
    global _service
    with _service_lock:
        if _service is None:
            _service = build_stt_service()
        return _service


def transcribe(
    audio: bytes, mime: str, *, target_locale: str, support_locale: str
) -> TranscriptionResult:
    """Transcribe one learner attempt. Raises SpeechTimeout / SpeechProviderError."""
    return default_service().transcribe(
        audio, mime, target_locale=target_locale, support_locale=support_locale
    )
