"""Live end-to-end playtest of "The Last Train" over HTTP (real GM, phrasebook, STT, TTS).

Plays whole journeys the way different players would and prints each as a readable transcript
(narration, lines, ledgers), so a human can judge whether it is FUN:
  payer     settles Mei's tab, haggles, takes the spicy dare          (voice + verbs + phrasebook)
  charmer   pays for nothing he does not drink: baijiu, a toast, manners; eats politely
  tourist   immersion mode, orders the wrong things, dithers, runs low on cash and time
The GM is a live model, so the driver adapts and asserts on state and payload shape only.

Needs the API running (bash run.sh --quiet, or uvicorn server.app:app --port 8100).
Run: PYTHONPATH=. python scripts/playtest_voice_live.py [--only payer,charmer,tourist]
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
import unicodedata
from typing import Any

import httpx

from scripts.testkit import ROOT, Checker

API = os.environ.get("POLYTALE_API", "http://127.0.0.1:8100")
T = Checker("playtest_voice_live")
LATENCY: dict[str, list[float]] = {"opening": [], "turn": [], "phrase": [], "stt": [],
                                   "first_audio": []}
ENDINGS: dict[str, str] = {}


def typed(romanization: str) -> str:
    plain = unicodedata.normalize("NFD", romanization)
    return "".join(ch for ch in plain if not unicodedata.combining(ch)).lower()


class Player:
    def __init__(self, http: httpx.Client, name: str, difficulty: str = "story",
                 persona: str = "warm") -> None:
        self.http, self.name = http, name
        body = http.post(f"{API}/api/journeys", json={"persona_id": persona}).json()
        self.jid, self.token = body["journey_id"], body["token"]
        self.hdr = {"X-Journey-Token": self.token}
        self.locale = body["state"]["language"]["locale"]
        self.audio_dir = ROOT / "scripts" / "fixtures" / "learner_audio" / self.locale
        self.last: dict[str, Any] = {}
        story = body["state"]["story"]
        print(f"\n{'=' * 78}\n{name.upper()}  —  {story['title']}: {story['premise']}")
        if difficulty != "story":
            r = http.post(self.url("difficulty"), json={"difficulty": difficulty}, headers=self.hdr)
            T.check(f"{name}: difficulty switch", r.status_code == 200
                    and r.json()["game"]["difficulty"] == difficulty)

    def url(self, path: str) -> str:
        return f"{API}/api/journeys/{self.jid}/{path}"

    def state(self) -> dict:
        return self.http.get(f"{API}/api/journeys/{self.jid}", headers=self.hdr).json()

    @property
    def complete(self) -> bool:
        return bool(self.last.get("scene_complete"))

    def _turn(self, label: str, r: httpx.Response, dt: float) -> dict:
        T.check(f"{self.name} {label}: 200 ({dt:.1f}s)", r.status_code == 200, r.text[:300])
        res = self.last = r.json()
        print(f"\n> {label}")
        print(f"  {res['narration']}")
        for line in res["lines"]:
            lit = f"  [lit: {', '.join(line['highlight_object_ids'])}]" if line[
                "highlight_object_ids"] else ""
            print(f"    {line['speaker_name']}: {line['text']}   {line['romanization']}{lit}")
        for event in res["events"]:
            if event["kind"] == "clue":
                print(f"  ** NOTEBOOK: {event['clue']['title']} — {event['clue']['text']}")
        g = res["game"]
        print(f"  [{g['clock']['time']} · {g['clock']['minutes_left']} min · ¥{g['wallet']} · "
              f"trust {g['trust']} · {dt:.1f}s]")
        T.check(f"{self.name} {label}: payload shape",
                res["narration"] and "stage_direction" not in res and res["lines"]
                and all(s["t"] for ln in res["lines"] for s in ln["segments"])
                and set(g) == {"wallet", "clock", "trust", "clues", "difficulty", "prices"})
        if res.get("ending"):
            e = res["ending"]
            ENDINGS[self.name] = e["id"]
            print(f"\n*** {e['title'].upper()} ***\n{e['text']}\n{e['stats']}")
        return res

    def enter(self) -> dict:
        t = time.monotonic()
        r = self.http.post(self.url("scene"), json={}, headers=self.hdr)
        dt = time.monotonic() - t
        LATENCY["opening"].append(dt)
        res = self._turn("(arrives)", r, dt)
        t = time.monotonic()
        audio = self.http.get(f"{API}{res['lines'][0]['audio_url']}?token={self.token}")
        LATENCY["first_audio"].append(time.monotonic() - t)
        T.check(f"{self.name}: first line audio", audio.status_code == 200
                and len(audio.content) > 1000, audio.status_code)
        return res

    def act(self, label: str, body: dict) -> dict:
        t = time.monotonic()
        r = self.http.post(self.url("act"), json=body, headers=self.hdr)
        dt = time.monotonic() - t
        LATENCY["turn"].append(dt)
        return self._turn(label, r, dt)

    def verb(self, action: str, object_id: str) -> dict:
        return self.act(f"[{action} {object_id}]", {"tap_object_id": object_id,
                                                    "action_id": action})

    def ask(self, english: str) -> dict:
        """Phrasebook, then type it as a beginner would (no tone marks)."""
        t = time.monotonic()
        r = self.http.post(self.url("phrase"), json={"text": english}, headers=self.hdr)
        LATENCY["phrase"].append(time.monotonic() - t)
        if not T.check(f"{self.name}: phrasebook {english!r}", r.status_code == 200, r.text[:200]):
            return self.last
        phrase = r.json()
        glosses = " · ".join(f"{s['t']}={s['g']}" for s in phrase["segments"] if s["g"])
        print(f"\n? how do I say \"{english}\" → {phrase['text']}  {phrase['romanization']}  "
              f"({glosses})")
        return self.act(f'types "{typed(phrase["romanization"])}"',
                        {"text": typed(phrase["romanization"])})

    def speak(self, clip: str) -> dict:
        """A recorded learner utterance through real STT, then played as the turn."""
        path = self.audio_dir / f"{clip}.wav"
        t = time.monotonic()
        r = self.http.post(self.url("transcribe"), headers=self.hdr,
                           files={"audio": (path.name, path.read_bytes(), "audio/wav")})
        LATENCY["stt"].append(time.monotonic() - t)
        if not T.check(f"{self.name}: STT {clip}", r.status_code == 200, r.text[:200]):
            return self.last
        heard = r.json()
        return self.act(f'says [{clip}.wav] heard as "{heard["transcript"]}" '
                        f'({heard["romanized"]}, {heard["confidence"]})',
                        {"attempt_id": heard["attempt_id"]})

    def play(self, moves: list[tuple[str, ...]]) -> None:
        for kind, *args in moves:
            if self.complete:
                return
            {"verb": self.verb, "ask": self.ask, "speak": self.speak,
             "type": lambda s: self.act(f'types "{s}"', {"text": s})}[kind](*args)

    def wrap(self) -> None:
        state = self.state()
        ending = state["ending"]
        T.check(f"{self.name}: the story reached an ending (never a dead end)",
                ending is not None, state["game"])
        if state["summary"]:
            print("\nSUMMARY: " + " | ".join(state["summary"]["lines"]))
            print("PHRASEBOOK: " + "; ".join(f"{p['source']} = {p['text']}"
                                             for p in state["summary"]["phrasebook"]))
        if state["phrasebook"]:
            p = state["phrasebook"][0]
            audio = self.http.get(f"{API}{p['audio_url']}?token={self.token}")
            T.check(f"{self.name}: phrase audio", audio.status_code == 200
                    and len(audio.content) > 1000, audio.status_code)


def payer(http: httpx.Client) -> None:
    p = Player(http, "payer")
    p.enter()
    p.play([("speak", "pijiu"), ("verb", "show", "photo"), ("ask", "where is she?"),
            ("verb", "pay", "tab"), ("ask", "where did she go?"), ("verb", "drink", "beer"),
            ("ask", "please, she is my friend")])
    T.check("payer: act 1 done", p.complete, p.last.get("game"))
    p.enter()
    p.play([("verb", "show", "photo"), ("verb", "point", "scarf"),
            ("ask", "how much are the dumplings?"), ("ask", "too expensive!"),
            ("ask", "ok, dumplings please"), ("verb", "eat", "chili"), ("speak", "xiexie"),
            ("ask", "where is she?"), ("ask", "where is my friend now?")])
    p.wrap()


def charmer(http: httpx.Client) -> None:
    p = Player(http, "charmer", persona="unhinged")
    p.enter()
    p.play([("type", "ni hao"), ("ask", "what is good here?"), ("verb", "point", "baijiu"),
            ("ask", "I want that one"), ("ask", "cheers!"), ("verb", "drink", "baijiu"),
            ("speak", "xiexie"), ("verb", "show", "photo"), ("ask", "she is my friend"),
            ("ask", "where is she?"), ("ask", "please, I am worried about her"),
            ("verb", "pay", "tab")])
    T.check("charmer: act 1 done", p.complete, p.last.get("game"))
    p.enter()
    p.play([("type", "ni hao"), ("ask", "I want noodles"), ("ask", "a bit cheaper?"),
            ("ask", "ok"), ("verb", "eat", "noodles"), ("ask", "it's delicious!"),
            ("verb", "show", "photo"), ("ask", "have you seen my friend?"),
            ("verb", "point", "scarf"), ("ask", "where is she?"), ("verb", "eat", "chili"),
            ("ask", "where is my friend now?")])
    p.wrap()


def tourist(http: httpx.Client) -> None:
    p = Player(http, "tourist", difficulty="immersion", persona="brisk")
    p.enter()
    p.play([("type", "hello? do you speak English?"), ("verb", "point", "menu"),
            ("speak", "wo_yao_pijiu"), ("verb", "drink", "beer"), ("verb", "point", "tea"),
            ("ask", "I want tea"), ("verb", "show", "photo"), ("type", "Mei? Mei?"),
            ("ask", "where is she?"), ("verb", "pay", "tab"), ("ask", "sorry, no money"),
            ("ask", "she is my friend"), ("ask", "cheers"), ("verb", "drink", "baijiu"),
            ("ask", "where is she?")])
    if p.complete and not p.last.get("ending"):
        p.enter()
        p.play([("verb", "point", "scarf"), ("verb", "take", "scarf"), ("verb", "show", "photo"),
                ("ask", "where is she?"), ("ask", "I have no money"), ("verb", "eat", "chili"),
                ("ask", "water please"), ("ask", "where is my friend?"),
                ("ask", "please, where?"), ("ask", "thank you")])
    if not p.last.get("ending"):
        p.http.post(p.url("finish"), headers=p.hdr)
        p.last["ending"] = p.state()["ending"]
        if p.last["ending"]:
            ENDINGS[p.name] = p.last["ending"]["id"]
            print(f"\n*** (gave up) {p.last['ending']['title'].upper()} ***\n"
                  f"{p.last['ending']['text']}")
    p.wrap()


PLAYERS = {"payer": payer, "charmer": charmer, "tourist": tourist}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=",".join(PLAYERS))
    args = parser.parse_args()
    with httpx.Client(timeout=90) as http:
        try:
            health = http.get(f"{API}/api/health").json()
        except httpx.HTTPError as exc:
            sys.exit(f"API not reachable at {API}: {exc}")
        print(f"API {API}: {health}")
        for key in args.only.split(","):
            T.run(key, lambda key=key: PLAYERS[key.strip()](http))
    print(f"\nendings: {ENDINGS}")
    for name, values in LATENCY.items():
        if values:
            print(f"{name:12s} n={len(values):3d} median {statistics.median(values):.2f}s "
                  f"max {max(values):.2f}s")
    if LATENCY["turn"]:
        T.check("median turn latency <= 3.5 s", statistics.median(LATENCY["turn"]) <= 3.5)
    T.finish()
