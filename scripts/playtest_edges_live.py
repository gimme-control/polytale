"""Live off-path learner behaviour over HTTP against a running server (real Gemini DM).

Scenarios (typed acts for speed; speech takes the same /act path):
  english_only   English-only request: she stays in Japanese and does not hand the key over.
  map_too_early  Asking for the map during the key beat does not skip the key beat.
  confused       "what?" / gibberish: no stage rises, she re-grounds in Japanese.
  tap_fallback   Help to level 5, tap the key: the key is given, no spoken stage is credited.

Run: PYTHONPATH=. python scripts/playtest_edges_live.py [scenario ...]
"""

from __future__ import annotations

import os
import sys

import httpx

from scripts.testkit import CARTRIDGE_ID, Checker

API = os.environ.get("POLYTALE_API", "http://127.0.0.1:8100")
T = Checker("playtest_edges_live")
SPEAKING = {"produced_with_cue", "produced_independently", "transferred"}


class Session:
    def __init__(self, http: httpx.Client) -> None:
        self.http = http
        body = http.post(f"{API}/api/sessions", json={"cartridge_id": CARTRIDGE_ID}).json()
        self.sid, self.hdr = body["session_id"], {"X-Session-Token": body["token"]}
        self.post("start")

    def post(self, path: str, **json) -> dict:
        r = self.http.post(f"{API}/api/sessions/{self.sid}/{path}", json=json or None,
                           headers=self.hdr)
        if r.status_code != 200:
            raise AssertionError(f"{path} → {r.status_code}: {r.text}")
        return r.json()

    def say(self, text: str) -> dict:
        res = self.post("act", text=text)
        print(f"\n>> {text!r}  [{res['latency_ms']} ms]\n   {res['narration']}")
        for ln in res["spoken_lines"]:
            print(f"   {ln['text']} / {ln['romanization']}  (lang={ln['language']})")
        for ev in res["evidence"]:
            print(f"   evidence {ev['evidence_type']} {ev['outcome']} {ev['stage_after']}")
        T.check(f"{text!r}: every line in Japanese with romanization",
                all(ln["language"] == "ja-JP" and ln["romanization"]
                    for ln in res["spoken_lines"]), res["spoken_lines"])
        return res

    def to_request_key(self) -> dict:
        res = self.say("kagi")
        if res["learning"]["active_beat"]["id"] == "ground_key":
            res = self.say("kagi!")
        T.check("reached request_key", res["learning"]["active_beat"]["id"] == "request_key")
        return res


def english_only(http: httpx.Client) -> None:
    s = Session(http)
    s.to_request_key()
    res = s.say("Can you please give me the key?")
    T.check("english-only: key not handed over",
            res["world"]["holders"]["obj.engine_key"] != "player", res["world"])
    T.check("english-only: no production credited",
            res["learning"]["concept_stage"]["object.key"] not in SPEAKING,
            res["learning"]["concept_stage"])


def map_too_early(http: httpx.Client) -> None:
    s = Session(http)
    s.to_request_key()
    res = s.say("chizu o kudasai")
    T.check("early map: still on request_key",
            res["learning"]["active_beat"]["id"] == "request_key", res["learning"]["active_beat"])
    T.check("early map: airship not launched",
            res["world"]["fixtures"]["fx.airship"] == "grounded", res["world"])


def confused(http: httpx.Client) -> None:
    s = Session(http)
    before = s.post("help")["learning"]  # a learner who already asked for help once
    res = s.say("what? I don't understand")
    T.check("confused: no stage rise", res["learning"]["concept_stage"]["object.key"] == "unseen",
            res["learning"]["concept_stage"])
    T.check("confused: she answers in Japanese", bool(res["spoken_lines"]))
    T.check("confused: help level never drops",
            res["learning"]["help_level"] >= before["help_level"], res["learning"])
    res = s.say("blorp zzt fnar")
    T.check("gibberish: still on ground_key", res["learning"]["active_beat"]["id"] == "ground_key")


def tap_fallback(http: httpx.Client) -> None:
    s = Session(http)
    s.to_request_key()
    levels = [s.post("help")["cue"]["level"] for _ in range(6) if True]
    T.check("help climbs one level at a time to 5", levels[:5] == [
        min(5, levels[0] + i) for i in range(5)] and max(levels) == 5, levels)
    view = s.post("help")["learning"]
    T.check("level 5 offers tap fallback", view["tap_fallback"] is True, view)
    res = s.post("act", tap_object_id="obj.engine_key")
    print(f"\n>> tap key [{res['latency_ms']} ms]\n   {res['narration']}")
    for ln in res["spoken_lines"]:
        print(f"   {ln['text']} / {ln['romanization']}")
    T.check("tap fallback: key given", res["world"]["holders"]["obj.engine_key"] == "player",
            res["world"])
    T.check("tap fallback: no spoken production credited",
            res["learning"]["concept_stage"]["object.key"] not in SPEAKING,
            res["learning"]["concept_stage"])


SCENARIOS = {"english_only": english_only, "map_too_early": map_too_early,
             "confused": confused, "tap_fallback": tap_fallback}

if __name__ == "__main__":
    chosen = sys.argv[1:] or list(SCENARIOS)
    with httpx.Client(timeout=90) as http:
        for name in chosen:
            print(f"\n================ {name}")
            T.run(name, lambda fn=SCENARIOS[name]: fn(http))
    T.finish()
