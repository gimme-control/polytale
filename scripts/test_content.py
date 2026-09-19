"""Content models, the shipped content, every validator error code, art path confinement."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from core.content import (
    CONTENT_ROOT,
    Content,
    ContentError,
    load_content,
    missing_art,
    resolve_art_path,
    validate_content,
)
from scripts.testkit import Checker

T = Checker("test_content")
CONTENT = load_content()


def codes(errors: list[str]) -> set[str]:
    return {e.split(":", 1)[0] for e in errors}


def mutated(fn: Callable[[Content], None]) -> set[str]:
    content = CONTENT.model_copy(deep=True)
    fn(content)
    return codes(validate_content(content))


def test_shipped_content() -> None:
    T.check("shipped content validates clean", validate_content(CONTENT) == [])
    T.check("both demo languages ship", set(CONTENT.languages) == {"zh-CN", "ja-JP"})
    T.check("journey is bar then market", CONTENT.journey.scenes == ["bar", "market"])
    T.check("three personas: warm, brisk, unhinged",
            [p.id for p in CONTENT.personas] == ["warm", "brisk", "unhinged"])
    bar, market = CONTENT.scene("bar"), CONTENT.scene("market")
    T.check("bar objects are the fixed art set",
            [o.id for o in bar.objects]
            == ["beer", "water", "tea", "baijiu", "menu", "tab", "football", "tv", "photo",
                "money"])
    T.check("market objects are the fixed art set",
            [o.id for o in market.objects]
            == ["noodles", "dumplings", "chili", "beer", "water", "flag", "scarf", "ticket",
                "photo", "money"])
    T.check("chili teaches the 'spicy' item", market.object("chili").item_id == "spicy")  # type: ignore[union-attr]
    T.check("8-12 targets per act", (len(bar.targets), len(market.targets)) == (12, 12))
    T.check("act 2 reuses >= 5 act 1 targets incl. friend, where, want, money",
            len(set(bar.targets) & set(market.targets)) >= 5
            and {"friend", "where", "want", "money"} <= set(bar.targets) & set(market.targets))
    T.check("the theme's showable football words are targets",
            {"football", "goal"} <= set(bar.targets) and {"ticket", "flag", "scarf"} <= set(
                market.targets))
    T.check("no official tournament branding anywhere in the content",
            not any(word in (CONTENT.journey.model_dump_json() + bar.model_dump_json()
                             + market.model_dump_json()).lower()
                    for word in ("fifa", "uefa", "messi", "ronaldo")))
    T.check("money and the photo start in the inventory; drinks start on display",
            bar.object("money").zone == "inventory"  # type: ignore[union-attr]
            and bar.object("photo").zone == "inventory"  # type: ignore[union-attr]
            and all(bar.object(o).zone == "display" for o in ("beer", "water", "tea")))  # type: ignore[union-attr]
    T.check("drinks and food carry a price",
            all(o.price for o in bar.objects if o.id in ("beer", "water", "tea"))
            and all(o.price for o in market.objects if o.id in ("noodles", "dumplings")))
    T.check("moods are neutral/pleased/puzzled", bar.moods == ["neutral", "pleased", "puzzled"])
    T.check("npc names resolve per locale with a fallback",
            bar.npc.display_name("zh-CN") == bar.npc.names["zh-CN"]
            and bar.npc.display_name("xx-XX") == bar.npc.name)
    T.check("npc voices: bartender and vendor differ",
            bar.npc.voice.gemini_voice and market.npc.voice.gemini_voice
            and bar.npc.voice.gemini_voice != market.npc.voice.gemini_voice)
    for locale, language in CONTENT.languages.items():
        needed = set(bar.item_ids) | set(market.item_ids)
        T.check(f"{locale} defines every item with text, romanization and gloss",
                needed <= set(language.items)
                and all(i.text and i.roman and i.gloss for i in language.items.values()))
    T.check("both languages define the same item ids",
            set(CONTENT.language("zh-CN").items) == set(CONTENT.language("ja-JP").items))
    trail = bar.goal("trail")
    assert trail is not None
    T.check("story goals evaluate against clues and flags",
            not trail.when.holds({}, [], []) and trail.when.holds({}, ["stall"], [])
            and bar.goal("ask").when.holds({}, [], ["photo_shown"]))  # type: ignore[union-attr]
    story = CONTENT.journey
    T.check("the story file: title, premise, wallet, clock, endings with a fallback",
            story.title == "Kickoff" and story.wallet == 60
            and story.clock.total_minutes == 75 and story.clock.minutes_per_turn == 3
            and story.clock.label == "Kickoff" and story.art == "title.webp"
            and [e.id for e in story.endings] == ["kickoff", "late", "outside"]
            and story.endings[-1].when.model_dump(exclude_defaults=True) == {})
    T.check("each act offers more than one way to its key clue",
            len(bar.clue("stall").reveal_when) >= 2  # type: ignore[union-attr]
            and len(market.clue("gate").reveal_when) >= 2  # type: ignore[union-attr]
            and "fan_zone" in bar.clue("stall").key_items)  # type: ignore[union-attr]
    T.check("characters have wants, secrets and a starting trust",
            all(s.npc.wants and s.npc.secrets and s.npc.trust == 0 for s in (bar, market)))
    T.check("market food can be haggled; the bar's prices are fixed",
            market.object("dumplings").price_floor == 8  # type: ignore[union-attr]
            and all(o.price_floor is None for o in bar.objects))
    T.check("the match ball can be grabbed (he will mind); the TV can only be pointed at",
            bar.object("football").actions == ["point", "take"]  # type: ignore[union-attr]
            and bar.object("tv").actions == ["point"]  # type: ignore[union-attr]
            and list(bar.object("tv").positions) == ["display"]  # type: ignore[union-attr]
            and market.object("ticket").zone == "display"  # type: ignore[union-attr]
            and market.object("flag").price_floor == 6)  # type: ignore[union-attr]
    T.check("objects carry verbs; the photo can be shown",
            "show" in bar.object("photo").actions  # type: ignore[union-attr]
            and "pay" in bar.object("tab").actions  # type: ignore[union-attr]
            and "eat" in market.object("chili").actions)  # type: ignore[union-attr]
    T.check("the clock: past-midnight ends wrap",
            story.clock.model_copy(update={"start": "23:30", "end": "00:15"}).total_minutes == 45)


def test_error_codes() -> None:
    def bar(c: Content):
        return c.scenes["bar"]

    cases: list[tuple[str, Callable[[Content], None]]] = [
        ("unknown_item", lambda c: setattr(bar(c).objects[0], "item_id", "whisky")),
        ("target_missing_in_language", lambda c: bar(c).targets.__setitem__(0, "goodbye")),
        ("unknown_object", lambda c: bar(c).goals[1].when.in_zone.update({"card": "npc"})),
        ("unknown_action", lambda c: bar(c).objects[0].actions.append("juggle")),
        ("price_floor_invalid", lambda c: setattr(bar(c).objects[0], "price_floor", 99)),
        ("price_floor_invalid", lambda c: setattr(bar(c).objects[4], "price_floor", 1)),
        ("unknown_clue", lambda c: setattr(bar(c).goals[1].when, "clue", "nope")),
        ("unknown_flag", lambda c: setattr(bar(c).goals[0].when, "flag", "nope")),
        ("unknown_flag", lambda c: bar(c).clues[0].reveal_when[0].flags.append("nope")),
        ("unknown_object", lambda c: bar(c).flags[1].requires_paid.append("menu")),
        ("unknown_item", lambda c: bar(c).support_words.append("whisky")),
        ("duplicate_id", lambda c: bar(c).clues.append(bar(c).clues[0])),
        ("duplicate_id", lambda c: bar(c).flags.append(bar(c).flags[0])),
        ("duplicate_id", lambda c: c.journey.endings.insert(0, c.journey.endings[0])),
        ("unknown_clue", lambda c: c.journey.endings[0].when.clues.append("nope")),
        ("unknown_flag", lambda c: c.journey.endings[0].when.flags.append("nope")),
        ("ending_no_fallback", lambda c: c.journey.endings.pop()),
        ("art_escapes_scene", lambda c: setattr(c.journey.endings[0], "art", "../../x.webp")),
        ("clock_empty", lambda c: setattr(c.journey.clock, "end", c.journey.clock.start)),
        ("unknown_zone", lambda c: setattr(bar(c).objects[0], "zone", "fridge")),
        ("unknown_zone", lambda c: bar(c).zones.append("fridge")),
        ("unknown_zone", lambda c: bar(c).goals[1].when.in_zone.update({"money": "fridge"})),
        ("zone_without_position", lambda c: setattr(bar(c).objects[0], "zone", "npc")),
        ("zone_without_position",
         lambda c: bar(c).goals[1].when.in_zone.update({"beer": "npc"})),
        ("unknown_zone", lambda c: setattr(bar(c).objects[0], "zone", "wallet")),
        ("duplicate_id", lambda c: bar(c).objects.append(bar(c).objects[0])),
        ("duplicate_id", lambda c: bar(c).goals.append(bar(c).goals[0])),
        ("duplicate_id", lambda c: c.personas.append(c.personas[0])),
        ("duplicate_id", lambda c: c.journey.scenes.append("bar")),
        ("art_escapes_scene", lambda c: setattr(bar(c).objects[0], "art", "../market/art/x.png")),
        ("art_escapes_scene", lambda c: setattr(bar(c).art, "cover", "/etc/passwd")),
        ("target_count", lambda c: setattr(bar(c), "targets", bar(c).targets[:7])),
        ("target_count", lambda c: setattr(
            c.scenes["market"], "targets",
            c.scenes["market"].targets + ["tea", "menu"])),
        ("recall_overlap", lambda c: setattr(
            c.scenes["market"], "targets",
            ["noodles", "dumplings", "spicy", "beer", "water", "money", "tea"])),
        ("journey_unknown_scene", lambda c: c.journey.scenes.append("airport")),
        ("personas_empty", lambda c: c.personas.clear()),
        ("goal_empty", lambda c: setattr(bar(c).goals[0].when, "flag", None)),
        ("romanization_missing",
         lambda c: setattr(c.languages["zh-CN"].items["beer"], "roman", " ")),
        ("romanization_unexpected", lambda c: setattr(c.languages["zh-CN"], "romanization", None)),
        ("languages_empty", lambda c: c.languages.clear()),
    ]
    for i, (code, fn) in enumerate(cases):
        got = mutated(fn)
        T.check(f"case {i}: {code} is reported", code in got, got)
    T.check("the shipped copy was not touched by the mutations", validate_content(CONTENT) == [])


def test_recall_overlap_boundary() -> None:
    def exactly(n: int) -> Callable[[Content], None]:
        shared = ["thanks", "friend", "where", "want", "money"][:n]
        fresh = ["noodles", "dumplings", "spicy"]

        def fn(c: Content) -> None:
            # Pad with market-only ids that every language defines, so only overlap varies.
            for locale in c.languages:
                for k in range(5):
                    c.languages[locale].items[f"pad{k}"] = c.languages[locale].items["spicy"]
            c.scenes["market"].targets = shared + fresh + [f"pad{k}" for k in range(8 - n - 3)]
        return fn

    T.check("4 shared targets -> recall_overlap", "recall_overlap" in mutated(exactly(4)))
    T.check("5 shared targets -> accepted", "recall_overlap" not in mutated(exactly(5)))


def test_loader_failures() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "content"
        shutil.copytree(CONTENT_ROOT, root, ignore=shutil.ignore_patterns("*.png", "*.webp"))
        T.check("a copied tree loads", load_content(root).journey.scenes == ["bar", "market"])
        story_path = root / "journey.json"
        story = json.loads(story_path.read_text(encoding="utf-8"))
        del story["wallet"]
        story_path.write_text(json.dumps(story), encoding="utf-8")
        try:
            load_content(root)
            T.check("a story file without a wallet is a schema error", False)
        except ContentError as exc:
            T.check("a story file without a wallet is a schema error",
                    codes(exc.errors) == {"schema"} and any("wallet" in e for e in exc.errors))
        story["wallet"] = 60
        story_path.write_text(json.dumps(story), encoding="utf-8")

        scene_path = root / "scenes" / "bar" / "scene.json"
        original = scene_path.read_text(encoding="utf-8")
        data = json.loads(original)
        data["objects"][0]["item_id"] = "whisky"
        scene_path.write_text(json.dumps(data), encoding="utf-8")
        try:
            load_content(root)
            T.check("loader raises on a validation error", False)
        except ContentError as exc:
            T.check("loader raises ContentError with codes", "unknown_item" in codes(exc.errors),
                    exc.errors)

        data = json.loads(original)
        data["objects"][0]["positions"]["display"]["x"] = 1.5
        del data["npc"]["anchor"]
        scene_path.write_text(json.dumps(data), encoding="utf-8")
        try:
            load_content(root)
            T.check("loader raises on a schema error", False)
        except ContentError as exc:
            T.check("schema errors name the file and field",
                    codes(exc.errors) == {"schema"} and any("anchor" in e for e in exc.errors)
                    and any("positions.display.x" in e for e in exc.errors), exc.errors)

        data = json.loads(original)
        data["id"] = "pub"
        scene_path.write_text(json.dumps(data), encoding="utf-8")
        try:
            load_content(root)
            T.check("loader raises on an id/dir mismatch", False)
        except ContentError as exc:
            T.check("scene id must match its directory", codes(exc.errors) == {"id_mismatch"})

        scene_path.write_text("{ not json", encoding="utf-8")
        try:
            load_content(root)
            T.check("loader raises on broken JSON", False)
        except ContentError as exc:
            T.check("broken JSON is 'unreadable'", codes(exc.errors) == {"unreadable"})


def test_art_paths() -> None:
    bar = CONTENT.scene("bar")
    path = resolve_art_path(bar, "art/obj_beer.png")
    T.check("art resolves inside the scene dir",
            path == (CONTENT_ROOT / "scenes" / "bar" / "art" / "obj_beer.png").resolve())
    for bad in ("../market/scene.json", "/etc/passwd", "art/../../../.env", "", "."):
        try:
            resolve_art_path(bar, bad)
            T.check(f"escape refused: {bad!r}", False)
        except ValueError:
            T.check(f"escape refused: {bad!r}", True)
    expected = {f"{s.id}/{rel}" for s in CONTENT.scenes.values() for rel in s.art_paths
                if not resolve_art_path(s, rel).is_file()}
    last = CONTENT.scene(CONTENT.journey.scenes[-1])
    expected |= {f"{last.id}/{e.art}" for e in CONTENT.journey.endings
                 if e.art and not resolve_art_path(last, e.art).is_file()}
    T.check("missing_art lists exactly the absent files", set(missing_art(CONTENT)) == expected)
    T.check("art paths follow the agreed names",
            set(bar.art_paths) == {"art/bg.webp", "art/cover.webp", "art/bg_pleased.webp",
                                   "art/bg_puzzled.webp", "art/obj_beer.png",
                                   "art/obj_water.png", "art/obj_tea.png", "art/obj_menu.png",
                                   "art/obj_money.png", "art/obj_baijiu.png", "art/obj_tab.png",
                                   "art/obj_photo.png", "art/obj_football.png",
                                   "art/obj_tv.png"})
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "content"
        shutil.copytree(CONTENT_ROOT, root, ignore=shutil.ignore_patterns("*.png", "*.webp"))
        art = root / "scenes" / "bar" / "art"
        art.mkdir(exist_ok=True)
        (art / "obj_beer.png").write_bytes(b"png")
        missing = missing_art(load_content(root))
        T.check("a present file is not reported missing", "bar/art/obj_beer.png" not in missing)


if __name__ == "__main__":
    T.run("shipped content", test_shipped_content)
    T.run("error codes", test_error_codes)
    T.run("recall overlap boundary", test_recall_overlap_boundary)
    T.run("loader failures", test_loader_failures)
    T.run("art paths", test_art_paths)
    T.finish()
