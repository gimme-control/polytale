"""Live DM test against real Gemini: golden path + mixed / English / low-confidence attempts.

Usage: PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/test_dm_live.py [--runs N]
Skips cleanly (exit 0) when GEMINI_API_KEY is not configured.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from core.cartridge import load_cartridge
from core.dm import run_opening, run_turn
from core.ledger import stage_at_least
from core.state import GameState, new_game
from scripts.testkit import CARTRIDGE_ID, Checker

CART = load_cartridge(CARTRIDGE_ID)
P = "request.give_object"
JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
# Attempts per beat; the driver uses the next one only if the beat did not complete.
GOLDEN = {
    "ground_key": ["kagi?", "kagi"],
    "request_key": ["kagi... kudasai", "kagi o kudasai"],
    "transfer_map": ["chizu please", "chizu o kudasai"],
}
MAX_TURNS = 8


class Session:
    def __init__(self, T: Checker, label: str) -> None:
        self.T, self.label = T, label
        self.state: GameState = new_game(CART, f"live{int(time.time() * 1000) % 10**9}")
        self.state, _ = run_opening(self.state, CART)
        self.n = 0
        self.turns: list[dict[str, Any]] = []

    def act(self, text: str, **extra: Any) -> dict[str, Any]:
        self.n += 1
        beat_before = self._beat()
        trace: list[dict[str, Any]] = []
        attempt = {"attempt_id": f"{self.label}-{self.n}", "input_mode": "text",
                   "transcript": text, **extra}
        self.state, result = run_turn(self.state, CART, attempt, trace=trace)
        calls = [c["name"] for r in trace for c in r["calls"]]
        errors = [c["receipt"].splitlines()[0] for r in trace for c in r["calls"]
                  if c["receipt"].startswith("ERROR")]
        record = {"text": text, "beat_before": beat_before, "result": result,
                  "rounds": len(trace), "calls": calls}
        self.turns.append(record)
        print(f"  [{self.label}] {text!r} ({beat_before}) -> {result['latency_ms']} ms, "
              f"{len(trace)} round(s), calls={calls}")
        for err in errors:
            print(f"      receipt {err}")
        print(f"      narration: {result['narration']}")
        for line in result["spoken_lines"]:
            print(f"      {line['speaker_name']}: {line['text']} | {line['romanization']} | "
                  f"{line['translation']} {line['concept_ids']} {line['pattern_id']}")
        self.check_lines(result)
        return result

    def _beat(self) -> str | None:
        ls = self.state.learning
        beats = CART.language_learning.learning_beats  # type: ignore[union-attr]
        return beats[ls.active_beat_index].id if ls and ls.active_beat_index < len(beats) else None

    def check_lines(self, result: dict[str, Any]) -> None:
        T, n = self.T, f"{self.label} turn {self.n}"
        lines = result["spoken_lines"]
        T.check(f"{n}: NPC spoke", bool(lines))
        for line in lines:
            T.check(f"{n}: NPC line in Japanese ({line['text']})",
                    line["language"] == "ja-JP" and bool(JAPANESE.search(line["text"])))
            T.check(f"{n}: romanization + translation present",
                    bool(line["romanization"].strip()) and bool(line["translation"].strip()))
        T.check(f"{n}: narration has no Japanese script", not JAPANESE.search(result["narration"]),
                result["narration"])


def golden(T: Checker, run: int) -> bool:
    before = len(T.failed)
    s = Session(T, f"golden{run}")
    tries = {beat: 0 for beat in GOLDEN}
    while not s.state.episode_complete and s.n < MAX_TURNS:
        beat = s._beat()
        assert beat is not None
        options = GOLDEN[beat]
        s.act(options[min(tries[beat], len(options) - 1)])
        tries[beat] += 1
    world, ls = s.state.world, s.state.learning
    assert ls is not None
    T.check(f"golden{run}: episode complete", s.state.episode_complete, f"{s.n} turns")
    T.check(f"golden{run}: key with player", world.holders["obj.engine_key"] == "player")
    T.check(f"golden{run}: panel open", world.fixtures["fx.engine_panel"] == "open")
    T.check(f"golden{run}: map with player", world.holders["obj.route_map"] == "player")
    T.check(f"golden{run}: airship launched", world.fixtures["fx.airship"] == "launched")
    T.check(f"golden{run}: key >= produced_with_cue",
            stage_at_least(ls.concept_stage["object.key"], "produced_with_cue"),
            ls.concept_stage["object.key"])
    map_stage = ls.concept_stage["object.map"]
    T.check(f"golden{run}: map transferred or honestly downgraded",
            map_stage in ("transferred", "produced_with_cue"), map_stage)
    print(f"  map stage: {map_stage} "
          f"({'transfer' if map_stage == 'transferred' else 'honest downgrade'}); "
          f"pattern stage {ls.pattern_stage[P]}")

    # No NPC line in the transfer beat may model 地図をください before the player's map attempt.
    entered = next((i for i, t in enumerate(s.turns)
                    if t["result"]["learning"]["active_beat"]
                    and t["result"]["learning"]["active_beat"]["id"] == "transfer_map"), None)
    first_map = next((i for i, t in enumerate(s.turns) if t["beat_before"] == "transfer_map"),
                     None)
    leaked = [
        line["text"]
        for t in s.turns[entered:first_map] if entered is not None and first_map is not None
        for line in t["result"]["spoken_lines"]
        if line["pattern_id"] == P and "object.map" in line["concept_ids"]
    ]
    T.check(f"golden{run}: transfer phrase never modeled before the map attempt", not leaked,
            leaked)
    T.check(f"golden{run}: one attempt per beat (3 turns)", s.n == 3, f"{s.n} turns")
    rounds = [t["rounds"] for t in s.turns]
    latencies = [t["result"]["latency_ms"] for t in s.turns]
    print(f"  golden{run}: turns={s.n} rounds={rounds} latency_ms={latencies}")
    return len(T.failed) == before


def to_request_beat(T: Checker, label: str) -> Session:
    s = Session(T, label)
    s.act("kagi?")
    if s._beat() == "ground_key":
        s.act("kagi")
    T.check(f"{label}: reached request_key", s._beat() == "request_key")
    return s


def mixed_language(T: Checker) -> None:
    s = to_request_beat(T, "mixed")
    s.act("key... kudasai")
    given = s.state.world.holders["obj.engine_key"] == "player"
    T.check("mixed: 'key... kudasai' is understood (key handed over)", given)
    ev = [r for r in s.state.learning.evidence if r.attempt_id == "mixed-" + str(s.n)]  # type: ignore[union-attr]
    T.check("mixed: evidence flagged mixed_language", any(r.mixed_language for r in ev),
            [(r.evidence_type, r.mixed_language) for r in ev])


def english_only(T: Checker) -> None:
    s = to_request_beat(T, "english")
    s.act("can I have the key?")
    T.check("english: key not handed over for an English-only request",
            s.state.world.holders["obj.engine_key"] == "npc.engineer")
    T.check("english: no evidence recorded for the English-only attempt",
            not any(r.attempt_id == f"english-{s.n}" for r in s.state.learning.evidence))  # type: ignore[union-attr]


def low_confidence(T: Checker) -> None:
    s = to_request_beat(T, "lowconf")
    world_before = s.state.world.model_dump(exclude={"focus"})
    s.act("kaki o kuda", input_mode="speech", confidence=0.22, detected_languages=["ja"])
    T.check("lowconf: no evidence recorded",
            not any(r.attempt_id == f"lowconf-{s.n}" for r in s.state.learning.evidence))  # type: ignore[union-attr]
    T.check("lowconf: world unchanged", s.state.world.model_dump(exclude={"focus"})
            == world_before)
    T.check("lowconf: no failure counted",
            s.state.learning.failures.get("request_key", 0) == 0)  # type: ignore[union-attr]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1, help="golden-path repetitions")
    parser.add_argument("--golden-only", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("GEMINI_API_KEY"):
        print("SKIP test_dm_live: GEMINI_API_KEY not set")
        sys.exit(0)
    T = Checker("test_dm_live")
    passes = 0
    for run in range(1, args.runs + 1):
        print(f"\n== golden path run {run}/{args.runs}")
        ok = [False]
        T.run(f"golden{run}", lambda: ok.__setitem__(0, golden(T, run)))
        passes += ok[0]
    print(f"\ngolden path: {passes}/{args.runs} runs passed")
    if not args.golden_only:
        for name, fn in (("mixed", mixed_language), ("english", english_only),
                         ("lowconf", low_confidence)):
            print(f"\n== {name}")
            T.run(name, lambda fn=fn: fn(T))
    T.finish()


if __name__ == "__main__":
    main()
