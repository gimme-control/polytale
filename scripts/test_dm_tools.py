"""DM tool executors: happy and error paths, receipts, per-turn guards, declarations."""

from __future__ import annotations

from typing import Any

from core.cartridge import load_cartridge
from core.state import Attempt, EvidenceEntry, GameState, new_game
from core.tools import (
    EXECUTORS,
    TERMINAL_TOOL,
    ToolContext,
    declaration_schemas,
    execute,
    is_error,
    tool_declarations,
)
from scripts.testkit import CARTRIDGE_ID, Checker

T = Checker("test_dm_tools")
CART = load_cartridge(CARTRIDGE_ID)


def ctx(mode: str | None = "speech", transcript: str = "kagi") -> ToolContext:
    att = (Attempt(attempt_id="a1", input_mode=mode, transcript=transcript)  # type: ignore[arg-type]
           if mode else None)
    return ToolContext(turn=1, attempt=att)


def run(state: GameState, name: str, args: dict[str, Any], c: ToolContext | None = None) -> str:
    return execute(name, state, CART, args, c or ctx())


def ok(receipt: str) -> bool:
    return receipt.startswith("OK:") and "\nNOW holders:" in receipt


def err(receipt: str, needle: str = "") -> bool:
    return is_error(receipt) and needle in receipt and "\nNOW holders:" in receipt


def line(**over: Any) -> dict[str, Any]:
    base = {"speaker": "npc.engineer", "text": "鍵。", "language": "ja-JP",
            "romanization": "Kagi.", "translation": "Key.", "concept_ids": ["object.key"]}
    base.update(over)
    return base


def test_show_object() -> None:
    s = new_game(CART, "t")
    r = run(s, "show_object", {"object_id": "obj.engine_key", "gesture": "hold_up"})
    T.check("show_object hold_up ok", ok(r) and s.world.focus is not None
            and s.world.focus.gesture == "hold_up", r)
    T.check("receipt NOW line shows focus", "focus: obj.engine_key hold_up" in r)
    T.check("show_object unknown object",
            err(run(s, "show_object", {"object_id": "obj.nope", "gesture": "point"}), "unknown"))
    T.check("show_object bad gesture",
            err(run(s, "show_object", {"object_id": "obj.engine_key", "gesture": "wave"})))
    s.world.holders["obj.engine_key"] = "player"
    for gesture in ("hold_up", "offer", "withhold"):
        T.check(f"{gesture} requires NPC holder",
                err(run(s, "show_object", {"object_id": "obj.engine_key", "gesture": gesture}),
                    "only an NPC"))
    T.check("point works on player-held object",
            ok(run(s, "show_object", {"object_id": "obj.engine_key", "gesture": "point"})))


def test_give() -> None:
    s = new_game(CART, "t")
    run(s, "show_object", {"object_id": "obj.engine_key", "gesture": "offer"})
    r = run(s, "give", {"object_id": "obj.engine_key", "to": "player"})
    T.check("give to player ok", ok(r) and s.world.holders["obj.engine_key"] == "player", r)
    T.check("give clears focus of that object", s.world.focus is None)
    T.check("give again from wrong holder",
            err(run(s, "give", {"object_id": "obj.engine_key", "to": "player"}), "already held"))
    T.check("give unknown object", err(run(s, "give", {"object_id": "x", "to": "player"})))
    T.check("give to unknown recipient",
            err(run(s, "give", {"object_id": "obj.route_map", "to": "npc.ghost"})))
    T.check("give back to npc ok",
            ok(run(s, "give", {"object_id": "obj.engine_key", "to": "npc.engineer"})))
    run(s, "show_object", {"object_id": "obj.route_map", "gesture": "hold_up"})
    run(s, "give", {"object_id": "obj.engine_key", "to": "player"})
    T.check("give keeps focus on other object",
            s.world.focus is not None and s.world.focus.object_id == "obj.route_map")


def test_set_fixture() -> None:
    s = new_game(CART, "t")
    r = run(s, "set_fixture", {"fixture_id": "fx.engine_panel", "state": "open"})
    T.check("set_fixture ok", ok(r) and s.world.fixtures["fx.engine_panel"] == "open", r)
    T.check("set_fixture same state ok (no change)",
            "no change" in run(s, "set_fixture", {"fixture_id": "fx.engine_panel",
                                                   "state": "open"}))
    T.check("set_fixture unknown fixture",
            err(run(s, "set_fixture", {"fixture_id": "fx.nope", "state": "open"})))
    T.check("set_fixture state of another fixture rejected",
            err(run(s, "set_fixture", {"fixture_id": "fx.engine_panel", "state": "launched"})))


def test_record_evidence() -> None:
    s = new_game(CART, "t")
    args = {"learning_beat_id": "ground_key", "concept_ids": ["object.key"],
            "evidence_type": "recognized", "outcome": "understood", "mixed_language": False}
    T.check("evidence without player attempt (opening) -> ERROR",
            err(run(s, "record_language_evidence", args, ctx(None)), "player attempt"))
    T.check("evidence wrong beat -> ERROR",
            err(run(s, "record_language_evidence", {**args, "learning_beat_id": "request_key"}),
                "active beat"))
    T.check("evidence bad type -> ERROR",
            err(run(s, "record_language_evidence", {**args, "evidence_type": "memorized"})))
    T.check("evidence bad outcome -> ERROR",
            err(run(s, "record_language_evidence", {**args, "outcome": "great"})))
    T.check("evidence unknown concept -> ERROR",
            err(run(s, "record_language_evidence", {**args, "concept_ids": ["object.nope"]})))
    T.check("evidence concept_ids not a list -> ERROR",
            err(run(s, "record_language_evidence", {**args, "concept_ids": "object.key"})))
    r = run(s, "record_language_evidence", args)
    T.check("evidence ok with resulting stage", ok(r) and "object.key -> speech_recognized" in r, r)
    entries = [e for e in s.transcript if isinstance(e, EvidenceEntry)]
    T.check("evidence transcript entry appended",
            len(entries) == 1 and entries[0].stage_after == {"object.key": "speech_recognized"}
            and entries[0].support_level == 0 and entries[0].input_mode == "speech")
    r = run(s, "record_language_evidence", args)
    T.check("duplicate evidence is idempotent (no second entry)",
            ok(r) and len([e for e in s.transcript if isinstance(e, EvidenceEntry)]) == 1, r)
    T.check("attempt id/input mode come from ctx, not args",
            s.learning.evidence[0].attempt_id == "a1")  # type: ignore[union-attr]
    r = run(s, "record_language_evidence",
            {**args, "evidence_type": "produced", "pattern_id": "request.give_object"},
            ctx("speech", "kagi kudasai"))
    T.check("produced in recognition beat -> ERROR", err(r, "recognition beat"))


def test_set_language_help() -> None:
    s = new_game(CART, "t")
    r = run(s, "set_language_help", {"learning_beat_id": "ground_key", "level": 1})
    T.check("set_language_help +1 ok with cue text", ok(r) and "Hear it slowly" in r, r)
    T.check("set_language_help skip -> ERROR",
            err(run(s, "set_language_help", {"learning_beat_id": "ground_key", "level": 3})))
    T.check("set_language_help lower -> ERROR",
            err(run(s, "set_language_help", {"learning_beat_id": "ground_key", "level": 0})))
    T.check("set_language_help non-int -> ERROR",
            err(run(s, "set_language_help", {"learning_beat_id": "ground_key", "level": "2"})))
    T.check("set_language_help float-int accepted",
            ok(run(s, "set_language_help", {"learning_beat_id": "ground_key", "level": 2.0})))
    T.check("set_language_help wrong beat -> ERROR",
            err(run(s, "set_language_help", {"learning_beat_id": "transfer_map", "level": 3})))
    T.check("help works without a player attempt (opening ctx)",
            ok(run(s, "set_language_help", {"learning_beat_id": "ground_key", "level": 3},
                   ctx(None))))


def test_advance_beat() -> None:
    s = new_game(CART, "t")
    c = ctx()
    r = run(s, "advance_beat", {"learning_beat_id": "ground_key"}, c)
    T.check("advance without evidence -> ERROR explains", err(r, "no recognition evidence"), r)
    T.check("failed advance does not consume the per-turn guard", not c.advanced)
    T.check("advance wrong beat -> ERROR",
            err(run(s, "advance_beat", {"learning_beat_id": "request_key"}, c), "active beat"))
    run(s, "record_language_evidence",
        {"learning_beat_id": "ground_key", "concept_ids": ["object.key"],
         "evidence_type": "recognized", "outcome": "understood", "mixed_language": False}, c)
    r = run(s, "advance_beat", {"learning_beat_id": "ground_key"}, c)
    T.check("advance ok names the next beat", ok(r) and "request_key" in r, r)
    T.check("NOW line shows new beat", "beat: request_key (2/3) help 1" in r)
    T.check("advance twice in one turn -> ERROR",
            err(run(s, "advance_beat", {"learning_beat_id": "request_key"}, c), "already"))

    c = ctx("text", "kagi o kudasai")
    run(s, "record_language_evidence",
        {"learning_beat_id": "request_key", "concept_ids": ["object.key"],
         "pattern_id": "request.give_object", "evidence_type": "produced",
         "outcome": "understood", "mixed_language": False}, c)
    r = run(s, "advance_beat", {"learning_beat_id": "request_key"}, c)
    T.check("advance with evidence but world unchanged -> ERROR",
            err(r, "must be held by player"), r)
    run(s, "give", {"object_id": "obj.engine_key", "to": "player"}, c)
    run(s, "set_fixture", {"fixture_id": "fx.engine_panel", "state": "open"}, c)
    T.check("advance after world result ok",
            ok(run(s, "advance_beat", {"learning_beat_id": "request_key"}, c)))

    c = ctx("speech", "chizu o kudasai")
    run(s, "give", {"object_id": "obj.route_map", "to": "player"}, c)
    run(s, "set_fixture", {"fixture_id": "fx.airship", "state": "launched"}, c)
    run(s, "record_language_evidence",
        {"learning_beat_id": "transfer_map", "concept_ids": ["object.map"],
         "pattern_id": "request.give_object", "evidence_type": "transferred",
         "outcome": "understood", "mixed_language": False}, c)
    r = run(s, "advance_beat", {"learning_beat_id": "transfer_map"}, c)
    T.check("final advance -> episode complete", ok(r) and "EPISODE COMPLETE" in r
            and s.episode_complete, r)
    T.check("NOW line after completion", "beat: all complete" in r)


def test_deliver_narration() -> None:
    s = new_game(CART, "t")
    c = ctx()
    r = run(s, TERMINAL_TOOL, {"narration": "She smiles.", "spoken_lines": [line()]}, c)
    T.check("deliver_narration ok sets terminal", ok(r) and c.terminal is not None, r)
    assert c.terminal is not None
    T.check("terminal line normalized",
            c.terminal["spoken_lines"][0]["pattern_id"] is None
            and c.terminal["spoken_lines"][0]["concept_ids"] == ["object.key"])

    def bad(label: str, args: dict[str, Any], needle: str = "") -> None:
        c = ctx()
        r = run(s, TERMINAL_TOOL, args, c)
        T.check(f"deliver_narration {label} -> ERROR", err(r, needle) and c.terminal is None, r)

    bad("missing romanization",
        {"narration": "x", "spoken_lines": [line(romanization="")]}, "romanization")
    bad("missing translation",
        {"narration": "x", "spoken_lines": [line(translation=" ")]}, "translation")
    bad("speaker not an npc", {"narration": "x", "spoken_lines": [line(speaker="narrator")]},
        "speaker")
    bad("bad locale", {"narration": "x", "spoken_lines": [line(language="Japanese")]}, "locale")
    bad("unknown concept", {"narration": "x", "spoken_lines": [line(concept_ids=["object.x"])]},
        "unknown concept")
    bad("unknown pattern", {"narration": "x", "spoken_lines": [line(pattern_id="p.x")]},
        "unknown pattern")
    bad("empty text", {"narration": "x", "spoken_lines": [line(text="")]}, "empty")
    bad("nothing at all", {"narration": "", "spoken_lines": []})
    bad("narration too long", {"narration": "word " * 100, "spoken_lines": []}, "too long")
    bad("too many lines", {"narration": "x", "spoken_lines": [line()] * 5}, "at most")
    bad("spoken_lines not a list", {"narration": "x", "spoken_lines": "鍵"})

    c = ctx()
    r = run(s, TERMINAL_TOOL, {"narration": "She waves.", "spoken_lines": [
        line(text="Okay!", language="en-US", romanization="", translation="",
             concept_ids=[])]}, c)
    T.check("support-language line needs no romanization", ok(r), r)

    c = ctx()
    c.round_errors = ["give: ERROR: already held"]
    r = run(s, TERMINAL_TOOL, {"narration": "x", "spoken_lines": [line()]}, c)
    T.check("narration rejected when another call in the round failed",
            err(r, "another call") and c.terminal is None, r)
    c = ctx()
    r = run(s, TERMINAL_TOOL, {"narration": "x", "spoken_lines": [line(pattern_id="")]}, c)
    T.check("empty pattern_id treated as null",
            ok(r) and c.terminal is not None and c.terminal["spoken_lines"][0]["pattern_id"] is None)


def test_dispatch_and_declarations() -> None:
    s = new_game(CART, "t")
    T.check("unknown tool -> ERROR", err(run(s, "teleport", {}), "unknown tool"))
    names = [d["name"] for d in declaration_schemas(CART)]
    T.check("7 tools declared", sorted(names) == sorted(EXECUTORS), names)
    T.check("deliver_narration declared last", names[-1] == TERMINAL_TOOL)
    by_name = {d["name"]: d for d in declaration_schemas(CART)}
    T.check("object ids enumerated",
            by_name["give"]["parameters"]["properties"]["object_id"]["enum"]
            == ["obj.engine_key", "obj.route_map"])
    item = by_name[TERMINAL_TOOL]["parameters"]["properties"]["spoken_lines"]["items"]
    T.check("spoken line requires romanization + translation + concept_ids",
            {"romanization", "translation", "concept_ids"} <= set(item["required"]))
    decls = tool_declarations(CART)
    T.check("gemini FunctionDeclarations build",
            len(decls) == 1 and len(decls[0].function_declarations) == 7)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            T.run(name, fn)
    T.finish()
