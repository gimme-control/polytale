"""Declarative cartridge schema, loader, and validator.

A cartridge is JSON only. `validate_cartridge` returns error codes of the form
``"<code>: <where>"``; the loader raises `CartridgeError` if there are any.
A cartridge without ``language_learning`` is valid (plain story mode).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError

log = logging.getLogger("polytale.cartridge")

CARTRIDGES_ROOT = Path(__file__).resolve().parents[1] / "cartridges"

LOCALE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")
ROMANIZATION_SYSTEMS = ("hepburn", "pinyin", "latin")
GESTURES = ("hold_up", "point", "offer", "withhold", "put_away")
PLAYER = "player"
WORLD = "world"
# Tools a cartridge opening may apply (the world tools; ledger tools need a player attempt).
OPENING_TOOLS = ("show_object", "give", "set_fixture")


class CartridgeError(ValueError):
    def __init__(self, cartridge_id: str, errors: list[str]):
        self.errors = errors
        super().__init__(f"cartridge {cartridge_id!r} invalid: " + "; ".join(errors))


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Identity(_Model):
    id: str
    name: str
    tagline: str = ""
    locale: str = "en-US"


class ArtVariant(_Model):
    id: str
    when: dict[str, str]
    image: str


class LocationArt(_Model):
    base: str
    variants: list[ArtVariant] = Field(default_factory=list)


class Location(_Model):
    id: str
    name: str
    description: str = ""
    art: LocationArt


class Setting(_Model):
    premise: str
    location: Location


class Voice(_Model):
    elevenlabs_voice_id: str = ""
    gemini_voice: str = "Kore"
    style: str = ""


class NpcArt(_Model):
    sprite: str
    portrait: str


class Point(_Model):
    x: float
    y: float


class StagePlacement(_Model):
    x: float
    y: float
    height: float
    hand: Point | None = None  # held-up object anchor, fractions of the sprite box


class Npc(_Model):
    id: str
    name: str
    role: str
    persona: str
    english: str = ""
    voice: Voice = Field(default_factory=Voice)
    art: NpcArt
    stage: StagePlacement


class GameObject(_Model):
    id: str
    concept_id: str | None = None
    icon: str
    holder: str


class Hotspot(_Model):
    x: float
    y: float
    r: float


class Fixture(_Model):
    id: str
    name: str
    states: list[str]
    initial: str
    hotspot: Hotspot


class OpeningAction(_Model):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class LineSpec(_Model):
    speaker: str
    text: str
    language: str
    romanization: str = ""
    translation: str = ""
    concept_ids: list[str] = Field(default_factory=list)
    pattern_id: str | None = None


class Opening(_Model):
    narration: str
    actions: list[OpeningAction] = Field(default_factory=list)
    spoken_lines: list[LineSpec] = Field(default_factory=list)


class Concept(_Model):
    id: str
    native: str
    romanization: str
    gloss: str
    referents: list[str] = Field(default_factory=list)


class Pattern(_Model):
    id: str
    function: str
    native_template: str
    romanization_template: str
    gloss_template: str = ""
    slots: dict[str, list[str]]


HelpKind = Literal["replay_slow", "word", "frame", "meaning", "full"]


class HelpEntry(_Model):
    level: int
    label: str
    kind: HelpKind
    line: LineSpec | None = None
    concept_ids: list[str] = Field(default_factory=list)
    pattern_id: str | None = None
    text: str | None = None
    native: str | None = None
    romanization: str | None = None
    translation: str | None = None
    tap_fallback: bool = False


class CompleteWhen(_Model):
    holders: dict[str, str] = Field(default_factory=dict)
    fixtures: dict[str, str] = Field(default_factory=dict)


SuccessEvidence = Literal["recognition", "production", "transfer"]


class LearningBeat(_Model):
    id: str
    objective: str
    concept_ids: list[str] = Field(default_factory=list)
    pattern: str | None = None
    slot_values: dict[str, str] = Field(default_factory=dict)
    initial_help_level: int = 0
    success_evidence: SuccessEvidence
    world_result: str = ""
    complete_when: CompleteWhen = Field(default_factory=CompleteWhen)
    help: list[HelpEntry] = Field(default_factory=list)

    def slot_concept(self) -> str | None:
        """The concept filling this beat's pattern slot (first slot value), if any."""
        for value in self.slot_values.values():
            return value
        return None

    def help_entry(self, level: int) -> HelpEntry | None:
        for entry in self.help:
            if entry.level == level:
                return entry
        return None


class LanguageLearning(_Model):
    target_locale: str
    support_locale: str
    romanization_system: str
    starting_level: str = "absolute_beginner"
    input_mode: str = "voice_first"
    narrator_language: str = "support"
    concepts: list[Concept]
    patterns: list[Pattern] = Field(default_factory=list)
    learning_beats: list[LearningBeat]
    next_episode: str = ""

    def concept(self, concept_id: str) -> Concept | None:
        return next((c for c in self.concepts if c.id == concept_id), None)

    def pattern(self, pattern_id: str) -> Pattern | None:
        return next((p for p in self.patterns if p.id == pattern_id), None)


class Cartridge(_Model):
    schema_version: int = 1
    identity: Identity
    setting: Setting
    npcs: list[Npc]
    objects: list[GameObject] = Field(default_factory=list)
    fixtures: list[Fixture] = Field(default_factory=list)
    opening: Opening
    language_learning: LanguageLearning | None = None

    _dir: Path | None = PrivateAttr(default=None)

    @property
    def id(self) -> str:
        return self.identity.id

    @property
    def directory(self) -> Path | None:
        return self._dir

    def npc(self, npc_id: str) -> Npc | None:
        return next((n for n in self.npcs if n.id == npc_id), None)

    def object(self, object_id: str) -> GameObject | None:
        return next((o for o in self.objects if o.id == object_id), None)

    def fixture(self, fixture_id: str) -> Fixture | None:
        return next((f for f in self.fixtures if f.id == fixture_id), None)

    def art_paths(self) -> list[str]:
        art = self.setting.location.art
        paths = [art.base, *(v.image for v in art.variants)]
        for npc in self.npcs:
            paths += [npc.art.sprite, npc.art.portrait]
        paths += [o.icon for o in self.objects]
        return list(dict.fromkeys(paths))


# ---------------------------------------------------------------- validation


def _path_escapes(path: str) -> bool:
    if not path or "\\" in path or ":" in path:
        return True
    pure = PurePosixPath(path)
    return pure.is_absolute() or ".." in pure.parts


def _duplicates(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    dupes: list[str] = []
    for item in ids:
        if item in seen and item not in dupes:
            dupes.append(item)
        seen.add(item)
    return dupes


def _check_line(
    line: LineSpec,
    where: str,
    cart: Cartridge,
    concept_ids: set[str],
    pattern_ids: set[str],
    target: str | None,
    errors: list[str],
) -> None:
    if cart.npc(line.speaker) is None:
        errors.append(f"unknown_npc: {where}.speaker={line.speaker}")
    if not LOCALE_RE.match(line.language):
        errors.append(f"locale_invalid: {where}.language={line.language}")
    for cid in line.concept_ids:
        if cid not in concept_ids:
            errors.append(f"unknown_concept: {where}.concept_ids={cid}")
    if line.pattern_id is not None and line.pattern_id not in pattern_ids:
        errors.append(f"unknown_pattern: {where}.pattern_id={line.pattern_id}")
    if target is not None and line.language == target:
        if not line.romanization.strip():
            errors.append(f"line_missing_romanization: {where}")
        if not line.translation.strip():
            errors.append(f"line_missing_translation: {where}")


def _check_holder(holder: str, where: str, npc_ids: set[str], errors: list[str]) -> None:
    if holder in (PLAYER, WORLD):
        return
    if holder not in npc_ids:
        errors.append(f"unknown_npc: {where}={holder}")


def _check_opening_action(
    action: OpeningAction, where: str, cart: Cartridge, npc_ids: set[str], errors: list[str]
) -> None:
    if action.tool not in OPENING_TOOLS:
        errors.append(f"unknown_tool: {where}.tool={action.tool}")
        return
    args = action.args
    if action.tool in ("show_object", "give"):
        oid = str(args.get("object_id") or "")
        if cart.object(oid) is None:
            errors.append(f"unknown_object: {where}.object_id={oid}")
    if action.tool == "show_object" and args.get("gesture") not in GESTURES:
        errors.append(f"invalid_gesture: {where}.gesture={args.get('gesture')}")
    if action.tool == "give":
        _check_holder(str(args.get("to") or ""), f"{where}.to", npc_ids, errors)
    if action.tool == "set_fixture":
        fid = str(args.get("fixture_id") or "")
        fixture = cart.fixture(fid)
        if fixture is None:
            errors.append(f"unknown_fixture: {where}.fixture_id={fid}")
        elif args.get("state") not in fixture.states:
            errors.append(f"unknown_fixture_state: {where}.state={args.get('state')}")


def _check_help(
    beat: LearningBeat,
    where: str,
    cart: Cartridge,
    concept_ids: set[str],
    pattern_ids: set[str],
    target: str,
    errors: list[str],
) -> None:
    levels = [h.level for h in beat.help]
    for level in levels:
        if not 1 <= level <= 5:
            errors.append(f"help_level_out_of_range: {where}.help level={level}")
    for dup in _duplicates([str(x) for x in levels]):
        errors.append(f"help_level_duplicate: {where}.help level={dup}")
    for entry in beat.help:
        hw = f"{where}.help[{entry.level}]"
        for cid in entry.concept_ids:
            if cid not in concept_ids:
                errors.append(f"unknown_concept: {hw}.concept_ids={cid}")
        if entry.pattern_id is not None and entry.pattern_id not in pattern_ids:
            errors.append(f"unknown_pattern: {hw}.pattern_id={entry.pattern_id}")
        missing = {
            "replay_slow": entry.line is None,
            "word": not entry.concept_ids,
            "frame": entry.pattern_id is None,
            "meaning": not (entry.text or "").strip(),
            "full": not ((entry.native or "").strip() and (entry.romanization or "").strip()),
        }[entry.kind]
        if missing:
            errors.append(f"help_entry_incomplete: {hw} kind={entry.kind}")
        if entry.line is not None:
            _check_line(entry.line, f"{hw}.line", cart, concept_ids, pattern_ids, target, errors)


def _check_learning(cart: Cartridge, errors: list[str]) -> None:
    ll = cart.language_learning
    if ll is None:
        return
    for field in ("target_locale", "support_locale"):
        value = getattr(ll, field)
        if not LOCALE_RE.match(value):
            errors.append(f"locale_invalid: language_learning.{field}={value}")
    if ll.romanization_system not in ROMANIZATION_SYSTEMS:
        errors.append(f"romanization_system_invalid: {ll.romanization_system}")

    object_ids = {o.id for o in cart.objects}
    concept_ids = {c.id for c in ll.concepts}
    pattern_ids = {p.id for p in ll.patterns}
    npc_ids = {n.id for n in cart.npcs}
    for kind, ids in (
        ("concept", [c.id for c in ll.concepts]),
        ("pattern", [p.id for p in ll.patterns]),
        ("beat", [b.id for b in ll.learning_beats]),
    ):
        for dup in _duplicates(ids):
            errors.append(f"duplicate_id: {kind} {dup}")

    for concept in ll.concepts:
        for ref in concept.referents:
            if ref not in object_ids:
                errors.append(f"referent_unknown_object: concept {concept.id} referent={ref}")
    for obj in cart.objects:
        if obj.concept_id is not None and obj.concept_id not in concept_ids:
            errors.append(f"unknown_concept: object {obj.id}.concept_id={obj.concept_id}")
    for pattern in ll.patterns:
        for slot, values in pattern.slots.items():
            for value in values:
                if value not in concept_ids:
                    errors.append(
                        f"pattern_slot_unknown_concept: pattern {pattern.id}.{slot}={value}"
                    )
    if not ll.learning_beats:
        errors.append("no_learning_beats: language_learning.learning_beats is empty")
    for beat in ll.learning_beats:
        where = f"beat {beat.id}"
        for cid in beat.concept_ids:
            if cid not in concept_ids:
                errors.append(f"unknown_concept: {where}.concept_ids={cid}")
        beat_pattern = ll.pattern(beat.pattern) if beat.pattern is not None else None
        if beat.pattern is not None and beat_pattern is None:
            errors.append(f"unknown_pattern: {where}.pattern={beat.pattern}")
        for slot, value in beat.slot_values.items():
            if value not in concept_ids:
                errors.append(f"unknown_concept: {where}.slot_values.{slot}={value}")
            elif beat_pattern is not None and value not in beat_pattern.slots.get(slot, []):
                errors.append(f"beat_slot_invalid: {where}.slot_values.{slot}={value}")
        if beat.success_evidence != "recognition" and (beat.pattern is None or not beat.slot_values):
            errors.append(f"beat_pattern_required: {where} ({beat.success_evidence})")
        if not 0 <= beat.initial_help_level <= 5:
            errors.append(f"help_level_out_of_range: {where}.initial_help_level")
        for oid, holder in beat.complete_when.holders.items():
            if oid not in object_ids:
                errors.append(f"unknown_object: {where}.complete_when.holders={oid}")
            _check_holder(holder, f"{where}.complete_when.holders.{oid}", npc_ids, errors)
        for fid, state in beat.complete_when.fixtures.items():
            fixture = cart.fixture(fid)
            if fixture is None:
                errors.append(f"unknown_fixture: {where}.complete_when.fixtures={fid}")
            elif state not in fixture.states:
                errors.append(f"unknown_fixture_state: {where}.complete_when.{fid}={state}")
        _check_help(beat, where, cart, concept_ids, pattern_ids, ll.target_locale, errors)


def validate_cartridge(data: dict[str, Any]) -> list[str]:
    """Return a list of ``"<code>: <where>"`` errors; empty means valid."""
    try:
        cart = Cartridge.model_validate(data)
    except ValidationError as exc:
        return [
            f"schema_invalid: {'.'.join(str(p) for p in err['loc'])} {err['msg']}"
            for err in exc.errors()
        ]
    errors: list[str] = []
    if cart.schema_version != 1:
        errors.append(f"schema_version_unsupported: {cart.schema_version}")
    if not LOCALE_RE.match(cart.identity.locale):
        errors.append(f"locale_invalid: identity.locale={cart.identity.locale}")

    npc_ids = {n.id for n in cart.npcs}
    for kind, ids in (
        ("npc", [n.id for n in cart.npcs]),
        ("object", [o.id for o in cart.objects]),
        ("fixture", [f.id for f in cart.fixtures]),
    ):
        for dup in _duplicates(ids):
            errors.append(f"duplicate_id: {kind} {dup}")
    for id_ in (*npc_ids, *(o.id for o in cart.objects)):
        if id_ in (PLAYER, WORLD):
            errors.append(f"reserved_id: {id_}")

    for obj in cart.objects:
        _check_holder(obj.holder, f"object {obj.id}.holder", npc_ids, errors)
    for fixture in cart.fixtures:
        if fixture.initial not in fixture.states:
            errors.append(f"fixture_initial_invalid: {fixture.id}.initial={fixture.initial}")
    for variant in cart.setting.location.art.variants:
        for fid, state in variant.when.items():
            when_fixture = cart.fixture(fid)
            if when_fixture is None:
                errors.append(f"variant_unknown_fixture: variant {variant.id} when={fid}")
            elif state not in when_fixture.states:
                errors.append(f"variant_unknown_state: variant {variant.id} {fid}={state}")
    for path in cart.art_paths():
        if _path_escapes(path):
            errors.append(f"art_path_escapes: {path}")

    for i, action in enumerate(cart.opening.actions):
        _check_opening_action(action, f"opening.actions[{i}]", cart, npc_ids, errors)
    ll = cart.language_learning
    concept_ids = {c.id for c in ll.concepts} if ll else set()
    pattern_ids = {p.id for p in ll.patterns} if ll else set()
    target = ll.target_locale if ll else None
    for i, line in enumerate(cart.opening.spoken_lines):
        _check_line(
            line, f"opening.spoken_lines[{i}]", cart, concept_ids, pattern_ids, target, errors
        )
    for obj in cart.objects:
        if ll is None and obj.concept_id is not None:
            errors.append(f"unknown_concept: object {obj.id}.concept_id={obj.concept_id}")
    _check_learning(cart, errors)
    return errors


# ---------------------------------------------------------------- loading


def load_cartridge(cartridge_id: str, root: Path = CARTRIDGES_ROOT) -> Cartridge:
    """Load and validate ``<root>/<cartridge_id>/cartridge.json``; raise on any error."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", cartridge_id):
        raise CartridgeError(cartridge_id, ["cartridge_id_invalid"])
    directory = Path(root) / cartridge_id
    path = directory / "cartridge.json"
    if not path.is_file():
        raise FileNotFoundError(f"no cartridge at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_cartridge(data)
    if not errors and data.get("identity", {}).get("id") != cartridge_id:
        errors.append(f"identity_mismatch: identity.id != directory {cartridge_id}")
    if errors:
        raise CartridgeError(cartridge_id, errors)
    cart = Cartridge.model_validate(data)
    cart._dir = directory.resolve()
    return cart


def list_cartridges(root: Path = CARTRIDGES_ROOT) -> list[dict[str, str | None]]:
    """Summaries of every valid cartridge under ``root`` (invalid ones are logged, skipped)."""
    out: list[dict[str, str | None]] = []
    if not Path(root).is_dir():
        return out
    for directory in sorted(p for p in Path(root).iterdir() if p.is_dir()):
        if not (directory / "cartridge.json").is_file():
            continue
        try:
            cart = load_cartridge(directory.name, root)
        except (CartridgeError, ValueError, OSError) as exc:
            log.warning("skipping cartridge %s: %s", directory.name, exc)
            continue
        ll = cart.language_learning
        out.append(
            {
                "id": cart.id,
                "name": cart.identity.name,
                "tagline": cart.identity.tagline,
                "target_locale": ll.target_locale if ll else None,
            }
        )
    return out


def resolve_art_path(cartridge: Cartridge, rel_path: str) -> Path | None:
    """Absolute path of an art file inside the cartridge dir, or None if it escapes."""
    if cartridge.directory is None or _path_escapes(rel_path):
        return None
    candidate = (cartridge.directory / rel_path).resolve()
    if not candidate.is_relative_to(cartridge.directory):
        return None
    return candidate


def missing_art(cartridge: Cartridge) -> list[str]:
    """Art paths the cartridge references that do not exist on disk."""
    missing: list[str] = []
    for rel in cartridge.art_paths():
        resolved = resolve_art_path(cartridge, rel)
        if resolved is None or not resolved.is_file():
            missing.append(rel)
    return missing
