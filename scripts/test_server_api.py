"""REST API contract: auth, scene entry, transcribe → act, text acts, the game ledgers
(clues, trust), phrasebook, help, audio, ending, summary, reset. Real core engine + scripted
fake Gemini + fake speech (offline).

Run: PYTHONPATH=. python scripts/test_server_api.py
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from functools import partial
from pathlib import Path
from typing import Any

os.environ["POLYTALE_STATES_DIR"] = tempfile.mkdtemp(prefix="polytale-api-")

from fastapi.testclient import TestClient

import media
from core import dm, phrasebook
from core.content import load_content
from core.state import Phrase, PhraseSegment
from media.stt import LanguageHint, TranscriptionResult
from media.tts import AudioClip
from scripts.testkit import Checker, call, lexicon_line, reply, say
from server.app import DEFAULT_LANGUAGE, Deps, app

T = Checker("test_server_api")
CONTENT = load_content()
SCENE_ID = CONTENT.journey.scenes[0]
BAR = CONTENT.scene(SCENE_ID)
LANG = CONTENT.language(DEFAULT_LANGUAGE)


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
SYNTH: list[tuple[str, str]] = []
HEARD = TranscriptionResult(LANG.items["hello"].text, LANG.items["hello"].roman,
                            [DEFAULT_LANGUAGE.split("-")[0]], 0.95, "fake")
STT_RESULT: dict[str, Any] = {"value": HEARD}
TTS_FAIL = {"on": False}


def fake_transcribe(audio: bytes, mime: str, *, target: LanguageHint, support_locale: str):
    assert target.locale == DEFAULT_LANGUAGE and target.name == LANG.name
    assert target.romanization_system == (LANG.romanization.system if LANG.romanization else None)
    value = STT_RESULT["value"]
    if isinstance(value, Exception):
        raise value
    return value


def fake_synthesize(text: str, *, language: str, voice: dict, variant: str = "normal"):
    SYNTH.append((text, voice.get("style", "")))
    if TTS_FAIL["on"]:
        raise media.SpeechProviderError("tts down")
    path = AUDIO_DIR / f"{abs(hash(text))}.wav"
    path.write_bytes(b"RIFF....WAVEfake")
    return AudioClip(path=path, mime="audio/wav", provider="fake", cached=False)


PHRASE: dict[str, Any] = {"raise": None, "calls": 0}


def fake_translate(journey, content, text: str) -> Phrase:
    """Stands in for the phrasebook's model call; the real refusal rules still run first."""
    PHRASE["calls"] += 1
    if PHRASE["raise"] is not None:
        raise PHRASE["raise"]
    if not text.strip():
        raise phrasebook.PhraseRefused("empty", "type what you want to say")
    item = LANG.items["where"]
    return Phrase(phrase_id=f"p-{PHRASE['calls']}", source=text.strip(),
                  segments=[PhraseSegment(t=item.text, r=item.roman, g="where")],
                  text=item.text, romanization=item.roman, item_ids=["where"],
                  audio_url=f"/api/journeys/{journey.journey_id}/phrases/p-{PHRASE['calls']}/audio")


def real_deps() -> Deps:
    return Deps(run_turn=partial(dm.run_turn, client=FAKE, models=["fake"]),
                run_opening=partial(dm.run_opening, client=FAKE, models=["fake"]),
                translate=fake_translate, transcribe=fake_transcribe, synthesize=fake_synthesize)


app.state.deps = real_deps()
client = TestClient(app)
WAV = ("clip.wav", b"RIFF" + b"\0" * 2000, "audio/wav")
OPENING = lambda: reply(say(lexicon_line(LANG, ["hello"]),  # noqa: E731
                            lexicon_line(LANG, ["cheers"]),
                            hint="Wants you to join in with the room"))


def new_journey(**body: Any) -> tuple[str, dict[str, str], dict]:
    data = client.post("/api/journeys", json=body).json()
    return data["journey_id"], {"X-Journey-Token": data["token"]}, data


def enter(jid: str, hdr: dict, **body: Any):
    FAKE.script = [OPENING()]
    return client.post(f"/api/journeys/{jid}/scene", json=body, headers=hdr)


def test_catalog() -> None:
    r = client.get("/api/health")
    T.check("health", r.status_code == 200 and r.json()["language"] == DEFAULT_LANGUAGE, r.text)
    cat = client.get("/api/catalog").json()
    T.check("catalog scenes in journey order",
            [s["id"] for s in cat["scenes"]] == CONTENT.journey.scenes, cat)
    T.check("catalog lists every shipped language, not personas",
            "personas" not in cat
            and [lang["locale"] for lang in cat["languages"]] == sorted(CONTENT.languages)
            and all(set(lang) == {"locale", "name", "native_name"} for lang in cat["languages"]),
            cat.get("languages"))
    T.check("catalog carries the story, never the GM brief",
            cat["story"] == {"title": CONTENT.journey.title, "tagline": CONTENT.journey.tagline,
                             "premise": CONTENT.journey.premise, "art_url": "/api/story/art"}
            and client.get("/api/story/art").status_code in (200, 404)
            and "gm_brief" not in json.dumps(cat))
    r = client.get(cat["scenes"][0]["cover_url"])
    T.check("cover art served", r.status_code == 200 and r.headers["content-type"].startswith(
        "image/"), r.status_code)
    for bad in (f"/api/scenes/{SCENE_ID}/art/../scene.json",
                f"/api/scenes/{SCENE_ID}/art/art/..%2F..%2F..%2F.env",
                "/api/scenes/nope/art/art/bg.webp"):
        T.check(f"art 404 {bad}", client.get(bad).status_code == 404)


def test_auth() -> None:
    jid, hdr, body = new_journey()
    T.check("fresh journey has no scene", body["state"]["scene"] is None
            and body["state"]["started"] is False, body["state"])
    T.check("fresh journey: story, empty ledgers, empty phrasebook",
            body["state"]["story"]["title"] == CONTENT.journey.title
            and body["state"]["game"] == {"trust": 0, "clues": []}
            and body["state"]["phrasebook"] == [] and body["state"]["ending"] is None,
            body["state"].get("game"))
    T.check("the public state carries no wallet, clock, persona or zones",
            not any(k in json.dumps(body["state"])
                    for k in ("wallet", "minutes_left", "persona", "zones", "difficulty")))
    T.check("missing token 403", client.get(f"/api/journeys/{jid}").status_code == 403)
    T.check("wrong token 403", client.get(f"/api/journeys/{jid}",
                                          headers={"X-Journey-Token": "x"}).status_code == 403)
    T.check("unknown journey 404", client.get("/api/journeys/nope", headers=hdr).status_code == 404)
    T.check("act before a scene 409", client.post(f"/api/journeys/{jid}/act", json={"text": "a"},
                                                  headers=hdr).status_code == 409)
    T.check("unknown language 400",
            client.post("/api/journeys", json={"language": "xx-XX"}).status_code == 400)
    for locale in sorted(CONTENT.languages):
        T.check(f"a journey can be started in {locale}",
                client.post("/api/journeys", json={"language": locale}).json()["state"][
                    "language"]["locale"] == locale)
    T.check("the removed routes are gone",
            client.post(f"/api/journeys/{jid}/persona", json={"persona_id": "warm"},
                        headers=hdr).status_code == 404
            and client.post(f"/api/journeys/{jid}/difficulty", json={"difficulty": "story"},
                            headers=hdr).status_code == 404)


def test_journey() -> None:
    jid, hdr, _ = new_journey()
    token = hdr["X-Journey-Token"]
    FAKE.script = [RuntimeError("boom"), RuntimeError("boom")]
    r = client.post(f"/api/journeys/{jid}/scene", json={}, headers=hdr)
    T.check("opening model failure 502", r.status_code == 502, r.status_code)
    T.check("failed opening leaves no scene",
            client.get(f"/api/journeys/{jid}", headers=hdr).json()["scene"] is None)

    FAKE.script = [RuntimeError("402 RESOURCE_EXHAUSTED: prepayment credits are depleted")]
    r = client.post(f"/api/journeys/{jid}/scene", json={}, headers=hdr)
    T.check("provider out of credits → 402 with a plain reason",
            r.status_code == 402 and "credits" in r.json()["detail"], r.text)

    r = enter(jid, hdr)
    T.check("scene entry 200", r.status_code == 200, r.text)
    opening = r.json()
    line = opening["lines"][1]
    T.check("line carries segments + derived text", line["segments"][0]["t"] == LANG.items[
        "cheers"].text and line["text"] == LANG.items["cheers"].text and line["romanization"])
    T.check("turn payload: narration + game, no intent hint, no highlights",
            opening["narration"] and "intent_hint" not in json.dumps(opening)
            and "highlight" not in json.dumps(opening) and opening["ending"] is None)
    state = client.get(f"/api/journeys/{jid}", headers=hdr).json()
    T.check("scene view: the room and its goals, no item text, no GM secrets",
            set(state["scene"]) == {"id", "name", "tagline", "intro", "background_url",
                                    "cover_url", "npc", "goals", "target_count"}
            and LANG.items["scarf"].text not in json.dumps(state["scene"], ensure_ascii=False)
            and BAR.npc.secrets not in json.dumps(state), sorted(state["scene"]))
    T.check("second entry 409", client.post(f"/api/journeys/{jid}/scene", json={},
                                            headers=hdr).status_code == 409)

    # audio
    url = f"{line['audio_url']}?token={token}"
    r = client.get(url)
    T.check("line audio served", r.status_code == 200 and r.headers["content-type"] == "audio/wav")
    T.check("the character's own voice reaches tts", SYNTH[-1][1] == BAR.npc.voice.style)
    T.check("audio without token 403", client.get(line["audio_url"]).status_code == 403)
    T.check("unknown line 404",
            client.get(f"/api/journeys/{jid}/lines/s0-t9-l9/audio?token={token}").status_code == 404)
    T.check("item audio refused during play",
            client.get(f"/api/journeys/{jid}/items/hello/audio?token={token}").status_code == 409)
    TTS_FAIL["on"] = True
    T.check("tts failure 503", client.get(url).status_code == 503)
    TTS_FAIL["on"] = False

    # help: two steps, no turn
    h1 = client.post(f"/api/journeys/{jid}/help", headers=hdr).json()
    T.check("help 1 = again", h1["help"]["kind"] == "again" and h1["help"]["line_ids"]
            and h1["help"]["hint"] is None and "highlight" not in json.dumps(h1), h1)
    h2 = client.post(f"/api/journeys/{jid}/help", headers=hdr).json()
    T.check("help 2 = intent hint", h2["help"]["kind"] == "hint" and "join" in h2["help"]["hint"])

    # phrasebook: no turn; marks the exchange; audio in the neutral voice
    before = client.get(f"/api/journeys/{jid}", headers=hdr).json()
    r = client.post(f"/api/journeys/{jid}/phrase", json={"text": "where is she?"}, headers=hdr)
    found = r.json()
    T.check("phrase shape", r.status_code == 200 and set(found) == {
        "phrase_id", "source", "segments", "text", "romanization", "audio_url", "item_ids"}
            and set(found["segments"][0]) == {"t", "r", "g"} and found["item_ids"] == ["where"],
            found)
    after = client.get(f"/api/journeys/{jid}", headers=hdr).json()
    T.check("a lookup costs no turn and is kept in the phrasebook",
            after["turn"] == before["turn"]
            and [p["phrase_id"] for p in after["phrasebook"]] == [found["phrase_id"]])
    SYNTH.clear()
    r = client.get(f"{found['audio_url']}?token={token}")
    T.check("phrase audio uses the language's phrasebook voice",
            r.status_code == 200 and SYNTH[-1] == (found["text"], LANG.phrasebook_voice.style))
    T.check("unknown phrase 404", client.get(
        f"/api/journeys/{jid}/phrases/p-nope/audio?token={token}").status_code == 404)
    T.check("phrase audio needs the token", client.get(found["audio_url"]).status_code == 403)
    r = client.post(f"/api/journeys/{jid}/phrase", json={"text": "  "}, headers=hdr)
    T.check("empty text 422 with a typed code",
            r.status_code == 422 and r.json()["detail"]["code"] == "empty", r.text)
    PHRASE["raise"] = phrasebook.PhraseRefused("target_language", "type it in English")
    r = client.post(f"/api/journeys/{jid}/phrase", json={"text": LANG.items["cheers"].text},
                    headers=hdr)
    T.check("target-language text 422", r.status_code == 422
            and r.json()["detail"]["code"] == "target_language")
    PHRASE["raise"] = phrasebook.PhraseError("down")
    T.check("phrasebook model failure 502", client.post(
        f"/api/journeys/{jid}/phrase", json={"text": "hi"}, headers=hdr).status_code == 502)
    PHRASE["raise"] = None
    T.check("phrase needs the token", client.post(f"/api/journeys/{jid}/phrase",
                                                  json={"text": "hi"}).status_code == 403)

    # speech: transcribe → failed turn → same attempt resent
    STT_RESULT["value"] = TranscriptionResult(LANG.items["where"].text, LANG.items["where"].roman,
                                              [DEFAULT_LANGUAGE.split("-")[0]], 0.95, "fake")
    r = client.post(f"/api/journeys/{jid}/transcribe", files={"audio": WAV},
                    data={"client_recording_id": "rec-1"}, headers=hdr)
    tr = r.json()
    STT_RESULT["value"] = HEARD
    T.check("transcription shape", r.status_code == 200
            and tr["transcript"] == LANG.items["where"].text
            and tr["requires_confirmation"] is False and tr["client_recording_id"] == "rec-1", tr)
    before = client.get(f"/api/journeys/{jid}", headers=hdr).json()
    FAKE.script = [RuntimeError("boom"), RuntimeError("boom")]
    r = client.post(f"/api/journeys/{jid}/act", json={"attempt_id": tr["attempt_id"]}, headers=hdr)
    T.check("model failure 502", r.status_code == 502, r.status_code)
    after = client.get(f"/api/journeys/{jid}", headers=hdr).json()
    T.check("failed turn changes nothing (turn, ledgers)",
            after["turn"] == before["turn"] and after["game"] == before["game"])
    FAKE.script = [reply(call("record_item", item_id="where", result="understood", produced=True),
                         say(lexicon_line(LANG, ["left"]), narration="He is not telling. Yet."))]
    r = client.post(f"/api/journeys/{jid}/act", json={"attempt_id": tr["attempt_id"]}, headers=hdr)
    res = r.json()
    T.check("attempt resent after failure",
            r.status_code == 200 and res["narration"] == "He is not telling. Yet.", r.text)
    T.check("consumed attempt 409", client.post(f"/api/journeys/{jid}/act", json={
        "attempt_id": tr["attempt_id"]}, headers=hdr).status_code == 409)
    for bad, code in (({"attempt_id": "a-nope"}, 404), ({"text": "a", "attempt_id": "b"}, 422),
                      ({"text": "  "}, 422), ({}, 422),
                      ({"tap_object_id": "beer"}, 422)):
        T.check(f"act {bad} → {code}", client.post(f"/api/journeys/{jid}/act", json=bad,
                                                   headers=hdr).status_code == code)

    # play the act out: photo, chant, the gate → the ending arrives on that turn
    FAKE.script = [reply(call("set_flag", flag="photo_shown"),
                         call("reveal_clue", clue_id="regular"),
                         say(lexicon_line(LANG, ["friend"])))]
    res = client.post(f"/api/journeys/{jid}/act", json={"text": "pengyou"}, headers=hdr).json()
    kinds = [e["kind"] for e in res["events"]]
    T.check("a text act: learner entry, then the clue event with its notebook text",
            res["events"][0]["kind"] == "learner" and "clue" in kinds
            and next(e for e in res["events"] if e["kind"] == "clue")["clue"] == {
                "id": "regular", "title": BAR.clue("regular").title,
                "text": BAR.clue("regular").text}, res["events"])
    FAKE.script = [reply(call("set_flag", flag="chanted"),
                         call("adjust_trust", delta=1, reason="sang the chant"),
                         call("reveal_clue", clue_id="gate"),
                         say(lexicon_line(LANG, ["she", "fan_zone"])))]
    res = client.post(f"/api/journeys/{jid}/act", json={"text": "jiayou"}, headers=hdr).json()
    T.check("the last clue: trust, clues, act complete, the ending on that turn",
            res["game"]["trust"] == 1
            and [c["id"] for c in res["game"]["clues"]] == ["regular", "gate"]
            and res["scene_complete"] is True and res["ending"]["id"] == "found"
            and res["summary"]["next_scene"] is None, res.get("game"))
    T.check("ending payload: art url and the surviving stats",
            res["ending"]["art_url"].startswith(f"/api/scenes/{SCENE_ID}/art/")
            and set(res["ending"]["stats"]) == {"clues", "words_mastered", "words_shaky"},
            res["ending"])
    where = next(i for i in res["summary"]["items"] if i["item_id"] == "where")
    T.check("summary: glosses, honest outcome (the intent hint was used → with_hint), phrasebook",
            where["gloss"] == LANG.items["where"].gloss and where["outcomes"] == ["with_hint"]
            and [p["source"] for p in res["summary"]["phrasebook"]] == ["where is she?"], where)
    T.check("act after completion 409", client.post(f"/api/journeys/{jid}/act", json={"text": "x"},
                                                    headers=hdr).status_code == 409)
    T.check("item audio on summary", client.get(
        f"/api/journeys/{jid}/items/hello/audio?token={token}").status_code == 200)
    restored = client.get(f"/api/journeys/{jid}", headers=hdr).json()
    T.check("refresh restores transcript + summary + ledgers", restored["summary"] is not None
            and {"npc", "learner", "scene", "narration", "clue"} <= {e["kind"] for e in restored[
                "transcript"]} and restored["ending"]["id"] == "found")
    T.check("no further scene after the ending: 409",
            client.post(f"/api/journeys/{jid}/scene", json={}, headers=hdr).status_code == 409)
    T.check("the phrasebook still answers after the ending", client.post(
        f"/api/journeys/{jid}/phrase", json={"text": "thank you"}, headers=hdr).status_code == 200)

    r = client.post(f"/api/journeys/{jid}/reset", headers=hdr)
    T.check("reset → fresh journey, same token",
            r.status_code == 200 and r.json()["scene"] is None and r.json()["ending"] is None
            and r.json()["phrasebook"] == []
            and client.get(f"/api/journeys/{jid}", headers=hdr).status_code == 200)


def test_finish() -> None:
    jid, hdr, _ = new_journey()
    enter(jid, hdr)
    r = client.post(f"/api/journeys/{jid}/finish", headers=hdr)
    T.check("finishing the only act resolves the fallback ending",
            r.status_code == 200 and r.json()["scene_id"] == SCENE_ID
            and client.get(
                f"/api/journeys/{jid}", headers=hdr).json()["ending"]["id"] == "outside", r.text)


def test_transcribe_edges() -> None:
    jid, hdr, _ = new_journey()
    enter(jid, hdr)
    post = lambda files, **kw: client.post(f"/api/journeys/{jid}/transcribe", files=files,  # noqa: E731
                                           headers=kw.get("headers", hdr))
    T.check("non-audio 415", post({"audio": ("x.txt", b"hi", "text/plain")}).status_code == 415)
    T.check("oversize 413", post({"audio": ("b.wav", b"\0" * (5 * 1024 * 1024 + 9),
                                            "audio/wav")}).status_code == 413)
    T.check("empty 400", post({"audio": ("e.wav", b"", "audio/wav")}).status_code == 400)
    T.check("needs token 403", post({"audio": WAV}, headers={}).status_code == 403)
    STT_RESULT["value"] = media.SpeechTimeout("slow")
    T.check("stt timeout 504", post({"audio": WAV}).status_code == 504)
    STT_RESULT["value"] = media.SpeechProviderError("down")
    T.check("stt failure 503", post({"audio": WAV}).status_code == 503)
    STT_RESULT["value"] = TranscriptionResult("", None, [], None, "fake")
    r = post({"audio": WAV})
    T.check("silence needs confirmation", r.json()["requires_confirmation"] is True)
    T.check("empty transcript cannot act", client.post(f"/api/journeys/{jid}/act", json={
        "attempt_id": r.json()["attempt_id"]}, headers=hdr).status_code == 422)
    STT_RESULT["value"] = HEARD


def test_concurrent_turn_rejected() -> None:
    jid, hdr, _ = new_journey()
    enter(jid, hdr)
    gate = threading.Event()

    def slow_turn(journey, content, attempt):
        gate.wait(5)
        raise dm.TurnError("released")

    app.state.deps.run_turn = slow_turn
    codes: list[int] = []
    th = threading.Thread(target=lambda: codes.append(client.post(
        f"/api/journeys/{jid}/act", json={"text": "a"}, headers=hdr).status_code))
    th.start()
    time.sleep(0.4)
    second = client.post(f"/api/journeys/{jid}/act", json={"text": "a"}, headers=hdr)
    gate.set()
    th.join()
    T.check("second concurrent turn 409", second.status_code == 409, second.status_code)
    T.check("first turn failed cleanly 502", codes == [502], codes)
    app.state.deps = real_deps()


for name, fn in [("catalog", test_catalog), ("auth", test_auth), ("journey", test_journey),
                 ("finish", test_finish),
                 ("transcribe_edges", test_transcribe_edges),
                 ("concurrency", test_concurrent_turn_rejected)]:
    T.run(name, fn)
T.finish()
