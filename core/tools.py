"""DM tool declarations (Gemini) and deterministic executors.

Every executor has the shape ``(state, cartridge, args, ctx) -> receipt`` and mutates
``state`` only after validating every id. Invalid calls return ``"ERROR: ..."`` receipts
so the model can retry inside the same loop. Every receipt ends with a NOW line.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from core import ledger
from core.cartridge import GESTURES, LOCALE_RE, PLAYER, Cartridge
from core.state import Attempt, EvidenceEntry, Focus, GameState

TERMINAL_TOOL = "deliver_narration"
LEDGER_TOOLS = ("record_language_evidence", "set_language_help", "advance_beat")
EVIDENCE_TYPES = ("recognized", "produced", "transferred")
OUTCOMES = ("understood", "clarified", "not_understood")
NPC_GESTURES = ("hold_up", "offer", "withhold")
MAX_NARRATION_CHARS = 320
MAX_LINE_CHARS = 200
MAX_SPOKEN_LINES = 4


@dataclass
class ToolContext:
    """Per-turn execution context. ``attempt`` is None for the opening."""

    turn: int
    attempt: Attempt | None = None
    advanced: bool = False
    round_errors: list[str] = field(default_factory=list)
    terminal: dict[str, Any] | None = None


# ---------------------------------------------------------------- receipts


def now_line(state: GameState, cartridge: Cartridge) -> str:
    """Compact committed-state summary appended to every receipt."""
    holders = ", ".join(f"{oid}={h}" for oid, h in state.world.holders.items()) or "-"
    fixtures = ", ".join(f"{fid}={s}" for fid, s in state.world.fixtures.items()) or "-"
    focus = state.world.focus
    parts = [f"holders: {holders}", f"fixtures: {fixtures}"]
    parts.append(f"focus: {focus.object_id} {focus.gesture}" if focus else "focus: none")
    beat = ledger.active_beat(state, cartridge)
    if beat is not None and state.learning is not None:
        ll = cartridge.language_learning
        total = len(ll.learning_beats) if ll else 0
        level = state.learning.help_level.get(beat.id, 0)
        parts.append(
            f"beat: {beat.id} ({state.learning.active_beat_index + 1}/{total}) help {level}"
        )
    elif state.learning is not None:
        parts.append("beat: all complete")
    return "NOW " + " | ".join(parts)


def _ok(state: GameState, cartridge: Cartridge, message: str) -> str:
    return f"OK: {message}\n{now_line(state, cartridge)}"


def _err(state: GameState, cartridge: Cartridge, message: str) -> str:
    return f"ERROR: {message}\n{now_line(state, cartridge)}"


def is_error(receipt: str) -> bool:
    return receipt.startswith("ERROR")


def describe_cue(cue: dict[str, Any] | None) -> str:
    """One-line description of what the learner now sees for a HelpCue."""
    if cue is None:
        return "no visible help (context only)"
    bits = [f"level {cue['level']} '{cue['label']}' ({cue['kind']})"]
    if "line" in cue:
        bits.append(f"slow replay of {cue['line']['text']}")
    if "concepts" in cue:
        bits.append(
            "shows " + ", ".join(f"{c['native']} {c['romanization']}" for c in cue["concepts"])
        )
    if "frame" in cue:
        bits.append(f"frame {cue['frame']['native']} / {cue['frame']['romanization']}")
    if "text" in cue:
        bits.append(f"hint: {cue['text']}")
    if "native" in cue:
        bits.append(f"full answer {cue['native']} / {cue.get('romanization', '')}")
    return "; ".join(bits)


# ---------------------------------------------------------------- executors


def _str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    return value.strip() if isinstance(value, str) else ""


def exec_show_object(
    state: GameState, cartridge: Cartridge, args: dict[str, Any], ctx: ToolContext
) -> str:
    oid, gesture = _str(args, "object_id"), _str(args, "gesture")
    if cartridge.object(oid) is None:
        valid = ", ".join(o.id for o in cartridge.objects)
        return _err(state, cartridge, f"unknown object_id '{oid}'. Valid: {valid}")
    if gesture not in GESTURES:
        return _err(state, cartridge, f"gesture must be one of {', '.join(GESTURES)}")
    holder = state.world.holders.get(oid, "")
    if gesture in NPC_GESTURES and cartridge.npc(holder) is None:
        return _err(
            state, cartridge,
            f"{oid} is held by {holder}; only an NPC holding it can {gesture} it "
            "(use 'point' instead)",
        )
    state.world.focus = Focus(object_id=oid, gesture=gesture)
    return _ok(state, cartridge, f"{gesture} {oid} (held by {holder})")


def exec_give(
    state: GameState, cartridge: Cartridge, args: dict[str, Any], ctx: ToolContext
) -> str:
    oid, to = _str(args, "object_id"), _str(args, "to")
    if cartridge.object(oid) is None:
        valid = ", ".join(o.id for o in cartridge.objects)
        return _err(state, cartridge, f"unknown object_id '{oid}'. Valid: {valid}")
    if to != PLAYER and cartridge.npc(to) is None:
        valid = ", ".join([PLAYER, *(n.id for n in cartridge.npcs)])
        return _err(state, cartridge, f"'to' must be one of {valid}, not '{to}'")
    current = state.world.holders.get(oid)
    if current == to:
        return _err(state, cartridge, f"{oid} is already held by {to}")
    state.world.holders[oid] = to
    if state.world.focus is not None and state.world.focus.object_id == oid:
        state.world.focus = None
    return _ok(state, cartridge, f"{oid} moved from {current} to {to}")


def exec_set_fixture(
    state: GameState, cartridge: Cartridge, args: dict[str, Any], ctx: ToolContext
) -> str:
    fid, value = _str(args, "fixture_id"), _str(args, "state")
    fixture = cartridge.fixture(fid)
    if fixture is None:
        valid = ", ".join(f.id for f in cartridge.fixtures)
        return _err(state, cartridge, f"unknown fixture_id '{fid}'. Valid: {valid}")
    if value not in fixture.states:
        return _err(state, cartridge, f"{fid} state must be one of {', '.join(fixture.states)}")
    before = state.world.fixtures.get(fid)
    state.world.fixtures[fid] = value
    if before == value:
        return _ok(state, cartridge, f"{fid} is already {value} (no change)")
    return _ok(state, cartridge, f"{fid} {before} -> {value}")


def exec_record_language_evidence(
    state: GameState, cartridge: Cartridge, args: dict[str, Any], ctx: ToolContext
) -> str:
    if ctx.attempt is None:
        return _err(state, cartridge, "no player attempt this turn; evidence needs a player attempt")
    evidence_type, outcome = _str(args, "evidence_type"), _str(args, "outcome")
    if evidence_type not in EVIDENCE_TYPES:
        return _err(state, cartridge, f"evidence_type must be one of {', '.join(EVIDENCE_TYPES)}")
    if outcome not in OUTCOMES:
        return _err(state, cartridge, f"outcome must be one of {', '.join(OUTCOMES)}")
    raw_concepts = args.get("concept_ids") or []
    if not isinstance(raw_concepts, list):
        return _err(state, cartridge, "concept_ids must be a list of concept ids")
    try:
        result = ledger.record_evidence(
            state, cartridge,
            attempt=ctx.attempt,
            turn=ctx.turn,
            beat_id=_str(args, "learning_beat_id"),
            concept_ids=[str(c).strip() for c in raw_concepts],
            pattern_id=_str(args, "pattern_id") or None,
            evidence_type=evidence_type,  # type: ignore[arg-type]
            outcome=outcome,  # type: ignore[arg-type]
            mixed_language=bool(args.get("mixed_language")),
        )
    except ledger.LedgerError as exc:
        return _err(state, cartridge, str(exc))
    if result.records:
        first = result.records[0]
        state.transcript.append(
            EvidenceEntry(
                turn=ctx.turn,
                beat_id=first.beat_id,
                concept_ids=[r.concept_id for r in result.records],
                evidence_type=first.evidence_type,
                outcome=first.outcome,
                stage_after={r.concept_id: r.stage_after for r in result.records},
                support_level=first.support_level,
                input_mode=first.input_mode,
            )
        )
    return _ok(state, cartridge, "; ".join(result.notes) or "recorded")


def exec_set_language_help(
    state: GameState, cartridge: Cartridge, args: dict[str, Any], ctx: ToolContext
) -> str:
    level = args.get("level")
    if isinstance(level, float) and level.is_integer():
        level = int(level)
    if not isinstance(level, int) or isinstance(level, bool):
        return _err(state, cartridge, "level must be an integer 0..5")
    try:
        cue = ledger.set_help_level(state, cartridge, _str(args, "learning_beat_id"), level)
    except ledger.LedgerError as exc:
        return _err(state, cartridge, str(exc))
    return _ok(state, cartridge, f"help now {describe_cue(cue)}")


def exec_advance_beat(
    state: GameState, cartridge: Cartridge, args: dict[str, Any], ctx: ToolContext
) -> str:
    if ctx.advanced:
        return _err(state, cartridge, "a beat was already advanced this turn; stay with this beat")
    finished = ledger.active_beat(state, cartridge)
    try:
        next_beat = ledger.advance_beat(state, cartridge, _str(args, "learning_beat_id"))
    except ledger.LedgerError as exc:
        return _err(state, cartridge, str(exc))
    ctx.advanced = True
    done = finished.id if finished else "?"
    if next_beat is None:
        return _ok(state, cartridge, f"beat {done} complete. EPISODE COMPLETE (final beat).")
    level = state.learning.help_level.get(next_beat.id, 0) if state.learning else 0
    return _ok(
        state, cartridge,
        f"beat {done} complete. New active beat {next_beat.id}: {next_beat.objective} "
        f"(success: {next_beat.success_evidence}; help level {level})",
    )


def _validate_line(
    raw: Any, index: int, cartridge: Cartridge
) -> tuple[dict[str, Any] | None, str | None]:
    where = f"spoken_lines[{index}]"
    if not isinstance(raw, dict):
        return None, f"{where} must be an object"
    speaker, text, language = _str(raw, "speaker"), _str(raw, "text"), _str(raw, "language")
    if cartridge.npc(speaker) is None:
        valid = ", ".join(n.id for n in cartridge.npcs)
        return None, f"{where}.speaker must be an npc id ({valid}), not '{speaker}'"
    if not text:
        return None, f"{where}.text is empty"
    if len(text) > MAX_LINE_CHARS:
        return None, f"{where}.text is too long; keep NPC lines short"
    if not LOCALE_RE.match(language):
        return None, f"{where}.language must be a locale like 'ja-JP', not '{language}'"
    romanization, translation = _str(raw, "romanization"), _str(raw, "translation")
    ll = cartridge.language_learning
    if ll is not None and language == ll.target_locale:
        if not romanization:
            return None, f"{where} is {language}: romanization ({ll.romanization_system}) required"
        if not translation:
            return None, f"{where} is {language}: translation ({ll.support_locale}) required"
    raw_concepts = raw.get("concept_ids") or []
    if not isinstance(raw_concepts, list):
        return None, f"{where}.concept_ids must be a list"
    concept_ids = [str(c).strip() for c in raw_concepts if str(c).strip()]
    for cid in concept_ids:
        if ll is None or ll.concept(cid) is None:
            return None, f"{where}.concept_ids: unknown concept '{cid}'"
    pattern_id = _str(raw, "pattern_id") or None
    if pattern_id is not None and (ll is None or ll.pattern(pattern_id) is None):
        return None, f"{where}.pattern_id: unknown pattern '{pattern_id}'"
    return {
        "speaker": speaker, "text": text, "language": language,
        "romanization": romanization, "translation": translation,
        "concept_ids": list(dict.fromkeys(concept_ids)), "pattern_id": pattern_id,
    }, None


def exec_deliver_narration(
    state: GameState, cartridge: Cartridge, args: dict[str, Any], ctx: ToolContext
) -> str:
    if ctx.round_errors:
        return _err(
            state, cartridge,
            "narration rejected because another call in this response failed ("
            + " | ".join(ctx.round_errors)
            + "). Fix or drop that call, then call deliver_narration again.",
        )
    narration = _str(args, "narration")
    raw_lines = args.get("spoken_lines") or []
    if not isinstance(raw_lines, list):
        return _err(state, cartridge, "spoken_lines must be a list")
    if not narration and not raw_lines:
        return _err(state, cartridge, "give a narration or at least one spoken line")
    if len(narration) > MAX_NARRATION_CHARS:
        return _err(state, cartridge, "narration too long: at most 2 short sentences")
    if len(raw_lines) > MAX_SPOKEN_LINES:
        return _err(state, cartridge, f"at most {MAX_SPOKEN_LINES} spoken lines per turn")
    lines: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_lines):
        line, error = _validate_line(raw, i, cartridge)
        if error is not None:
            return _err(state, cartridge, error)
        assert line is not None
        lines.append(line)
    ctx.terminal = {"narration": narration, "spoken_lines": lines}
    return _ok(state, cartridge, "narration delivered; the turn ends")


Executor = Callable[[GameState, Cartridge, dict[str, Any], ToolContext], str]

EXECUTORS: dict[str, Executor] = {
    "show_object": exec_show_object,
    "give": exec_give,
    "set_fixture": exec_set_fixture,
    "record_language_evidence": exec_record_language_evidence,
    "set_language_help": exec_set_language_help,
    "advance_beat": exec_advance_beat,
    TERMINAL_TOOL: exec_deliver_narration,
}


def execute(
    name: str, state: GameState, cartridge: Cartridge, args: dict[str, Any], ctx: ToolContext
) -> str:
    """Dispatch one tool call. Unknown tools and ledger tools in plain mode are ERRORs."""
    executor = EXECUTORS.get(name)
    if executor is None or (name in LEDGER_TOOLS and cartridge.language_learning is None):
        return _err(state, cartridge, f"unknown tool '{name}'")
    return executor(state, cartridge, args, ctx)


# ---------------------------------------------------------------- declarations


def _enum(values: list[str], description: str) -> dict[str, Any]:
    return {"type": "string", "enum": values, "description": description}


def declaration_schemas(cartridge: Cartridge) -> list[dict[str, Any]]:
    """JSON-schema tool declarations with the cartridge's ids as enums."""
    object_ids = [o.id for o in cartridge.objects]
    npc_ids = [n.id for n in cartridge.npcs]
    fixture_ids = [f.id for f in cartridge.fixtures]
    fixture_states = sorted({s for f in cartridge.fixtures for s in f.states})
    ll = cartridge.language_learning
    decls: list[dict[str, Any]] = []
    if object_ids:
        decls += [
            {
                "name": "show_object",
                "description": (
                    "The NPC gestures with an object so the player can SEE what a word refers "
                    "to. Use it whenever an NPC line names an object (ground the word in the "
                    "world). hold_up/offer/withhold require that the NPC holds the object; "
                    "point works for any object."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "object_id": _enum(object_ids, "Object to gesture with."),
                        "gesture": _enum(list(GESTURES), "Visible gesture."),
                    },
                    "required": ["object_id", "gesture"],
                },
            },
            {
                "name": "give",
                "description": (
                    "Hand an object to someone. This is how the NPC shows she understood a "
                    "request: the world changes. The current holder must be someone else."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "object_id": _enum(object_ids, "Object to hand over."),
                        "to": _enum([PLAYER, *npc_ids], "Recipient."),
                    },
                    "required": ["object_id", "to"],
                },
            },
        ]
    if fixture_ids:
        decls.append(
            {
                "name": "set_fixture",
                "description": "Change a piece of scenery to one of its authored states.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "fixture_id": _enum(fixture_ids, "Fixture to change."),
                        "state": _enum(fixture_states, "New state (must be valid for it)."),
                    },
                    "required": ["fixture_id", "state"],
                },
            }
        )
    if ll is not None:
        beat_ids = [b.id for b in ll.learning_beats]
        concept_ids = [c.id for c in ll.concepts]
        pattern_ids = [p.id for p in ll.patterns]
        decls += [
            {
                "name": "record_language_evidence",
                "description": (
                    "Record what THIS player attempt showed, at most once per attempt, only "
                    "if the attempt contains some target language (the word or the request "
                    "pattern; English may be mixed in). An English-only request is not "
                    "evidence. concept_ids = the object the player actually asked about or "
                    "for, never one they did not ask for. recognized = the player connected "
                    "a word to its object (said it back, asked about it, tapped it). "
                    "produced = the player asked for the beat's object with the request "
                    "(fragments and mixed language count). transferred = the player reused "
                    "the request pattern with a NEW object. outcome not_understood only when "
                    "the intent is truly unclear. The server decides stages and support level."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "learning_beat_id": _enum(beat_ids, "Must be the ACTIVE beat."),
                        "concept_ids": {
                            "type": "array",
                            "items": _enum(concept_ids, "Concept the attempt used or showed."),
                            "description": (
                                "What the PLAYER used or pointed at, normally just the object "
                                "concept. Never words that only the NPC said."
                            ),
                        },
                        "pattern_id": _enum(
                            pattern_ids, "The request pattern (for produced/transferred)."
                        ),
                        "evidence_type": _enum(list(EVIDENCE_TYPES), "What the attempt showed."),
                        "outcome": _enum(list(OUTCOMES), "Whether the NPC understood."),
                        "mixed_language": {
                            "type": "boolean",
                            "description": "True if the attempt mixed English and the target.",
                        },
                    },
                    "required": [
                        "learning_beat_id", "concept_ids", "evidence_type", "outcome",
                        "mixed_language",
                    ],
                },
            },
            {
                "name": "set_language_help",
                "description": (
                    "Raise visible help by one level (never skips, never lowers). Use only "
                    "when the player explicitly asks for help or is clearly lost."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "learning_beat_id": _enum(beat_ids, "Must be the ACTIVE beat."),
                        "level": {"type": "integer", "description": "current or current+1"},
                    },
                    "required": ["learning_beat_id", "level"],
                },
            },
            {
                "name": "advance_beat",
                "description": (
                    "Complete the ACTIVE learning beat once its world result is committed and "
                    "its evidence is recorded (call it after those calls, in the same "
                    "response). At most once per turn."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"learning_beat_id": _enum(beat_ids, "The ACTIVE beat.")},
                    "required": ["learning_beat_id"],
                },
            },
        ]
    line_props: dict[str, Any] = {
        "speaker": _enum(npc_ids, "NPC id."),
        "text": {"type": "string", "description": "Exactly what the NPC says (native script)."},
        "language": {"type": "string", "description": "Locale of the text, e.g. ja-JP."},
        "romanization": {
            "type": "string",
            "description": "Pronunciation line for target-language text (required for it).",
        },
        "translation": {
            "type": "string",
            "description": "Natural support-language translation (required for target text).",
        },
    }
    if ll is not None:
        line_props["concept_ids"] = {
            "type": "array",
            "items": _enum([c.id for c in ll.concepts], "Concept spoken in this line."),
            "description": "Every authored concept whose word appears in the line.",
        }
        if ll.patterns:
            line_props["pattern_id"] = _enum(
                [p.id for p in ll.patterns],
                "Set ONLY when the line itself contains the pattern (e.g. ...をください).",
            )
    decls.append(
        {
            "name": TERMINAL_TOOL,
            "description": (
                "TERMINAL: ends the turn. Call it in the SAME response as your other tool "
                "calls, after them. narration = support-language orientation, at most 2 "
                "short sentences. spoken_lines = the NPC's short lines."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "narration": {"type": "string", "description": "<= 2 short sentences."},
                    "spoken_lines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": line_props,
                            "required": [
                                k for k in line_props if k not in ("pattern_id",)
                            ],
                        },
                    },
                },
                "required": ["narration", "spoken_lines"],
            },
        }
    )
    return decls


def tool_declarations(cartridge: Cartridge) -> list[Any]:
    """Gemini ``types.Tool`` list for the DM loop."""
    from google.genai import types

    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name=d["name"],
                    description=d["description"],
                    parameters_json_schema=d["parameters"],
                )
                for d in declaration_schemas(cartridge)
            ]
        )
    ]
