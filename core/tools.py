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
    NEUTRAL_MOOD,
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
    LearnerEntry,
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
    # Items mastered when the turn began. The highlight gate judges against what the snapshot
    # told the model, not against results recorded earlier in the same response.
    mastered: frozenset[str] = frozenset()
    # Words owed an unsupported pass when the turn began (see vocab.owed_items).
    owed: tuple[str, ...] = ()
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
    zones = ", ".join(f"{oid}={zone}" for oid, zone in run.zones.items())
    goals = ", ".join(
        f"{g.id}={'done' if g.id in run.goals_done else 'open'}" for g in scene.goals
    )
    return (f"NOW zones: {zones} | goals: {goals} | wallet: {state.wallet} | trust: "
            f"{game.trust(journey, scene)} | clues: {', '.join(state.clues) or '-'} | flags: "
            f"{', '.join(state.flags) or '-'} | mood: {run.mood}")


def complete_ready_goals(journey: Journey, scene: Scene) -> list[str]:
    """Goals complete themselves the moment their condition holds. Returns the new ones."""
    run = _run(journey)
    done: list[str] = []
    for goal in scene.goals:
        if goal.id not in run.goals_done and goal.when.holds(
                run.zones, journey.game.clues, journey.game.flags):
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


def exec_move_object(journey: Journey, args: dict[str, Any], ctx: ToolContext) -> str:
    run, scene = _run(journey), ctx.scene
    oid, zone = _str(args, "object_id"), _str(args, "to_zone")
    obj = scene.object(oid)
    if obj is None:
        valid = ", ".join(o.id for o in scene.objects)
        return _err(journey, ctx, f"unknown object_id '{oid}'. Valid: {valid}")
    if zone not in scene.zones:
        return _err(journey, ctx, f"unknown to_zone '{zone}'. Valid: {', '.join(scene.zones)}")
    if not obj.can_be_in(zone):
        places = ", ".join(z for z in scene.zones if obj.can_be_in(z))
        return _err(journey, ctx, f"{oid} has no place in '{zone}'. It can be in: {places}")
    before = run.zones.get(oid, obj.zone)
    if before == zone:
        return _ok(journey, ctx, f"{oid} is already in {zone} (no change)")
    run.zones[oid] = zone
    run.transcript.append(
        SceneEventEntry(turn=run.turn, event="object_moved", object_id=oid,
                        from_zone=before, to_zone=zone)
    )
    unlit = " It is out of sight now: do not light it up." if zone == "gone" else ""
    return _ok(journey, ctx, f"{oid} moved {before} -> {zone}.{unlit}{_goal_note(journey, scene)}")


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
    produced = bool(args.get("produced")) and attempt.input_mode != "tap"
    if produced and not player_said(attempt, ctx.language.items[item_id]):
        return _ok(journey, ctx, f"nothing recorded for {item_id}: the player's own words do "
                                 "not contain it (a foreign word that means it is not it)")
    language = ctx.language
    if attempt.input_mode != "tap" and not any(
            player_said(attempt, item) for item in language.items.values()):
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


def exec_pay(journey: Journey, args: dict[str, Any], ctx: ToolContext) -> str:
    if ctx.attempt is None:
        return _err(journey, ctx, "the player has not done anything yet; nobody pays in the opening")
    scene, state = ctx.scene, journey.game
    amount, tip = _int(args, "amount"), bool(args.get("tip"))
    object_ids = _str_list(args.get("for_object_ids")) or []
    if amount is None or amount <= 0:
        return _err(journey, ctx, "amount must be a positive whole number")
    priced: dict[str, int] = {}
    for oid in object_ids:
        price = game.price_of(journey, scene, oid)
        if price is None:
            return _err(journey, ctx, f"'{oid}' is not something with a price here")
        priced[oid] = price
    if not tip and not priced:
        return _err(journey, ctx, "say what is being paid for (for_object_ids), or set tip=true")
    if not tip and amount != sum(priced.values()):
        owed = " + ".join(f"{oid} {p}" for oid, p in priced.items())
        return _err(journey, ctx, f"amount must equal the current prices: {owed} = "
                                  f"{sum(priced.values())} (haggle with set_price first)")
    if amount > state.wallet:
        return _err(journey, ctx, f"the player only has {state.wallet}: they cannot pay {amount}. "
                                  "Nothing was paid; play that moment instead")
    state.wallet -= amount
    state.spent += amount
    _run(journey).spent += amount
    paid = state.paid_for.setdefault(scene.id, [])
    paid += [oid for oid in priced if oid not in paid]
    what = ", ".join(priced) if priced else "a tip"
    return _ok(journey, ctx, f"paid {amount} for {what}; the player has {state.wallet} left")


def exec_set_price(journey: Journey, args: dict[str, Any], ctx: ToolContext) -> str:
    obj, amount = ctx.scene.object(_str(args, "object_id")), _int(args, "amount")
    if obj is None or obj.price is None:
        return _err(journey, ctx, f"'{_str(args, 'object_id')}' is not something with a price")
    if obj.price_floor is None:
        return _err(journey, ctx, f"the price of {obj.id} is fixed at {obj.price}: no haggling")
    if amount is None or not obj.price_floor <= amount <= obj.price:
        return _err(journey, ctx, f"{obj.id} can go no lower than {obj.price_floor} and no higher "
                                  f"than {obj.price}; hold the line at {obj.price_floor}")
    journey.game.prices.setdefault(ctx.scene.id, {})[obj.id] = amount
    return _ok(journey, ctx, f"{obj.id} now costs {amount}")


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
    paid = journey.game.paid_for.get(ctx.scene.id, [])
    if flag.requires_paid and not any(o in paid for o in flag.requires_paid):
        return _err(journey, ctx, f"flag {flag.id} needs {' or '.join(flag.requires_paid)} paid "
                                  "for first (the pay tool, in this same response, before "
                                  "set_flag). It has not happened yet; play what did")
    journey.game.flags.append(flag.id)
    openable = [c.id for c in ctx.scene.clues
                if c.id not in journey.game.clues and game.can_reveal(journey, ctx.scene, c)]
    note = f" You may now reveal: {', '.join(openable)}." if openable else ""
    return _ok(journey, ctx, f"flag {flag.id} set.{note}{_goal_note(journey, ctx.scene)}")


def describe_when(when: GoalWhen) -> str:
    """Plain-words goal condition for receipts and the snapshot."""
    clauses = [f"{oid} in {zone}" for oid, zone in when.in_zone.items()]
    if when.clue is not None:
        clauses.append(f"clue {when.clue} revealed")
    if when.flag is not None:
        clauses.append(f"flag {when.flag} set")
    if when.any_in_zone is not None:
        clauses.append(
            f"any of {'/'.join(when.any_in_zone.objects)} in {when.any_in_zone.zone}"
        )
    return " and ".join(clauses)


def is_word(text: str) -> bool:
    """True when a segment carries letters or digits (so it is spoken, not punctuation)."""
    return any(unicodedata.category(ch)[0] in "LN" for ch in text)


def is_clean_word(text: str) -> bool:
    """A word segment holds the word only: letters, digits, marks and in-word joiners
    (apostrophe, hyphen, middle dot). Sentence punctuation belongs in its own segment."""
    return all(
        unicodedata.category(ch)[0] in "LNM" or unicodedata.category(ch) == "Pd"
        or ch in "'\u2019\u00b7"
        for ch in text
    )


def spoken(segments: Sequence[Any], part: str, word_spacing: bool) -> bool:
    """True when ``part`` is one segment (or, in a spaced language, a run of whole segments)."""
    texts = [s.t for s in segments]
    if not word_spacing:
        return part in texts
    wanted = part.split()
    return any(texts[i:i + len(wanted)] == wanted for i in range(len(texts)))


def _has_been_out(run: SceneRun, object_id: str) -> bool:
    """True once the player has used the object or it has changed hands in this act."""
    return any(
        (isinstance(e, LearnerEntry) and e.tapped_object_id == object_id)
        or (isinstance(e, SceneEventEntry) and e.object_id == object_id)
        for e in run.transcript
    )


def _validate_line(
    journey: Journey, raw: Any, index: int, ctx: ToolContext
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
    item_ids, object_ids = _str_list(raw.get("item_ids")), _str_list(raw.get("highlight_object_ids"))
    if item_ids is None or object_ids is None:
        return None, f"{where}.item_ids and highlight_object_ids must be lists"
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
    run = _run(journey)
    for oid in object_ids:
        obj = scene.object(oid)
        if obj is None:
            valid = ", ".join(o.id for o in scene.objects)
            return None, f"{where}.highlight_object_ids: unknown object '{oid}'. Valid: {valid}"
        if run.zones.get(oid) == "gone":
            return None, f"{where}: {oid} is gone and cannot be highlighted"
        if (run.zones.get(oid) == "inventory" and "pay" not in obj.actions
                and not _has_been_out(run, oid)):
            return None, (
                f"{where}: {oid} is still in the player's pocket. Your character has never "
                "seen it and cannot point at it; drop that highlight"
            )
        if obj.item_id not in item_ids:
            return None, (
                f"{where} highlights {oid} but does not say its word "
                f"({ctx.language.items[obj.item_id].text}). A highlight means \"this word is "
                "that thing\": light an object only on a line that names it, or drop the highlight"
            )
        if obj.item_id in ctx.mastered:
            return None, (
                f"{where}: {oid} cannot be highlighted: this learner has mastered "
                f"'{obj.item_id}'. mastered: present it with no highlight"
            )
    return {"segments": segments, "item_ids": item_ids, "highlight_object_ids": object_ids}, None


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
        line, error = _validate_line(journey, raw, i, ctx)
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
    mood = _str(args, "mood") or NEUTRAL_MOOD
    if mood not in ctx.scene.moods:
        return _err(journey, ctx, f"mood must be one of {', '.join(ctx.scene.moods)}")
    ctx.terminal = {"lines": lines, "narration": narration, "intent_hint": hint, "mood": mood}
    return _ok(journey, ctx, "said; the turn ends")


Executor = Callable[[Journey, dict[str, Any], ToolContext], str]

EXECUTORS: dict[str, Executor] = {
    "move_object": exec_move_object,
    "pay": exec_pay,
    "set_price": exec_set_price,
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
    object_ids = [o.id for o in scene.objects]
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
            "highlight_object_ids": {
                "type": "array",
                "items": _enum(object_ids, "Object to light up while this line plays."),
                "description": (
                    "Objects the learner sees light up during THIS line. A highlight tells "
                    "them \"this word is that thing\", so light an object ONLY on a line "
                    "that says that object's own word (a line that is just a price, a "
                    "thank-you or 'this one' lights nothing). Follow each word's "
                    "presentation guidance; a mastered word's object is refused."
                ),
            },
        },
        "required": ["segments", "item_ids", "highlight_object_ids"],
    }
    flag_ids = [f.id for f in scene.flags]
    clue_ids = [c.id for c in scene.clues]
    priced = [o.id for o in scene.objects if o.price is not None]
    haggle = [o.id for o in scene.objects if o.price_floor is not None]
    decls: list[dict[str, Any]] = [
        {
            "name": "move_object",
            "description": (
                "Something physically happens to an object: you serve it (to counter), take "
                "it back (to display), take something the player hands you (to npc), hand "
                "them something to keep (to inventory), it is eaten, drunk or cleared away "
                "(to gone). This is how the player SEES what happened. Only move what the "
                "moment really calls for."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_id": _enum(object_ids, "Object that moves."),
                    "to_zone": _enum(list(scene.zones), "Where it ends up."),
                },
                "required": ["object_id", "to_zone"],
            },
        },
        {
            "name": "pay",
            "description": (
                "The player pays you. Only when they have handed money over or clearly agreed "
                "to pay. amount must equal the current prices of for_object_ids (after any "
                "set_price), unless tip=true. The server refuses what they cannot afford: "
                "then nothing was paid, and you play that moment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "integer", "description": "Cash that changes hands."},
                    "for_object_ids": {"type": "array", "items": _enum(priced, "Paid for."),
                                       "description": "What this payment settles."},
                    "tip": {"type": "boolean", "description": "True for money beyond prices."},
                },
                "required": ["amount", "for_object_ids"],
            },
        },
        {
            "name": "adjust_trust",
            "description": (
                "How your character feels about the player just moved, because of what they "
                "just did: +1 for manners, paying without fuss, good company, nerve you "
                "admire, kindness; -1 for rudeness, shouting in a foreign language, trying to "
                "cheat, pushing too hard. At most once per turn; most turns, not at all."
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
                "bare word) or acted correctly on a word you had just said (answered it, "
                "pointed at the right thing). missed = ONLY a wrong ACTION: you had just put "
                "that word to them and they pointed at, or asked for, the wrong thing. One "
                "call per word the attempt clearly involved; a word that only occurs inside a "
                "longer listed phrase they said counts for the phrase, not separately. The "
                "server decides what the result is worth. Never let this shape the story."
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
    if haggle:
        decls.append({
            "name": "set_price",
            "description": (
                "Haggling: your character names a new price for something. Call it in the "
                "SAME turn the new price is spoken, so the price tag the player sees matches "
                "what they heard. The server holds you to your floor and your asking price. "
                "Come down only when the player actually pushes back, and make them work "
                "for it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_id": _enum(haggle, "What is being haggled over."),
                    "amount": {"type": "integer", "description": "The newly agreed price."},
                },
                "required": ["object_id", "amount"],
            },
        })
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
                        "What happens, what it costs, what it feels like. Never a "
                        "word-for-word translation of your lines."
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
                "mood": _enum(
                    scene.moods,
                    "Your character's visible expression as the turn ends. puzzled whenever "
                    "they did not catch what the player said.",
                ),
            },
            "required": ["narration", "lines", "intent_hint", "mood"],
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
