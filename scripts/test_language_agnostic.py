"""Language-agnostic core: no target-language literals or language names in code, and the
offline loop plays end to end from a different lexicon (ja-JP) and from one with no
romanization."""

from __future__ import annotations

import re

from core.content import Language, Romanization, load_content, validate_content
from core.prompt import build_snapshot, build_system_prompt
from core.tools import declaration_schemas
from core.views import public_state
from core import phrasebook
from scripts.test_dm_offline import bar_by_tab, market_by_dare
from scripts.testkit import ROOT, Checker

T = Checker("test_language_agnostic")
CONTENT = load_content()
SCAN_DIRS = ("core", "server", "media", "web/src")
SCAN_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".json"}
SKIP_PARTS = {"__pycache__", "node_modules", "fixtures", "dist"}
# Hiragana, katakana, CJK ideographs (+ext A), hangul, CJK punctuation, full-width forms.
TARGET_SCRIPT = re.compile(r"[　-ヿ㐀-䶿一-鿿가-힯＀-￯]")


def language_names() -> list[str]:
    """Every name a shipped language file gives itself or its romanization."""
    names: set[str] = set()
    for language in CONTENT.languages.values():
        names |= set(language.name.split()) | {language.native_name}
        if language.romanization is not None:
            names |= set(language.romanization.system.split()) | {language.romanization.label}
    return sorted(names)


def test_no_literals() -> None:
    names = [n for n in language_names() if not TARGET_SCRIPT.search(n)]
    T.check("language names come from the content files", {"Mandarin", "Japanese"} <= set(names),
            names)
    name_re = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b", re.IGNORECASE)
    for rel in SCAN_DIRS:
        base = ROOT / rel
        if not base.is_dir():
            print(f"SKIP {rel}/ (not present)")
            continue
        offenders: list[str] = []
        for path in sorted(base.rglob("*")):
            parts = set(path.relative_to(ROOT).parts)
            if (not path.is_file() or path.suffix not in SCAN_SUFFIXES or parts & SKIP_PARTS
                    or "mock" in path.name.lower()):
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                hit = TARGET_SCRIPT.search(line) or name_re.search(line)
                if hit:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {hit.group(0)!r}")
        T.check(f"{rel}/ has no target-language literals or language names", not offenders,
                f"{len(offenders)} hits, first: {offenders[:5]}")


def test_prompt_is_built_from_the_lexicon() -> None:
    bar = CONTENT.scene("bar")
    zh, ja = CONTENT.language("zh-CN"), CONTENT.language("ja-JP")
    zh_prompt = build_system_prompt(CONTENT, bar, zh)
    ja_prompt = build_system_prompt(CONTENT, bar, ja)
    T.check("each prompt names its own language and romanization",
            zh.name in zh_prompt and zh.romanization.label in zh_prompt  # type: ignore[union-attr]
            and ja.name in ja_prompt and ja.romanization.label in ja_prompt  # type: ignore[union-attr]
            and zh.name not in ja_prompt and ja.name not in zh_prompt)
    T.check("examples are rendered from the active lexicon only",
            zh.items["beer"].text in zh_prompt and ja.items["beer"].text in ja_prompt
            and ja.items["beer"].text not in zh_prompt and zh.items["beer"].text not in ja_prompt)
    T.check("typed-romanization example strips marks for either language",
            "`pijiu`" in zh_prompt and "`biru`" in ja_prompt)
    T.check("the speaker name follows the locale",
            bar.npc.names["zh-CN"] in zh_prompt and bar.npc.names["ja-JP"] in ja_prompt)
    T.check("tool declarations name the active language, never another",
            ja.name in str(declaration_schemas(bar, ja))
            and zh.name not in str(declaration_schemas(bar, ja)))
    pb = phrasebook.build_prompt(ja, bar, CONTENT)
    T.check("the phrasebook prompt is built from the active lexicon too",
            ja.name in pb and ja.items["beer"].text in pb and zh.name not in pb
            and zh.items["beer"].text not in pb)


def test_ja_offline_loop() -> None:
    ja = CONTENT.language("ja-JP")
    journey, bar = bar_by_tab("ja-JP")
    journey, market = market_by_dare(journey, "ja-JP")
    T.check("ja-JP: the scripted story plays through both acts to an ending",
            bar[-1].scene_complete and market[-1].ending is not None
            and market[-1].ending.id == "kickoff" and journey.game.wallet == 12)
    T.check("ja-JP: lines are built from the ja lexicon with its romanization",
            bar[0].lines[1].text == ja.items["beer"].text
            and bar[0].lines[1].romanization == ja.items["beer"].roman
            and bar[0].lines[0].speaker_name == CONTENT.scene("bar").npc.names["ja-JP"])
    summary = market[-1].summary
    assert summary is not None
    T.check("ja-JP: summary items use ja text",
            {i.item_id: i.text for i in summary.items}["scarf"] == ja.items["scarf"].text)
    T.check("ja-JP: same ledger outcomes as any other language",
            journey.vocab["where"].state == "mastered"
            and journey.vocab["too_expensive"].results[0].outcome == "first_try")
    fresh, _ = bar_by_tab("ja-JP")
    snapshot = build_snapshot(fresh, CONTENT, CONTENT.scene("bar"), ja, CONTENT.personas[0], None)
    zh_texts = [i.text for i in CONTENT.language("zh-CN").items.values()]
    ja_texts = {i.text for i in ja.items.values()}
    T.check("ja-JP: the snapshot carries no other language's words",
            not any(t in snapshot for t in zh_texts if t not in ja_texts
                    and not any(t in j for j in ja_texts)))


def test_language_without_romanization() -> None:
    content = CONTENT.model_copy(deep=True)
    source = content.language("zh-CN")
    content.languages["xx-XX"] = Language(
        locale="xx-XX", name="Testish", native_name="Testish", romanization=None,
        word_spacing=True, typing_note="",
        items={k: v.model_copy(update={"text": "w" + k.replace("_", ""), "roman": ""})
               for k, v in source.items.items()},
    )
    T.check("a spaced language with no romanization validates", validate_content(content) == [])
    journey, results = bar_by_tab("xx-XX", content)
    T.check("no romanization: lines have empty romanization and spaced text",
            all(line.romanization == "" and all(s.r == "" for s in line.segments)
                for r in results for line in r.lines)
            and results[3].lines[0].text == "wshe wfanzone")
    prompt = build_system_prompt(content, content.scene("bar"), content.language("xx-XX"))
    T.check("no romanization: the prompt does not promise one",
            "subtitles with" not in prompt and "`wbeer`" in prompt)
    T.check("public state reports a null romanization label",
            public_state(journey, content).language.romanization_label is None)
    roman = Romanization(system="sys", label="Lbl")
    T.check("romanization model needs both system and label", roman.system and roman.label)


if __name__ == "__main__":
    T.run("no literals", test_no_literals)
    T.run("prompt from lexicon", test_prompt_is_built_from_the_lexicon)
    T.run("ja-JP offline loop", test_ja_offline_loop)
    T.run("no-romanization language", test_language_without_romanization)
    T.finish()
