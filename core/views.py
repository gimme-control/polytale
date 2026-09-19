"""Client-facing payload builders: World, CartridgeView, PublicState, line lookup."""

from __future__ import annotations

from typing import Any

from core import ledger
from core.cartridge import Cartridge
from core.recap import build_recap
from core.state import GameState, NpcEntry, SpokenLine


def art_url(cartridge: Cartridge, rel_path: str) -> str:
    return f"/api/cartridges/{cartridge.id}/art/{rel_path}"


def plate_path(cartridge: Cartridge, fixtures: dict[str, str]) -> str:
    """Most-specific matching variant wins (count of matched keys); ties -> later entry."""
    art = cartridge.setting.location.art
    best, best_score = art.base, 0
    for variant in art.variants:
        if variant.when and all(fixtures.get(k) == v for k, v in variant.when.items()):
            if len(variant.when) >= best_score:
                best, best_score = variant.image, len(variant.when)
    return best


def world_view(state: GameState, cartridge: Cartridge) -> dict[str, Any]:
    world = state.world
    return {
        "holders": dict(world.holders),
        "fixtures": dict(world.fixtures),
        "focus": world.focus.model_dump() if world.focus else None,
        "plate_url": art_url(cartridge, plate_path(cartridge, world.fixtures)),
    }


def cartridge_view(cartridge: Cartridge) -> dict[str, Any]:
    """Public cartridge description. Objects never expose their English gloss."""
    ll = cartridge.language_learning
    initial_fixtures = {f.id: f.initial for f in cartridge.fixtures}
    objects = []
    for obj in cartridge.objects:
        concept = ll.concept(obj.concept_id) if ll and obj.concept_id else None
        objects.append(
            {
                "id": obj.id,
                "concept_id": obj.concept_id,
                "icon_url": art_url(cartridge, obj.icon),
                "native": concept.native if concept else None,
                "romanization": concept.romanization if concept else None,
            }
        )
    return {
        "id": cartridge.id,
        "name": cartridge.identity.name,
        "tagline": cartridge.identity.tagline,
        "target_locale": ll.target_locale if ll else None,
        "support_locale": ll.support_locale if ll else cartridge.identity.locale,
        "romanization_system": ll.romanization_system if ll else None,
        "location": {
            "name": cartridge.setting.location.name,
            "plate_url": art_url(cartridge, plate_path(cartridge, initial_fixtures)),
        },
        "npcs": [
            {
                "id": npc.id,
                "name": npc.name,
                "role": npc.role,
                "sprite_url": art_url(cartridge, npc.art.sprite),
                "portrait_url": art_url(cartridge, npc.art.portrait),
                "stage": npc.stage.model_dump(),
            }
            for npc in cartridge.npcs
        ],
        "objects": objects,
        "fixtures": [
            {"id": f.id, "name": f.name, "states": list(f.states), "hotspot": f.hotspot.model_dump()}
            for f in cartridge.fixtures
        ],
    }


def public_state(state: GameState, cartridge: Cartridge) -> dict[str, Any]:
    """PublicState payload; ``help_cue`` is the cue for the active beat's current level."""
    return {
        "session_id": state.session_id,
        "cartridge": cartridge_view(cartridge),
        "started": state.started,
        "turn": state.turn,
        "transcript": [entry.model_dump() for entry in state.transcript],
        "world": world_view(state, cartridge),
        "learning": ledger.learning_view(state, cartridge),
        "episode_complete": state.episode_complete,
        "recap": build_recap(state, cartridge) if state.episode_complete else None,
        "help_cue": ledger.current_help_cue(state, cartridge),
    }


def find_line(state: GameState, cartridge: Cartridge, line_id: str) -> SpokenLine | None:
    """A spoken line by id: delivered transcript lines, then authored help-cue lines."""
    for entry in state.transcript:
        if isinstance(entry, NpcEntry) and entry.line.line_id == line_id:
            return entry.line
    ll = cartridge.language_learning
    if ll is None or not line_id.startswith("help-"):
        return None
    for beat in ll.learning_beats:
        for help_entry in beat.help:
            if help_entry.line is not None and line_id == ledger.help_line_id(
                beat.id, help_entry.level
            ):
                return SpokenLine.build(cartridge, state.session_id, line_id, help_entry.line)
    return None
