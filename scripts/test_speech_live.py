"""Live speech test: real TTS + STT round trip; writes learner-audio fixtures.

Run: cd polytale && PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/test_speech_live.py

Gemini path always runs (needs GEMINI_API_KEY). ElevenLabs is skipped cleanly without
ELEVENLABS_API_KEY. Fixtures (16 kHz mono 16-bit PCM WAV, 0.3 s lead/tail silence) land in
scripts/fixtures/learner_audio/<locale>/ for playtests to use as fake microphone input.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import time
import unicodedata
import wave
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from media.common import SpeechError  # noqa: E402
from media.stt import (  # noqa: E402
    DEFAULT_ELEVENLABS_STT_MODEL,
    ElevenLabsSTT,
    GeminiSTT,
    LanguageHint,
    STTService,
    TranscriptionResult,
    build_stt_service,
    needs_confirmation,
)
from media.tts import (  # noqa: E402
    DEFAULT_ELEVENLABS_TTS_MODEL,
    DEFAULT_GEMINI_TTS_MODEL,
    ElevenLabsTTS,
    GeminiTTS,
    TTSService,
)

# The live run exercises one language profile; media/ itself knows none.
TARGET = LanguageHint("zh-CN", "Mandarin Chinese", "pinyin")
SUPPORT_LOCALE = "en-US"
FIXTURES = ROOT / "scripts" / "fixtures" / "learner_audio" / TARGET.locale
FIXTURE_RATE = 16000
LEAD_SILENCE_S = 0.3
TAIL_SILENCE_S = 0.3
FIXTURE_ATTEMPTS = 5
NPC_VOICE = {"elevenlabs_voice_id": "", "gemini_voice": "Charon",
             "style": "a man in his forties tending a bar; relaxed, low, unhurried; brisk tonight"}
LEARNER_VOICE = {"gemini_voice": "Puck",
                 "style": "an adult learner speaking carefully, plain and clear"}
# (line, exact text STT must hear back: proves verbatim reading, no instructions read aloud)
NPC_LINES = ["你要什么？", "好的，一瓶啤酒。十块钱。"]
# (fixture name, text to speak, TTS language, exact transcript, romanized letters or None)
# Transcript/romanized are compared with punctuation, spacing, case and tone marks removed.
LEARNER_UTTERANCES: list[tuple[str, str, str, str, str | None]] = [
    ("pijiu", "啤酒。", "zh-CN", "啤酒", "pijiu"),
    ("wo_yao_pijiu", "我要啤酒。", "zh-CN", "我要啤酒", "woyaopijiu"),
    ("zhege", "这个。", "zh-CN", "这个", "zhege"),
    ("duoshao_qian", "多少钱？", "zh-CN", "多少钱", "duoshaoqian"),
    ("xiexie", "谢谢。", "zh-CN", "谢谢", "xiexie"),
    ("wo_yao_mian", "我要面。", "zh-CN", "我要面", "woyaomian"),
    ("a_beer_please_en", "Can I get a beer please?", "en-US", "canigetabeerplease", None),
    # Spoken with an English voice locale so "beer" stays English instead of a loanword.
    ("mixed_beer_xiexie", "Beer, 谢谢。", "en-US", "beer谢谢", "beerxiexie"),
]

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'} {name}{'' if condition or not detail else ' :: ' + detail}")
    if not condition:
        FAILURES.append(name)


def read_wav(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data)) as src:
        if src.getsampwidth() != 2:
            raise ValueError("expected 16-bit PCM")
        samples = np.frombuffer(src.readframes(src.getnframes()), dtype="<i2").astype(np.float64)
        if src.getnchannels() > 1:
            samples = samples.reshape(-1, src.getnchannels()).mean(axis=1)
        return samples / 32768.0, src.getframerate()


def resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Windowed-sinc polyphase resample (integer up/down ratio)."""
    if src_rate == dst_rate:
        return samples
    gcd = np.gcd(src_rate, dst_rate)
    up, down = dst_rate // gcd, src_rate // gcd
    cutoff = 0.9 / max(up, down)  # fraction of the upsampled Nyquist
    taps = 64 * max(up, down) + 1
    n = np.arange(taps) - (taps - 1) / 2
    kernel = cutoff * np.sinc(cutoff * n) * np.kaiser(taps, 8.0) * up
    stuffed = np.zeros(len(samples) * up)
    stuffed[::up] = samples
    filtered = np.convolve(stuffed, kernel, mode="same")
    return filtered[::down]


def fixture_wav(samples: np.ndarray, rate: int) -> bytes:
    audio = resample(samples, rate, FIXTURE_RATE)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 0:
        audio = audio * (0.8 / peak)
    lead = np.zeros(int(LEAD_SILENCE_S * FIXTURE_RATE))
    tail = np.zeros(int(TAIL_SILENCE_S * FIXTURE_RATE))
    pcm = (np.clip(np.concatenate([lead, audio, tail]), -1, 1) * 32767).astype("<i2").tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(FIXTURE_RATE)
        out.writeframes(pcm)
    return buffer.getvalue()


def silence_wav(seconds: float = 1.5) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(FIXTURE_RATE)
        out.writeframes(b"\x00\x00" * int(seconds * FIXTURE_RATE))
    return buffer.getvalue()


def squash(text: str | None) -> str:
    """Lower-case letters/digits only, tone marks and other diacritics removed."""
    decomposed = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in decomposed if c.isalnum() and not unicodedata.combining(c)).lower()


def heard_as(result: TranscriptionResult, transcript: str, romanized: str | None) -> bool:
    if squash(result.transcript) != squash(transcript):
        return False
    return romanized is None or squash(result.romanized) == romanized


def timed_tts(service: TTSService, text: str, language: str, voice: dict) -> tuple[bytes, float]:
    start = time.perf_counter()
    clip = service.synthesize(text, language=language, voice=voice)
    elapsed = time.perf_counter() - start
    return clip.path.read_bytes(), elapsed


def run_gemini_tts(cache: Path, stt: STTService) -> None:
    print(f"\n== Gemini TTS ({os.environ.get('GEMINI_TTS_MODEL') or DEFAULT_GEMINI_TTS_MODEL})")
    model = os.environ.get("GEMINI_TTS_MODEL") or DEFAULT_GEMINI_TTS_MODEL
    service = TTSService([GeminiTTS(model=model)], cache_dir=cache)
    for text in NPC_LINES:
        try:
            audio, elapsed = timed_tts(service, text, TARGET.locale, NPC_VOICE)
        except SpeechError as exc:
            check(f"gemini tts {text}", False, str(exc))
            continue
        samples, rate = read_wav(audio)
        duration = len(samples) / rate
        low, high = 0.3, 2.5 + 0.45 * len(text)  # reading the prompt aloud would blow this
        check(f"gemini tts {text} valid WAV {rate} Hz, {duration:.2f}s in [{low:.1f},{high:.1f}]",
              rate == 24000 and low <= duration <= high)
        print(f"   latency {elapsed:.2f}s (uncached, full clip = first audio)")
        start = time.perf_counter()
        clip = service.synthesize(text, language=TARGET.locale, voice=NPC_VOICE)
        check(f"gemini tts {text} cached replay", clip.cached,
              f"{(time.perf_counter() - start) * 1000:.1f} ms")
        print(f"   cached lookup {(time.perf_counter() - start) * 1000:.1f} ms")
        heard = stt.transcribe(audio, "audio/wav", target=TARGET, support_locale=SUPPORT_LOCALE)
        check(f"gemini tts {text} read verbatim (STT heard {heard.transcript!r})",
              squash(heard.transcript) == squash(text))


def make_fixtures(stt: STTService) -> dict[str, bytes]:
    """Synthesize learner clips; re-synthesize (TTS is nondeterministic) until STT round-trips,
    so the saved fixtures are reliable fake microphone input for playtests."""
    print("\n== Learner fixtures (Gemini TTS, voice Puck) -> 16 kHz mono WAV")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    tts = GeminiTTS()
    out: dict[str, bytes] = {}
    for name, text, language, transcript, romanized in LEARNER_UTTERANCES:
        for attempt in range(1, FIXTURE_ATTEMPTS + 1):
            start = time.perf_counter()
            try:
                audio = tts.synthesize(text, language=language, voice=LEARNER_VOICE,
                                       variant="normal")
            except SpeechError as exc:
                print(f"   {name}: tts attempt {attempt} failed: {exc}")
                continue
            elapsed = time.perf_counter() - start
            samples, rate = read_wav(audio)
            data = fixture_wav(samples, rate)
            heard = stt.transcribe(data, "audio/wav", target=TARGET,
                                   support_locale=SUPPORT_LOCALE)
            print(f"   {name}.wav attempt {attempt}: {len(samples) / rate:.2f}s speech, "
                  f"tts {elapsed:.2f}s, heard {heard.transcript!r}")
            if heard_as(heard, transcript, romanized):
                out[name] = data
                (FIXTURES / f"{name}.wav").write_bytes(data)
                break
        check(f"fixture {name}.wav round-trips through STT as {transcript!r}", name in out)
    out["silence"] = silence_wav()
    (FIXTURES / "silence.wav").write_bytes(out["silence"])
    for name, data in out.items():
        with wave.open(io.BytesIO(data)) as src:
            ok = (src.getframerate(), src.getnchannels(), src.getsampwidth()) == (16000, 1, 2)
            lead = np.frombuffer(src.readframes(int(0.28 * 16000)), dtype="<i2")
        check(f"fixture {name}.wav is 16 kHz mono PCM16 with quiet lead-in",
              ok and int(np.max(np.abs(lead))) == 0)
    return out


def round_trip(label: str, service: STTService, fixtures: dict[str, bytes], *,
               romanizes: bool = True) -> None:
    """`romanizes` is False for providers that return no romanization (ElevenLabs)."""
    print(f"\n== STT round trip: {label}")
    latencies: list[float] = []
    for name, _text, _language, transcript, romanized in LEARNER_UTTERANCES:
        if name not in fixtures:
            continue
        start = time.perf_counter()
        try:
            result = service.transcribe(fixtures[name], "audio/wav", target=TARGET,
                                        support_locale=SUPPORT_LOCALE)
        except SpeechError as exc:
            check(f"{label} stt {name}", False, str(exc))
            continue
        elapsed = time.perf_counter() - start
        latencies.append(elapsed)
        print(f"   {name}: transcript={result.transcript!r} romanized={result.romanized!r} "
              f"langs={result.detected_languages} conf={result.confidence} "
              f"confirm={needs_confirmation(result)} {elapsed:.2f}s")
        check(f"{label} stt {name} == {transcript!r} / {romanized!r}",
              heard_as(result, transcript, romanized if romanizes else None))
    start = time.perf_counter()
    try:
        silent = service.transcribe(fixtures["silence"], "audio/wav", target=TARGET,
                                    support_locale=SUPPORT_LOCALE)
        print(f"   silence: {silent} {time.perf_counter() - start:.2f}s")
        # Gated before the provider: Gemini hallucinates confident phrases on pure silence.
        check(f"{label} stt silence -> empty (silence gate)", silent.transcript == ""
              and needs_confirmation(silent))
    except SpeechError as exc:
        check(f"{label} stt silence", False, str(exc))
    if latencies:
        print(f"   STT latency: median {sorted(latencies)[len(latencies) // 2]:.2f}s, "
              f"max {max(latencies):.2f}s")


def run_elevenlabs(cache: Path, fixtures: dict[str, bytes]) -> None:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        print("\nSKIP ElevenLabs (ELEVENLABS_API_KEY not set)")
        return
    model = os.environ.get("ELEVENLABS_TTS_MODEL") or DEFAULT_ELEVENLABS_TTS_MODEL
    print(f"\n== ElevenLabs TTS ({model})")
    service = TTSService([ElevenLabsTTS(key, model=model)], cache_dir=cache)
    for text in NPC_LINES:
        try:
            audio, elapsed = timed_tts(service, text, TARGET.locale, NPC_VOICE)
        except SpeechError as exc:
            check(f"elevenlabs tts {text}", False, str(exc))
            continue
        check(f"elevenlabs tts {text} returned mp3 ({len(audio)} bytes)",
              len(audio) > 1000 and (audio[:3] == b"ID3" or audio[0] == 0xFF))
        print(f"   latency {elapsed:.2f}s")
    stt_model = os.environ.get("ELEVENLABS_STT_MODEL") or DEFAULT_ELEVENLABS_STT_MODEL
    round_trip(f"elevenlabs {stt_model}", STTService([ElevenLabsSTT(key, model=stt_model)]),
               fixtures, romanizes=False)


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        print("FAIL GEMINI_API_KEY not set")
        return 1
    with tempfile.TemporaryDirectory() as tmp:  # fresh cache: measure real synthesis latency
        cache = Path(tmp)
        gemini_stt = build_stt_service({**os.environ, "SPEECH_PROVIDER": "gemini"})
        run_gemini_tts(cache, gemini_stt)
        fixtures = make_fixtures(gemini_stt)
        first = gemini_stt.providers[0]
        label = f"gemini {first.model}" if isinstance(first, GeminiSTT) else "gemini"
        round_trip(label, gemini_stt, fixtures)
        run_elevenlabs(cache, fixtures)
    print(f"\n{'FAILED ' + str(len(FAILURES)) if FAILURES else 'ALL PASSED'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
