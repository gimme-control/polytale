"""Offline tests for media/ speech providers (stubbed HTTP + fake Gemini client).

Run: cd polytale && PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/test_speech_providers.py
"""

from __future__ import annotations

import io
import json
import math
import os
import struct
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

import media
from media.common import KeyedLocks, SpeechProviderError, SpeechTimeout, pcm_to_wav, provider_chain
from media.common import select_provider, wav_loudest_frame_dbfs
from media.stt import (
    CONFIRMATION_THRESHOLD,
    SILENCE_GATE_DBFS,
    ElevenLabsSTT,
    GeminiSTT,
    STTService,
    TranscriptionResult,
    build_stt_service,
    needs_confirmation,
)
from media.tts import (
    DEFAULT_ELEVENLABS_VOICE_ID,
    ElevenLabsTTS,
    GeminiTTS,
    TTSService,
    build_tts_service,
    cache_key,
)

FAILURES: list[str] = []
VOICE = {"elevenlabs_voice_id": "voice123", "gemini_voice": "Kore", "style": "warm, clear"}


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'} {name}{'' if condition else ' :: ' + detail}")
    if not condition:
        FAILURES.append(name)


def raises(fn: Any, exc_type: type[BaseException]) -> bool:
    try:
        fn()
    except exc_type:
        return True
    except Exception as exc:  # wrong type
        print(f"   (raised {type(exc).__name__}: {exc})")
        return False
    return False


# ---------------------------------------------------------------- fakes


class FakeTTS:
    def __init__(self, name: str = "fake", *, delay: float = 0.0, error: Exception | None = None):
        self.name = name
        self.model = "fake-model"
        self.ext = "wav"
        self.calls = 0
        self.delay = delay
        self.error = error
        self._lock = threading.Lock()

    def voice_key(self, voice: Any) -> str:
        return str(voice.get("gemini_voice") or "")

    def synthesize(self, text: str, *, language: str, voice: Any, variant: str) -> bytes:
        with self._lock:
            self.calls += 1
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return pcm_to_wav(b"\x00\x01" * 100, sample_rate=24000)


def fake_audio_response(pcm: bytes, mime: str = "audio/l16; rate=24000; channels=1") -> Any:
    part = SimpleNamespace(inline_data=SimpleNamespace(data=pcm, mime_type=mime))
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])


class FakeGeminiClient:
    """Mimics client.models.generate_content; `script` is a list of results or exceptions."""

    def __init__(self, script: list[Any]):
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.models = self

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item


def tone_wav(dbfs: float, seconds: float = 0.5, rate: int = 16000) -> bytes:
    """440 Hz sine whose RMS is `dbfs`."""
    amplitude = math.sqrt(2) * 10 ** (dbfs / 20)
    n = int(seconds * rate)
    samples = [int(32767 * amplitude * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n)]
    return pcm_to_wav(struct.pack(f"<{n}h", *samples), sample_rate=rate)


def mock_http(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------- tests


def test_selection() -> None:
    matrix = [
        ({"SPEECH_PROVIDER": "auto", "ELEVENLABS_API_KEY": "k"}, "elevenlabs"),
        ({"SPEECH_PROVIDER": "auto", "ELEVENLABS_API_KEY": ""}, "gemini"),
        ({}, "gemini"),
        ({"ELEVENLABS_API_KEY": "k"}, "elevenlabs"),
        ({"SPEECH_PROVIDER": "elevenlabs", "ELEVENLABS_API_KEY": "k"}, "elevenlabs"),
        ({"SPEECH_PROVIDER": "elevenlabs"}, "gemini"),
        ({"SPEECH_PROVIDER": "gemini", "ELEVENLABS_API_KEY": "k"}, "gemini"),
        ({"SPEECH_PROVIDER": "GEMINI"}, "gemini"),
        ({"SPEECH_PROVIDER": "bogus", "ELEVENLABS_API_KEY": "k"}, "elevenlabs"),
        ({"SPEECH_PROVIDER": "auto", "ELEVENLABS_API_KEY": "   "}, "gemini"),
    ]
    for env, expected in matrix:
        got = select_provider(env)
        check(f"select_provider {env} -> {expected}", got == expected, got)

    both = {"ELEVENLABS_API_KEY": "k", "GEMINI_API_KEY": "g"}
    check("chain auto+both keys = elevenlabs,gemini",
          provider_chain(both) == ["elevenlabs", "gemini"], str(provider_chain(both)))
    check("chain elevenlabs without gemini key = elevenlabs only",
          provider_chain({"ELEVENLABS_API_KEY": "k"}) == ["elevenlabs"])
    check("chain forced gemini = gemini only",
          provider_chain({**both, "SPEECH_PROVIDER": "gemini"}) == ["gemini"])

    with tempfile.TemporaryDirectory() as tmp:
        tts = build_tts_service({**both, "ELEVENLABS_TTS_MODEL": "eleven_flash_v2_5"},
                                cache_dir=Path(tmp))
    check("build_tts_service chain", [p.name for p in tts.providers] == ["elevenlabs", "gemini"])
    check("build_tts_service honours ELEVENLABS_TTS_MODEL",
          tts.providers[0].model == "eleven_flash_v2_5")
    stt = build_stt_service({"GEMINI_API_KEY": "g", "GEMINI_STT_MODEL": "m1",
                             "GEMINI_STT_FALLBACKS": "m2, m3"})
    gem = stt.providers[0]
    check("build_stt_service gemini models from env",
          isinstance(gem, GeminiSTT) and gem.models == ["m1", "m2", "m3"])

    saved = {k: os.environ.get(k) for k in ("SPEECH_PROVIDER", "ELEVENLABS_API_KEY")}
    try:
        os.environ["SPEECH_PROVIDER"] = "auto"
        os.environ["ELEVENLABS_API_KEY"] = ""
        status = media.speech_status()
        check("speech_status shape",
              status == {"speech_provider": "gemini", "tts_provider": "gemini"}, str(status))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_cache_key() -> None:
    base = dict(provider="gemini", model="m", voice="Kore", language="ja-JP", text="鍵。",
                variant="normal")
    key = cache_key(**base)
    check("cache_key deterministic", key == cache_key(**base))
    check("cache_key is sha256 hex", len(key) == 64 and all(c in "0123456789abcdef" for c in key))
    for field, other in [("provider", "elevenlabs"), ("model", "m2"), ("voice", "Puck"),
                         ("language", "en-US"), ("text", "地図。"), ("variant", "slow")]:
        check(f"cache_key changes with {field}", cache_key(**{**base, field: other}) != key)


def test_cache_and_dedupe() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        provider = FakeTTS()
        service = TTSService([provider], cache_dir=Path(tmp))
        first = service.synthesize("鍵。", language="ja-JP", voice=VOICE)
        second = service.synthesize("鍵。", language="ja-JP", voice=VOICE)
        check("first synth not cached", first.cached is False and first.path.exists())
        check("second synth cached, provider not called again",
              second.cached is True and provider.calls == 1 and second.path == first.path)
        check("AudioClip mime/provider", first.mime == "audio/wav" and first.provider == "fake")
        slow = service.synthesize("鍵。", language="ja-JP", voice=VOICE, variant="slow")
        check("slow variant is a separate cache entry",
              slow.path != first.path and provider.calls == 2)
        other_voice = service.synthesize("鍵。", language="ja-JP", voice={"gemini_voice": "Puck"})
        check("voice change misses cache", other_voice.path != first.path and provider.calls == 3)
        leftovers = [p.name for p in Path(tmp).iterdir() if p.suffix == ".tmp"]
        check("atomic write leaves no temp files", not leftovers, str(leftovers))
        check("empty text rejected",
              raises(lambda: service.synthesize("  ", language="ja-JP", voice=VOICE), ValueError))
        check("unknown variant rejected",
              raises(lambda: service.synthesize("鍵", language="ja-JP", voice=VOICE,
                                                variant="fast"), ValueError))

    with tempfile.TemporaryDirectory() as tmp:
        provider = FakeTTS(delay=0.2)
        service = TTSService([provider], cache_dir=Path(tmp))
        results: list[Any] = []

        def worker() -> None:
            results.append(service.synthesize("地図。", language="ja-JP", voice=VOICE))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        check("per-key lock: 8 concurrent requests synthesize once", provider.calls == 1,
              f"calls={provider.calls}")
        check("per-key lock: exactly one uncached result",
              sum(1 for r in results if not r.cached) == 1 and len(results) == 8)
        check("per-key lock table drained", len(service._locks) == 0)

    locks = KeyedLocks()
    order: list[str] = []

    def hold(key: str, tag: str) -> None:
        with locks.hold(key):
            order.append(f"{tag}+")
            time.sleep(0.1)
            order.append(f"{tag}-")

    a = threading.Thread(target=hold, args=("a", "A"))
    b = threading.Thread(target=hold, args=("b", "B"))
    a.start()
    time.sleep(0.02)
    b.start()
    a.join()
    b.join()
    check("different keys do not serialize", order[:2] == ["A+", "B+"], str(order))


def test_wav_wrapping() -> None:
    pcm = bytes(range(256)) * 18 + b"\x07"  # 4609 bytes: odd -> trailing half-frame dropped
    wav_bytes = pcm_to_wav(pcm, sample_rate=24000)
    check("WAV header RIFF/WAVE", wav_bytes[:4] == b"RIFF" and wav_bytes[8:12] == b"WAVE")
    with wave.open(io.BytesIO(wav_bytes)) as src:
        ok = (src.getnchannels(), src.getsampwidth(), src.getframerate(), src.getnframes())
        frames = src.readframes(src.getnframes())
    check("WAV params mono/16-bit/24k/2304 frames", ok == (1, 2, 24000, 2304), str(ok))
    check("WAV total length = 44 + data", len(wav_bytes) == 44 + 4608, str(len(wav_bytes)))
    check("WAV payload preserved", frames == pcm[:4608])

    client = FakeGeminiClient([fake_audio_response(b"\x01\x00" * 2400, "audio/L16;codec=pcm;rate=16000")])
    audio = GeminiTTS(client=client).synthesize("鍵。", language="ja-JP", voice=VOICE,
                                                variant="normal")
    with wave.open(io.BytesIO(audio)) as src:
        check("GeminiTTS wraps PCM using rate from mime", src.getframerate() == 16000
              and src.getnframes() == 2400)
    call = client.calls[0]
    speech = call["config"].speech_config
    check("GeminiTTS uses voice + language",
          speech.voice_config.prebuilt_voice_config.voice_name == "Kore"
          and speech.language_code == "ja-JP")
    check("GeminiTTS prompt carries text + style + verbatim rule",
          "鍵。" in call["contents"] and "warm, clear" in call["contents"]
          and "verbatim" in call["contents"])
    check("GeminiTTS explicit 20 s timeout", call["config"].http_options.timeout == 20000)

    client = FakeGeminiClient([RuntimeError("404 not found"),
                               fake_audio_response(b"\x00\x00" * 10)])
    GeminiTTS(client=client).synthesize("鍵", language="ja-JP", voice={}, variant="normal")
    check("GeminiTTS falls back to 2.5 TTS model",
          [c["model"] for c in client.calls]
          == ["gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"])

    client = FakeGeminiClient([httpx.ReadTimeout("slow")])
    check("GeminiTTS timeout -> SpeechTimeout (no second model)",
          raises(lambda: GeminiTTS(client=client).synthesize(
              "鍵", language="ja-JP", voice={}, variant="normal"), SpeechTimeout)
          and len(client.calls) == 1)
    empty = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]))])
    check("GeminiTTS no audio -> SpeechProviderError",
          raises(lambda: GeminiTTS(client=FakeGeminiClient([empty])).synthesize(
              "鍵", language="ja-JP", voice={}, variant="normal"), SpeechProviderError))


def test_elevenlabs_tts_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"ID3fake-mp3")

    tts = ElevenLabsTTS("secret", http=mock_http(handler))
    audio = tts.synthesize("鍵。", language="ja-JP", voice=VOICE, variant="normal")
    req = seen[-1]
    body = json.loads(req.content)
    check("EL TTS url + voice id",
          req.url.path == "/v1/text-to-speech/voice123" and req.url.host == "api.elevenlabs.io")
    check("EL TTS POST + xi-api-key header",
          req.method == "POST" and req.headers["xi-api-key"] == "secret")
    check("EL TTS mp3 output format", req.url.params.get("output_format") == "mp3_44100_128")
    check("EL TTS body text/model", body["text"] == "鍵。"
          and body["model_id"] == "eleven_multilingual_v2")
    check("EL TTS no language_code for multilingual_v2", "language_code" not in body)
    check("EL TTS returns audio bytes", audio == b"ID3fake-mp3")

    ElevenLabsTTS("secret", model="eleven_flash_v2_5", http=mock_http(handler)).synthesize(
        "鍵。", language="ja-JP", voice={"elevenlabs_voice_id": ""}, variant="slow")
    req = seen[-1]
    body = json.loads(req.content)
    check("EL TTS language_code=ja for flash_v2_5", body.get("language_code") == "ja")
    check("EL TTS empty voice id -> default voice",
          req.url.path == f"/v1/text-to-speech/{DEFAULT_ELEVENLABS_VOICE_ID}")
    check("EL TTS slow variant sets speed", body.get("voice_settings", {}).get("speed") == 0.8)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    check("EL TTS timeout -> SpeechTimeout", raises(
        lambda: ElevenLabsTTS("k", http=mock_http(boom)).synthesize(
            "鍵", language="ja-JP", voice=VOICE, variant="normal"), SpeechTimeout))
    check("EL TTS 401 -> SpeechProviderError", raises(
        lambda: ElevenLabsTTS("k", http=mock_http(lambda r: httpx.Response(401, text="bad key")))
        .synthesize("鍵", language="ja-JP", voice=VOICE, variant="normal"), SpeechProviderError))


def test_tts_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        el = ElevenLabsTTS("k", http=mock_http(lambda r: httpx.Response(500, text="down")))
        gemini = FakeTTS("gemini")
        service = TTSService([el, gemini], cache_dir=Path(tmp))
        clip = service.synthesize("鍵。", language="ja-JP", voice=VOICE)
        check("EL TTS failure -> Gemini fallback", clip.provider == "gemini" and gemini.calls == 1)

        slow_a, slow_b = FakeTTS("a", error=SpeechTimeout("a")), FakeTTS("b", error=SpeechTimeout("b"))
        check("all providers time out -> SpeechTimeout", raises(
            lambda: TTSService([slow_a, slow_b], cache_dir=Path(tmp)).synthesize(
                "x", language="ja-JP", voice=VOICE), SpeechTimeout))
        mixed = [FakeTTS("a", error=SpeechTimeout("a")), FakeTTS("b", error=SpeechProviderError("b"))]
        check("mixed failures -> SpeechProviderError", raises(
            lambda: TTSService(mixed, cache_dir=Path(tmp)).synthesize(
                "x", language="ja-JP", voice=VOICE), SpeechProviderError))


def test_elevenlabs_stt_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={
            "language_code": "jpn", "language_probability": 0.42, "text": "鍵をください",
            "words": [{"text": "鍵を", "type": "word", "logprob": -0.05},
                      {"text": " ", "type": "spacing", "logprob": -3.0},
                      {"text": "ください", "type": "word", "logprob": -0.15}],
        })

    stt = ElevenLabsSTT("secret", http=mock_http(handler))
    result = stt.transcribe(b"RIFFfake", "audio/wav", target_locale="ja-JP", support_locale="en-US")
    req = seen[-1]
    body = req.content.decode("latin-1")
    check("EL STT url + POST + header", str(req.url) == "https://api.elevenlabs.io/v1/speech-to-text"
          and req.method == "POST" and req.headers["xi-api-key"] == "secret")
    check("EL STT multipart with model_id scribe_v1",
          "multipart/form-data" in req.headers["content-type"]
          and 'name="model_id"' in body and "scribe_v1" in body and 'name="file"' in body)
    check("EL STT does NOT force language", "language_code" not in body)
    expected = (0.951229 + 0.860708) / 2
    check("EL STT confidence from word logprobs (spacing ignored)",
          result.confidence is not None and abs(result.confidence - expected) < 1e-4,
          str(result.confidence))
    check("EL STT languages normalized jpn->ja", result.detected_languages == ["ja"])
    check("EL STT transcript/provider", result.transcript == "鍵をください"
          and result.provider == "elevenlabs" and result.romanized is None)

    lp = ElevenLabsSTT("k", http=mock_http(lambda r: httpx.Response(200, json={
        "language_code": "eng", "language_probability": 0.8, "text": "key kudasai", "words": []})))
    res = lp.transcribe(b"x", "audio/webm", target_locale="ja-JP", support_locale="en-US")
    check("EL STT confidence falls back to language_probability", res.confidence == 0.8
          and res.detected_languages == ["en"])

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out", request=request)

    check("EL STT timeout -> SpeechTimeout", raises(
        lambda: ElevenLabsSTT("k", http=mock_http(boom)).transcribe(
            b"x", "audio/wav", target_locale="ja-JP", support_locale="en-US"), SpeechTimeout))


class FakeSTT:
    def __init__(self, name: str, result: TranscriptionResult | None = None,
                 error: Exception | None = None):
        self.name = name
        self.result = result
        self.error = error
        self.calls = 0

    def transcribe(self, audio: bytes, mime: str, *, target_locale: str,
                   support_locale: str) -> TranscriptionResult:
        self.calls += 1
        if self.error:
            raise self.error
        assert self.result is not None
        return self.result


def test_stt_service() -> None:
    el = ElevenLabsSTT("k", http=mock_http(lambda r: httpx.Response(503, text="busy")))
    gem = FakeSTT("gemini", TranscriptionResult("鍵をください", "kagi o kudasai", ["ja"], 0.9, "gemini"))
    wav = tone_wav(-18.0)
    result = STTService([el, gem]).transcribe(wav, "audio/wav", target_locale="ja-JP",
                                             support_locale="en-US")
    check("EL STT failure -> Gemini fallback", result.provider == "gemini" and gem.calls == 1)

    spy = FakeSTT("gemini", TranscriptionResult("x", None, [], 1.0, "gemini"))
    service = STTService([spy])
    for label, audio, mime in [("b''", b"", "audio/wav"),
                               ("0-frame wav", pcm_to_wav(b"", sample_rate=16000), "audio/wav"),
                               ("digital silence", pcm_to_wav(b"\x00" * 32000, sample_rate=16000),
                                "audio/wav"),
                               ("-60 dBFS hiss", tone_wav(-60.0), "audio/x-wav"),
                               ("b'' webm", b"", "audio/webm")]:
        res = service.transcribe(audio, mime, target_locale="ja-JP", support_locale="en-US")
        check(f"empty/silent audio ({label}) -> empty result, no provider call",
              res.transcript == "" and res.confidence is None and spy.calls == 0
              and needs_confirmation(res))
    check("SILENCE_GATE_DBFS is -50", SILENCE_GATE_DBFS == -50.0)
    level = wav_loudest_frame_dbfs(tone_wav(-18.0))
    check("loudest-frame level of a -18 dBFS tone", level is not None and abs(level + 18) < 0.2,
          str(level))
    check("non-WAV bytes are not gated", wav_loudest_frame_dbfs(b"OggS....") is None)
    for label, audio, mime in [("-40 dBFS quiet speech", tone_wav(-40.0), "audio/wav"),
                               ("webm bytes", b"\x1aE\xdf\xa3webm", "audio/webm")]:
        service.transcribe(audio, mime, target_locale="ja-JP", support_locale="en-US")
    check("audible WAV and non-WAV audio reach the provider", spy.calls == 2, str(spy.calls))

    timeouts = [FakeSTT("a", error=SpeechTimeout("a")), FakeSTT("b", error=SpeechTimeout("b"))]
    check("STT all timeouts -> SpeechTimeout", raises(lambda: STTService(timeouts).transcribe(
        wav, "audio/wav", target_locale="ja-JP", support_locale="en-US"), SpeechTimeout))


def test_gemini_stt() -> None:
    ok = SimpleNamespace(text=json.dumps({"transcript": "key... ください",
                                          "romanized": "key... kudasai",
                                          "languages": ["en", "ja-JP"], "confidence": 0.83}))
    client = FakeGeminiClient([ok])
    stt = GeminiSTT(client=client)
    res = stt.transcribe(b"RIFF....", "audio/wav;codecs=1", target_locale="ja-JP",
                         support_locale="en-US")
    call = client.calls[0]
    part, prompt = call["contents"]
    check("GeminiSTT inline audio + normalized mime", part.inline_data.mime_type == "audio/wav"
          and part.inline_data.data == b"RIFF....")
    check("GeminiSTT prompt: verbatim, no correction, mixed kept",
          "VERBATIM" in prompt and "Never correct" in prompt and "Hepburn" in prompt
          and "鍵をください" in prompt)
    cfg = call["config"]
    check("GeminiSTT JSON schema + minimal thinking + 15 s timeout",
          cfg.response_mime_type == "application/json"
          and set(cfg.response_json_schema["required"])
          == {"transcript", "romanized", "languages", "confidence"}
          and str(cfg.thinking_config.thinking_level).endswith("MINIMAL")
          and cfg.http_options.timeout == 15000)
    check("GeminiSTT parse keeps mix", res.transcript == "key... ください"
          and res.romanized == "key... kudasai" and res.detected_languages == ["en", "ja"]
          and res.confidence == 0.83 and res.provider == "gemini")

    silence = SimpleNamespace(text=json.dumps({"transcript": "", "romanized": "", "languages": [],
                                               "confidence": 0}))
    res = GeminiSTT(client=FakeGeminiClient([silence])).transcribe(
        b"x", "audio/wav", target_locale="ja-JP", support_locale="en-US")
    check("GeminiSTT silence -> empty, confidence None", res.transcript == ""
          and res.confidence is None and res.romanized is None and needs_confirmation(res))

    client = FakeGeminiClient([SimpleNamespace(text="not json"), ok])
    res = GeminiSTT(client=client).transcribe(b"x", "audio/mpeg", target_locale="ja-JP",
                                              support_locale="en-US")
    check("GeminiSTT bad JSON -> next model",
          res.transcript == "key... ください"
          and [c["model"] for c in client.calls] == ["gemini-3.5-flash", "gemini-3.5-flash-lite"]
          and client.calls[0]["contents"][0].inline_data.mime_type == "audio/mp3")

    client = FakeGeminiClient([RuntimeError("request timed out")])
    check("GeminiSTT timeout -> SpeechTimeout", raises(lambda: GeminiSTT(client=client).transcribe(
        b"x", "audio/wav", target_locale="ja-JP", support_locale="en-US"), SpeechTimeout)
        and len(client.calls) == 1)


def test_confirmation_policy() -> None:
    def r(transcript: str, confidence: float | None) -> TranscriptionResult:
        return TranscriptionResult(transcript, None, [], confidence, "x")

    check("threshold constant is 0.6", CONFIRMATION_THRESHOLD == 0.6)
    cases = [(r("鍵", None), True), (r("鍵", 0.0), True), (r("鍵", 0.599), True),
             (r("鍵", 0.6), False), (r("鍵", 0.95), False), (r("", 0.99), True),
             (r("   ", 1.0), True)]
    for result, expected in cases:
        check(f"needs_confirmation({result.transcript!r}, {result.confidence}) == {expected}",
              needs_confirmation(result) is expected)


def main() -> int:
    for test in (test_selection, test_cache_key, test_cache_and_dedupe, test_wav_wrapping,
                 test_elevenlabs_tts_shape, test_tts_fallback, test_elevenlabs_stt_shape,
                 test_stt_service, test_gemini_stt, test_confirmation_policy):
        try:
            test()
        except Exception as exc:
            check(f"{test.__name__} crashed", False, f"{type(exc).__name__}: {exc}")
    print(f"\n{'FAILED ' + str(len(FAILURES)) if FAILURES else 'ALL PASSED'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
