"""Recap: deterministic, observed-behaviour sentences from the ledger, never a score."""

from __future__ import annotations

import json

from core import ledger
from core.cartridge import Cartridge, load_cartridge
from core.recap import build_recap
from core.state import Attempt, GameState, SpokenLine, new_game
from scripts.testkit import CARTRIDGE_ID, Checker, plain_cartridge_data

T = Checker("test_recap")
CART = load_cartridge(CARTRIDGE_ID)
P = "request.give_object"
RECAP_KEYS = {"recognized", "productions", "transfer", "lines", "next_episode"}


def ev(s: GameState, att_id: str, mode: str, text: str, concept: str, etype: str,
       mixed: bool = False) -> None:
    beat = ledger.active_beat(s, CART)
    assert beat is not None
    ledger.record_evidence(
        s, CART, attempt=Attempt(attempt_id=att_id, input_mode=mode, transcript=text),  # type: ignore[arg-type]
        turn=s.turn, beat_id=beat.id, concept_ids=[concept],
        pattern_id=P if etype != "recognized" else None, evidence_type=etype,  # type: ignore[arg-type]
        outcome="understood", mixed_language=mixed,
    )


def model_phrase(s: GameState, concept: str) -> None:
    ledger.note_spoken_lines(s, CART, [SpokenLine(
        line_id="m", speaker="npc.engineer", speaker_name="Hana", text="…をください",
        language="ja-JP", romanization="… o kudasai", translation="…", concept_ids=[concept],
        pattern_id=P, audio_url="/x")])


def play(*, key_modeled: bool, key_help: int, map_mode: str, map_help: int,
         map_mixed: bool = False) -> GameState:
    s = new_game(CART, "recap")
    ev(s, "a1", "speech", "kagi?", "object.key", "recognized")
    ledger.advance_beat(s, CART, "ground_key")
    if key_modeled:
        model_phrase(s, "object.key")
    for _ in range(key_help):
        ledger.request_help(s, CART)
    ev(s, "a2", "speech", "kagi o kudasai", "object.key", "produced")
    s.world.holders["obj.engine_key"] = "player"
    s.world.fixtures["fx.engine_panel"] = "open"
    ledger.advance_beat(s, CART, "request_key")
    for _ in range(map_help):
        ledger.request_help(s, CART)
    ev(s, "a3", map_mode, "chizu please" if map_mode != "tap" else "", "object.map",
       "transferred", mixed=map_mixed)
    s.world.holders["obj.route_map"] = "player"
    s.world.fixtures["fx.airship"] = "launched"
    ledger.advance_beat(s, CART, "transfer_map")
    return s


def test_golden() -> None:
    s = play(key_modeled=True, key_help=0, map_mode="speech", map_help=0, map_mixed=True)
    r = build_recap(s, CART)
    T.check("recap keys", set(r) == RECAP_KEYS)
    T.check("recognized key and map",
            [c["concept_id"] for c in r["recognized"]] == ["object.key", "object.map"])
    T.check("two productions",
            [(p["beat_id"], p["stage"]) for p in r["productions"]]
            == [("request_key", "produced_with_cue"), ("transfer_map", "transferred")])
    T.check("production support level and transcript",
            r["productions"][0]["support_level"] == 1
            and r["productions"][1]["transcript"] == "chizu please")
    T.check("transfer achieved", r["transfer"]["achieved"] is True)
    T.check("key sentence mentions modeled phrase",
            "You asked for the key after hearing Hana say the full phrase." in r["lines"],
            r["lines"])
    T.check("map sentence: reused without the full phrase, mixed",
            any(line.startswith("You reused the request for the map without the full phrase")
                and "mixing in English" in line for line in r["lines"]), r["lines"])
    T.check("less help second time", any("less help" in line for line in r["lines"]))
    T.check("next episode", r["next_episode"] == "Next: ask where something is.")
    T.check("never a fluency score",
            "%" not in json.dumps(r) and "fluen" not in json.dumps(r).lower()
            and "score" not in json.dumps(r).lower())
    T.check("deterministic", build_recap(s, CART) == r)


def test_frame_and_downgrade() -> None:
    s = play(key_modeled=False, key_help=2, map_mode="speech", map_help=3)
    r = build_recap(s, CART)
    T.check("key with phrase frame sentence",
            "You asked for the key with a phrase frame (help level 3)." in r["lines"], r["lines"])
    T.check("map downgraded to produced_with_cue",
            r["productions"][1]["stage"] == "produced_with_cue")
    T.check("transfer not achieved when downgraded", r["transfer"]["achieved"] is False
            and "supported" in r["transfer"]["summary"])
    T.check("downgraded map sentence honest",
            "You reused the request for the map with a phrase frame (help level 3)."
            in r["lines"], r["lines"])


def test_independent_and_tap() -> None:
    s = play(key_modeled=False, key_help=0, map_mode="tap", map_help=5)
    r = build_recap(s, CART)
    T.check("key without seeing phrase",
            "You asked for the key without seeing the full phrase." in r["lines"], r["lines"])
    T.check("tap fallback sentence", "You used the tap fallback for the map." in r["lines"])
    T.check("tap production stage null + input mode tap",
            r["productions"][1]["stage"] is None and r["productions"][1]["input_mode"] == "tap")
    T.check("tap is not transfer", r["transfer"]["achieved"] is False)
    T.check("map not recognized by tap fallback",
            "object.map" not in [c["concept_id"] for c in r["recognized"]])


def test_empty_and_plain() -> None:
    r = build_recap(new_game(CART, "e"), CART)
    T.check("fresh game recap empty", r["recognized"] == [] and r["productions"] == []
            and r["transfer"]["achieved"] is False and r["lines"] == [])
    data = plain_cartridge_data()
    cart = Cartridge.model_validate(data)
    r = build_recap(new_game(cart, "p"), cart)
    T.check("plain mode recap tolerated", set(r) == RECAP_KEYS and r["lines"] == [])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            T.run(name, fn)
    T.finish()
