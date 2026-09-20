"""Character tool declarations (Gemini) and deterministic executors.

Every executor has the shape ``(journey, args, ctx) -> receipt`` and mutates the scene run only
after validating every id. Invalid calls return ``"ERROR: ..."`` receipts so the model retries
inside the same loop. Every receipt ends with a NOW line.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from core import game, vocab
from core.content import (
    SUPPORT_LANGUAGE,
    TRUST_MAX,
    TRUST_MIN,
    GoalWhen,
    Item,
    Language,
    Scene,
    is_latin,
)
from core.state import (
    Attempt,
    ClueEntry,
    ClueView,
    Journey,
    SceneEventEntry,
    SceneRun,
    Segment,
)

TERMINAL_TOOL = "say"
RESULTS = ("understood", "missed")
MAX_LINES = 3
MAX_WORD_SEGMENTS = 14
MAX_NARRATION_WORDS = 60  # the GM is told 45; the slack keeps a good turn from bouncing
MAX_HINT_WORDS = 16


@dataclass
class ToolContext:
    """Per-turn execution context. ``attempt`` is None for the opening."""

    scene: Scene
    language: Language
    attempt: Attempt | None = None
    trust_adjusted: bool = False
    round_errors: list[str] = field(default_factory=list)
    terminal: dict[str, Any] | None = None


# ---------------------------------------------------------------- receipts


def _run(journey: Journey) -> SceneRun:
    if journey.scene is None:
        raise ValueError("no scene in progress")
    return journey.scene


def now_line(journey: Journey, scene: Scene) -> str:
    """Compact committed-state summary appended to every receipt."""
    run, state = _run(journey), journey.game
    goals = ", ".join(
        f"{g.id}={'done' if g.id in run.goals_done else 'open'}" for g in scene.goals
    )
    return (f"NOW goals: {goals} | trust: {game.trust(journey, scene)} | clues: "
            f"{', '.join(state.clues) or '-'} | flags: {', '.join(state.flags) or '-'}")


def complete_ready_goals(journey: Journey, scene: Scene) -> list[str]:
    """Goals complete themselves the moment their condition holds. Returns the new ones."""
    run = _run(journey)
    done: list[str] = []
    for goal in scene.goals:
        if goal.id not in run.goals_done and goal.when.holds(
                journey.game.clues, journey.game.flags):
            run.goals_done.append(goal.id)
            run.transcript.append(
                SceneEventEntry(turn=run.turn, event="goal_done", goal_id=goal.id))
            done.append(goal.id)
    return done


def _goal_note(journey: Journey, scene: Scene) -> str:
    done = complete_ready_goals(journey, scene)
    if not done:
        return ""
    left = [g.id for g in scene.goals if g.id not in _run(journey).goals_done]
    tail = f"still open: {', '.join(left)}" if left else "ALL GOALS DONE: this act ends with your say"
    return f" Goal done: {', '.join(done)} ({tail})."


def _int(args: dict[str, Any], key: str) -> int | None:
    value = args.get(key)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _ok(journey: Journey, ctx: ToolContext, message: str) -> str:
    return f"OK: {message}\n{now_line(journey, ctx.scene)}"


def _err(journey: Journey, ctx: ToolContext, message: str) -> str:
    return f"ERROR: {message}\n{now_line(journey, ctx.scene)}"


def is_error(receipt: str) -> bool:
    return receipt.startswith("ERROR")


def _str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    return value.strip() if isinstance(value, str) else ""


def _str_list(raw: Any) -> list[str] | None:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    return list(dict.fromkeys(str(v).strip() for v in raw if str(v).strip()))


# ---------------------------------------------------------------- executors


def _squash(text: str) -> str:
    """Letters and digits only, no marks, no case: how typed and heard input is compared."""
    plain = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in plain if ch.isalnum() and not unicodedata.combining(ch)).casefold()


def player_said(attempt: Attempt, item: Item) -> bool:
    """True when the player's own input really contains the word: in its script, or in its
    romanization however they typed it (no marks, any spacing), or as the recognizer heard it.
    A word of their own language that merely MEANS it does not count."""
    heard = [_squash(attempt.transcript), _squash(attempt.romanized or "")]
    forms = [[_squash(part) for part in item.parts]]
    if item.roman:
        forms.append([_squash(item.roman)])
    return any(all(part and part in source for part in form)
               for form in forms for source in heard if source)


def exec_record_item(journey: Journey, args: dict[str, Any], ctx: ToolContext) -> str:
    attempt = ctx.attempt
    if attempt is None:
        return _err(journey, ctx, "no learner attempt this turn; there is nothing to record")
    item_id, result = _str(args, "item_id"), _str(args, "result")
    if item_id not in ctx.scene.targets:
        valid = ", ".join(ctx.scene.targets)
        return _err(journey, ctx, f"'{item_id}' is not a target of this scene. Targets: {valid}")
    if result not in RESULTS:
        return _err(journey, ctx, f"result must be one of {', '.join(RESULTS)}")
    exchange = _run(journey).exchange
    produced = bool(args.get("produced"))
    if produced and not player_said(attempt, ctx.language.items[item_id]):
        return _ok(journey, ctx, f"nothing recorded for {item_id}: the player's own words do "
                                 "not contain it (a foreign word that means it is not it)")
    language = ctx.language
    if not any(player_said(attempt, item) for item in language.items.values()):
        return _ok(journey, ctx, f"nothing recorded for {item_id}: nothing the player said is "
                                 f"{language.name}, so it shows nothing about their {language.name}")
    if not produced and item_id not in exchange.posed_item_ids:
        return _ok(journey, ctx, f"nothing recorded for {item_id}: they did not say it, and it "
                                 "was not in your last lines for them to act on")
    stamped, is_new = vocab.record_result(
        journey, item_id=item_id, understood=result == "understood", produced=produced,
        attempt_id=attempt.attempt_id,
    )
    if not is_new:
        return _ok(journey, ctx, f"{item_id} already recorded for this attempt (no change)")
    state = journey.record(item_id).state
    recall = " RECALL from an earlier scene." if stamped.recall else ""
    return _ok(journey, ctx, f"{item_id}: {stamped.outcome} -> {state}.{recall}")


def exec_adjust_trust(journey: Journey, args: dict[str, Any], ctx: ToolContext) -> str:
    if ctx.attempt is None:
        return _err(journey, ctx, "trust moves in response to what the player does; not yet")
    delta = _int(args, "delta")
    if delta not in (-1, 1):
        return _err(journey, ctx, "delta must be -1 or 1")
    if not _str(args, "reason"):
        return _err(journey, ctx, "give the reason: what did the player just do?")
    if ctx.trust_adjusted:
        return _ok(journey, ctx, "trust already moved this turn (no change)")
    ctx.trust_adjusted = True
    before = game.trust(journey, ctx.scene)
    after = max(TRUST_MIN, min(TRUST_MAX, before + delta))
    journey.game.trust[ctx.scene.id] = after
    openable = [c.id for c in ctx.scene.clues
                if c.id not in journey.game.clues and game.can_reveal(journey, ctx.scene, c)]
    note = f" You may now reveal: {', '.join(openable)}." if openable else ""
    return _ok(journey, ctx, f"trust {before} -> {after}.{note}")


def exec_reveal_clue(journey: Journey, args: dict[str, Any], ctx: ToolContext) -> str:
    scene = ctx.scene
    clue = scene.clue(_str(args, "clue_id"))
    if clue is None:
        valid = ", ".join(c.id for c in scene.clues)
        return _err(journey, ctx, f"unknown clue_id '{_str(args, 'clue_id')}'. Valid: {valid}")
    if clue.id in journey.game.clues:
        return _ok(journey, ctx, f"clue {clue.id} is already known (no change)")
    if not game.can_reveal(journey, scene, clue):
        ways = " OR ".join(", ".join(game.unmet(journey, scene, w)) for w in clue.reveal_when)
        return _err(
            journey, ctx,
            f"clue {clue.id} stays secret: it still needs {ways}. Your character would not say "
            "it yet. Do not hint at its content in narration or lines; play the reluctance",
        )
    run = _run(journey)
    journey.game.clues.append(clue.id)
    run.transcript.append(
        ClueEntry(turn=run.turn, clue=ClueView(id=clue.id, title=clue.title, text=clue.text)))
    return _ok(journey, ctx, f"clue {clue.id} is in the player's notebook."
                             f"{_goal_note(journey, scene)}")


def exec_set_flag(journey: Journey, args: dict[str, Any], ctx: ToolContext) -> str:
    flag = ctx.scene.flag(_str(args, "flag"))
    if flag is None:
        valid = ", ".join(f.id for f in ctx.scene.flags)
        return _err(journey, ctx, f"unknown flag '{_str(args, 'flag')}'. Valid: {valid}")
    if flag.id in journey.game.flags:
        return _ok(journey, ctx, f"flag {flag.id} is already set (no change)")
    journey.game.flags.append(flag.id)
    openable = [c.id for c in ctx.scene.clues
                if c.id not in journey.game.clues and game.can_reveal(journey, ctx.scene, c)]
    note = f" You may now reveal: {', '.join(openable)}." if openable else ""
    return _ok(journey, ctx, f"flag {flag.id} set.{note}{_goal_note(journey, ctx.scene)}")


def describe_when(when: GoalWhen) -> str:
    """Plain-words goal condition for receipts and the snapshot."""
    clauses: list[str] = []
    if when.clue is not None:
        clauses.append(f"clue {when.clue} revealed")
    if when.flag is not None:
        clauses.append(f"flag {when.flag} set")
    return " and ".join(clauses)


def is_word(text: str) -> bool:
    """True when a segment carries letters or digits (so it is spoken, not punctuation)."""
    return any(unicodedata.category(ch)[0] in "LN" for ch in text)


def is_clean_word(text: str) -> bool:
    """A word segment holds the word only: letters, digits, marks and in-word joiners
    (apostrophe, hyphen, middle dot). Sentence punctuation belongs in its own segment."""
    return all(
        unicodedata.category(ch)[0] in "LNM" or unicodedata.category(ch) == "Pd"
        or ch in "'’·"
        for ch in text
    )


def spoken(segments: Sequence[Any], part: str, word_spacing: bool) -> bool:
    """True when ``part`` is one segment (or, in a spaced language, a run of whole segments)."""
    texts = [s.t for s in segments]
    if not word_spacing:
        return part in texts
    wanted = part.split()
    return any(texts[i:i + len(wanted)] == wanted for i in range(len(texts)))


def _validate_line(
    raw: Any, index: int, ctx: ToolContext
) -> tuple[dict[str, Any] | None, str | None]:
    where = f"lines[{index}]"
    scene, romanized = ctx.scene, ctx.language.romanization is not None
    if not isinstance(raw, dict):
        return None, f"{where} must be an object"
    raw_segments = raw.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        return None, f"{where}.segments needs at least one segment"
    segments: list[Segment] = []
    for j, seg in enumerate(raw_segments):
        text = seg.get("t") if isinstance(seg, dict) else None
        if not isinstance(text, str) or not text.strip():
            return None, f"{where}.segments[{j}].t is empty"
        if is_word(text) and not is_clean_word(text.strip()):
            return None, (
                f"{where}.segments[{j}] '{text.strip()}' mixes a word with punctuation: one "
                "segment per word, each punctuation mark in its own segment"
            )
        if not ctx.language.latin_script and any(is_latin(ch) for ch in text):
            return None, (
                f"{where}.segments[{j}].t '{text.strip()}' holds Latin letters: t is "
                f"{ctx.language.name} in its own script only; romanization goes in r"
            )
        roman = _str(seg, "r") if romanized else ""
        if romanized and is_word(text) and not roman:
            return None, (
                f"{where}.segments[{j}] '{text.strip()}' is a word: give its "
                f"{ctx.language.romanization.system} in r"  # type: ignore[union-attr]
            )
        segments.append(Segment(t=text.strip(), r=roman if is_word(text) else ""))
    if romanized:  # a lexicon word's romanization is the lexicon's, however the model wrote it
        lexicon = {item.text: item.roman for item in ctx.language.items.values()}
        segments = [Segment(t=s.t, r=lexicon.get(s.t, s.r)) for s in segments]
    words = sum(1 for s in segments if is_word(s.t))
    if words == 0:
        return None, f"{where} has no words"
    if words > MAX_WORD_SEGMENTS:
        return None, f"{where} is too long ({words} words): say less, at most 8 words a line"
    item_ids = _str_list(raw.get("item_ids"))
    if item_ids is None:
        return None, f"{where}.item_ids must be a list"
    for item_id in item_ids:
        if item_id not in scene.item_ids:
            return None, f"{where}.item_ids: unknown item '{item_id}'"
    # The ledger counts a listed word only when it was really said: one segment (each part,
    # for a frame) spelled as the lexicon spells it. A tag without the word is dropped, a word
    # without its tag is added; neither is worth bouncing the turn.
    item_ids = [
        i for i in scene.item_ids
        if all(spoken(segments, p, ctx.language.word_spacing)
               for p in ctx.language.items[i].parts)
    ]
    return {"segments": segments, "item_ids": item_ids}, None


def exec_say(journey: Journey, args: dict[str, Any], ctx: ToolContext) -> str:
    if ctx.round_errors:
        return _err(
            journey, ctx,
            "say rejected because another call in this response failed ("
            + " | ".join(ctx.round_errors)
            + "). Fix or drop that call, then call say again.",
        )
    raw_lines = args.get("lines")
    if not isinstance(raw_lines, list) or not 1 <= len(raw_lines) <= MAX_LINES:
        return _err(journey, ctx, f"lines must hold 1 to {MAX_LINES} lines")
    lines: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_lines):
        line, error = _validate_line(raw, i, ctx)
        if error is not None or line is None:
            return _err(journey, ctx, error or "invalid line")
        lines.append(line)
    spoken_items = {i for line in lines for i in line["item_ids"]}
    for clue in ctx.scene.clues:  # a clue's giveaway words may only be spoken once it is out
        said = [i for i in clue.key_items if i in spoken_items]
        if said and clue.id not in journey.game.clues:
            if game.can_reveal(journey, ctx.scene, clue):
                return _err(journey, ctx, f"your lines give away clue {clue.id}: call "
                                          f"reveal_clue({clue.id}) in this same response")
            words = ", ".join(ctx.language.items[i].text for i in said)
            return _err(journey, ctx, f"clue {clue.id} is still LOCKED, so your character would "
                                      f"not say {words} yet. Deflect instead")
    narration, hint = _str(args, "narration"), _str(args, "intent_hint")
    if not narration:
        return _err(journey, ctx, "narration is required: every turn the story's voice speaks")
    if len(narration.split()) > MAX_NARRATION_WORDS:
        return _err(journey, ctx, "narration is too long: 1-3 short sentences, at most 45 words")
    if not hint:
        return _err(journey, ctx, "intent_hint is required: what do you want from the learner?")
    if len(hint.split()) > MAX_HINT_WORDS:
        return _err(journey, ctx, f"intent_hint: at most {MAX_HINT_WORDS} words")
    ctx.terminal = {"lines": lines, "narration": narration, "intent_hint": hint}
    return _ok(journey, ctx, "said; the turn ends")


Executor = Callable[[Journey, dict[str, Any], ToolContext], str]

EXECUTORS: dict[str, Executor] = {
    "adjust_trust": exec_adjust_trust,
    "reveal_clue": exec_reveal_clue,
    "set_flag": exec_set_flag,
    "record_item": exec_record_item,
    TERMINAL_TOOL: exec_say,
}


def execute(name: str, journey: Journey, args: dict[str, Any], ctx: ToolContext) -> str:
    """Dispatch one tool call. Unknown tools are ERRORs."""
    executor = EXECUTORS.get(name)
    if executor is None:
        return _err(journey, ctx, f"unknown tool '{name}'. Tools: {', '.join(EXECUTORS)}")
    return executor(journey, args, ctx)


# ---------------------------------------------------------------- declarations


def _enum(values: list[str], description: str) -> dict[str, Any]:
    return {"type": "string", "enum": values, "description": description}


def declaration_schemas(scene: Scene, language: Language) -> list[dict[str, Any]]:
    """JSON-schema tool declarations with this scene's ids as enums."""
    roman = language.romanization
    r_description = (
        f"{roman.system} for this word, with its proper marks. \"\" for punctuation."
        if roman is not None
        else 'Always "".'
    )
    line = {
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "description": (
                    "The line split into words and punctuation marks, in order. One segment "
                    "per dictionary word, never per syllable or character; each punctuation "
                    "mark is its own segment. A word from the word list is exactly ONE "
                    "segment, spelled exactly as listed."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "t": {"type": "string",
                              "description": f"The word in {language.name}, native script."},
                        "r": {"type": "string", "description": r_description},
                    },
                    "required": ["t", "r"],
                },
            },
            "item_ids": {
                "type": "array",
                "items": _enum(scene.item_ids, "Item whose word is spoken in this line."),
                "description": "Every listed item whose word you actually say in this line.",
            },
        },
        "required": ["segments", "item_ids"],
    }
    flag_ids = [f.id for f in scene.flags]
    clue_ids = [c.id for c in scene.clues]
    decls: list[dict[str, Any]] = [
        {
            "name": "adjust_trust",
            "description": (
                "How your character feels about the player just moved, because of what they "
                "just did: +1 for good company, joining in, nerve you admire, kindness, "
                "getting behind the team; -1 for rudeness, shouting in a foreign language, "
                "sneering at the match, pushing too hard. At most once per turn; most turns, "
                "not at all."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "delta": {"type": "integer", "enum": [-1, 1]},
                    "reason": {"type": "string", "description": "What the player did."},
                },
                "required": ["delta", "reason"],
            },
        },
        {
            "name": "record_item",
            "description": (
                "Note what THIS player attempt showed about one target word. FIRST: input in a "
                "language you do not understand, or speech you are unsure you heard, shows "
                "nothing at all: record nothing for it, not even missed (a foreign word that "
                "happens to MEAN a listed word is still a foreign word). understood = "
                "they used the word themselves (any spelling, romanized, bad pronunciation, "
                "bare word) or answered correctly a word you had just said. missed = ONLY a "
                "clearly wrong answer to a word you had just put to them. One call per word "
                "the attempt clearly involved; a word that only occurs inside a longer listed "
                "phrase they said counts for the phrase, not separately. The server decides "
                "what the result is worth. Never let this shape the story."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": _enum(list(scene.targets), "The target word."),
                    "result": _enum(list(RESULTS), "What the attempt showed."),
                    "produced": {
                        "type": "boolean",
                        "description": "True only if the player said or typed the word itself.",
                    },
                },
                "required": ["item_id", "result", "produced"],
            },
        },
    ]
    if clue_ids:
        decls.append({
            "name": "reveal_clue",
            "description": (
                "Your character gives up something they know: it goes into the player's "
                "notebook. The server refuses a clue whose conditions do not hold yet. Call "
                "it in the same response in which your lines and narration let it out."
            ),
            "parameters": {
                "type": "object",
                "properties": {"clue_id": _enum(clue_ids, "The clue that comes out.")},
                "required": ["clue_id"],
            },
        })
    if flag_ids:
        decls.append({
            "name": "set_flag",
            "description": "Mark that one of the scene's authored events has now happened.",
            "parameters": {
                "type": "object",
                "properties": {"flag": _enum(flag_ids, "The event that just happened.")},
                "required": ["flag"],
            },
        })
    decls.append({
        "name": TERMINAL_TOOL,
        "description": (
            "TERMINAL: the turn the player sees. Call it in the SAME response as your other "
            f"calls, after them. narration is the story's voice in {SUPPORT_LANGUAGE}; lines "
            f"are what your character says out loud, in {language.name} only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "narration": {
                    "type": "string",
                    "description": (
                        f"Required. {SUPPORT_LANGUAGE}, second person, present tense, the "
                        "player's own inner voice: 1-3 short sentences, at most 45 words. "
                        "What happens, what it feels like. Never a word-for-word translation "
                        "of your lines."
                    ),
                },
                "lines": {"type": "array", "items": line, "minItems": 1, "maxItems": MAX_LINES,
                          "description": f"1-{MAX_LINES} spoken lines."},
                "intent_hint": {
                    "type": "string",
                    "description": (
                        f"Required. {SUPPORT_LANGUAGE}, at most 14 words: what your "
                        "character wants from the player right now. Intent only: never "
                        "quote your words, never pair a word with its meaning."
                    ),
                },
            },
            "required": ["narration", "lines", "intent_hint"],
        },
    })
    return decls


def tool_declarations(scene: Scene, language: Language) -> list[Any]:
    """Gemini ``types.Tool`` list for the turn loop."""
    from google.genai import types

    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name=d["name"], description=d["description"],
                    parameters_json_schema=d["parameters"],
                )
                for d in declaration_schemas(scene, language)
            ]
        )
    ]
