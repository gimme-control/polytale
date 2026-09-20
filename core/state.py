"""Journey state models and atomic persistence.

A Journey is one learner's run through the scene list. The vocabulary record lives on the
journey (it outlives scenes); everything about the scene being played lives on its SceneRun.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from core.content import Content

STATES_ROOT = Path(__file__).resolve().parents[1] / "states"
SCHEMA_VERSION = 4

InputMode = Literal["speech", "text"]
Outcome = Literal["first_try", "with_help", "with_hint", "missed"]
VocabState = Literal["not_encountered", "shaky", "mastered"]

_JOURNEY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- vocabulary record


class Result(BaseModel):
    scene_id: str
    turn: int
    attempt_id: str
    outcome: Outcome
    produced: bool = False
    recall: bool = False


class VocabRecord(BaseModel):
    appearances: int = 0
    results: list[Result] = Field(default_factory=list)
    first_scene: str = ""
    last_scene: str = ""
    state: VocabState = "not_encountered"
    produced: bool = False

    @property
    def met(self) -> bool:
        """The learner has come across this item: the character said it, or they used it."""
        return self.appearances > 0 or bool(self.results)


# ---------------------------------------------------------------- dialogue + transcript


class Segment(BaseModel):
    t: str
    r: str = ""


class Line(BaseModel):
    line_id: str
    speaker_name: str
    segments: list[Segment]
    text: str
    romanization: str
    item_ids: list[str] = Field(default_factory=list)
    audio_url: str


class NpcEntry(BaseModel):
    kind: Literal["npc"] = "npc"
    turn: int
    line: Line


class NarrationEntry(BaseModel):
    kind: Literal["narration"] = "narration"
    turn: int
    text: str


class ClueView(BaseModel):
    id: str
    title: str
    text: str


class ClueEntry(BaseModel):
    kind: Literal["clue"] = "clue"
    turn: int
    clue: ClueView


class LearnerEntry(BaseModel):
    kind: Literal["learner"] = "learner"
    turn: int
    attempt_id: str
    input_mode: InputMode
    transcript: str
    romanized: str | None = None


class SceneEventEntry(BaseModel):
    kind: Literal["scene"] = "scene"
    turn: int
    event: Literal["goal_done"] = "goal_done"
    goal_id: str | None = None


Entry = Annotated[
    NpcEntry | NarrationEntry | ClueEntry | LearnerEntry | SceneEventEntry,
    Field(discriminator="kind"),
]


class Attempt(BaseModel):
    attempt_id: str
    input_mode: InputMode
    transcript: str = ""
    romanized: str | None = None
    detected_languages: list[str] = Field(default_factory=list)
    confidence: float | None = None
    created_at: str = Field(default_factory=_now)
    consumed: bool = False
    turn: int | None = None  # turn that consumed it


# ---------------------------------------------------------------- summary (persisted in history)


class SummaryItem(BaseModel):
    item_id: str
    text: str
    roman: str
    gloss: str
    state: VocabState
    outcomes: list[Outcome] = Field(default_factory=list)
    produced: bool = False
    recall: bool = False
    heard: bool = False  # the character said it in this journey, whether or not it was acted on
    audio_url: str


class SummaryCounts(BaseModel):
    mastered: int = 0
    shaky: int = 0
    heard: int = 0  # the character said it; the learner never acted on it
    not_encountered: int = 0


class SceneRef(BaseModel):
    id: str
    name: str
    tagline: str = ""


class PhraseSegment(BaseModel):
    t: str
    r: str = ""
    g: str = ""  # per-word gloss: it is the player's own sentence, so glossing it is fine


class Phrase(BaseModel):
    """One "How do I say…?" lookup, kept as the player's own phrasebook."""

    phrase_id: str
    source: str
    segments: list[PhraseSegment]
    text: str
    romanization: str
    audio_url: str
    item_ids: list[str] = Field(default_factory=list)


class Summary(BaseModel):
    scene_id: str
    scene_name: str
    items: list[SummaryItem]
    counts: SummaryCounts
    recalled: list[str] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)
    next_scene: SceneRef | None = None
    phrasebook: list[Phrase] = Field(default_factory=list)


# ---------------------------------------------------------------- scene run + journey


class Exchange(BaseModel):
    """What the character last put in front of the learner; resets every time it speaks."""

    posed_item_ids: list[str] = Field(default_factory=list)
    help_level: int = Field(default=0, ge=0, le=2)
    line_ids: list[str] = Field(default_factory=list)
    intent_hint: str = ""
    phrasebook_item_ids: list[str] = Field(default_factory=list)  # looked up this exchange


class SceneRun(BaseModel):
    scene_id: str
    turn: int = 0
    started: bool = False
    complete: bool = False
    goals_done: list[str] = Field(default_factory=list)
    transcript: list[Entry] = Field(default_factory=list)
    exchange: Exchange = Field(default_factory=Exchange)


class Game(BaseModel):
    """The story's ledgers. Code owns every field; the GM changes them only through tools."""

    trust: dict[str, int] = Field(default_factory=dict)  # scene_id -> the character's trust
    clues: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    phrasebook: list[Phrase] = Field(default_factory=list)
    ending_id: str | None = None


class Journey(BaseModel):
    journey_id: str
    language: str
    created_at: str = Field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    vocab: dict[str, VocabRecord] = Field(default_factory=dict)
    scene_index: int = 0
    scene: SceneRun | None = None
    history: list[Summary] = Field(default_factory=list)
    attempts: dict[str, Attempt] = Field(default_factory=dict)
    game: Game = Field(default_factory=Game)

    def record(self, item_id: str) -> VocabRecord:
        return self.vocab.setdefault(item_id, VocabRecord())


def line_audio_url(journey_id: str, line_id: str) -> str:
    """Relative audio URL; the client appends the journey token."""
    return f"/api/journeys/{journey_id}/lines/{line_id}/audio"


def item_audio_url(journey_id: str, item_id: str) -> str:
    return f"/api/journeys/{journey_id}/items/{item_id}/audio"


def phrase_audio_url(journey_id: str, phrase_id: str) -> str:
    return f"/api/journeys/{journey_id}/phrases/{phrase_id}/audio"


def new_journey(content: Content, journey_id: str, *, language: str) -> Journey:
    """A fresh journey with no scene entered yet."""
    if not _JOURNEY_ID_RE.match(journey_id):
        raise ValueError(f"invalid journey id {journey_id!r}")
    if language not in content.languages:
        raise ValueError(f"unknown language {language!r}")
    return Journey(journey_id=journey_id, language=language)


def _journey_path(journey_id: str, root: Path) -> Path:
    if not _JOURNEY_ID_RE.match(journey_id):
        raise ValueError(f"invalid journey id {journey_id!r}")
    return Path(root) / "journeys" / f"{journey_id}.json"


def save_journey(journey: Journey, root: Path = STATES_ROOT) -> Path:
    """Atomically write ``<root>/journeys/<journey_id>.json`` (tmp + os.replace)."""
    path = _journey_path(journey.journey_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(journey.model_dump_json(indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_journey(journey_id: str, root: Path = STATES_ROOT) -> Journey | None:
    """Load a saved journey, or None when it does not exist."""
    path = _journey_path(journey_id, root)
    if not path.is_file():
        return None
    return Journey.model_validate_json(path.read_text(encoding="utf-8"))
