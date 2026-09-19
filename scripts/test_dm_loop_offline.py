"""DM loop with a scripted fake Gemini client: golden path, retries, nudges, failures."""

from __future__ import annotations

from typing import Any

from google.genai import types

from core import views
from core.cartridge import load_cartridge
from core.dm import TurnError, run_opening, run_turn
from core.state import EvidenceEntry, GameState, NarrationEntry, NpcEntry, PlayerEntry, new_game
from scripts.testkit import CARTRIDGE_ID, Checker

T = Checker("test_dm_loop_offline")
CART = load_cartridge(CARTRIDGE_ID)
TURN_KEYS = {"turn", "narration", "spoken_lines", "world", "learning", "evidence",
             "episode_complete", "recap", "latency_ms"}
LINE_KEYS = {"line_id", "speaker", "speaker_name", "text", "language", "romanization",
             "translation", "concept_ids", "pattern_id", "audio_url"}


def call(name: str, **args: Any) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=name, args=args, id=f"id-{name}"))


def reply(*parts: types.Part) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))]
    )


def text_reply(text: str) -> types.GenerateContentResponse:
    return reply(types.Part(text=text))


class FakeModels:
    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, *, model: str, contents: list[Any], config: Any) -> Any:
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        if not self.script:
            raise AssertionError("fake client script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, script: list[Any]) -> None:
        self.models = FakeModels(script)


def jline(text: str, rom: str, tr: str, concepts: list[str], pattern: str | None = None) -> dict:
    line = {"speaker": "npc.engineer", "text": text, "language": "ja-JP", "romanization": rom,
            "translation": tr, "concept_ids": concepts}
    if pattern:
        line["pattern_id"] = pattern
    return line


def narrate(narration: str, *lines: dict) -> types.Part:
    return call("deliver_narration", narration=narration, spoken_lines=list(lines))


def ev(beat: str, concept: str, etype: str, pattern: str | None = None,
       mixed: bool = False) -> types.Part:
    args: dict[str, Any] = {"learning_beat_id": beat, "concept_ids": [concept],
                            "evidence_type": etype, "outcome": "understood",
                            "mixed_language": mixed}
    if pattern:
        args["pattern_id"] = pattern
    return call("record_language_evidence", **args)


P = "request.give_object"
GROUND = reply(
    ev("ground_key", "object.key", "recognized"),
    call("advance_beat", learning_beat_id="ground_key"),
    call("show_object", object_id="obj.engine_key", gesture="withhold"),
    narrate("She beams and holds the key just out of reach.",
            jline("はい、鍵！", "Hai, kagi!", "Yes, key!", ["word.hai", "object.key"]),
            jline("鍵をください。", "Kagi o kudasai.", "Please give me the key.",
                  ["object.key"], P)),
)
REQUEST = reply(
    call("give", object_id="obj.engine_key", to="player"),
    call("set_fixture", fixture_id="fx.engine_panel", state="open"),
    ev("request_key", "object.key", "produced", P, mixed=True),
    call("advance_beat", learning_beat_id="request_key"),
    call("show_object", object_id="obj.route_map", gesture="hold_up"),
    narrate("She hands you the key and the panel swings open. Then she lifts a rolled chart.",
            jline("はい、鍵をください、ですね。どうぞ。", "Hai, kagi o kudasai, desu ne. Douzo.",
                  "Yes, 'please give me the key', right. Here you go.",
                  ["word.hai", "object.key", "word.douzo"], P),
            jline("地図。", "Chizu.", "Map.", ["object.map"])),
)
TRANSFER = reply(
    call("give", object_id="obj.route_map", to="player"),
    call("set_fixture", fixture_id="fx.airship", state="launched"),
    ev("transfer_map", "object.map", "transferred", P),
    call("advance_beat", learning_beat_id="transfer_map"),
    narrate("She hands you the map and the airship lifts off.",
            jline("はい、どうぞ！", "Hai, douzo!", "Yes, here you go!", ["word.hai", "word.douzo"])),
)


def started() -> GameState:
    s, _ = run_opening(new_game(CART, "off1"), CART)
    return s


def attempt(i: int, text: str, mode: str = "text") -> dict[str, Any]:
    return {"attempt_id": f"att{i}", "input_mode": mode, "transcript": text}


def test_opening() -> None:
    s0 = new_game(CART, "off1")
    s, result = run_opening(s0, CART)
    T.check("opening does not mutate input state", not s0.started and s0.transcript == [])
    T.check("opening result has TurnResult keys", set(result) == TURN_KEYS, set(result))
    T.check("opening started", s.started and s.turn == 1 and result["turn"] == 0)
    T.check("opening focus hold_up key", s.world.focus is not None
            and s.world.focus.object_id == "obj.engine_key"
            and result["world"]["focus"] == {"object_id": "obj.engine_key", "gesture": "hold_up"})
    line = result["spoken_lines"][0]
    T.check("opening line shape", set(line) == LINE_KEYS and line["line_id"] == "t0-l0"
            and line["speaker_name"] == "Hana" and line["text"] == "鍵。"
            and line["audio_url"] == "/api/sessions/off1/lines/t0-l0/audio")
    T.check("opening exposure counted", s.learning.exposures["object.key"] == 1)  # type: ignore[union-attr]
    T.check("opening transcript narration then npc",
            [type(e) for e in s.transcript] == [NarrationEntry, NpcEntry])
    T.check("plate is base art", result["world"]["plate_url"]
            == "/api/cartridges/broken-airship-ja/art/art/plate_base.png")
    try:
        run_opening(s, CART)
        T.check("second opening rejected", False)
    except ValueError:
        T.check("second opening rejected", True)


def test_golden_path() -> None:
    s = started()
    client = FakeClient([GROUND, REQUEST, TRANSFER])
    s, r1 = run_turn(s, CART, attempt(1, "kagi?"), client=client, models=["m1"])
    T.check("turn 1 one model round", len(client.models.calls) == 1)
    T.check("turn 1 TurnResult keys", set(r1) == TURN_KEYS)
    T.check("turn 1 advanced to request_key",
            r1["learning"]["active_beat"]["id"] == "request_key")
    T.check("turn 1 line ids", [x["line_id"] for x in r1["spoken_lines"]] == ["t1-l0", "t1-l1"])
    T.check("turn 1 evidence entry", len(r1["evidence"]) == 1
            and r1["evidence"][0]["stage_after"] == {"object.key": "speech_recognized"})
    T.check("request phrase modeled in new beat",
            s.learning.phrase_modeled["request_key"])  # type: ignore[union-attr]
    T.check("config forces function calling + system prompt",
            client.models.calls[0]["config"].system_instruction is not None
            and client.models.calls[0]["config"].tool_config is not None)

    s, r2 = run_turn(s, CART, attempt(2, "key... kudasai"), client=client, models=["m1"])
    T.check("turn 2 key with player", r2["world"]["holders"]["obj.engine_key"] == "player")
    T.check("turn 2 panel open plate variant",
            r2["world"]["plate_url"].endswith("art/plate_panel_open.png"))
    T.check("turn 2 key produced_with_cue (phrase modeled)",
            r2["learning"]["concept_stage"]["object.key"] == "produced_with_cue")
    T.check("turn 2 now in transfer beat at help 0",
            r2["learning"]["active_beat"]["id"] == "transfer_map"
            and r2["learning"]["help_level"] == 0)
    T.check("recast line in request beat does not model the transfer",
            not s.learning.phrase_modeled["transfer_map"])  # type: ignore[union-attr]

    s, r3 = run_turn(s, CART, attempt(3, "chizu o kudasai", "speech"), client=client,
                     models=["m1"])
    T.check("turn 3 map with player + launched",
            r3["world"]["holders"]["obj.route_map"] == "player"
            and r3["world"]["fixtures"]["fx.airship"] == "launched"
            and r3["world"]["plate_url"].endswith("art/plate_launched.png"))
    T.check("episode complete with recap", r3["episode_complete"] and r3["recap"] is not None)
    T.check("map transferred", r3["learning"]["concept_stage"]["object.map"] == "transferred")
    T.check("turn counter", s.turn == 4 and r3["turn"] == 3)
    T.check("latency recorded", isinstance(r3["latency_ms"], int) and r3["latency_ms"] >= 0)
    kinds = [e.kind for e in s.transcript if e.turn == 2]
    T.check("transcript order player, evidence, narration, npc",
            kinds == ["player", "evidence", "narration", "npc", "npc"], kinds)
    T.check("attempts consumed", all(a.consumed for a in s.attempts.values())
            and len(s.attempts) == 3)
    T.check("line ids unique", len({e.line.line_id for e in s.transcript
                                    if isinstance(e, NpcEntry)})
            == len([e for e in s.transcript if isinstance(e, NpcEntry)]))
    found = views.find_line(s, CART, "t2-l0")
    T.check("find_line transcript line", found is not None and found.text.startswith("はい"))
    help_line = views.find_line(s, CART, "help-request_key-1")
    T.check("find_line help line", help_line is not None and help_line.text == "鍵をください。")
    T.check("find_line unknown", views.find_line(s, CART, "t9-l9") is None)
    pub = views.public_state(s, CART)
    T.check("public_state keys", set(pub) == {"session_id", "cartridge", "started", "turn",
                                              "transcript", "world", "learning",
                                              "episode_complete", "recap", "help_cue"})
    T.check("cartridge view hides English gloss",
            "gloss" not in str(pub["cartridge"]["objects"])
            and pub["cartridge"]["objects"][0]["native"] == "鍵")
    T.check("public transcript serializable", all("kind" in e for e in pub["transcript"]))
    try:
        run_turn(s, CART, attempt(3, "again"), client=FakeClient([]), models=["m1"])
        T.check("consumed attempt rejected", False)
    except ValueError:
        T.check("consumed attempt rejected", True)


def test_error_then_retry() -> None:
    s = started()
    bad = reply(
        call("advance_beat", learning_beat_id="ground_key"),
        narrate("She nods.", jline("鍵。", "Kagi.", "Key.", ["object.key"])),
    )
    good = reply(
        ev("ground_key", "object.key", "recognized"),
        call("advance_beat", learning_beat_id="ground_key"),
        narrate("She nods.", jline("はい、鍵！", "Hai, kagi!", "Yes, key!",
                                   ["word.hai", "object.key"])),
    )
    client = FakeClient([bad, good])
    s2, r = run_turn(s, CART, attempt(1, "kagi"), client=client, models=["m1"])
    T.check("retry: two rounds", len(client.models.calls) == 2)
    responses = client.models.calls[1]["contents"][-1].parts
    receipts = [p.function_response.response["result"] for p in responses]
    T.check("round 1 receipts: advance ERROR and narration rejected",
            receipts[0].startswith("ERROR") and receipts[1].startswith("ERROR")
            and "another call" in receipts[1], receipts)
    T.check("function responses carry call ids",
            responses[0].function_response.id == "id-advance_beat")
    T.check("model content appended before responses",
            client.models.calls[1]["contents"][-2].role == "model")
    T.check("retry succeeded", r["learning"]["active_beat"]["id"] == "request_key"
            and r["spoken_lines"][0]["text"] == "はい、鍵！")

    bad_line = reply(narrate("She nods.", jline("鍵。", "", "Key.", ["object.key"])))
    good_line = reply(narrate("She nods.", jline("鍵。", "Kagi.", "Key.", ["object.key"])))
    client = FakeClient([bad_line, good_line])
    _, r = run_turn(s, CART, attempt(2, "hello"), client=client, models=["m1"])
    T.check("missing romanization retried", len(client.models.calls) == 2
            and r["spoken_lines"][0]["romanization"] == "Kagi.")


def test_nudge() -> None:
    s = started()
    client = FakeClient([text_reply("Hana smiles."), reply(narrate("She smiles."))])
    _, r = run_turn(s, CART, attempt(1, "hello"), client=client, models=["m1"])
    T.check("prose-only reply nudged then narrated", len(client.models.calls) == 2
            and r["narration"] == "She smiles.")
    nudge = client.models.calls[1]["contents"][-1].parts[0].text
    T.check("nudge asks for tool calls", "tool calls" in nudge)

    s = started()
    before = s.model_dump()
    client = FakeClient([text_reply("a"), text_reply("b"), text_reply("c")])
    try:
        run_turn(s, CART, attempt(1, "hello"), client=client, models=["m1"])
        T.check("three prose replies -> TurnError", False)
    except TurnError:
        T.check("three prose replies -> TurnError", True)
    T.check("failure keeps original state unchanged", s.model_dump() == before)
    T.check("failed attempt stays unconsumed", "att1" not in s.attempts)


def test_failures() -> None:
    s = started()
    before = s.model_dump()
    client = FakeClient([reply(call("give", object_id="obj.nope", to="player"))] * 6)
    try:
        run_turn(s, CART, attempt(1, "kagi"), client=client, models=["m1"])
        T.check("max rounds -> TurnError", False)
    except TurnError:
        T.check("max rounds -> TurnError", True)
    T.check("max rounds: 6 model calls", len(client.models.calls) == 6)
    T.check("max rounds: state unchanged", s.model_dump() == before)

    # A committed world change followed by a model failure must not leak into the caller.
    client = FakeClient([
        reply(call("give", object_id="obj.engine_key", to="player")),
        RuntimeError("500 internal"),
    ])
    try:
        run_turn(s, CART, attempt(1, "kagi"), client=client, models=["m1"])
        T.check("mid-turn model failure -> TurnError", False)
    except TurnError:
        T.check("mid-turn model failure -> TurnError", True)
    T.check("mid-turn failure: world unchanged in caller state",
            s.world.holders["obj.engine_key"] == "npc.engineer" and s.model_dump() == before)

    client = FakeClient([RuntimeError("503 UNAVAILABLE high demand"), reply(narrate("Hi."))])
    _, r = run_turn(s, CART, attempt(1, "hi"), client=client, models=["m1", "m2"])
    T.check("cascade to next model on transient error",
            [c["model"] for c in client.models.calls] == ["m1", "m2"] and r["narration"] == "Hi.")

    client = FakeClient([RuntimeError("Your credits are depleted"), reply(narrate("Hi."))])
    try:
        run_turn(s, CART, attempt(1, "hi"), client=client, models=["m1", "m2"])
        T.check("credits error stops cascade", False)
    except TurnError:
        T.check("credits error stops cascade", len(client.models.calls) == 1)

    for label, bad_attempt in (
        ("empty transcript", {"attempt_id": "x", "input_mode": "speech", "transcript": "  "}),
        ("tap unknown object", {"attempt_id": "x", "input_mode": "tap",
                                "tapped_object_id": "obj.nope"}),
        ("bad input mode", {"attempt_id": "x", "input_mode": "telepathy", "transcript": "hi"}),
    ):
        try:
            run_turn(s, CART, bad_attempt, client=FakeClient([]), models=["m1"])
            T.check(f"invalid attempt rejected: {label}", False)
        except (ValueError, TypeError):
            T.check(f"invalid attempt rejected: {label}", True)
    try:
        run_turn(new_game(CART, "x"), CART, attempt(1, "hi"), client=FakeClient([]),
                 models=["m1"])
        T.check("turn before opening rejected", False)
    except ValueError:
        T.check("turn before opening rejected", True)


def test_tap_attempt() -> None:
    s = started()
    client = FakeClient([reply(
        ev("ground_key", "object.key", "recognized"),
        call("advance_beat", learning_beat_id="ground_key"),
        narrate("She grins.", jline("はい！", "Hai!", "Yes!", ["word.hai"])),
    )])
    s, r = run_turn(s, CART, {"attempt_id": "tap1", "input_mode": "tap",
                              "tapped_object_id": "obj.engine_key"},
                    client=client, models=["m1"])
    T.check("tap recognition -> context_recognized",
            r["learning"]["concept_stage"]["object.key"] == "context_recognized")
    player = next(e for e in s.transcript if isinstance(e, PlayerEntry))
    T.check("tap player entry", player.input_mode == "tap"
            and player.tapped_object_id == "obj.engine_key")
    T.check("tap evidence entry input_mode", any(
        isinstance(e, EvidenceEntry) and e.input_mode == "tap" for e in s.transcript))
    snapshot = client.models.calls[0]["contents"][0].parts[0].text
    T.check("snapshot names tapped object", "tapped object: obj.engine_key" in snapshot)


def test_snapshot_contents() -> None:
    s = started()
    client = FakeClient([reply(narrate("She tilts her head."))])
    run_turn(s, CART, {"attempt_id": "c1", "input_mode": "speech", "transcript": "kaki",
                       "detected_languages": ["ja"], "confidence": 0.31},
             client=client, models=["m1"])
    snap = client.models.calls[0]["contents"][0].parts[0].text
    system = client.models.calls[0]["config"].system_instruction
    for needle in ("Premise:", "Hana", "WORLD (committed)", "ACTIVE LEARNING BEAT 1/3",
                   "help level 0", "RECENT TRANSCRIPT", "recognition confidence: 0.31 (LOW",
                   "detected languages: ja", "still missing before advance_beat"):
        T.check(f"snapshot has {needle!r}", needle in snap)
    for needle in ("ALWAYS in Japanese", "Recast, never correct", "NEVER translate",
                   "transfer beat", "もう一度", "ONE response"):
        T.check(f"system prompt has {needle!r}", needle in system)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            T.run(name, fn)
    T.finish()
