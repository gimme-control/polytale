"""Cartridge schema + validation: the real cartridge is valid; mutations yield error codes."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.cartridge import (
    CartridgeError,
    list_cartridges,
    load_cartridge,
    missing_art,
    resolve_art_path,
    validate_cartridge,
)
from scripts.testkit import CARTRIDGE_ID, Checker, plain_cartridge_data, raw_cartridge

T = Checker("test_cartridge_schema")


def codes(data: dict[str, Any]) -> set[str]:
    return {e.split(":", 1)[0] for e in validate_cartridge(data)}


def ll(d: dict[str, Any]) -> dict[str, Any]:
    return d["language_learning"]


def beat(d: dict[str, Any], beat_id: str) -> dict[str, Any]:
    return next(b for b in ll(d)["learning_beats"] if b["id"] == beat_id)


def expect(label: str, code: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    data = raw_cartridge()
    mutate(data)
    found = codes(data)
    T.check(f"{label} -> {code}", code in found, sorted(found))


def test_real_cartridge() -> None:
    data = raw_cartridge()
    T.check("real cartridge validates", validate_cartridge(data) == [], validate_cartridge(data))
    cart = load_cartridge(CARTRIDGE_ID)
    T.check("loads via load_cartridge", cart.id == CARTRIDGE_ID)
    assert cart.language_learning is not None
    T.check("three beats", [b.id for b in cart.language_learning.learning_beats]
            == ["ground_key", "request_key", "transfer_map"])
    for b in cart.language_learning.learning_beats:
        T.check(f"{b.id} help ladder has levels 1..5",
                sorted(h.level for h in b.help) == [1, 2, 3, 4, 5])
    opening = cart.opening.spoken_lines[0]
    T.check("opening line is 鍵。/Kagi.", (opening.text, opening.romanization) == ("鍵。", "Kagi."))
    T.check("opening narration <= 2 sentences",
            cart.opening.narration.count(".") <= 2, cart.opening.narration)
    T.check("list_cartridges lists it",
            any(c["id"] == CARTRIDGE_ID and c["target_locale"] == "ja-JP"
                for c in list_cartridges()))
    T.check("missing_art returns a list of relative paths",
            isinstance(missing_art(cart), list)
            and all(p.startswith("art/") for p in missing_art(cart)))
    T.check("resolve_art_path rejects escape", resolve_art_path(cart, "../secret.png") is None)
    T.check("resolve_art_path accepts art/", resolve_art_path(cart, "art/plate_base.png")
            is not None)


def test_plain_story_mode() -> None:
    data = plain_cartridge_data()
    T.check("cartridge without language_learning is valid",
            validate_cartridge(data) == [], validate_cartridge(data))


def test_mutations() -> None:
    expect("object holder unknown npc", "unknown_npc",
           lambda d: d["objects"][0].update(holder="npc.ghost"))
    expect("opening speaker unknown", "unknown_npc",
           lambda d: d["opening"]["spoken_lines"][0].update(speaker="npc.ghost"))
    expect("opening action unknown object", "unknown_object",
           lambda d: d["opening"]["actions"][0]["args"].update(object_id="obj.nope"))
    expect("opening action unknown tool", "unknown_tool",
           lambda d: d["opening"]["actions"][0].update(tool="advance_beat"))
    expect("opening action bad gesture", "invalid_gesture",
           lambda d: d["opening"]["actions"][0]["args"].update(gesture="juggle"))
    expect("complete_when unknown fixture", "unknown_fixture",
           lambda d: beat(d, "transfer_map")["complete_when"]["fixtures"].update(
               {"fx.nope": "open"}))
    expect("complete_when bad fixture state", "unknown_fixture_state",
           lambda d: beat(d, "transfer_map")["complete_when"]["fixtures"].update(
               {"fx.airship": "sunk"}))
    expect("complete_when unknown object", "unknown_object",
           lambda d: beat(d, "request_key")["complete_when"]["holders"].update(
               {"obj.nope": "player"}))
    expect("beat unknown concept", "unknown_concept",
           lambda d: beat(d, "ground_key")["concept_ids"].append("object.nope"))
    expect("object unknown concept", "unknown_concept",
           lambda d: d["objects"][0].update(concept_id="object.nope"))
    expect("opening line unknown concept", "unknown_concept",
           lambda d: d["opening"]["spoken_lines"][0]["concept_ids"].append("object.nope"))
    expect("beat unknown pattern", "unknown_pattern",
           lambda d: beat(d, "request_key").update(pattern="request.nope"))
    expect("line unknown pattern", "unknown_pattern",
           lambda d: d["opening"]["spoken_lines"][0].update(pattern_id="request.nope"))
    expect("help unknown pattern", "unknown_pattern",
           lambda d: beat(d, "request_key")["help"][2].update(pattern_id="request.nope"))
    expect("concept referent not an object", "referent_unknown_object",
           lambda d: ll(d)["concepts"][0]["referents"].append("obj.nope"))
    expect("pattern slot value not a concept", "pattern_slot_unknown_concept",
           lambda d: ll(d)["patterns"][0]["slots"]["object"].append("object.nope"))
    expect("beat slot value outside pattern slots", "beat_slot_invalid",
           lambda d: beat(d, "request_key")["slot_values"].update(object="word.hai"))
    expect("fixture initial not in states", "fixture_initial_invalid",
           lambda d: d["fixtures"][0].update(initial="exploded"))
    expect("variant when key not a fixture", "variant_unknown_fixture",
           lambda d: d["setting"]["location"]["art"]["variants"][0]["when"].update(
               {"fx.nope": "open"}))
    expect("variant when value not a state", "variant_unknown_state",
           lambda d: d["setting"]["location"]["art"]["variants"][0].update(
               when={"fx.engine_panel": "melted"}))
    expect("help level 0", "help_level_out_of_range",
           lambda d: beat(d, "ground_key")["help"][0].update(level=0))
    expect("help level 6", "help_level_out_of_range",
           lambda d: beat(d, "ground_key")["help"][4].update(level=6))
    expect("help level duplicated", "help_level_duplicate",
           lambda d: beat(d, "ground_key")["help"][1].update(level=1))
    expect("help entry missing its content", "help_entry_incomplete",
           lambda d: beat(d, "request_key")["help"][3].update(text=None))
    expect("romanization system unknown", "romanization_system_invalid",
           lambda d: ll(d).update(romanization_system="kunrei"))
    expect("target locale not BCP-47-ish", "locale_invalid",
           lambda d: ll(d).update(target_locale="Japanese"))
    expect("support locale lower-case region", "locale_invalid",
           lambda d: ll(d).update(support_locale="en-us"))
    expect("identity locale invalid", "locale_invalid",
           lambda d: d["identity"].update(locale="english"))
    expect("art path with ..", "art_path_escapes",
           lambda d: d["setting"]["location"]["art"].update(base="../outside.png"))
    expect("absolute art path", "art_path_escapes",
           lambda d: d["npcs"][0]["art"].update(sprite="/etc/passwd"))
    expect("windows art path", "art_path_escapes",
           lambda d: d["objects"][0].update(icon="C:\\art\\key.png"))
    expect("opening target line missing romanization", "line_missing_romanization",
           lambda d: d["opening"]["spoken_lines"][0].update(romanization=""))
    expect("opening target line missing translation", "line_missing_translation",
           lambda d: d["opening"]["spoken_lines"][0].update(translation=""))
    expect("help line missing romanization", "line_missing_romanization",
           lambda d: beat(d, "request_key")["help"][0]["line"].update(romanization=""))
    expect("duplicate beat id", "duplicate_id",
           lambda d: beat(d, "request_key").update(id="ground_key"))
    expect("duplicate object id", "duplicate_id",
           lambda d: d["objects"][1].update(id="obj.engine_key"))
    expect("production beat without pattern", "beat_pattern_required",
           lambda d: beat(d, "request_key").update(pattern=None, slot_values={}))
    expect("unknown top-level field (executable logic)", "schema_invalid",
           lambda d: d.update(script="give_everything()"))
    expect("missing required field", "schema_invalid",
           lambda d: d.pop("setting"))
    expect("bad success_evidence", "schema_invalid",
           lambda d: beat(d, "ground_key").update(success_evidence="vibes"))
    expect("schema version", "schema_version_unsupported",
           lambda d: d.update(schema_version=2))


def test_loader_raises() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = raw_cartridge()
        data["fixtures"][0]["initial"] = "exploded"
        (root / CARTRIDGE_ID).mkdir()
        (root / CARTRIDGE_ID / "cartridge.json").write_text(json.dumps(data), encoding="utf-8")
        try:
            load_cartridge(CARTRIDGE_ID, root)
            T.check("loader raises on invalid cartridge", False)
        except CartridgeError as exc:
            T.check("loader raises on invalid cartridge",
                    any(e.startswith("fixture_initial_invalid") for e in exc.errors))
        T.check("list_cartridges skips invalid", list_cartridges(root) == [])

        good = raw_cartridge()
        (root / "other-id").mkdir()
        (root / "other-id" / "cartridge.json").write_text(json.dumps(good), encoding="utf-8")
        try:
            load_cartridge("other-id", root)
            T.check("loader rejects identity/dir mismatch", False)
        except CartridgeError as exc:
            T.check("loader rejects identity/dir mismatch",
                    any(e.startswith("identity_mismatch") for e in exc.errors))
    try:
        load_cartridge("../etc")
        T.check("loader rejects path-like id", False)
    except CartridgeError:
        T.check("loader rejects path-like id", True)


if __name__ == "__main__":
    T.run("real cartridge", test_real_cartridge)
    T.run("plain story mode", test_plain_story_mode)
    T.run("mutations", test_mutations)
    T.run("loader", test_loader_raises)
    T.finish()
