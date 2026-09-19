"""Game state models and atomic persistence."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from core.cartridge import Cartridge, LineSpec

STATES_ROOT = Path(__file__).resolve().parents[1] / "states"

Stage = Literal[
    "unseen",
    "context_recognized",
    "speech_recognized",
    "produced_with_cue",
    "produced_independently",
    "transferred",
]
STAGES: tuple[Stage, ...] = (
    "unseen",
    "context_recognized",
    "speech_recognized",
    "produced_with_cue",
    "produced_independently",
    "transferred",
)
InputMode = Literal["speech", "text", "tap"]
EvidenceType = Literal["recognized", "produced", "transferred"]
Outcome = Literal["understood", "clarified", "not_understood"]
FlagValue = bool | str | int

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Focus(BaseModel):
    object_id: str
    gesture: str


class World(BaseModel):
    holders: dict[str, str] = Field(default_factory=dict)
    fixtures: dict[str, str] = Field(default_factory=dict)
    focus: Focus | None = None
    flags: dict[str, FlagValue] = Field(default_factory=dict)


class EvidenceRecord(BaseModel):
    """One ledger record per (attempt, concept, evidence_type)."""

    attempt_id: str
    turn: int
    beat_id: str
    concept_id: str
    pattern_id: str | None = None
    evidence_type: EvidenceType
    outcome: Outcome
    input_mode: InputMode
    mixed_language: bool = False
    support_level: int
    transcript: str = ""
    stage_after: Stage | None = None  # None: no stage change (tap fallback / not_understood)
    pattern_stage_after: Stage | None = None
    tap_fallback: bool = False
    downgraded: bool = False  # transfer attempt recorded as produced_with_cue (support used)


class LastConstruction(BaseModel):
    pattern_id: str
    concept_id: str
    beat_id: str
    support_level: int


class LearningState(BaseModel):
    target_locale: str
    support_locale: str
    active_beat_index: int = 0
    concept_stage: dict[str, Stage] = Field(default_factory=dict)
    pattern_stage: dict[str, Stage] = Field(default_factory=dict)
    exposures: dict[str, int] = Field(default_factory=dict)
    help_level: dict[str, int] = Field(default_factory=dict)
    help_max_used: dict[str, int] = Field(default_factory=dict)
    failures: dict[str, int] = Field(default_factory=dict)
    phrase_modeled: dict[str, bool] = Field(default_factory=dict)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    last_successful_construction: LastConstruction | None = None


class SpokenLine(BaseModel):
    line_id: str
    speaker: str
    speaker_name: str
    text: str
    language: str
    romanization: str = ""
    translation: str = ""
    concept_ids: list[str] = Field(default_factory=list)
    pattern_id: str | None = None
    audio_url: str

    @classmethod
    def build(
        cls, cartridge: Cartridge, session_id: str, line_id: str, spec: LineSpec | dict
    ) -> SpokenLine:
        """Runtime line from an authored/validated spec; audio is served per line_id."""
        data = spec.model_dump() if isinstance(spec, LineSpec) else dict(spec)
        npc = cartridge.npc(str(data.get("speaker") or ""))
        return cls(
            line_id=line_id,
            speaker=str(data.get("speaker") or ""),
            speaker_name=npc.name if npc else str(data.get("speaker") or ""),
            text=str(data.get("text") or ""),
            language=str(data.get("language") or ""),
            romanization=str(data.get("romanization") or ""),
            translation=str(data.get("translation") or ""),
            concept_ids=list(data.get("concept_ids") or []),
            pattern_id=data.get("pattern_id") or None,
            audio_url=line_audio_url(session_id, line_id),
        )


def line_audio_url(session_id: str, line_id: str) -> str:
    """Relative audio URL; the server/client append the session token."""
    return f"/api/sessions/{session_id}/lines/{line_id}/audio"


class NarrationEntry(BaseModel):
    kind: Literal["narration"] = "narration"
    turn: int
    text: str


class NpcEntry(BaseModel):
    kind: Literal["npc"] = "npc"
    turn: int
    line: SpokenLine


class PlayerEntry(BaseModel):
    kind: Literal["player"] = "player"
    turn: int
    attempt_id: str
    input_mode: InputMode
    transcript: str
    romanized: str | None = None
    tapped_object_id: str | None = None


class EvidenceEntry(BaseModel):
    kind: Literal["evidence"] = "evidence"
    turn: int
    beat_id: str
    concept_ids: list[str]
    evidence_type: EvidenceType
    outcome: Outcome
    stage_after: dict[str, Stage | None]  # concept_id -> stage after (None: unchanged/tap)
    support_level: int
    input_mode: InputMode


TranscriptEntry = Annotated[
    NarrationEntry | NpcEntry | PlayerEntry | EvidenceEntry, Field(discriminator="kind")
]


class Attempt(BaseModel):
    attempt_id: str
    input_mode: InputMode
    transcript: str = ""
    romanized: str | None = None
    detected_languages: list[str] = Field(default_factory=list)
    confidence: float | None = None
    tapped_object_id: str | None = None
    created_at: str = Field(default_factory=_now)
    consumed: bool = False
    turn: int | None = None  # turn that consumed it


class GameState(BaseModel):
    session_id: str
    cartridge_id: str
    created_at: str = Field(default_factory=_now)
    started: bool = False
    turn: int = 0
    world: World = Field(default_factory=World)
    learning: LearningState | None = None
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    attempts: dict[str, Attempt] = Field(default_factory=dict)
    episode_complete: bool = False
    schema_version: int = 1


def new_game(cartridge: Cartridge, session_id: str) -> GameState:
    """Fresh state: authored holders/fixtures, learning ledger at the first beat."""
    from core.ledger import enter_beat

    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"invalid session id {session_id!r}")
    world = World(
        holders={o.id: o.holder for o in cartridge.objects},
        fixtures={f.id: f.initial for f in cartridge.fixtures},
    )
    state = GameState(session_id=session_id, cartridge_id=cartridge.id, world=world)
    ll = cartridge.language_learning
    if ll is not None:
        state.learning = LearningState(
            target_locale=ll.target_locale,
            support_locale=ll.support_locale,
            concept_stage={c.id: "unseen" for c in ll.concepts},
            pattern_stage={p.id: "unseen" for p in ll.patterns},
            exposures={c.id: 0 for c in ll.concepts},
        )
        enter_beat(state, cartridge, 0)
    return state


def _session_path(session_id: str, root: Path) -> Path:
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"invalid session id {session_id!r}")
    return Path(root) / "sessions" / f"{session_id}.json"


def save_state(state: GameState, root: Path = STATES_ROOT) -> Path:
    """Atomically write ``<root>/sessions/<session_id>.json`` (tmp + os.replace)."""
    path = _session_path(state.session_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(state.model_dump_json(indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_state(session_id: str, root: Path = STATES_ROOT) -> GameState | None:
    """Load a saved session, or None when it does not exist."""
    path = _session_path(session_id, root)
    if not path.is_file():
        return None
    return GameState.model_validate_json(path.read_text(encoding="utf-8"))
