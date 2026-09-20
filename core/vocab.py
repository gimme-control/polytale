"""Vocabulary rules: appearances, results, presentation guidance, help.

Deterministic. Outcomes are stamped from the server's exchange ledger (how much help the
learner asked for, what they looked up), never from anything the model claims.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from typing import Literal

from pydantic import BaseModel, Field

from core.content import Language
from core.state import Exchange, Journey, Outcome, Result, VocabRecord

MAX_HELP_LEVEL = 2
HELP_LABELS = {1: "Say it again, slowly", 2: "What do they want?"}

Presentation = Literal["introduce", "support", "unaided", "known", "theirs"]
GUIDANCE: dict[Presentation, str] = {
    "theirs": "THEIR line, never yours: do not say it for them; when they say it, just answer",
    "introduce": "introduce: say it, and make what it means unmistakable from the moment",
    "support": "say it again, and make the meaning plain: repeat, gesture, act it out",
    "unaided": "use it plainly, with no extra help; let them carry it",
    "known": "they have this: just use it, like anyone would",
}


class NextHelp(BaseModel):
    level: int
    label: str


class Help(BaseModel):
    level: int
    kind: Literal["again", "hint"]
    line_ids: list[str] = Field(default_factory=list)
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
    if exchange.help_level == 1:
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
        return "known"
    helped_here = any(
        r.scene_id == scene_id and r.outcome == "with_help" for r in record.results
    )
    return "unaided" if helped_here else "support"


def next_help(exchange: Exchange) -> NextHelp | None:
    level = exchange.help_level + 1
    return NextHelp(level=level, label=HELP_LABELS[level]) if level <= MAX_HELP_LEVEL else None


def request_help(journey: Journey) -> Help:
    """Raise help by exactly one level for this exchange (in place) and say what to show.

    Level 1 replays the character's last lines slowly; level 2 reveals the intent hint. A press
    at the maximum returns level 2 again.
    """
    run = journey.scene
    if run is None or not run.started or run.complete:
        raise ValueError("no scene in play")
    exchange = run.exchange
    exchange.help_level = min(MAX_HELP_LEVEL, exchange.help_level + 1)
    if exchange.help_level == 1:
        return Help(level=1, kind="again", line_ids=list(exchange.line_ids))
    return Help(level=2, kind="hint", line_ids=list(exchange.line_ids),
                hint=exchange.intent_hint or None)

# ---------------------------------------------------------------- lexicon matching

MIN_STEM = 4  # shortest prefix that may stand in for an inflected form


def fold(text: str) -> str:
    """Compare the way speech varies, not the way it is spelled: no marks, no case."""
    plain = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in plain if not unicodedata.combining(ch)).strip().casefold()


def lexicon_index(language: Language) -> dict[str, str]:
    """Folded surface form -> item id, for forms that can only mean one thing.

    A whole listed form always goes in. A single word OF a listed phrase goes in only when no
    other item uses that word: "foto" belongs to "la foto" alone and is safe, but "esta" sits
    in both "donde esta" and "esta noche", so on its own it means nothing and is left out.
    Indexing it anyway is how "esta noche" once came back glossed "where is (she)?".
    """
    owners: dict[str, set[str]] = {}
    index: dict[str, str] = {}
    for item_id, item in language.items.items():
        for part in item.parts:
            index.setdefault(fold(part), item_id)
            for word in part.split():
                owners.setdefault(fold(word), set()).add(item_id)
    for word, ids in owners.items():
        if len(ids) == 1 and word not in index:
            index[word] = next(iter(ids))
    return index


def phrase_forms(language: Language) -> list[tuple[list[str], str]]:
    """Multi-word listed forms as folded word runs, longest first."""
    forms = [
        ([fold(w) for w in part.split()], item_id)
        for item_id, item in language.items.items()
        for part in item.parts
        if len(part.split()) > 1
    ]
    return sorted(forms, key=lambda f: len(f[0]), reverse=True)


def match_item(text: str, index: dict[str, str]) -> str | None:
    """The lexicon item a single spoken word belongs to, tolerating a different ending."""
    key = fold(text)
    if not key:
        return None
    if key in index:
        return index[key]
    # An inflected form shares a long prefix with the listed one (amigo/amiga). Kept tight so
    # two genuinely different words cannot collide.
    best: tuple[int, str] | None = None
    for surface, item_id in index.items():
        if abs(len(surface) - len(key)) > 2:
            continue
        shared = 0
        for a, b in zip(surface, key):
            if a != b:
                break
            shared += 1
        if shared >= MIN_STEM and shared >= min(len(surface), len(key)) - 2:
            if best is None or shared > best[0]:
                best = (shared, item_id)
    return best[1] if best else None


def scan_items(
    words: Sequence[str], language: Language
) -> list[tuple[str, str | None]]:
    """Walk spoken words left to right: ``(what was said, the item it is)``.

    A listed PHRASE only counts when its words really are said together, so "esta noche" is
    one entry meaning tonight and never two wrong ones. Anything unrecognised comes back with
    ``None`` rather than being dropped: he talks freely, and the player still heard it.
    """
    index, phrases = lexicon_index(language), phrase_forms(language)
    folded = [fold(w) for w in words]
    out: list[tuple[str, str | None]] = []
    i = 0
    while i < len(words):
        for run, item_id in phrases:
            n = len(run)
            if folded[i:i + n] == run:
                out.append((" ".join(words[i:i + n]), item_id))
                i += n
                break
        else:
            out.append((words[i], match_item(words[i], index)))
            i += 1
    return out
