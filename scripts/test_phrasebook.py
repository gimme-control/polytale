"""The player's phrasebook with a scripted fake client: structure, refusals, ledger stamps."""

from __future__ import annotations

import json
from typing import Any

from core import phrasebook, vocab
from core.content import load_content
from core.dm import enter_scene
from core.state import Journey, new_journey
from scripts.testkit import Checker, FakeClient

T = Checker("test_phrasebook")
CONTENT = load_content()
ZH = CONTENT.language("zh-CN")
MODELS = ["fast-a", "fast-b"]


class Text:
    """Stands in for a structured-output response: just ``.text``."""

    def __init__(self, payload: Any) -> None:
        self.text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)


def seg(item_id: str, gloss: str = "g", roman: str | None = None) -> dict[str, str]:
    item = ZH.items[item_id]
    return {"t": item.text, "r": item.roman if roman is None else roman, "g": gloss}


def in_bar() -> Journey:
    journey = enter_scene(new_journey(CONTENT, "pb1", language="zh-CN"), CONTENT)
    assert journey.scene is not None
    journey.scene.started = True
    return journey


def test_lookup() -> None:
    j = in_bar()
    answer = {"refused": False, "segments": [seg("she", "she"), seg("where", "where is", "ZAI NAR"),
                                             {"t": "？", "r": "x", "g": "?"}]}
    client = FakeClient([Text(answer)])
    j2, phrase = phrasebook.lookup(j, CONTENT, "  where   is she? ", client=client, models=MODELS)
    T.check("one model call, on the first (fastest) model",
            [c["model"] for c in client.models.calls] == ["fast-a"])
    T.check("the input journey is untouched", j.game.phrasebook == []
            and j.scene is not None and j.scene.exchange.phrasebook_item_ids == [])
    T.check("phrase shape: id, normalized source, text, romanization, audio url",
            phrase.phrase_id.startswith("p-") and phrase.source == "where is she?"
            and phrase.text == ZH.items["she"].text + ZH.items["where"].text + "？"
            and phrase.romanization == f"{ZH.items['she'].roman} {ZH.items['where'].roman}"
            and phrase.audio_url == f"/api/journeys/pb1/phrases/{phrase.phrase_id}/audio")
    T.check("segments carry t, r, g; lexicon words take the lexicon's romanization; "
            "punctuation has neither r nor g",
            [s.model_dump() for s in phrase.segments] == [
                {"t": ZH.items["she"].text, "r": ZH.items["she"].roman, "g": "she"},
                {"t": ZH.items["where"].text, "r": ZH.items["where"].roman, "g": "where is"},
                {"t": "？", "r": "", "g": ""}])
    T.check("lexicon items in the phrase are found by code", phrase.item_ids == ["where", "she"])
    assert j2.scene is not None
    T.check("the phrase is kept, and its words are marked assisted for this exchange",
            j2.game.phrasebook == [phrase]
            and j2.scene.exchange.phrasebook_item_ids == ["where", "she"])
    result, _ = vocab.record_result(j2, item_id="where", understood=True, produced=True,
                                    attempt_id="a1")
    T.check("...so saying it next stamps with_help, by code", result.outcome == "with_help")
    T.check("a lookup costs no turn and no clock",
            j2.game.minutes_used == 0 and j2.scene.turn == j.scene.turn)  # type: ignore[union-attr]
    T.check("find_phrase resolves by id", phrasebook.find_phrase(j2, phrase.phrase_id) == phrase
            and phrasebook.find_phrase(j2, "p-nope") is None)
    sent = client.models.calls[0]
    system = sent["config"].system_instruction
    T.check("the prompt is scene-aware and leans on the scene's words",
            CONTENT.scene("bar").name in system and ZH.items["baijiu"].text in system
            and ZH.items["noodles"].text not in system and "".join(sent["contents"]) == "where is she?")
    T.check("structured output is requested",
            sent["config"].response_mime_type == "application/json")


def test_refusals() -> None:
    j = in_bar()
    for label, text, code in (("empty", "   ", "empty"),
                              ("target-language input", ZH.items["beer"].text, "target_language"),
                              ("mixed input", "what is " + ZH.items["beer"].text, "target_language")):
        client = FakeClient([])
        try:
            phrasebook.lookup(j, CONTENT, text, client=client, models=MODELS)
            T.check(f"{label} is refused", False)
        except phrasebook.PhraseRefused as exc:
            T.check(f"{label} is refused by code, before any model call ({code})",
                    exc.code == code and client.models.calls == [])
    client = FakeClient([Text({"refused": True, "segments": []})])
    try:
        phrasebook.lookup(j, CONTENT, "what did he just say?", client=client, models=MODELS)
        T.check("a request to translate the character is refused", False)
    except phrasebook.PhraseRefused as exc:
        T.check("a request to translate the character is refused (model says so, typed error)",
                exc.code == "not_a_phrase" and len(client.models.calls) == 1)
    T.check("nothing was stored by any refusal", j.game.phrasebook == [])
    T.check("the prompt tells the model what to refuse",
            "translate the other person" in phrasebook.build_prompt(ZH, CONTENT.scene("bar"),
                                                                    CONTENT))


def test_bad_output_cascades() -> None:
    j = in_bar()
    good = {"refused": False, "segments": [seg("beer", "beer")]}
    for label, bad in (
        ("not JSON", Text("sorry!")),
        ("no segments", Text({"refused": False, "segments": []})),
        ("romanization in t", Text({"refused": False, "segments": [
            {"t": "pijiu", "r": "píjiǔ", "g": "beer"}]})),
        ("word without romanization", Text({"refused": False, "segments": [
            {"t": "慢", "r": "", "g": "slow"}]})),
        ("word glued to punctuation", Text({"refused": False, "segments": [
            {"t": ZH.items["beer"].text + "？", "r": "x", "g": "beer"}]})),
        ("far too long", Text({"refused": False, "segments": [seg("beer")] * 13})),
        ("provider error", RuntimeError("503 unavailable")),
    ):
        client = FakeClient([bad, Text(good)])
        _, phrase = phrasebook.lookup(j, CONTENT, "a beer", client=client, models=MODELS)
        T.check(f"{label}: falls through to the next model",
                [c["model"] for c in client.models.calls] == MODELS
                and phrase.text == ZH.items["beer"].text)
    try:
        phrasebook.lookup(j, CONTENT, "a beer", models=MODELS,
                          client=FakeClient([Text("x"), RuntimeError("boom")]))
        T.check("every model failing raises PhraseError", False)
    except phrasebook.PhraseError:
        T.check("every model failing raises PhraseError; nothing stored",
                j.game.phrasebook == [])


def test_outside_play() -> None:
    fresh = new_journey(CONTENT, "pb2", language="zh-CN")
    answer = Text({"refused": False, "segments": [seg("hello", "hello")]})
    j2, phrase = phrasebook.lookup(fresh, CONTENT, "hello", client=FakeClient([answer]),
                                   models=MODELS)
    T.check("works before any scene is entered (whole lexicon, no exchange to mark)",
            phrase.item_ids == ["hello"] and j2.game.phrasebook == [phrase])
    j = in_bar()
    for i in range(phrasebook.MAX_KEPT + 3):
        j, _ = phrasebook.lookup(j, CONTENT, f"hello {i}", models=MODELS, client=FakeClient(
            [Text({"refused": False, "segments": [seg("hello", "hello")]})]))
    T.check("the kept phrasebook is capped, newest last",
            len(j.game.phrasebook) == phrasebook.MAX_KEPT
            and j.game.phrasebook[-1].source == f"hello {phrasebook.MAX_KEPT + 2}")
    T.check("an over-long ask is trimmed, not refused",
            len(phrasebook.lookup(j, CONTENT, "beer " * 100, models=MODELS, client=FakeClient(
                [Text({"refused": False, "segments": [seg("beer")]})]))[1].source)
            <= phrasebook.MAX_SOURCE_CHARS)
    ja_journey = enter_scene(new_journey(CONTENT, "pb3", language="ja-JP"), CONTENT)
    ja = CONTENT.language("ja-JP")
    _, ja_phrase = phrasebook.lookup(ja_journey, CONTENT, "a beer please", models=MODELS,
                                     client=FakeClient([Text({"refused": False, "segments": [
                                         {"t": ja.items["beer"].text, "r": "x", "g": "beer"},
                                         {"t": ja.items["want"].text, "r": "y", "g": "please"}]})]))
    T.check("the same code serves another language from its own lexicon",
            ja_phrase.romanization == f"{ja.items['beer'].roman} {ja.items['want'].roman}"
            and set(ja_phrase.item_ids) == {"beer", "want"})


if __name__ == "__main__":
    T.run("lookup", test_lookup)
    T.run("refusals", test_refusals)
    T.run("bad output cascades", test_bad_output_cascades)
    T.run("outside play", test_outside_play)
    T.finish()
