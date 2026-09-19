"""Vocabulary rules: appearances, results, presentation guidance, the highlight gate, help.

Deterministic. Outcomes are stamped from the server's exchange ledger (what was highlighted,
how much help the learner asked for), never from anything the model claims.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from core.content import Content, Scene
from core.state import Exchange, Journey, Outcome, Result, VocabRecord

MAX_HELP_LEVEL = 2
HELP_LABELS = {1: "Say it again, slowly", 2: "What do they want?"}

MAX_UNSUPPORTED_OFFERS = 2

Presentation = Literal["introduce", "highlight", "no_highlight", "no_support", "theirs"]
GUIDANCE: dict[Presentation, str] = {
    "theirs": "THEIR line, never yours: do not say it for them; when they say it, just answer",
    "introduce": "introduce: say it, highlight it, act it out",
    "highlight": "use it with a highlight",
    "no_highlight": "use it WITHOUT a highlight",
    "no_support": "use it with NO support",
}


class NextHelp(BaseModel):
    level: int
    label: str


class Help(BaseModel):
    level: int
    kind: Literal["again", "hint"]
    line_ids: list[str] = Field(default_factory=list)
    highlight_object_ids: list[str] = Field(default_factory=list)
    hint: str | None = None


def note_appearances(journey: Journey, scene_id: str, item_ids: list[str]) -> None:
    """One appearance per item carried by a character line. Never changes ``state``."""
    for item_id in item_ids:
        record = journey.record(item_id)
        record.appearances += 1
        record.first_scene = record.first_scene or scene_id
        record.last_scene = scene_id


def outcome_for(exchange: Exchange, item_id: str, understood: bool) -> Outcome:
    if not understood:
        return "missed"
    if exchange.help_level >= 2:
        return "with_hint"
    if (exchange.help_level == 1 or item_id in exchange.highlighted_item_ids
            or item_id in exchange.phrasebook_item_ids):
        return "with_help"
    return "first_try"


def record_result(
    journey: Journey, *, item_id: str, understood: bool, produced: bool, attempt_id: str
) -> tuple[Result, bool]:
    """Stamp one result for the scene being played. Returns ``(result, is_new)``.

    A repeat of the same ``(attempt_id, item_id)`` returns the stored result unchanged.
    """
    scene = journey.scene
    if scene is None:
        raise ValueError("no scene in progress")
    record = journey.record(item_id)
    for existing in record.results:
        if existing.attempt_id == attempt_id:
            return existing, False
    outcome = outcome_for(scene.exchange, item_id, understood)
    met_before = record.first_scene not in ("", scene.scene_id)
    result = Result(
        scene_id=scene.scene_id, turn=scene.turn, attempt_id=attempt_id, outcome=outcome,
        produced=produced and understood, recall=outcome == "first_try" and met_before,
    )
    record.results.append(result)
    record.first_scene = record.first_scene or scene.scene_id
    record.last_scene = scene.scene_id
    record.state = "mastered" if outcome == "first_try" else "shaky"
    record.produced = record.produced or result.produced
    return result, True


def presentation(
    record: VocabRecord | None, scene_id: str, learner_side: bool = False
) -> Presentation:
    """How the character should present an item to this learner right now."""
    if learner_side:
        return "theirs"
    if record is None or record.state == "not_encountered":
        return "introduce"
    if record.state == "mastered":
        return "no_support"
    helped_here = any(
        r.scene_id == scene_id and r.outcome == "with_help" for r in record.results
    )
    return "no_highlight" if helped_here else "highlight"


def owed_items(journey: Journey, scene: Scene) -> list[str]:
    """Object words still owed an unsupported pass in the scene being played.

    Owed: the learner got it here only with a highlight or help (no first_try yet this scene).
    The debt lapses once the word has come back un-highlighted ``MAX_UNSUPPORTED_OFFERS`` times,
    so the scene can never be held hostage.
    """
    run = journey.scene
    if run is None:
        return []
    owed: list[str] = []
    for item_id in dict.fromkeys(o.item_id for o in scene.objects if o.item_id in scene.targets):
        record = journey.vocab.get(item_id)
        here = [r.outcome for r in record.results if r.scene_id == scene.id] if record else []
        helped = any(o in ("with_help", "with_hint") for o in here)
        if (helped and "first_try" not in here
                and run.unsupported_offers.get(item_id, 0) < MAX_UNSUPPORTED_OFFERS):
            owed.append(item_id)
    return owed


def mastered_items(journey: Journey) -> frozenset[str]:
    """The highlight gate's input: items this learner has mastered (never highlighted)."""
    return frozenset(i for i, record in journey.vocab.items() if record.state == "mastered")


def next_help(exchange: Exchange) -> NextHelp | None:
    level = exchange.help_level + 1
    return NextHelp(level=level, label=HELP_LABELS[level]) if level <= MAX_HELP_LEVEL else None


def request_help(journey: Journey, content: Content) -> Help:
    """Raise help by exactly one level for this exchange (in place) and say what to show.

    Level 1 replays the character's last lines slowly and highlights what they posed; level 2
    reveals the intent hint. A press at the maximum returns level 2 again.
    """
    run = journey.scene
    if run is None or not run.started or run.complete:
        raise ValueError("no scene in play")
    exchange = run.exchange
    exchange.help_level = min(MAX_HELP_LEVEL, exchange.help_level + 1)
    scene = content.scene(run.scene_id)
    highlight = [
        o.id for o in scene.objects
        if o.item_id in exchange.posed_item_ids and run.zones.get(o.id) != "gone"
    ]
    if exchange.help_level == 1:
        return Help(level=1, kind="again", line_ids=list(exchange.line_ids),
                    highlight_object_ids=highlight)
    return Help(level=2, kind="hint", line_ids=list(exchange.line_ids),
                highlight_object_ids=highlight, hint=exchange.intent_hint or None)
