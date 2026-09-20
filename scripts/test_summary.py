"""End-of-scene summary: items, counts, recall, honest observed-behaviour lines, no scores."""

from __future__ import annotations

import re

from core import vocab
from core.content import load_content
from core.dm import enter_scene, finish_scene
from core.state import Exchange, Journey, new_journey
from core.summary import build_summary
from scripts.testkit import Checker

T = Checker("test_summary")
CONTENT = load_content()
SCENE_ID = CONTENT.journey.scenes[0]
BAR = CONTENT.scene(SCENE_ID)
ZH = CONTENT.language("zh-CN")
TARGETS = BAR.targets
N = len(TARGETS)


def started(journey: Journey) -> Journey:
    assert journey.scene is not None
    journey.scene.started = True
    return journey


def record(journey: Journey, item: str, attempt: str, *, understood: bool = True,
           produced: bool = False, help_level: int = 0) -> None:
    assert journey.scene is not None
    journey.scene.exchange = Exchange(posed_item_ids=[item], help_level=help_level)
    vocab.record_result(journey, item_id=item, understood=understood, produced=produced,
                        attempt_id=attempt)


def played_bar() -> Journey:
    j = started(enter_scene(new_journey(CONTENT, "sum1", language="zh-CN"), CONTENT))
    assert j.scene is not None
    heard = TARGETS[:7]
    vocab.note_appearances(j, SCENE_ID, list(heard))
    record(j, TARGETS[1], "a1", produced=True, help_level=1)
    record(j, TARGETS[1], "a2", produced=True)
    record(j, TARGETS[2], "a3", produced=True)
    record(j, TARGETS[3], "a4", help_level=1)
    record(j, TARGETS[4], "a5", help_level=2)
    record(j, TARGETS[5], "a6", understood=False)
    j.game.clues = ["regular", "gate"]
    j.game.flags = ["photo_shown"]
    j.scene.goals_done = ["ask", "trail"]
    return j


def test_bar_summary() -> None:
    j = played_bar()
    summary = finish_scene(j, CONTENT)
    items = {i.item_id: i for i in summary.items}
    T.check("summary names the scene and lists its targets in order",
            summary.scene_id == SCENE_ID and summary.scene_name == BAR.name
            and [i.item_id for i in summary.items] == TARGETS)
    first = items[TARGETS[1]]
    T.check("items carry text, roman, gloss and the word-audio url",
            first.text == ZH.items[TARGETS[1]].text and first.roman == ZH.items[TARGETS[1]].roman
            and first.gloss == ZH.items[TARGETS[1]].gloss
            and first.audio_url == f"/api/journeys/sum1/items/{TARGETS[1]}/audio")
    T.check("states and per-scene outcomes come from the record",
            first.state == "mastered" and first.outcomes == ["with_help", "first_try"]
            and items[TARGETS[3]].state == "shaky"
            and items[TARGETS[4]].outcomes == ["with_hint"]
            and items[TARGETS[5]].outcomes == ["missed"]
            and items[TARGETS[-1]].state == "not_encountered"
            and items[TARGETS[-1]].outcomes == [])
    T.check("a word heard but never acted on stays not_encountered",
            items[TARGETS[0]].state == "not_encountered" and items[TARGETS[6]].outcomes == [])
    T.check("produced is per scene", first.produced and items[TARGETS[2]].produced
            and not items[TARGETS[3]].produced)
    T.check("counts add up to the target count",
            sum(summary.counts.model_dump().values()) == len(summary.items)
            and summary.counts.mastered == 2 and summary.counts.shaky == 3
            and summary.counts.heard == sum(1 for i in summary.items
                                            if i.heard and i.state == "not_encountered")
            and items[TARGETS[0]].heard and not items[TARGETS[-1]].heard, summary.counts)
    T.check("nothing is recalled in the first scene",
            summary.recalled == [] and not any(i.recall for i in summary.items))
    T.check("a one-act journey has no next scene", summary.next_scene is None)
    text = " ".join(summary.lines)
    T.check("lines report goals, words met, unaided words and what the learner said",
            f"Done here: {BAR.goal('ask').label} and {BAR.goal('trail').label}."  # type: ignore[union-attr]
            in summary.lines
            and f"7 of {N} words came up in {BAR.name}." in summary.lines
            and f"You understood 2 of {N} words with no help." in summary.lines
            and f"You said {ZH.items[TARGETS[1]].text} and {ZH.items[TARGETS[2]].text} yourself."
            in summary.lines, summary.lines)
    T.check("shaky words are named with what happens next",
            any("still need a second look" in ln and ZH.items[TARGETS[3]].text in ln
                and ZH.items[TARGETS[5]].text in ln for ln in summary.lines), summary.lines)
    T.check("no score, percentage, grade or fluency claim",
            not re.search(r"%|\bscore|\bfluen|\bgrade|\bpoints?\b|\blevel\b|\bpercent", text,
                          re.IGNORECASE), text)
    T.check("finish_scene completes the scene in place", j.scene is not None and j.scene.complete)


def test_recall_summary() -> None:
    """Recall is stamped by code whenever a word first met in an earlier act comes back."""
    content = CONTENT.model_copy(deep=True)
    earlier = content.scene(SCENE_ID).model_copy(deep=True)
    earlier.id, earlier.name = "earlier", "The Night Before"
    content.scenes["earlier"] = earlier
    j = played_bar()
    j.record(TARGETS[7]).first_scene = "earlier"
    record(j, TARGETS[7], "r1", produced=True)
    summary = build_summary(j, content)
    items = {i.item_id: i for i in summary.items}
    T.check("recalled lists first_try words first met in an earlier scene",
            summary.recalled == [TARGETS[7]] and items[TARGETS[7]].recall
            and not items[TARGETS[2]].recall)
    T.check("the recall sentence names the word and where it came from",
            f"{ZH.items[TARGETS[7]].text} came back from The Night Before and you got it with "
            "no hints." in summary.lines, summary.lines)
    T.check("an origin scene that is no longer shipped degrades instead of crashing",
            any("came back from" in ln for ln in build_summary(j, CONTENT).lines))


def test_edges() -> None:
    j = started(enter_scene(new_journey(CONTENT, "sum2", language="zh-CN"), CONTENT))
    summary = build_summary(j, CONTENT)
    T.check("an untouched scene summarizes honestly",
            summary.counts.model_dump() == {"mastered": 0, "shaky": 0, "heard": 0,
                                            "not_encountered": N}
            and summary.lines == [f"0 of {N} words came up in {BAR.name}."], summary.lines)
    record(j, TARGETS[0], "e1", help_level=1)
    one = build_summary(j, CONTENT)
    T.check("singular grammar for one shaky word",
            f"{ZH.items[TARGETS[0]].text} still needs a second look." in one.lines, one.lines)
    for locale in sorted(CONTENT.languages):
        other = started(enter_scene(new_journey(CONTENT, "sum3", language=locale), CONTENT))
        T.check(f"the summary speaks the journey's language ({locale})",
                build_summary(other, CONTENT).items[0].text
                == CONTENT.language(locale).items[TARGETS[0]].text)
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
