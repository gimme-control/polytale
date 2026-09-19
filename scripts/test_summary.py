"""End-of-scene summary: items, counts, recall, honest observed-behaviour lines, no scores."""

from __future__ import annotations

import re

from core import vocab
from core.content import load_content
from core.dm import enter_scene, finish_scene
from core.state import Exchange, Journey, Phrase, new_journey
from core.summary import build_summary
from scripts.testkit import Checker

T = Checker("test_summary")
CONTENT = load_content()
ZH = CONTENT.language("zh-CN")


def started(journey: Journey) -> Journey:
    assert journey.scene is not None
    journey.scene.started = True
    return journey


def record(journey: Journey, item: str, attempt: str, *, understood: bool = True,
           produced: bool = False, highlighted: bool = False, help_level: int = 0) -> None:
    assert journey.scene is not None
    journey.scene.exchange = Exchange(posed_item_ids=[item], help_level=help_level,
                                      highlighted_item_ids=[item] if highlighted else [])
    vocab.record_result(journey, item_id=item, understood=understood, produced=produced,
                        attempt_id=attempt)


def played_bar() -> Journey:
    j = started(enter_scene(new_journey(CONTENT, "sum1", language="zh-CN"), CONTENT))
    assert j.scene is not None
    vocab.note_appearances(j, "bar", ["hello", "beer", "friend", "tea", "how_much", "money",
                                      "thanks"])
    record(j, "beer", "a1", produced=True, highlighted=True)
    record(j, "beer", "a2", produced=True)
    record(j, "how_much", "a3", produced=True)
    record(j, "friend", "a4", highlighted=True)
    record(j, "money", "a5", help_level=2)
    record(j, "tea", "a6", understood=False)
    j.game.clues = ["regular", "market"]
    j.game.flags = ["photo_shown"]
    j.scene.goals_done = ["ask", "trail"]
    j.game.phrasebook = [Phrase(phrase_id="p-1", source="where is she?", text="x",
                                romanization="y", audio_url="/a", segments=[])]
    return j


def test_bar_summary() -> None:
    j = played_bar()
    summary = finish_scene(j, CONTENT)
    items = {i.item_id: i for i in summary.items}
    T.check("summary names the scene and lists its targets in order",
            summary.scene_id == "bar" and summary.scene_name == "The Corner Bar"
            and [i.item_id for i in summary.items] == CONTENT.scene("bar").targets)
    T.check("items carry text, roman, gloss and the word-audio url",
            items["beer"].text == ZH.items["beer"].text and items["beer"].roman
            == ZH.items["beer"].roman and items["beer"].gloss == "beer"
            and items["beer"].audio_url == "/api/journeys/sum1/items/beer/audio")
    T.check("states and per-scene outcomes come from the record",
            items["beer"].state == "mastered" and items["beer"].outcomes
            == ["with_help", "first_try"] and items["friend"].state == "shaky"
            and items["money"].outcomes == ["with_hint"] and items["tea"].outcomes == ["missed"]
            and items["baijiu"].state == "not_encountered" and items["baijiu"].outcomes == [])
    T.check("a word heard but never acted on stays not_encountered",
            items["hello"].state == "not_encountered" and items["thanks"].outcomes == [])
    T.check("produced is per scene", items["beer"].produced and items["how_much"].produced
            and not items["friend"].produced)
    T.check("counts add up to the target count",
            sum(summary.counts.model_dump().values()) == len(summary.items)
            and summary.counts.mastered == 2 and summary.counts.shaky == 3
            and summary.counts.heard == sum(1 for i in summary.items
                                            if i.heard and i.state == "not_encountered")
            and items["hello"].heard and not items["baijiu"].heard, summary.counts)
    T.check("the summary carries the player's own phrasebook",
            [p.source for p in summary.phrasebook] == ["where is she?"])
    T.check("nothing is recalled in the first scene",
            summary.recalled == [] and not any(i.recall for i in summary.items))
    T.check("next scene is the market", summary.next_scene is not None
            and summary.next_scene.model_dump() == {
                "id": "market", "name": "Night Market",
                "tagline": CONTENT.scene("market").tagline})
    text = " ".join(summary.lines)
    T.check("lines report goals, words met, unaided words and what the learner said",
            "Done here: Show someone Mei's photo and Find out where Mei went." in summary.lines
            and "7 of 11 words came up in The Corner Bar." in summary.lines
            and "You understood 2 of 11 words with no help." in summary.lines
            and f"You said {ZH.items['beer'].text} and {ZH.items['how_much'].text} yourself."
            in summary.lines, summary.lines)
    T.check("shaky words are named with what happens next",
            any("still need a second look" in ln and ZH.items["friend"].text in ln
                and ZH.items["tea"].text in ln for ln in summary.lines), summary.lines)
    T.check("no score, percentage, grade or fluency claim",
            not re.search(r"%|\bscore|\bfluen|\bgrade|\bpoints?\b|\blevel\b|\bpercent", text,
                          re.IGNORECASE), text)
    T.check("finish_scene completes the scene in place", j.scene is not None and j.scene.complete)


def test_recall_summary() -> None:
    j = played_bar()
    finish_scene(j, CONTENT)
    j = started(enter_scene(j, CONTENT))
    vocab.note_appearances(j, "market", ["noodles", "beer"])
    record(j, "beer", "m1", produced=True)
    record(j, "friend", "m2", highlighted=True)
    record(j, "noodles", "m3")
    summary = build_summary(j, CONTENT)
    items = {i.item_id: i for i in summary.items}
    T.check("recalled lists first_try words first met in an earlier scene",
            summary.recalled == ["beer"] and items["beer"].recall and not items["noodles"].recall
            and not items["friend"].recall)
    T.check("the recall sentence names the word and where it came from",
            f"{ZH.items['beer'].text} came back from The Corner Bar and you got it with no hints."
            in summary.lines, summary.lines)
    T.check("outcomes are this scene's only", items["beer"].outcomes == ["first_try"]
            and items["friend"].outcomes == ["with_help"])
    T.check("bar-only words are not market targets", "tea" not in items and "baijiu" not in items)
    T.check("last scene has no next scene", summary.next_scene is None)
    T.check("history holds the archived bar summary",
            [s.scene_id for s in j.history] == ["bar"] and j.history[0].counts.mastered == 2)


def test_edges() -> None:
    j = started(enter_scene(new_journey(CONTENT, "sum2", language="zh-CN"), CONTENT))
    summary = build_summary(j, CONTENT)
    T.check("an untouched scene summarizes honestly",
            summary.counts.model_dump() == {"mastered": 0, "shaky": 0, "heard": 0,
                                            "not_encountered": 11}
            and summary.lines == ["0 of 11 words came up in The Corner Bar."], summary.lines)
    record(j, "tea", "e1", highlighted=True)
    one = build_summary(j, CONTENT)
    T.check("singular grammar for one shaky word",
            f"{ZH.items['tea'].text} still needs a second look; expect a highlight next time."
            in one.lines, one.lines)
    ja = started(enter_scene(new_journey(CONTENT, "sum3", language="ja-JP"), CONTENT))
    T.check("the summary speaks the journey's language",
            build_summary(ja, CONTENT).items[5].text == CONTENT.language("ja-JP").items["beer"].text)
    for label, journey in (("no scene", new_journey(CONTENT, "sum4", language="zh-CN")),
                           ("unstarted scene", enter_scene(
                               new_journey(CONTENT, "sum5", language="zh-CN"), CONTENT))):
        try:
            finish_scene(journey, CONTENT)
            T.check(f"finish_scene refuses: {label}", False)
        except ValueError:
            T.check(f"finish_scene refuses: {label}", True)


if __name__ == "__main__":
    T.run("bar summary", test_bar_summary)
    T.run("recall summary", test_recall_summary)
    T.run("edges", test_edges)
    T.finish()
