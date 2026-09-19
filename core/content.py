"""Declarative content: languages, scenes, personas, journey. Models, validators, loader.

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

ZONES: tuple[str, ...] = ("display", "counter", "npc", "inventory", "gone")
UNPOSITIONED_ZONES = frozenset({"inventory", "gone"})  # HUD tray / off stage: no coordinates
NEUTRAL_MOOD = "neutral"
# The player's own language: narration, clues, glosses and intent hints are written in it.
SUPPORT_LANGUAGE = "English"
ACTIONS: dict[str, str] = {  # verb id -> button label
    "point": "Point at", "take": "Take", "give": "Give", "show": "Show", "drink": "Drink",
    "eat": "Eat", "pay": "Pay",
}
DIFFICULTIES: tuple[str, ...] = ("story", "immersion")
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
    # A customer's line ("how much?"): the learner's to say. The character never says it for
    # them; it answers when asked.
    learner_side: bool = False

    @property
    def parts(self) -> list[str]:
        """The spoken parts of ``text``: a placeholder ("…", "...", "~") splits a frame."""
        return [p.strip() for p in re.split("\u2026|\\.{3}|~|\u301c", self.text) if p.strip()]


class Language(BaseModel):
    locale: str = Field(pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
    name: str = Field(min_length=1)
    native_name: str = Field(min_length=1)
    romanization: Romanization | None = None
    word_spacing: bool = False
    currency_symbol: str = ""  # drawn before object prices
    phrasebook_voice: Voice = Field(default_factory=lambda: Voice())  # reads looked-up phrases
    typing_note: str = ""
    items: dict[str, Item]

    @property
    def latin_script(self) -> bool:
        """True when the language is written in Latin letters (judged from its own lexicon)."""
        return any(is_latin(ch) for item in self.items.values() for ch in item.text)


class Position(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    h: float = Field(gt=0, le=1)


class SceneObject(BaseModel):
    id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    art: str = Field(min_length=1)
    zone: str
    price: int | None = Field(default=None, ge=0)
    price_floor: int | None = Field(default=None, ge=0)  # set => the price can be haggled down
    actions: list[str] = Field(default_factory=lambda: ["point"])
    positions: dict[str, Position] = Field(default_factory=dict)

    def can_be_in(self, zone: str) -> bool:
        return zone in UNPOSITIONED_ZONES or zone in self.positions


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
    moods: dict[str, str] = Field(default_factory=dict)


class AnyInZone(BaseModel):
    zone: str
    objects: list[str] = Field(min_length=1)


class GoalWhen(BaseModel):
    clue: str | None = None
    flag: str | None = None
    in_zone: dict[str, str] = Field(default_factory=dict)
    any_in_zone: AnyInZone | None = None

    def holds(self, zones: dict[str, str], clues: Iterable[str] = (),
              flags: Iterable[str] = ()) -> bool:
        """True when every clause holds for the live zones, clues and flags."""
        if self.clue is not None and self.clue not in clues:
            return False
        if self.flag is not None and self.flag not in flags:
            return False
        if any(zones.get(oid) != zone for oid, zone in self.in_zone.items()):
            return False
        clause = self.any_in_zone
        return clause is None or any(zones.get(oid) == clause.zone for oid in clause.objects)


class RevealWhen(BaseModel):
    """One way a clue can come out. Every field given must hold."""

    trust_at_least: int | None = None
    flags: list[str] = Field(default_factory=list)
    paid_at_least: int | None = None  # spent in THIS scene


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
    requires_paid: list[str] = Field(default_factory=list)  # ANY one of these was paid for


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
    travel_minutes: int = Field(default=0, ge=0)  # clock cost of getting here
    art: Art
    npc: Npc
    zones: list[str]
    objects: list[SceneObject]
    targets: list[str]
    support_words: list[str] = Field(default_factory=list)  # non-target words the GM may lean on
    clues: list[Clue] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    goals: list[Goal] = Field(min_length=1)
    _dir: Path = PrivateAttr(default=Path("."))

    def object(self, object_id: str) -> SceneObject | None:
        return next((o for o in self.objects if o.id == object_id), None)

    def goal(self, goal_id: str) -> Goal | None:
        return next((g for g in self.goals if g.id == goal_id), None)

    def clue(self, clue_id: str) -> Clue | None:
        return next((c for c in self.clues if c.id == clue_id), None)

    def flag(self, flag_id: str) -> Flag | None:
        return next((f for f in self.flags if f.id == flag_id), None)

    @property
    def moods(self) -> list[str]:
        return list(dict.fromkeys([NEUTRAL_MOOD, *self.art.moods]))

    @property
    def item_ids(self) -> list[str]:
        """Every item a line in this scene may carry: targets, object items, support words."""
        return list(dict.fromkeys(
            [*self.targets, *(o.item_id for o in self.objects), *self.support_words]
        ))

    @property
    def art_paths(self) -> list[str]:
        paths = [self.art.background, self.art.cover, *self.art.moods.values()]
        return list(dict.fromkeys([*paths, *(o.art for o in self.objects)]))


class Persona(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    blurb: str = ""
    prompt: str = Field(min_length=1)
    voice_style: str = ""


class Clock(BaseModel):
    label: str = Field(min_length=1)
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")
    minutes_per_turn: int = Field(gt=0)

    @property
    def start_minute(self) -> int:
        return int(self.start[:2]) * 60 + int(self.start[3:])

    @property
    def total_minutes(self) -> int:
        """Minutes from start to end; an end earlier than the start is past midnight."""
        end = int(self.end[:2]) * 60 + int(self.end[3:])
        return (end - self.start_minute) % (24 * 60)


class EndingWhen(BaseModel):
    clues: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    clock_left: bool | None = None
    minutes_left_at_least: int | None = None
    wallet_at_least: int | None = None


class EndingSpec(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    art: str = ""  # relative to the LAST scene's directory
    when: EndingWhen = Field(default_factory=EndingWhen)


class JourneyPlan(BaseModel):
    """The story file: premise, resources, the act list and the endings."""

    title: str = Field(min_length=1)
    tagline: str = ""
    art: str = ""  # title art, relative to the content root
    premise: str = Field(min_length=1)
    gm_brief: str = Field(min_length=1)
    wallet: int = Field(ge=0)
    clock: Clock
    scenes: list[str] = Field(min_length=1)
    endings: list[EndingSpec] = Field(min_length=1)


class Content(BaseModel):
    languages: dict[str, Language]
    scenes: dict[str, Scene]
    personas: list[Persona]
    journey: JourneyPlan

    def language(self, locale: str) -> Language:
        return self.languages[locale]

    def scene(self, scene_id: str) -> Scene:
        return self.scenes[scene_id]

    def persona(self, persona_id: str) -> Persona | None:
        return next((p for p in self.personas if p.id == persona_id), None)


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
        ("object", [o.id for o in scene.objects]),
        ("goal", [g.id for g in scene.goals]),
        ("clue", [c.id for c in scene.clues]),
        ("flag", [f.id for f in scene.flags]),
        ("target", scene.targets),
        ("zone", scene.zones),
    ):
        errors += [f"duplicate_id: {sid} {label} '{v}'" for v in _duplicates(values)]
    errors += [f"unknown_zone: {sid} declares '{z}'" for z in scene.zones if z not in ZONES]
    zones = set(scene.zones)
    object_ids = {o.id for o in scene.objects}

    for obj in scene.objects:
        where = f"{sid} object '{obj.id}'"
        if obj.zone not in zones:
            errors.append(f"unknown_zone: {where} starts in '{obj.zone}'")
        elif not obj.can_be_in(obj.zone):
            errors.append(f"zone_without_position: {where} starts in '{obj.zone}'")
        for zone in obj.positions:
            if zone not in zones:
                errors.append(f"unknown_zone: {where} has a position for '{zone}'")
            elif zone in UNPOSITIONED_ZONES:
                errors.append(f"unknown_zone: {where} positions '{zone}', which has no place")
        errors += [f"unknown_action: {where} has '{a}'" for a in obj.actions if a not in ACTIONS]
        if obj.price_floor is not None and (obj.price is None or obj.price_floor > obj.price):
            errors.append(f"price_floor_invalid: {where} floor must be <= its price")

    for locale, language in languages.items():
        for item_id in scene.targets:
            if item_id not in language.items:
                errors.append(f"target_missing_in_language: {sid} '{item_id}' not in {locale}")
        for obj in scene.objects:
            if obj.item_id not in language.items:
                errors.append(
                    f"unknown_item: {sid} object '{obj.id}' item '{obj.item_id}' not in {locale}"
                )
        errors += [f"unknown_item: {sid} support word '{w}' not in {locale}"
                   for w in scene.support_words if w not in language.items]

    if not MIN_TARGETS <= len(scene.targets) <= MAX_TARGETS:
        errors.append(
            f"target_count: {sid} has {len(scene.targets)} targets, "
            f"needs {MIN_TARGETS}-{MAX_TARGETS}"
        )

    for goal in scene.goals:
        where = f"{sid} goal '{goal.id}'"
        clause = goal.when.any_in_zone
        pairs = list(goal.when.in_zone.items())
        if clause is not None:
            pairs += [(oid, clause.zone) for oid in clause.objects]
        if not pairs and goal.when.clue is None and goal.when.flag is None:
            errors.append(f"goal_empty: {where} has no condition")
        if goal.when.clue is not None and scene.clue(goal.when.clue) is None:
            errors.append(f"unknown_clue: {where} names '{goal.when.clue}'")
        if goal.when.flag is not None and goal.when.flag not in flags:
            errors.append(f"unknown_flag: {where} names '{goal.when.flag}'")
        for oid, zone in pairs:
            if oid not in object_ids:
                errors.append(f"unknown_object: {where} names '{oid}'")
            elif zone not in zones:
                errors.append(f"unknown_zone: {where} names '{zone}'")
            elif not scene.object(oid).can_be_in(zone):  # type: ignore[union-attr]
                errors.append(f"zone_without_position: {where} needs '{oid}' in '{zone}'")

    for clue in scene.clues:
        errors += [f"unknown_flag: {sid} clue '{clue.id}' needs '{f}'"
                   for way in clue.reveal_when for f in way.flags if f not in flags]
        errors += [f"unknown_item: {sid} clue '{clue.id}' key item '{i}'"
                   for i in clue.key_items if i not in scene.item_ids]
    for flag in scene.flags:
        for oid in flag.requires_paid:
            needed = scene.object(oid)
            if needed is None or needed.price is None:
                errors.append(f"unknown_object: {sid} flag '{flag.id}' needs priced object '{oid}'")

    for rel in scene.art_paths:
        try:
            resolve_art_path(scene, rel)
        except ValueError:
            errors.append(f"art_escapes_scene: {sid} '{rel}'")
    return errors


def validate_personas(personas: list[Persona]) -> list[str]:
    errors = [f"duplicate_id: persona '{v}'" for v in _duplicates(p.id for p in personas)]
    if not personas:
        errors.append("personas_empty: at least one persona is required")
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
    if plan.clock.total_minutes == 0:
        errors.append("clock_empty: the clock has no time on it")
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
    errors += validate_personas(content.personas)
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
    personas = [
        _parse(Persona, raw, f"personas.json[{i}]")
        for i, raw in enumerate(_read(root / "personas.json"))
    ]
    journey = _parse(JourneyPlan, _read(root / "journey.json"), "journey.json")
    content = Content(languages=languages, scenes=scenes, personas=personas, journey=journey)
    errors = validate_content(content)
    if errors:
        raise ContentError(errors)
    return content
