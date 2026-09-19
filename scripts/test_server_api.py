"""REST API contract: auth, start, transcribe → act, text/tap acts, help, audio, recap, reset.

Uses the real core engine with a scripted fake Gemini client and fake speech providers, so it
runs offline. Run: PYTHONPATH=. python scripts/test_server_api.py
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from functools import partial
from pathlib import Path
from typing import Any

os.environ["POLYTALE_STATES_DIR"] = tempfile.mkdtemp(prefix="polytale-api-")

from fastapi.testclient import TestClient
from google.genai import types

import media
from core import dm
from media.stt import TranscriptionResult
from media.tts import AudioClip
from scripts.testkit import CARTRIDGE_ID, Checker
from server.app import Deps, app

T = Checker("test_server_api")
ENG = "npc.engineer"


def call(name: str, **args: Any) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=name, args=args, id=f"id-{name}"))


def reply(*parts: types.Part) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))]
    )


def line(text: str, rom: str, tr: str, concepts: list[str], pattern: str | None = None) -> dict:
    return {"speaker": ENG, "text": text, "language": "ja-JP", "romanization": rom,
            "translation": tr, "concept_ids": concepts, "pattern_id": pattern}


class FakeClient:
    def __init__(self) -> None:
        self.script: list[Any] = []
        self.models = self

    def generate_content(self, *, model: str, contents: list[Any], config: Any) -> Any:
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


FAKE = FakeClient()
AUDIO_DIR = Path(tempfile.mkdtemp(prefix="polytale-audio-"))
SYNTH_CALLS: list[str] = []
STT_RESULT = {"value": TranscriptionResult("鍵をください", "kagi o kudasai", ["ja"], 0.95, "fake")}
TTS_FAIL = {"on": False}


def fake_transcribe(audio: bytes, mime: str, *, target_locale: str, support_locale: str):
    assert target_locale == "ja-JP" and support_locale == "en-US"
    value = STT_RESULT["value"]
    if isinstance(value, Exception):
        raise value
    return value


def fake_synthesize(text: str, *, language: str, voice: dict, variant: str = "normal"):
    SYNTH_CALLS.append(text)
    if TTS_FAIL["on"]:
        raise media.SpeechProviderError("tts down")
    path = AUDIO_DIR / f"{abs(hash(text))}.wav"
    path.write_bytes(b"RIFF....WAVEfake")
    return AudioClip(path=path, mime="audio/wav", provider="fake", cached=False)


app.state.deps = Deps(run_turn=partial(dm.run_turn, client=FAKE, models=["fake"]),
                      transcribe=fake_transcribe, synthesize=fake_synthesize)
client = TestClient(app)
WAV = ("clip.wav", b"RIFF" + b"\0" * 2000, "audio/wav")


def new_session() -> tuple[str, dict[str, str], dict]:
    r = client.post("/api/sessions", json={"cartridge_id": CARTRIDGE_ID})
    body = r.json()
    return body["session_id"], {"X-Session-Token": body["token"]}, body


def test_catalog() -> None:
    r = client.get("/api/health")
    T.check("health ok", r.status_code == 200 and r.json()["ok"] is True, r.text)
    r = client.get("/api/cartridges")
    T.check("cartridge listed", any(c["id"] == CARTRIDGE_ID for c in r.json()), r.text)
    r = client.get(f"/api/cartridges/{CARTRIDGE_ID}/art/art/plate_base.png")
    T.check("art served", r.status_code == 200 and r.headers["content-type"] == "image/png")
    r = client.get(f"/api/cartridges/{CARTRIDGE_ID}/art/../cartridge.json")
    T.check("art traversal rejected", r.status_code == 404, r.status_code)
    r = client.get(f"/api/cartridges/{CARTRIDGE_ID}/art/art/..%2F..%2F..%2F.env")
    T.check("encoded traversal rejected", r.status_code == 404, r.status_code)
    r = client.get("/api/cartridges/nope/art/x.png")
    T.check("unknown cartridge art 404", r.status_code == 404)
    r = client.post("/api/sessions", json={"cartridge_id": "nope"})
    T.check("unknown cartridge session 404", r.status_code == 404, r.status_code)


def test_auth() -> None:
    sid, hdr, body = new_session()
    T.check("create returns public state", body["state"]["started"] is False
            and body["state"]["cartridge"]["id"] == CARTRIDGE_ID)
    T.check("no gloss in cartridge objects",
            all("gloss" not in o for o in body["state"]["cartridge"]["objects"]))
    T.check("missing token 403", client.get(f"/api/sessions/{sid}").status_code == 403)
    r = client.get(f"/api/sessions/{sid}", headers={"X-Session-Token": "wrong"})
    T.check("wrong token 403", r.status_code == 403)
    r = client.get("/api/sessions/doesnotexist", headers=hdr)
    T.check("unknown session 404", r.status_code == 404)
    r = client.get("/api/sessions/..%2F..%2Fetc", headers=hdr)
    T.check("path-ish session id 404", r.status_code == 404, r.status_code)
    r = client.post(f"/api/sessions/{sid}/act", json={"text": "kagi"}, headers=hdr)
    T.check("act before start 409", r.status_code == 409, r.status_code)


def test_golden_path() -> None:
    sid, hdr, _ = new_session()
    r = client.post(f"/api/sessions/{sid}/start", headers=hdr)
    T.check("start 200", r.status_code == 200, r.text)
    opening = r.json()
    T.check("opening line has romanization",
            opening["spoken_lines"][0]["romanization"] == "Kagi.", opening["spoken_lines"])
    T.check("opening focus on key", opening["world"]["focus"]["object_id"] == "obj.engine_key")
    T.check("second start 409",
            client.post(f"/api/sessions/{sid}/start", headers=hdr).status_code == 409)

    # audio: token via query param, prewarm already ran through the fake synth
    line_id = opening["spoken_lines"][0]["line_id"]
    token = hdr["X-Session-Token"]
    r = client.get(f"/api/sessions/{sid}/lines/{line_id}/audio?token={token}")
    T.check("audio served", r.status_code == 200 and r.headers["content-type"] == "audio/wav")
    T.check("audio synthesized the native text", "鍵。" in SYNTH_CALLS, SYNTH_CALLS)
    r = client.get(f"/api/sessions/{sid}/lines/{line_id}/audio")
    T.check("audio without token 403", r.status_code == 403)
    r = client.get(f"/api/sessions/{sid}/lines/t99-l9/audio?token={token}")
    T.check("unknown line 404", r.status_code == 404)
    TTS_FAIL["on"] = True
    r = client.get(f"/api/sessions/{sid}/lines/{line_id}/audio?token={token}")
    T.check("tts failure 503 (text stays usable)", r.status_code == 503)
    TTS_FAIL["on"] = False

    # beat 1: recognition by tap
    FAKE.script = [reply(
        call("record_language_evidence", learning_beat_id="ground_key",
             concept_ids=["object.key"], evidence_type="recognized", outcome="understood",
             mixed_language=False),
        call("advance_beat", learning_beat_id="ground_key"),
        call("show_object", object_id="obj.engine_key", gesture="withhold"),
        call("deliver_narration", narration="She grins and pulls the key back.",
             spoken_lines=[line("はい！鍵をください。", "Hai! Kagi o kudasai.",
                                "Yes! Please give me the key.",
                                ["word.hai", "object.key"], "request.give_object")]),
    )]
    r = client.post(f"/api/sessions/{sid}/act", json={"tap_object_id": "obj.engine_key"},
                    headers=hdr)
    T.check("tap act 200", r.status_code == 200, r.text)
    T.check("advanced to request_key",
            r.json()["learning"]["active_beat"]["id"] == "request_key", r.json()["learning"])

    # beat 2: speech via transcribe → act
    r = client.post(f"/api/sessions/{sid}/transcribe", files={"audio": WAV},
                    data={"client_recording_id": "rec-1"}, headers=hdr)
    T.check("transcribe 200", r.status_code == 200, r.text)
    tr = r.json()
    T.check("transcription shape", tr["transcript"] == "鍵をください"
            and tr["romanized"] == "kagi o kudasai" and tr["requires_confirmation"] is False
            and tr["client_recording_id"] == "rec-1" and tr["attempt_id"].startswith("a-"), tr)
    before = client.get(f"/api/sessions/{sid}", headers=hdr).json()
    T.check("transcribe does not spend a turn", before["turn"] == 2, before["turn"])

    FAKE.script = [RuntimeError("model exploded")] + [RuntimeError("again")]
    r = client.post(f"/api/sessions/{sid}/act", json={"attempt_id": tr["attempt_id"]},
                    headers=hdr)
    T.check("model failure 502", r.status_code == 502, r.status_code)
    after = client.get(f"/api/sessions/{sid}", headers=hdr).json()
    T.check("failed turn leaves state unchanged",
            after["turn"] == before["turn"] and after["world"] == before["world"])

    FAKE.script = [reply(
        call("give", object_id="obj.engine_key", to="player"),
        call("set_fixture", fixture_id="fx.engine_panel", state="open"),
        call("record_language_evidence", learning_beat_id="request_key",
             concept_ids=["object.key"], pattern_id="request.give_object",
             evidence_type="produced", outcome="understood", mixed_language=False),
        call("advance_beat", learning_beat_id="request_key"),
        call("deliver_narration", narration="The key is yours. The panel swings open.",
             spoken_lines=[line("はい、どうぞ。", "Hai, douzo.", "Here you go.",
                                ["word.hai", "word.douzo"])]),
    )]
    r = client.post(f"/api/sessions/{sid}/act", json={"attempt_id": tr["attempt_id"]},
                    headers=hdr)
    T.check("pending attempt resubmits after failure", r.status_code == 200, r.text)
    res = r.json()
    T.check("key with player", res["world"]["holders"]["obj.engine_key"] == "player")
    T.check("plate switched to panel_open", res["world"]["plate_url"].endswith(
        "plate_panel_open.png"), res["world"]["plate_url"])
    r = client.post(f"/api/sessions/{sid}/act", json={"attempt_id": tr["attempt_id"]},
                    headers=hdr)
    T.check("consumed attempt 409", r.status_code == 409, r.status_code)
    r = client.post(f"/api/sessions/{sid}/act", json={"attempt_id": "a-nope"}, headers=hdr)
    T.check("unknown attempt 404", r.status_code == 404, r.status_code)
    r = client.post(f"/api/sessions/{sid}/act", json={"text": "a", "tap_object_id": "x"},
                    headers=hdr)
    T.check("two inputs 422", r.status_code == 422, r.status_code)
    r = client.post(f"/api/sessions/{sid}/act", json={"text": "   "}, headers=hdr)
    T.check("blank text 422", r.status_code == 422, r.status_code)
    r = client.post(f"/api/sessions/{sid}/act", json={"tap_object_id": "obj.nope"}, headers=hdr)
    T.check("unknown tap object 422", r.status_code == 422, r.status_code)

    # help ladder on transfer beat: never skips, no story turn
    r = client.post(f"/api/sessions/{sid}/help", headers=hdr)
    T.check("help 200", r.status_code == 200, r.text)
    T.check("help raises exactly one level", r.json()["cue"]["level"] == 1, r.json()["cue"])
    turn_now = client.get(f"/api/sessions/{sid}", headers=hdr).json()["turn"]
    T.check("help spends no turn", turn_now == res["turn"] + 1, (turn_now, res["turn"]))
    T.check("recap 409 before end",
            client.get(f"/api/sessions/{sid}/recap", headers=hdr).status_code == 409)

    # beat 3: typed map request
    FAKE.script = [reply(
        call("give", object_id="obj.route_map", to="player"),
        call("set_fixture", fixture_id="fx.airship", state="launched"),
        call("record_language_evidence", learning_beat_id="transfer_map",
             concept_ids=["object.map"], pattern_id="request.give_object",
             evidence_type="transferred", outcome="understood", mixed_language=True),
        call("advance_beat", learning_beat_id="transfer_map"),
        call("deliver_narration", narration="The airship rises.",
             spoken_lines=[line("地図、どうぞ！", "Chizu, douzo!", "The map, here you go!",
                                ["object.map", "word.douzo"])]),
    )]
    r = client.post(f"/api/sessions/{sid}/act", json={"text": "chizu please"}, headers=hdr)
    T.check("text act 200", r.status_code == 200, r.text)
    res = r.json()
    T.check("episode complete", res["episode_complete"] is True)
    T.check("turn carries recap", res["recap"] is not None and res["recap"]["lines"])
    r = client.get(f"/api/sessions/{sid}/recap", headers=hdr)
    T.check("recap 200", r.status_code == 200 and r.json()["transfer"]["achieved"], r.text)
    r = client.post(f"/api/sessions/{sid}/act", json={"text": "more"}, headers=hdr)
    T.check("act after completion 409", r.status_code == 409)

    # refresh restores everything
    ps = client.get(f"/api/sessions/{sid}", headers=hdr).json()
    kinds = [e["kind"] for e in ps["transcript"]]
    T.check("history restored", {"narration", "npc", "player", "evidence"} <= set(kinds), kinds)

    r = client.post(f"/api/sessions/{sid}/reset", headers=hdr)
    T.check("reset 200 and fresh", r.status_code == 200 and r.json()["started"] is False
            and r.json()["transcript"] == [], r.text)
    T.check("token still valid after reset",
            client.get(f"/api/sessions/{sid}", headers=hdr).status_code == 200)


def test_transcribe_edges() -> None:
    sid, hdr, _ = new_session()
    client.post(f"/api/sessions/{sid}/start", headers=hdr)
    r = client.post(f"/api/sessions/{sid}/transcribe",
                    files={"audio": ("x.txt", b"hello", "text/plain")}, headers=hdr)
    T.check("non-audio 415", r.status_code == 415, r.status_code)
    big = ("big.wav", b"\0" * (5 * 1024 * 1024 + 10), "audio/wav")
    r = client.post(f"/api/sessions/{sid}/transcribe", files={"audio": big}, headers=hdr)
    T.check("oversize 413", r.status_code == 413, r.status_code)
    r = client.post(f"/api/sessions/{sid}/transcribe",
                    files={"audio": ("e.wav", b"", "audio/wav")}, headers=hdr)
    T.check("empty recording 400", r.status_code == 400, r.status_code)
    r = client.post(f"/api/sessions/{sid}/transcribe", files={"audio": WAV})
    T.check("transcribe needs token", r.status_code == 403, r.status_code)
    r = client.post(f"/api/sessions/{sid}/transcribe",
                    files={"audio": ("c.webm", b"\x1a" * 50, "audio/webm;codecs=opus")},
                    headers=hdr)
    T.check("webm with codec params accepted", r.status_code == 200, r.status_code)

    STT_RESULT["value"] = media.SpeechTimeout("slow")
    r = client.post(f"/api/sessions/{sid}/transcribe", files={"audio": WAV}, headers=hdr)
    T.check("stt timeout 504", r.status_code == 504, r.status_code)
    STT_RESULT["value"] = media.SpeechProviderError("down")
    r = client.post(f"/api/sessions/{sid}/transcribe", files={"audio": WAV}, headers=hdr)
    T.check("stt failure 503", r.status_code == 503, r.status_code)

    STT_RESULT["value"] = TranscriptionResult("", None, [], None, "fake")
    r = client.post(f"/api/sessions/{sid}/transcribe", files={"audio": WAV}, headers=hdr)
    T.check("silence needs confirmation", r.json()["requires_confirmation"] is True, r.text)
    r = client.post(f"/api/sessions/{sid}/act", json={"attempt_id": r.json()["attempt_id"]},
                    headers=hdr)
    T.check("empty transcript cannot be acted on", r.status_code == 422, r.status_code)

    STT_RESULT["value"] = TranscriptionResult("key ください", None, ["en", "ja"], 0.4, "fake")
    r = client.post(f"/api/sessions/{sid}/transcribe", files={"audio": WAV}, headers=hdr)
    T.check("mixed transcript preserved + low confidence flagged",
            r.json()["transcript"] == "key ください" and r.json()["detected_languages"] == [
                "en", "ja"] and r.json()["requires_confirmation"] is True, r.text)
    STT_RESULT["value"] = TranscriptionResult("鍵をください", "kagi o kudasai", ["ja"], 0.95, "fake")


def test_concurrent_turn_rejected() -> None:
    sid, hdr, _ = new_session()
    client.post(f"/api/sessions/{sid}/start", headers=hdr)
    gate = threading.Event()

    def slow_turn(state, cart, attempt):
        gate.wait(5)
        raise dm.TurnError("released")

    app.state.deps.run_turn = slow_turn
    results: list[int] = []
    th = threading.Thread(target=lambda: results.append(
        client.post(f"/api/sessions/{sid}/act", json={"text": "kagi"}, headers=hdr).status_code))
    th.start()
    time.sleep(0.4)
    second = client.post(f"/api/sessions/{sid}/act", json={"text": "kagi"}, headers=hdr)
    gate.set()
    th.join()
    T.check("second concurrent turn 409", second.status_code == 409, second.status_code)
    T.check("first turn failed cleanly 502", results == [502], results)
    app.state.deps.run_turn = partial(dm.run_turn, client=FAKE, models=["fake"])


for name, fn in [("catalog", test_catalog), ("auth", test_auth),
                 ("golden_path", test_golden_path), ("transcribe_edges", test_transcribe_edges),
                 ("concurrency", test_concurrent_turn_rejected)]:
    T.run(name, fn)
T.finish()
