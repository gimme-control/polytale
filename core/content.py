"""Declarative content: languages, scenes, journey. Models, validators, loader.

Validators return ``"<code>: <detail>"`` strings; ``load_content`` raises ``ContentError``
when any validator reports anything. Missing art is a separate, non-fatal check.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr, ValidationError

CONTENT_ROOT = Path(__file__).resolve().parents[1] / "content"

# The player's own language: narration, clues, glosses and intent hints are written in it.
SUPPORT_LANGUAGE = "English"
TRUST_MIN, TRUST_MAX = -2, 3
MIN_TARGETS, MAX_TARGETS = 8, 12
MIN_RECALL_OVERLAP = 5


def is_latin(ch: str) -> bool:
    return ch.isalpha() and unicodedata.name(ch, "").startswith("LATIN")


class ContentError(ValueError):
    """Content failed validation; ``errors`` carries every ``code: detail`` line."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("invalid content:\n  " + "\n  ".join(errors))
        self.errors = errors


# ---------------------------------------------------------------- models


class Romanization(BaseModel):
    system: str = Field(min_length=1)
    label: str = Field(min_length=1)


class Item(BaseModel):
    text: str = Field(min_length=1)
    roman: str = ""
    gloss: str = Field(min_length=1)
    kind: str = "noun"
    # A line of the player's own ("where is she?"): theirs to say. The character never says it
    # for them; it answers when asked.
    learner_side: bool = False

    @property
    def parts(self) -> list[str]:
        """The spoken parts of ``text``: a placeholder (ellipsis, "...", "~") splits a frame."""
        return [p.strip() for p in re.split("\u2026|\\.{3}|~|\u301c", self.text) if p.strip()]


class Language(BaseModel):
    locale: str = Field(pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
    name: str = Field(min_length=1)
    native_name: str = Field(min_length=1)
    romanization: Romanization | None = None
    word_spacing: bool = False
    currency_symbol: str = ""  # kept in the language file; the game no longer spends money
    phrasebook_voice: Voice = Field(default_factory=lambda: Voice())  # reads looked-up phrases
    typing_note: str = ""
    items: dict[str, Item]

    @property
    def latin_script(self) -> bool:
        """True when the language is written in Latin letters (judged from its own lexicon)."""
        return any(is_latin(ch) for item in self.items.values() for ch in item.text)


class Voice(BaseModel):
    gemini_voice: str = ""
    elevenlabs_voice_id: str = ""
    style: str = ""


class Anchor(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class Npc(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    names: dict[str, str] = Field(default_factory=dict)
    role: str = Field(min_length=1)
    character: str = Field(min_length=1)
    wants: str = ""  # GM-facing: what they are after tonight
    secrets: str = ""  # GM-facing: what they know and will not say yet
    trust: int = Field(default=0, ge=TRUST_MIN, le=TRUST_MAX)  # starting trust
    voice: Voice = Field(default_factory=Voice)
    anchor: Anchor

    def display_name(self, locale: str) -> str:
        return self.names.get(locale) or self.name


class Art(BaseModel):
    background: str = Field(min_length=1)
    cover: str = Field(min_length=1)


class GoalWhen(BaseModel):
    clue: str | None = None
    flag: str | None = None

    def holds(self, clues: Iterable[str] = (), flags: Iterable[str] = ()) -> bool:
        """True when every clause holds for the live clues and flags."""
        if self.clue is not None and self.clue not in clues:
            return False
        return self.flag is None or self.flag in flags


class RevealWhen(BaseModel):
    """One way a clue can come out. Every field given must hold."""

    trust_at_least: int | None = None
    flags: list[str] = Field(default_factory=list)


class Clue(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)  # player-facing notebook entry
    gm_note: str = ""  # GM-facing: how it comes out
    key_items: list[str] = Field(default_factory=list)  # words that give it away when spoken
    reveal_when: list[RevealWhen] = Field(default_factory=list)  # ANY one suffices; [] = free


class Flag(BaseModel):
    id: str = Field(min_length=1)
    when: str = Field(min_length=1)  # GM-facing: what must have happened


class Goal(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    when: GoalWhen


class Scene(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    name: str = Field(min_length=1)
    tagline: str = ""
    intro: str = ""
    setting: str = Field(min_length=1)
    art: Art
    npc: Npc
    targets: list[str]  # the vocabulary this scene teaches
    support_words: list[str] = Field(default_factory=list)  # non-target words the GM may lean on
    clues: list[Clue] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    goals: list[Goal] = Field(min_length=1)
    _dir: Path = PrivateAttr(default=Path("."))

    def goal(self, goal_id: str) -> Goal | None:
        return next((g for g in self.goals if g.id == goal_id), None)

    def clue(self, clue_id: str) -> Clue | None:
        return next((c for c in self.clues if c.id == clue_id), None)

    def flag(self, flag_id: str) -> Flag | None:
        return next((f for f in self.flags if f.id == flag_id), None)

    @property
    def item_ids(self) -> list[str]:
        """Every item a line in this scene may carry: targets and support words."""
        return list(dict.fromkeys([*self.targets, *self.support_words]))

    @property
    def art_paths(self) -> list[str]:
        return list(dict.fromkeys([self.art.background, self.art.cover]))


class EndingWhen(BaseModel):
    clues: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class EndingSpec(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    art: str = ""  # relative to the LAST scene's directory
    when: EndingWhen = Field(default_factory=EndingWhen)


class JourneyPlan(BaseModel):
    """The story file: premise, the act list and the endings."""

    title: str = Field(min_length=1)
    tagline: str = ""
    art: str = ""  # title art, relative to the content root
    premise: str = Field(min_length=1)
    gm_brief: str = Field(min_length=1)
    scenes: list[str] = Field(min_length=1)
    endings: list[EndingSpec] = Field(min_length=1)


class Content(BaseModel):
    languages: dict[str, Language]
    scenes: dict[str, Scene]
    journey: JourneyPlan

    def language(self, locale: str) -> Language:
        return self.languages[locale]

    def scene(self, scene_id: str) -> Scene:
        return self.scenes[scene_id]


# ---------------------------------------------------------------- validators


def _duplicates(values: Iterable[str]) -> list[str]:
    return sorted(v for v, n in Counter(values).items() if n > 1)


def validate_language(language: Language) -> list[str]:
    errors: list[str] = []
    for item_id, item in language.items.items():
        if language.romanization is not None and not item.roman.strip():
            errors.append(f"romanization_missing: {language.locale} item '{item_id}'")
        if language.romanization is None and item.roman.strip():
            errors.append(f"romanization_unexpected: {language.locale} item '{item_id}'")
    return errors


def resolve_art_path(scene: Scene, rel: str) -> Path:
    """Absolute path of a scene art file. Raises ValueError when it escapes the scene dir."""
    base = scene._dir.resolve()
    path = (base / rel).resolve()
    if not rel or Path(rel).is_absolute() or not path.is_relative_to(base) or path == base:
        raise ValueError(f"art path {rel!r} escapes scene '{scene.id}'")
    return path


def validate_scene(
    scene: Scene, languages: dict[str, Language], known_flags: Iterable[str] | None = None
) -> list[str]:
    """``known_flags``: every flag id in the story (flags carry across scenes)."""
    errors: list[str] = []
    sid = scene.id
    flags = set(known_flags) if known_flags is not None else {f.id for f in scene.flags}
    for label, values in (
        ("goal", [g.id for g in scene.goals]),
        ("clue", [c.id for c in scene.clues]),
        ("flag", [f.id for f in scene.flags]),
        ("target", scene.targets),
    ):
        errors += [f"duplicate_id: {sid} {label} '{v}'" for v in _duplicates(values)]

    for locale, language in languages.items():
        errors += [f"target_missing_in_language: {sid} '{i}' not in {locale}"
                   for i in scene.targets if i not in language.items]
        errors += [f"unknown_item: {sid} support word '{w}' not in {locale}"
                   for w in scene.support_words if w not in language.items]

    if not MIN_TARGETS <= len(scene.targets) <= MAX_TARGETS:
        errors.append(
            f"target_count: {sid} has {len(scene.targets)} targets, "
            f"needs {MIN_TARGETS}-{MAX_TARGETS}"
        )

    for goal in scene.goals:
        where = f"{sid} goal '{goal.id}'"
        if goal.when.clue is None and goal.when.flag is None:
            errors.append(f"goal_empty: {where} has no condition")
        if goal.when.clue is not None and scene.clue(goal.when.clue) is None:
            errors.append(f"unknown_clue: {where} names '{goal.when.clue}'")
        if goal.when.flag is not None and goal.when.flag not in flags:
            errors.append(f"unknown_flag: {where} names '{goal.when.flag}'")

    for clue in scene.clues:
        errors += [f"unknown_flag: {sid} clue '{clue.id}' needs '{f}'"
                   for way in clue.reveal_when for f in way.flags if f not in flags]
        errors += [f"unknown_item: {sid} clue '{clue.id}' key item '{i}'"
                   for i in clue.key_items if i not in scene.item_ids]

    for rel in scene.art_paths:
        try:
            resolve_art_path(scene, rel)
        except ValueError:
            errors.append(f"art_escapes_scene: {sid} '{rel}'")
    return errors


def validate_journey(plan: JourneyPlan, scenes: dict[str, Scene]) -> list[str]:
    errors = [f"duplicate_id: journey scene '{v}'" for v in _duplicates(plan.scenes)]
    errors += [f"journey_unknown_scene: '{s}'" for s in plan.scenes if s not in scenes]
    errors += [f"duplicate_id: ending '{v}'" for v in _duplicates(e.id for e in plan.endings)]
    played = [scenes[s] for s in plan.scenes if s in scenes]
    clues = {c.id for s in played for c in s.clues}
    flags = {f.id for s in played for f in s.flags}
    for ending in plan.endings:
        errors += [f"unknown_clue: ending '{ending.id}' needs '{c}'"
                   for c in ending.when.clues if c not in clues]
        errors += [f"unknown_flag: ending '{ending.id}' needs '{f}'"
                   for f in ending.when.flags if f not in flags]
        if ending.art and played:
            try:
                resolve_art_path(played[-1], ending.art)
            except ValueError:
                errors.append(f"art_escapes_scene: ending '{ending.id}' '{ending.art}'")
    if plan.endings[-1].when != EndingWhen():
        errors.append("ending_no_fallback: the last ending must have an empty 'when'")
    # Recall across acts: only meaningful once a journey has more than one scene.
    earlier: set[str] = set()
    for index, scene_id in enumerate(s for s in plan.scenes if s in scenes):
        targets = set(scenes[scene_id].targets)
        if index > 0 and len(targets & earlier) < MIN_RECALL_OVERLAP:
            errors.append(
                f"recall_overlap: '{scene_id}' shares {len(targets & earlier)} targets with "
                f"earlier scenes, needs {MIN_RECALL_OVERLAP}"
            )
        earlier |= targets
    return errors


def validate_content(content: Content) -> list[str]:
    errors: list[str] = []
    if not content.languages:
        errors.append("languages_empty: at least one language is required")
    for language in content.languages.values():
        errors += validate_language(language)
    flags = [f.id for s in content.scenes.values() for f in s.flags]
    for scene in content.scenes.values():
        errors += validate_scene(scene, content.languages, flags)
    errors += validate_journey(content.journey, content.scenes)
    return errors


def missing_art(content: Content) -> list[str]:
    """``"<scene_id>/<rel>"`` for every authored art path with no file on disk."""
    missing: list[str] = []
    for scene in content.scenes.values():
        for rel in scene.art_paths:
            try:
                present = resolve_art_path(scene, rel).is_file()
            except ValueError:
                present = False
            if not present:
                missing.append(f"{scene.id}/{rel}")
    last = content.scenes.get(content.journey.scenes[-1])
    for ending in content.journey.endings:
        if last is not None and ending.art and not (last._dir / ending.art).is_file():
            missing.append(f"{last.id}/{ending.art}")
    return list(dict.fromkeys(missing))


# ---------------------------------------------------------------- loader


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentError([f"unreadable: {path.name}: {exc}"]) from exc


def _parse(model: type[BaseModel], data: Any, label: str) -> Any:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ContentError(
            [f"schema: {label}: {'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        ) from exc


def load_content(root: Path = CONTENT_ROOT) -> Content:
    """Load and validate everything under ``content/``. Raises ContentError on any problem."""
    root = Path(root)
    languages: dict[str, Language] = {}
    for path in sorted((root / "languages").glob("*.json")):
        language = _parse(Language, _read(path), path.name)
        if language.locale != path.stem:
            raise ContentError([f"id_mismatch: {path.name} declares locale '{language.locale}'"])
        languages[language.locale] = language
    scenes: dict[str, Scene] = {}
    for path in sorted((root / "scenes").glob("*/scene.json")):
        scene = _parse(Scene, _read(path), f"{path.parent.name}/scene.json")
        if scene.id != path.parent.name:
            raise ContentError([f"id_mismatch: {path.parent.name}/scene.json has id '{scene.id}'"])
        scene._dir = path.parent
        scenes[scene.id] = scene
    journey = _parse(JourneyPlan, _read(root / "journey.json"), "journey.json")
    content = Content(languages=languages, scenes=scenes, journey=journey)
    errors = validate_content(content)
    if errors:
        raise ContentError(errors)
    return content
