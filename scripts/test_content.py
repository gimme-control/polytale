"""Content models, the shipped content, every validator error code, art path confinement."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from core.content import (
    CONTENT_ROOT,
    MAX_TARGETS,
    MIN_TARGETS,
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
SCENE_ID = CONTENT.journey.scenes[0]
LOCALES = ("es-ES", "ja-JP", "ko-KR", "zh-CN")


def codes(errors: list[str]) -> set[str]:
    return {e.split(":", 1)[0] for e in errors}


def mutated(fn: Callable[[Content], None]) -> set[str]:
    content = CONTENT.model_copy(deep=True)
    fn(content)
    return codes(validate_content(content))


def test_shipped_content() -> None:
    bar = CONTENT.scene(SCENE_ID)
    T.check("shipped content validates clean", validate_content(CONTENT) == [])
    T.check("four demo languages ship", set(CONTENT.languages) == set(LOCALES))
    T.check("the journey is one act", CONTENT.journey.scenes == [SCENE_ID])
    T.check("the scene carries no objects, zones or mood art",
            not hasattr(bar, "objects") and not hasattr(bar, "zones")
            and not hasattr(bar.art, "moods")
            and set(bar.art.model_dump()) == {"background", "cover"})
    T.check("the story file carries no wallet and no clock",
            set(CONTENT.journey.model_dump())
            == {"title", "tagline", "art", "premise", "gm_brief", "scenes", "endings"},
            sorted(CONTENT.journey.model_dump()))
    T.check(f"{MIN_TARGETS}-{MAX_TARGETS} targets", MIN_TARGETS <= len(bar.targets) <= MAX_TARGETS)
    T.check("targets and support words are distinct and both feed item_ids",
            not (set(bar.targets) & set(bar.support_words))
            and bar.item_ids == [*bar.targets, *bar.support_words])
    T.check("the theme's showable football words are targets",
            {"goal", "go_team", "fan_zone", "cheers"} <= set(bar.targets), bar.targets)
    T.check("no official tournament branding anywhere in the content",
            not any(word in (CONTENT.journey.model_dump_json() + bar.model_dump_json()).lower()
                    for word in ("fifa", "uefa", "messi", "ronaldo")))
    T.check("the character is a football fan, not a bartender",
            "fan" in bar.npc.role.lower() and "bartender" not in bar.npc.role.lower(),
            bar.npc.role)
    T.check("npc names resolve for every shipped locale, with a fallback",
            all(bar.npc.display_name(loc) == bar.npc.names[loc] for loc in LOCALES)
            and bar.npc.display_name("xx-XX") == bar.npc.name)
    T.check("the npc has a voice", bool(bar.npc.voice.gemini_voice))
    for locale, language in CONTENT.languages.items():
        T.check(f"{locale} defines every item of the act with text and gloss",
                set(bar.item_ids) <= set(language.items)
                and all(i.text and i.gloss for i in language.items.values()))
        T.check(f"{locale} romanization is all-or-nothing",
                all(bool(i.roman) == (language.romanization is not None)
                    for i in language.items.values()))
    T.check("every language defines the same item ids",
            len({tuple(sorted(lang.items)) for lang in CONTENT.languages.values()}) == 1)
    T.check("one language ships in Latin script with no romanization",
            any(lang.romanization is None and lang.latin_script
                for lang in CONTENT.languages.values()))
    trail = bar.goal("trail")
    assert trail is not None
    T.check("story goals evaluate against clues and flags",
            not trail.when.holds([], []) and trail.when.holds(["gate"], [])
            and bar.goal("ask").when.holds([], ["photo_shown"]))  # type: ignore[union-attr]
    story = CONTENT.journey
    T.check("the story file: title, premise, title art, endings with a fallback",
            story.title and story.premise and story.art
            and [e.id for e in story.endings] == ["found", "outside"]
            and story.endings[-1].when.model_dump(exclude_defaults=True) == {})
    T.check("the good ending turns on the last clue, not on a clock or a wallet",
            story.endings[0].when.clues == ["gate"]
            and set(story.endings[0].when.model_dump()) == {"clues", "flags"})
    T.check("the act offers several ways to its key clue",
            len(bar.clue("gate").reveal_when) >= 2  # type: ignore[union-attr]
            and "fan_zone" in bar.clue("gate").key_items)  # type: ignore[union-attr]
    T.check("the character has wants, secrets and a starting trust",
            bool(bar.npc.wants) and bool(bar.npc.secrets) and bar.npc.trust == 0)


def test_error_codes() -> None:
    def bar(c: Content):
        return c.scenes[SCENE_ID]

    cases: list[tuple[str, Callable[[Content], None]]] = [
        ("target_missing_in_language", lambda c: bar(c).targets.__setitem__(0, "goodbye")),
        ("unknown_clue", lambda c: setattr(bar(c).goals[1].when, "clue", "nope")),
        ("unknown_flag", lambda c: setattr(bar(c).goals[0].when, "flag", "nope")),
        ("unknown_flag", lambda c: bar(c).clues[0].reveal_when[0].flags.append("nope")),
        ("unknown_item", lambda c: bar(c).support_words.append("whisky")),
        ("unknown_item", lambda c: bar(c).clues[-1].key_items.append("whisky")),
        ("duplicate_id", lambda c: bar(c).clues.append(bar(c).clues[0])),
        ("duplicate_id", lambda c: bar(c).flags.append(bar(c).flags[0])),
        ("duplicate_id", lambda c: bar(c).goals.append(bar(c).goals[0])),
        ("duplicate_id", lambda c: bar(c).targets.append(bar(c).targets[0])),
        ("duplicate_id", lambda c: c.journey.endings.insert(0, c.journey.endings[0])),
        ("duplicate_id", lambda c: c.journey.scenes.append(SCENE_ID)),
        ("unknown_clue", lambda c: c.journey.endings[0].when.clues.append("nope")),
        ("unknown_flag", lambda c: c.journey.endings[0].when.flags.append("nope")),
        ("ending_no_fallback", lambda c: c.journey.endings.pop()),
        ("art_escapes_scene", lambda c: setattr(c.journey.endings[0], "art", "../../x.webp")),
        ("art_escapes_scene", lambda c: setattr(bar(c).art, "cover", "/etc/passwd")),
        ("art_escapes_scene", lambda c: setattr(bar(c).art, "background", "../../.env")),
        ("target_count", lambda c: setattr(bar(c), "targets", bar(c).targets[:MIN_TARGETS - 1])),
        ("target_count", lambda c: setattr(
            bar(c), "targets", bar(c).targets + bar(c).support_words[:MAX_TARGETS])),
        ("journey_unknown_scene", lambda c: c.journey.scenes.append("airport")),
        ("goal_empty", lambda c: setattr(bar(c).goals[0].when, "flag", None)),
        ("romanization_missing",
         lambda c: setattr(c.languages["zh-CN"].items["hello"], "roman", " ")),
        ("romanization_unexpected", lambda c: setattr(c.languages["zh-CN"], "romanization", None)),
        ("languages_empty", lambda c: c.languages.clear()),
    ]
    for i, (code, fn) in enumerate(cases):
        got = mutated(fn)
        T.check(f"case {i}: {code} is reported", code in got, got)
    T.check("the shipped copy was not touched by the mutations", validate_content(CONTENT) == [])


def test_recall_overlap() -> None:
    """Recall across acts is only checked once a journey has a second act."""
    T.check("a one-act journey never trips recall_overlap",
            "recall_overlap" not in codes(validate_content(CONTENT)))

    def two_acts(shared: int) -> Callable[[Content], None]:
        def fn(c: Content) -> None:
            first = c.scenes[SCENE_ID]
            second = first.model_copy(deep=True)
            second.id = "second"
            second._dir = first._dir
            second.targets = (first.targets[:shared]
                              + first.support_words[:MIN_TARGETS - shared])
            c.scenes["second"] = second
            c.journey.scenes = [SCENE_ID, "second"]
        return fn

    from core.content import MIN_RECALL_OVERLAP
    T.check(f"{MIN_RECALL_OVERLAP - 1} shared targets -> recall_overlap",
            "recall_overlap" in mutated(two_acts(MIN_RECALL_OVERLAP - 1)))
    T.check(f"{MIN_RECALL_OVERLAP} shared targets -> accepted",
            "recall_overlap" not in mutated(two_acts(MIN_RECALL_OVERLAP)))


def test_loader_failures() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "content"
        shutil.copytree(CONTENT_ROOT, root, ignore=shutil.ignore_patterns("*.png", "*.webp"))
        T.check("a copied tree loads", load_content(root).journey.scenes == [SCENE_ID])
        story_path = root / "journey.json"
        story = json.loads(story_path.read_text(encoding="utf-8"))
        original_story = dict(story)
        del story["premise"]
        story_path.write_text(json.dumps(story), encoding="utf-8")
        try:
            load_content(root)
            T.check("a story file without a premise is a schema error", False)
        except ContentError as exc:
            T.check("a story file without a premise is a schema error",
                    codes(exc.errors) == {"schema"} and any("premise" in e for e in exc.errors))
        story_path.write_text(json.dumps(original_story), encoding="utf-8")

        scene_path = root / "scenes" / SCENE_ID / "scene.json"
        original = scene_path.read_text(encoding="utf-8")
        data = json.loads(original)
        data["support_words"].append("whisky")
        scene_path.write_text(json.dumps(data), encoding="utf-8")
        try:
            load_content(root)
            T.check("loader raises on a validation error", False)
        except ContentError as exc:
            T.check("loader raises ContentError with codes", "unknown_item" in codes(exc.errors),
                    exc.errors)

        data = json.loads(original)
        del data["npc"]["anchor"]
        data["npc"]["trust"] = 99
        scene_path.write_text(json.dumps(data), encoding="utf-8")
        try:
            load_content(root)
            T.check("loader raises on a schema error", False)
        except ContentError as exc:
            T.check("schema errors name the file and field",
                    codes(exc.errors) == {"schema"} and any("anchor" in e for e in exc.errors)
                    and any("trust" in e for e in exc.errors), exc.errors)

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
    bar = CONTENT.scene(SCENE_ID)
    path = resolve_art_path(bar, bar.art.background)
    T.check("art resolves inside the scene dir",
            path == (CONTENT_ROOT / "scenes" / SCENE_ID / bar.art.background).resolve())
    for bad in ("../journey.json", "/etc/passwd", "art/../../../.env", "", "."):
        try:
            resolve_art_path(bar, bad)
            T.check(f"escape refused: {bad!r}", False)
        except ValueError:
            T.check(f"escape refused: {bad!r}", True)
    T.check("a scene declares exactly one background and one cover, and no object art",
            set(bar.art_paths) == {bar.art.background, bar.art.cover}
            and not any("obj_" in rel for rel in bar.art_paths))
    expected = {f"{s.id}/{rel}" for s in CONTENT.scenes.values() for rel in s.art_paths
                if not resolve_art_path(s, rel).is_file()}
    last = CONTENT.scene(CONTENT.journey.scenes[-1])
    expected |= {f"{last.id}/{e.art}" for e in CONTENT.journey.endings
                 if e.art and not resolve_art_path(last, e.art).is_file()}
    T.check("missing_art lists exactly the absent files", set(missing_art(CONTENT)) == expected)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "content"
        shutil.copytree(CONTENT_ROOT, root, ignore=shutil.ignore_patterns("*.png", "*.webp"))
        art = root / "scenes" / SCENE_ID / "art"
        art.mkdir(exist_ok=True)
        (art / Path(bar.art.background).name).write_bytes(b"webp")
        missing = missing_art(load_content(root))
        T.check("a present file is not reported missing",
                f"{SCENE_ID}/{bar.art.background}" not in missing, missing)


if __name__ == "__main__":
    T.run("shipped content", test_shipped_content)
    T.run("error codes", test_error_codes)
    T.run("recall overlap", test_recall_overlap)
    T.run("loader failures", test_loader_failures)
    T.run("art paths", test_art_paths)
    T.finish()
