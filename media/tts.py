"""Text-to-speech: ElevenLabs primary, Gemini fallback, sha256-keyed disk cache.

`synthesize()` is synchronous and thread-safe; call it from a worker thread in async code.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from media.common import (
    KeyedLocks,
    SpeechError,
    SpeechProviderError,
    SpeechTimeout,
    classify_exception,
    env_value,
    language_name,
    log,
    pcm_to_wav,
    provider_chain,
)

TTS_TIMEOUT_S = 20.0
CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "audio"
VARIANTS = ("normal", "slow")

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
DEFAULT_ELEVENLABS_TTS_MODEL = "eleven_multilingual_v2"
# "Sarah" (premade, available on every account): soft, young, clear female voice; with the
# multilingual models it reads Japanese with clean standard pronunciation.
# Override per NPC via voice.elevenlabs_voice_id or globally via ELEVENLABS_DEFAULT_VOICE_ID.
DEFAULT_ELEVENLABS_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
# Only these models accept `language_code`; others reject the request if it is sent.
ELEVENLABS_LANGUAGE_CODE_MODELS = frozenset({"eleven_turbo_v2_5", "eleven_flash_v2_5"})
ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"
ELEVENLABS_SLOW_SPEED = 0.8

DEFAULT_GEMINI_TTS_MODEL = "gemini-3.1-flash-tts-preview"
FALLBACK_GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_GEMINI_VOICE = "Kore"
DEFAULT_STYLE = "warm, clear, unhurried"
GEMINI_PCM_RATE = 24000

MIME_BY_EXT = {"mp3": "audio/mpeg", "wav": "audio/wav"}


@dataclass(frozen=True)
class AudioClip:
    path: Path
    mime: str
    provider: str
    cached: bool


class TTSProvider(Protocol):
    name: str
    model: str
    ext: str

    def voice_key(self, voice: Mapping[str, Any]) -> str: ...

    def synthesize(
        self, text: str, *, language: str, voice: Mapping[str, Any], variant: str
    ) -> bytes: ...


class ElevenLabsTTS:
    name = "elevenlabs"
    ext = "mp3"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_ELEVENLABS_TTS_MODEL,
        default_voice_id: str = DEFAULT_ELEVENLABS_VOICE_ID,
        http: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.default_voice_id = default_voice_id
        self.http = http or httpx.Client(timeout=httpx.Timeout(TTS_TIMEOUT_S, connect=5.0))

    def voice_key(self, voice: Mapping[str, Any]) -> str:
        return str(voice.get("elevenlabs_voice_id") or "").strip() or self.default_voice_id

    def synthesize(
        self, text: str, *, language: str, voice: Mapping[str, Any], variant: str
    ) -> bytes:
        body: dict[str, Any] = {"text": text, "model_id": self.model}
        if self.model in ELEVENLABS_LANGUAGE_CODE_MODELS:
            body["language_code"] = language.split("-")[0].lower()
        if variant == "slow":
            body["voice_settings"] = {"speed": ELEVENLABS_SLOW_SPEED}
        try:
            response = self.http.post(
                ELEVENLABS_TTS_URL.format(voice_id=self.voice_key(voice)),
                params={"output_format": ELEVENLABS_OUTPUT_FORMAT},
                headers={"xi-api-key": self.api_key, "accept": "audio/mpeg"},
                json=body,
                timeout=httpx.Timeout(TTS_TIMEOUT_S, connect=5.0),
            )
        except Exception as exc:
            raise classify_exception(exc, self.name) from exc
        if response.status_code != 200:
            raise SpeechProviderError(
                f"elevenlabs tts HTTP {response.status_code}: {response.text[:300]}"
            )
        if not response.content:
            raise SpeechProviderError("elevenlabs tts returned no audio")
        return response.content


def gemini_tts_prompt(text: str, *, language: str, style: str, variant: str) -> str:
    pace = (
        "slowly and very clearly, with a short pause between phrases"
        if variant == "slow"
        else "at a natural, unhurried pace"
    )
    return (
        f"Speak the transcript below in {language_name(language)}. Voice direction: {style}. "
        f"Use clear, natural, standard pronunciation that a beginner learner can follow, {pace}. "
        "Read the transcript verbatim: do not add, drop, translate, or explain anything, "
        "and do not read these instructions aloud.\n\n"
        f"TRANSCRIPT:\n{text}"
    )


def _pcm_rate(mime: str) -> int:
    match = re.search(r"rate=(\d+)", mime)
    return int(match.group(1)) if match else GEMINI_PCM_RATE


class GeminiTTS:
    name = "gemini"
    ext = "wav"

    def __init__(
        self,
        *,
        model: str = DEFAULT_GEMINI_TTS_MODEL,
        fallback_models: Sequence[str] = (FALLBACK_GEMINI_TTS_MODEL,),
        client: Any = None,
    ) -> None:
        self.model = model
        self.models = list(dict.fromkeys([model, *fallback_models]))
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from core.gemini import get_client

            self._client = get_client()
        return self._client

    def voice_key(self, voice: Mapping[str, Any]) -> str:
        name = str(voice.get("gemini_voice") or "").strip() or DEFAULT_GEMINI_VOICE
        style = str(voice.get("style") or "").strip() or DEFAULT_STYLE
        return f"{name}|{style}"

    def synthesize(
        self, text: str, *, language: str, voice: Mapping[str, Any], variant: str
    ) -> bytes:
        from google.genai import types

        voice_name, style = self.voice_key(voice).split("|", 1)
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                language_code=language,
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                ),
            ),
            http_options=types.HttpOptions(timeout=int(TTS_TIMEOUT_S * 1000)),
        )
        prompt = gemini_tts_prompt(text, language=language, style=style, variant=variant)
        errors: list[str] = []
        for model in self.models:
            try:
                response = self.client.models.generate_content(
                    model=model, contents=prompt, config=config
                )
                return _gemini_audio_to_wav(response)
            except Exception as exc:
                error = classify_exception(exc, f"gemini tts {model}")
                if isinstance(error, SpeechTimeout):
                    raise error from exc
                errors.append(str(error))
        raise SpeechProviderError(" | ".join(errors))


def _gemini_audio_to_wav(response: Any) -> bytes:
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            data = getattr(part, "inline_data", None)
            if data is None or not data.data:
                continue
            mime = (data.mime_type or "").lower()
            if "wav" in mime:
                return bytes(data.data)
            return pcm_to_wav(bytes(data.data), sample_rate=_pcm_rate(mime))
    raise SpeechProviderError("gemini tts returned no audio")


def cache_key(
    *, provider: str, model: str, voice: str, language: str, text: str, variant: str
) -> str:
    identity = json.dumps(
        [provider, model, voice, language, text, variant], ensure_ascii=False
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class TTSService:
    """Tries providers in order; each result is cached under its own provider's key."""

    def __init__(self, providers: Sequence[TTSProvider], cache_dir: Path = CACHE_DIR) -> None:
        if not providers:
            raise ValueError("TTSService needs at least one provider")
        self.providers = list(providers)
        self.cache_dir = cache_dir
        self._locks = KeyedLocks()

    def cache_path(
        self, provider: TTSProvider, text: str, *, language: str, voice: Mapping[str, Any],
        variant: str,
    ) -> Path:
        key = cache_key(
            provider=provider.name, model=provider.model, voice=provider.voice_key(voice),
            language=language, text=text, variant=variant,
        )
        return self.cache_dir / f"{key}.{provider.ext}"

    def synthesize(
        self, text: str, *, language: str, voice: Mapping[str, Any], variant: str = "normal"
    ) -> AudioClip:
        text = text.strip()
        if not text:
            raise ValueError("synthesize() needs non-empty text")
        if variant not in VARIANTS:
            raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")
        errors: list[SpeechError] = []
        for provider in self.providers:
            path = self.cache_path(provider, text, language=language, voice=voice, variant=variant)
            mime = MIME_BY_EXT[provider.ext]
            with self._locks.hold(path.name):
                if path.exists():
                    return AudioClip(path, mime, provider.name, cached=True)
                try:
                    audio = provider.synthesize(
                        text, language=language, voice=voice, variant=variant
                    )
                except SpeechError as exc:
                    log.warning("TTS provider %s failed: %s", provider.name, exc)
                    errors.append(exc)
                    continue
                _atomic_write(path, audio)
                if errors:
                    log.warning("TTS fell back to %s after: %s", provider.name, errors[-1])
                return AudioClip(path, mime, provider.name, cached=False)
        detail = " | ".join(str(error) for error in errors)
        if all(isinstance(error, SpeechTimeout) for error in errors):
            raise SpeechTimeout(detail)
        raise SpeechProviderError(detail)


def build_tts_service(
    env: Mapping[str, str] | None = None, *, cache_dir: Path = CACHE_DIR
) -> TTSService:
    values = os.environ if env is None else env
    providers: list[TTSProvider] = []
    for name in provider_chain(values):
        if name == "elevenlabs":
            providers.append(
                ElevenLabsTTS(
                    values["ELEVENLABS_API_KEY"].strip(),
                    model=env_value(values, "ELEVENLABS_TTS_MODEL", DEFAULT_ELEVENLABS_TTS_MODEL),
                    default_voice_id=env_value(
                        values, "ELEVENLABS_DEFAULT_VOICE_ID", DEFAULT_ELEVENLABS_VOICE_ID
                    ),
                )
            )
        else:
            providers.append(
                GeminiTTS(model=env_value(values, "GEMINI_TTS_MODEL", DEFAULT_GEMINI_TTS_MODEL))
            )
    return TTSService(providers, cache_dir=cache_dir)


_service: TTSService | None = None
_service_lock = threading.Lock()


def default_service() -> TTSService:
    """Process-wide service built from the environment on first use."""
    global _service
    with _service_lock:
        if _service is None:
            _service = build_tts_service()
        return _service


def synthesize(
    text: str, *, language: str, voice: Mapping[str, Any], variant: str = "normal"
) -> AudioClip:
    """Synthesize (or fetch from cache) one line. Raises SpeechTimeout / SpeechProviderError."""
    return default_service().synthesize(text, language=language, voice=voice, variant=variant)
