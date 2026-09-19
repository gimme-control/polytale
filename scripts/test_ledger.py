"""Learning ledger rules (core/ledger.py), including boundaries."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from core import ledger
from core.cartridge import Cartridge, load_cartridge
from core.state import Attempt, GameState, SpokenLine, load_state, new_game, save_state
from scripts.testkit import CARTRIDGE_ID, Checker, plain_cartridge_data, raw_cartridge

T = Checker("test_ledger")
CART = load_cartridge(CARTRIDGE_ID)
_n = 0


def attempt(mode: str = "speech", transcript: str = "kagi", attempt_id: str | None = None) -> Attempt:
    global _n
    _n += 1
    return Attempt(attempt_id=attempt_id or f"a{_n}", input_mode=mode, transcript=transcript)  # type: ignore[arg-type]


def record(state: GameState, cart: Cartridge = CART, *, att: Attempt | None = None,
           beat: str | None = None, concepts: list[str] | None = None,
           pattern: str | None = None, etype: str = "recognized", outcome: str = "understood",
           mixed: bool = False) -> ledger.EvidenceResult:
    active = ledger.active_beat(state, cart)
    return ledger.record_evidence(
        state, cart, attempt=att or attempt(), turn=state.turn,
        beat_id=beat or (active.id if active else ""), concept_ids=concepts or ["object.key"],
        pattern_id=pattern, evidence_type=etype, outcome=outcome,  # type: ignore[arg-type]
        mixed_language=mixed,
    )


def raises(fn: Any) -> bool:
    try:
        fn()
    except ledger.LedgerError:
        return True
    return False


def fresh(cart: Cartridge = CART) -> GameState:
    return new_game(cart, "sess1")


def at_beat(beat_id: str, cart: Cartridge = CART) -> GameState:
    """Drive the ledger to the start of ``beat_id`` through legal steps."""
    s = fresh(cart)
    if beat_id == "ground_key":
        return s
    record(s, cart, etype="recognized")
    ledger.advance_beat(s, cart, "ground_key")
    if beat_id == "request_key":
        return s
    record(s, cart, etype="produced", pattern="request.give_object", att=attempt("speech"))
    s.world.holders["obj.engine_key"] = "player"
    s.world.fixtures["fx.engine_panel"] = "open"
    ledger.advance_beat(s, cart, "request_key")
    return s


def modeled_line(concept: str) -> SpokenLine:
    return SpokenLine(line_id="x", speaker="npc.engineer", speaker_name="Hana",
                      text="…をください。", language="ja-JP", romanization="… o kudasai.",
                      translation="Please give me …", concept_ids=[concept],
                      pattern_id="request.give_object", audio_url="/x")


def cart_with(mutate: Any) -> Cartridge:
    data = raw_cartridge()
    mutate(data)
    return Cartridge.model_validate(data)


# ---------------------------------------------------------------- tests


def test_new_game() -> None:
    s = fresh()
    ls = s.learning
    assert ls is not None
    T.check("new game starts at ground_key", ledger.active_beat(s, CART).id == "ground_key")  # type: ignore[union-attr]
    T.check("all concepts unseen", set(ls.concept_stage.values()) == {"unseen"})
    T.check("ground_key help starts at authored 0", ls.help_level["ground_key"] == 0)
    T.check("holders from cartridge", s.world.holders["obj.engine_key"] == "npc.engineer")
    T.check("fixtures from cartridge", s.world.fixtures == {"fx.engine_panel": "locked",
                                                           "fx.airship": "grounded"})


def test_recognition() -> None:
    s = fresh()
    record(s, att=attempt("tap"), etype="recognized")
    T.check("tap recognized -> context_recognized",
            s.learning.concept_stage["object.key"] == "context_recognized")  # type: ignore[union-attr]
    record(s, att=attempt("speech"), etype="recognized")
    T.check("speech recognized -> speech_recognized",
            s.learning.concept_stage["object.key"] == "speech_recognized")  # type: ignore[union-attr]
    record(s, att=attempt("tap"), etype="recognized")
    T.check("stages only rise (tap after speech keeps speech_recognized)",
            s.learning.concept_stage["object.key"] == "speech_recognized")  # type: ignore[union-attr]
    s2 = fresh()
    record(s2, att=attempt("text"), etype="recognized")
    T.check("text recognized -> speech_recognized",
            s2.learning.concept_stage["object.key"] == "speech_recognized")  # type: ignore[union-attr]
    T.check("recognition beat rejects produced",
            raises(lambda: record(fresh(), etype="produced", pattern="request.give_object")))


def test_production() -> None:
    s = at_beat("request_key")
    ls = s.learning
    assert ls is not None
    T.check("request_key starts at authored help 1", ls.help_level["request_key"] == 1)
    res = record(s, att=attempt("tap"), etype="produced", pattern="request.give_object")
    T.check("tap cannot produce: no stage", ls.concept_stage["object.key"] == "speech_recognized")
    T.check("tap produce recorded as tap fallback",
            res.records and res.records[0].tap_fallback and res.records[0].stage_after is None)
    T.check("tap receipt says tap fallback", any("tap fallback" in n for n in res.notes))
    T.check("tap fallback below level 5 does not complete the beat",
            bool(ledger.completion_gaps(s, CART, ledger.active_beat(s, CART))))  # type: ignore[arg-type]

    s = at_beat("request_key")
    res = record(s, etype="produced", pattern="request.give_object")
    T.check("produced without cue (help 1, not modeled) -> produced_independently",
            s.learning.concept_stage["object.key"] == "produced_independently")  # type: ignore[union-attr]
    T.check("pattern raised to same stage",
            s.learning.pattern_stage["request.give_object"] == "produced_independently")  # type: ignore[union-attr]
    T.check("support level is server help_max_used (1)", res.records[0].support_level == 1)
    T.check("last_successful_construction set",
            s.learning.last_successful_construction is not None  # type: ignore[union-attr]
            and s.learning.last_successful_construction.support_level == 1)  # type: ignore[union-attr]

    s = at_beat("request_key")
    ledger.note_spoken_lines(s, CART, [modeled_line("object.key")])
    T.check("phrase_modeled set by NPC line with pattern+slot",
            s.learning.phrase_modeled["request_key"])  # type: ignore[union-attr]
    record(s, etype="produced", pattern=None)
    T.check("produced after phrase modeled -> produced_with_cue",
            s.learning.concept_stage["object.key"] == "produced_with_cue")  # type: ignore[union-attr]
    T.check("pattern defaults to the beat pattern",
            s.learning.pattern_stage["request.give_object"] == "produced_with_cue")  # type: ignore[union-attr]

    s = at_beat("request_key")
    ledger.request_help(s, CART)
    ledger.request_help(s, CART)
    res = record(s, etype="produced", pattern="request.give_object")
    T.check("produced at help 3 -> produced_with_cue",
            s.learning.concept_stage["object.key"] == "produced_with_cue")  # type: ignore[union-attr]
    T.check("support level recorded 3", res.records[0].support_level == 3)

    s = at_beat("request_key")
    T.check("production with wrong pattern rejected",
            raises(lambda: record(s, etype="produced", pattern="request.other")))
    T.check("production concept outside pattern slots rejected",
            raises(lambda: record(s, etype="produced", concepts=["word.hai"])))
    T.check("wrong beat id rejected",
            raises(lambda: record(s, beat="transfer_map", etype="produced")))
    T.check("unknown concept rejected", raises(lambda: record(s, concepts=["object.nope"])))
    T.check("empty concept list rejected",
            raises(lambda: ledger.record_evidence(
                s, CART, attempt=attempt(), turn=0, beat_id="request_key", concept_ids=[],
                pattern_id=None, evidence_type="recognized", outcome="understood",
                mixed_language=False)))


def test_transfer() -> None:
    s = at_beat("request_key")
    T.check("transfer without prior different slot -> ERROR",
            raises(lambda: record(s, etype="transferred", pattern="request.give_object")))

    s = fresh()
    record(s, etype="recognized")
    ledger.advance_beat(s, CART, "ground_key")
    ledger.request_help(s, CART)  # level 2
    ledger.request_help(s, CART)  # level 3 -> with cue
    record(s, etype="produced", pattern="request.give_object")
    T.check("same-slot transfer (key again) -> ERROR",
            raises(lambda: record(s, etype="transferred", concepts=["object.key"],
                                  pattern="request.give_object")))

    s = at_beat("transfer_map")
    ls = s.learning
    assert ls is not None
    T.check("transfer beat starts at help 0", ls.help_level["transfer_map"] == 0)
    res = record(s, etype="transferred", concepts=["object.map"], pattern="request.give_object")
    T.check("unsupported transfer -> concept transferred",
            ls.concept_stage["object.map"] == "transferred")
    T.check("unsupported transfer -> pattern transferred",
            ls.pattern_stage["request.give_object"] == "transferred")
    T.check("transfer record not downgraded", not res.records[0].downgraded)

    s = at_beat("transfer_map")
    ledger.note_spoken_lines(s, CART, [modeled_line("object.map")])
    res = record(s, etype="transferred", concepts=["object.map"], pattern="request.give_object")
    ls = s.learning
    assert ls is not None
    T.check("phrase modeled -> honest downgrade to produced_with_cue",
            ls.concept_stage["object.map"] == "produced_with_cue")
    T.check("honest downgrade leaves pattern stage unchanged",
            ls.pattern_stage["request.give_object"] == "produced_independently")
    T.check("downgrade flagged and explained",
            res.records[0].downgraded and any("honest downgrade" in n for n in res.notes))

    s = at_beat("transfer_map")
    for _ in range(3):
        ledger.request_help(s, CART)
    record(s, etype="transferred", concepts=["object.map"], pattern="request.give_object")
    T.check("help >= 3 -> honest downgrade",
            s.learning.concept_stage["object.map"] == "produced_with_cue")  # type: ignore[union-attr]
    s.world.holders["obj.route_map"] = "player"
    s.world.fixtures["fx.airship"] = "launched"
    T.check("downgraded transfer still completes the transfer beat",
            ledger.completion_gaps(s, CART, ledger.active_beat(s, CART)) == [])  # type: ignore[arg-type]

    s = at_beat("transfer_map")
    record(s, etype="produced", concepts=["object.map"], pattern="request.give_object")
    s.world.holders["obj.route_map"] = "player"
    s.world.fixtures["fx.airship"] = "launched"
    T.check("transfer beat needs a transferred evidence attempt",
            bool(ledger.completion_gaps(s, CART, ledger.active_beat(s, CART))))  # type: ignore[arg-type]


def test_failures_and_help() -> None:
    s = at_beat("request_key")
    ls = s.learning
    assert ls is not None
    record(s, etype="produced", outcome="not_understood")
    T.check("not_understood: no stage change",
            ls.concept_stage["object.key"] == "speech_recognized")
    T.check("not_understood: failures 1", ls.failures["request_key"] == 1)
    T.check("one failure keeps help level", ls.help_level["request_key"] == 1)
    res = record(s, etype="produced", outcome="not_understood")
    T.check("two failures raise help by one", ls.help_level["request_key"] == 2)
    T.check("failures reset after escalation", ls.failures["request_key"] == 0)
    T.check("escalation noted in receipt", any("help raised to level 2" in n for n in res.notes))
    T.check("not_understood never produces", ls.pattern_stage["request.give_object"] == "unseen")
    for _ in range(10):
        record(s, etype="produced", outcome="not_understood")
    T.check("failure escalation caps at 5", ls.help_level["request_key"] == 5)

    s = fresh()
    levels = []
    for _ in range(7):
        cue = ledger.request_help(s, CART)
        levels.append(cue["level"] if cue else None)
    T.check("request_help never skips and caps at 5", levels == [1, 2, 3, 4, 5, 5, 5], levels)
    T.check("help_max_used tracks highest", s.learning.help_max_used["ground_key"] == 5)  # type: ignore[union-attr]

    s = at_beat("request_key")
    T.check("set_help_level below current rejected",
            raises(lambda: ledger.set_help_level(s, CART, "request_key", 0)))
    T.check("set_help_level +2 rejected",
            raises(lambda: ledger.set_help_level(s, CART, "request_key", 3)))
    T.check("set_help_level wrong beat rejected",
            raises(lambda: ledger.set_help_level(s, CART, "ground_key", 2)))
    cue = ledger.set_help_level(s, CART, "request_key", 2)
    T.check("set_help_level +1 ok", s.learning.help_level["request_key"] == 2  # type: ignore[union-attr]
            and cue is not None and cue["kind"] == "word")
    ledger.set_help_level(s, CART, "request_key", 2)
    T.check("set_help_level same level ok", s.learning.help_level["request_key"] == 2)  # type: ignore[union-attr]
    for _ in range(3):
        ledger.request_help(s, CART)
    T.check("set_help_level cannot exceed 5",
            raises(lambda: ledger.set_help_level(s, CART, "request_key", 6)))


def test_help_cues() -> None:
    s = at_beat("request_key")
    cue1 = ledger.current_help_cue(s, CART)
    T.check("level 1 cue is slow replay with a SpokenLine",
            cue1 is not None and cue1["kind"] == "replay_slow"
            and cue1["line"]["audio_url"].endswith("/lines/help-request_key-1/audio")
            and cue1["line"]["romanization"] == "Kagi o kudasai.")
    cue2 = ledger.request_help(s, CART)
    T.check("level 2 word cue shows concept chip",
            cue2 is not None and cue2["concepts"] == [
                {"id": "object.key", "native": "鍵", "romanization": "kagi"}])
    cue3 = ledger.request_help(s, CART)
    T.check("level 3 frame cue",
            cue3 is not None and cue3["frame"] == {"native": "___をください",
                                                   "romanization": "___ o kudasai"}
            and cue3["concepts"][0]["id"] == "object.key")
    cue4 = ledger.request_help(s, CART)
    T.check("level 4 meaning cue has text", cue4 is not None and "kudasai" in cue4["text"])
    cue5 = ledger.request_help(s, CART)
    T.check("level 5 full cue", cue5 is not None and cue5["native"] == "鍵をください"
            and cue5["translation"] == "Please give me the key.")
    T.check("level 0 has no cue", ledger.current_help_cue(fresh(), CART) is None)
    s = at_beat("transfer_map")
    for level in range(1, 5):
        cue = ledger.request_help(s, CART)
        T.check(f"transfer cue level {level} never shows the completed sentence",
                "地図をください" not in str(cue))


def test_tap_fallback() -> None:
    s = at_beat("request_key")
    view = ledger.learning_view(s, CART)
    T.check("tap not offered at request_key level 1", view["tap_fallback"] is False)
    for _ in range(4):
        ledger.request_help(s, CART)
    view = ledger.learning_view(s, CART)
    T.check("tap offered at level 5", view["tap_fallback"] is True and view["next_help"] is None)
    record(s, att=attempt("tap"), etype="produced", pattern="request.give_object")
    s.world.holders["obj.engine_key"] = "player"
    s.world.fixtures["fx.engine_panel"] = "open"
    T.check("tap fallback at level 5 completes production beat",
            ledger.completion_gaps(s, CART, ledger.active_beat(s, CART)) == [])  # type: ignore[arg-type]
    T.check("tap fallback leaves concept below produced",
            s.learning.concept_stage["object.key"] == "speech_recognized")  # type: ignore[union-attr]
    T.check("recognition beat always allows tap", ledger.learning_view(fresh(), CART)["tap_fallback"])


def test_beat_entry_reuse() -> None:
    s = at_beat("transfer_map")
    T.check("reuse: transfer starts at min(initial 0, support-1)",
            s.learning.help_level["transfer_map"] == 0)  # type: ignore[union-attr]

    cart = cart_with(lambda d: d["language_learning"]["learning_beats"][2].update(
        initial_help_level=4))
    s = fresh(cart)
    record(s, cart, etype="recognized")
    ledger.advance_beat(s, cart, "ground_key")
    for _ in range(2):
        ledger.request_help(s, cart)  # request_key at level 3
    record(s, cart, etype="produced", pattern="request.give_object")
    s.world.holders["obj.engine_key"] = "player"
    s.world.fixtures["fx.engine_panel"] = "open"
    ledger.advance_beat(s, cart, "request_key")
    T.check("reuse starts one level below prior success (3 -> 2, initial 4)",
            s.learning.help_level["transfer_map"] == 2)  # type: ignore[union-attr]
    T.check("entry level counts as help used",
            s.learning.help_max_used["transfer_map"] == 2)  # type: ignore[union-attr]

    cart = cart_with(lambda d: d["language_learning"]["learning_beats"][1].update(
        initial_help_level=2))
    s = fresh(cart)
    record(s, cart, etype="recognized")
    ledger.advance_beat(s, cart, "ground_key")
    T.check("no prior construction: authored initial level (2)",
            s.learning.help_level["request_key"] == 2)  # type: ignore[union-attr]


def test_advance() -> None:
    s = fresh()
    T.check("advance without evidence rejected",
            raises(lambda: ledger.advance_beat(s, CART, "ground_key")))
    T.check("advance wrong beat rejected",
            raises(lambda: ledger.advance_beat(s, CART, "request_key")))
    record(s, etype="recognized", outcome="not_understood")
    T.check("not_understood recognition does not complete",
            raises(lambda: ledger.advance_beat(s, CART, "ground_key")))
    record(s, etype="recognized")
    nxt = ledger.advance_beat(s, CART, "ground_key")
    T.check("advance returns next beat", nxt is not None and nxt.id == "request_key")
    record(s, etype="produced", pattern="request.give_object")
    try:
        ledger.advance_beat(s, CART, "request_key")
        T.check("advance with evidence but world unchanged rejected", False)
    except ledger.LedgerError as exc:
        T.check("advance with evidence but world unchanged rejected",
                "obj.engine_key must be held by player" in str(exc), str(exc))
    s.world.holders["obj.engine_key"] = "player"
    s.world.fixtures["fx.engine_panel"] = "open"
    ledger.advance_beat(s, CART, "request_key")
    record(s, etype="transferred", concepts=["object.map"], pattern="request.give_object")
    s.world.holders["obj.route_map"] = "player"
    s.world.fixtures["fx.airship"] = "launched"
    T.check("final advance returns None", ledger.advance_beat(s, CART, "transfer_map") is None)
    T.check("episode_complete set", s.episode_complete)
    T.check("active index == len(beats)", s.learning.active_beat_index == 3)  # type: ignore[union-attr]
    T.check("advance after completion rejected",
            raises(lambda: ledger.advance_beat(s, CART, "transfer_map")))
    T.check("request_help after completion -> None", ledger.request_help(s, CART) is None)
    view = ledger.learning_view(s, CART)
    T.check("finished learning view", view["active_beat"] is None and view["help_level"] == 0)


def test_idempotency() -> None:
    s = at_beat("request_key")
    att = attempt("speech", attempt_id="same")
    record(s, att=att, etype="produced", pattern="request.give_object")
    n = len(s.learning.evidence)  # type: ignore[union-attr]
    res = record(s, att=att, etype="produced", pattern="request.give_object")
    T.check("duplicate (attempt, concept, type) is idempotent",
            len(s.learning.evidence) == n and not res.records)  # type: ignore[union-attr]
    s = at_beat("request_key")
    att = attempt("speech", attempt_id="dup")
    record(s, att=att, etype="produced", outcome="not_understood")
    record(s, att=att, etype="produced", outcome="not_understood")
    T.check("duplicate failure counted once", s.learning.failures["request_key"] == 1)  # type: ignore[union-attr]


def test_exposures() -> None:
    s = at_beat("request_key")
    before = s.learning.exposures["object.key"]  # type: ignore[union-attr]
    line = modeled_line("object.key")
    player_line = line.model_copy(update={"speaker": "player"})
    ledger.note_spoken_lines(s, CART, [line, player_line])
    T.check("NPC line increments exposures once",
            s.learning.exposures["object.key"] == before + 1)  # type: ignore[union-attr]
    s = at_beat("request_key")
    ledger.note_spoken_lines(s, CART, [modeled_line("object.map")])
    T.check("pattern with a different slot concept does not model the beat",
            not s.learning.phrase_modeled["request_key"])  # type: ignore[union-attr]
    s = at_beat("request_key")
    ledger.note_spoken_lines(s, CART, [modeled_line("object.key").model_copy(
        update={"pattern_id": None})])
    T.check("word without pattern does not model the beat",
            not s.learning.phrase_modeled["request_key"])  # type: ignore[union-attr]


def test_save_load() -> None:
    s = at_beat("transfer_map")
    record(s, etype="transferred", concepts=["object.map"], pattern="request.give_object")
    with tempfile.TemporaryDirectory() as tmp:
        path = save_state(s, Path(tmp))
        loaded = load_state("sess1", Path(tmp))
        T.check("save/load round-trip equal", loaded is not None
                and loaded.model_dump() == s.model_dump())
        T.check("atomic save leaves no .tmp", not list(Path(tmp).rglob("*.tmp")))
        T.check("saved under sessions/", path.parent.name == "sessions")
        T.check("load missing -> None", load_state("nope", Path(tmp)) is None)
    try:
        save_state(s.model_copy(update={"session_id": "../evil"}), Path("/tmp"))
        T.check("path-like session id rejected", False)
    except ValueError:
        T.check("path-like session id rejected", True)


def test_plain_mode() -> None:
    data = plain_cartridge_data()
    cart = Cartridge.model_validate(data)
    s = new_game(cart, "plain")
    T.check("plain: no learning state", s.learning is None)
    T.check("plain: learning_view empty", ledger.learning_view(s, cart)["active_beat"] is None)
    T.check("plain: request_help None", ledger.request_help(s, cart) is None)
    T.check("plain: record raises LedgerError",
            raises(lambda: ledger.record_evidence(
                s, cart, attempt=attempt(), turn=0, beat_id="x", concept_ids=["y"],
                pattern_id=None, evidence_type="recognized", outcome="understood",
                mixed_language=False)))
    ledger.note_spoken_lines(s, cart, [modeled_line("object.key")])
    T.check("plain: note_spoken_lines is a no-op", s.learning is None)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            T.run(name, fn)
    T.finish()
