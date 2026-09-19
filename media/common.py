"""Shared speech plumbing: typed errors, provider selection, per-key locks, WAV helpers."""

from __future__ import annotations

import io
import logging
import math
import os
import threading
import wave
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Literal

import httpx
import numpy as np

log = logging.getLogger("polytale.media")

ProviderName = Literal["elevenlabs", "gemini"]
PROVIDER_CHOICES = ("auto", "elevenlabs", "gemini")


class SpeechError(Exception):
    """Base class for speech provider failures."""


class SpeechTimeout(SpeechError):
    """A provider call exceeded its explicit timeout."""


class SpeechProviderError(SpeechError):
    """A provider rejected the request, returned garbage, or is not configured."""


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def select_provider(env: Mapping[str, str] | None = None) -> ProviderName:
    """Resolve SPEECH_PROVIDER (auto|elevenlabs|gemini) against the configured keys.

    auto -> elevenlabs when ELEVENLABS_API_KEY is set, else gemini. A forced
    elevenlabs without a key degrades to gemini (logged) instead of failing every call.
    """
    values = _env(env)
    has_elevenlabs = bool(values.get("ELEVENLABS_API_KEY", "").strip())
    choice = values.get("SPEECH_PROVIDER", "auto").strip().lower() or "auto"
    if choice not in PROVIDER_CHOICES:
        log.warning("Unknown SPEECH_PROVIDER=%r; using auto", choice)
        choice = "auto"
    if choice == "gemini":
        return "gemini"
    if choice == "elevenlabs" and not has_elevenlabs:
        log.warning("SPEECH_PROVIDER=elevenlabs but ELEVENLABS_API_KEY is empty; using gemini")
    return "elevenlabs" if has_elevenlabs else "gemini"


def provider_chain(env: Mapping[str, str] | None = None) -> list[ProviderName]:
    """Providers to try in order: the selected one, then Gemini as runtime fallback."""
    values = _env(env)
    primary = select_provider(values)
    chain: list[ProviderName] = [primary]
    if primary == "elevenlabs" and values.get("GEMINI_API_KEY", "").strip():
        chain.append("gemini")
    return chain


def env_value(env: Mapping[str, str] | None, name: str, default: str) -> str:
    return _env(env).get(name, "").strip() or default


def classify_exception(exc: Exception, provider: str) -> SpeechError:
    """Map a transport/SDK exception to a typed speech error."""
    if isinstance(exc, SpeechError):
        return exc
    if isinstance(exc, httpx.TimeoutException) or "timed out" in str(exc).lower():
        return SpeechTimeout(f"{provider}: timed out ({type(exc).__name__})")
    return SpeechProviderError(f"{provider}: {type(exc).__name__}: {str(exc)[:300]}")


class KeyedLocks:
    """One lock per key so concurrent requests for the same key do the work once."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, tuple[threading.Lock, int]] = {}

    @contextmanager
    def hold(self, key: str) -> Iterator[None]:
        with self._guard:
            lock, users = self._locks.get(key, (threading.Lock(), 0))
            self._locks[key] = (lock, users + 1)
        try:
            with lock:
                yield
        finally:
            with self._guard:
                lock, users = self._locks[key]
                if users <= 1:
                    del self._locks[key]
                else:
                    self._locks[key] = (lock, users - 1)

    def __len__(self) -> int:
        with self._guard:
            return len(self._locks)


def pcm_to_wav(pcm: bytes, *, sample_rate: int, channels: int = 1, sample_width: int = 2) -> bytes:
    """Wrap raw little-endian PCM in a WAV container (drops a trailing partial frame)."""
    frame = channels * sample_width
    usable = len(pcm) - (len(pcm) % frame)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(sample_width)
        out.setframerate(sample_rate)
        out.writeframes(pcm[:usable])
    return buffer.getvalue()


def wav_loudest_frame_dbfs(audio: bytes) -> float | None:
    """Loudest 20 ms frame RMS of a 16-bit PCM WAV in dBFS (-inf when silent/empty).

    None when the payload is not a readable 16-bit WAV (caller must not gate on it).
    """
    try:
        with wave.open(io.BytesIO(audio), "rb") as src:
            if src.getsampwidth() != 2:
                return None
            frame = max(1, src.getframerate() // 50) * src.getnchannels()
            pcm = src.readframes(src.getnframes())
    except (wave.Error, EOFError):
        return None
    samples = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype="<i2").astype(np.float64)
    if samples.size == 0:
        return float("-inf")
    usable = samples.size - samples.size % frame
    frames = samples[:usable].reshape(-1, frame) if usable else samples.reshape(1, -1)
    rms = np.sqrt(np.mean((frames / 32768.0) ** 2, axis=1))
    peak = float(rms.max())
    return 20 * math.log10(peak) if peak > 0 else float("-inf")
