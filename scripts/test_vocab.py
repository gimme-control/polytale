"""Vocabulary rules: appearances, outcomes from the exchange ledger, states, recall, help."""

from __future__ import annotations

from core import vocab
from core.content import load_content
from core.dm import enter_scene
from core.state import Exchange, Journey, new_journey
from scripts.testkit import Checker

T = Checker("test_vocab")
CONTENT = load_content()


def journey_in(scene_id: str = "bar", started: bool = True) -> Journey:
    journey = enter_scene(new_journey(CONTENT, "vocab1", language="zh-CN"), CONTENT, scene_id)
    assert journey.scene is not None
    journey.scene.started = started
    return journey


def pose(journey: Journey, posed: list[str], highlighted: list[str], help_level: int = 0) -> None:
    assert journey.scene is not None
    journey.scene.exchange = Exchange(posed_item_ids=posed, highlighted_item_ids=highlighted,
                                      help_level=help_level, line_ids=["s0-t0-l0"],
                                      intent_hint="Wants to know which drink you want")


def record(journey: Journey, item: str, understood: bool = True, produced: bool = False,
           attempt: str = "a1"):
    return vocab.record_result(journey, item_id=item, understood=understood, produced=produced,
                               attempt_id=attempt)


def test_appearances() -> None:
    j = journey_in()
    vocab.note_appearances(j, "bar", ["beer", "water"])
    vocab.note_appearances(j, "bar", ["beer"])
    T.check("appearances count per line", j.vocab["beer"].appearances == 2
            and j.vocab["water"].appearances == 1)
    T.check("appearances never change state",
            j.vocab["beer"].state == "not_encountered" and j.vocab["beer"].results == [])
    T.check("first/last scene stamped", j.vocab["beer"].first_scene == "bar"
            and j.vocab["beer"].last_scene == "bar")
    vocab.note_appearances(j, "market", ["beer"])
    T.check("last_scene follows, first_scene sticks",
            j.vocab["beer"].first_scene == "bar" and j.vocab["beer"].last_scene == "market")


def test_outcomes() -> None:
    for label, highlighted, help_level, understood, outcome, state in (
        ("understood, no support", [], 0, True, "first_try", "mastered"),
        ("understood, highlighted", ["beer"], 0, True, "with_help", "shaky"),
        ("understood, help level 1", [], 1, True, "with_help", "shaky"),
        ("understood, help level 2", [], 2, True, "with_hint", "shaky"),
        ("hint beats highlight", ["beer"], 2, True, "with_hint", "shaky"),
        ("missed", [], 0, False, "missed", "shaky"),
        ("missed even with help", ["beer"], 2, False, "missed", "shaky"),
    ):
        j = journey_in()
        pose(j, ["beer"], highlighted, help_level)
        result, is_new = record(j, "beer", understood)
        T.check(f"{label} -> {outcome}/{state}",
                is_new and result.outcome == outcome and j.vocab["beer"].state == state,
                (result, j.vocab["beer"].state))
    j = journey_in()
    pose(j, ["water"], ["water"])
    result, _ = record(j, "beer")
    T.check("another item's highlight does not count as help", result.outcome == "first_try")


def test_state_transitions() -> None:
    j = journey_in()
    pose(j, ["beer"], ["beer"])
    record(j, "beer", attempt="a1")
    T.check("with_help leaves it shaky", j.vocab["beer"].state == "shaky")
    pose(j, ["beer"], [])
    record(j, "beer", attempt="a2")
    T.check("a later first_try masters it", j.vocab["beer"].state == "mastered")
    record(j, "beer", understood=False, attempt="a3")
    T.check("a mastered item that is missed drops to shaky", j.vocab["beer"].state == "shaky")
    T.check("results accumulate in order",
            [r.outcome for r in j.vocab["beer"].results] == ["with_help", "first_try", "missed"])


def test_idempotent_and_produced() -> None:
    j = journey_in()
    pose(j, ["beer"], ["beer"])
    first, new1 = record(j, "beer", produced=True, attempt="dup")
    pose(j, ["beer"], [])  # ledger changed; the duplicate must not re-stamp
    second, new2 = record(j, "beer", understood=False, attempt="dup")
    T.check("duplicate (attempt, item) is idempotent",
            new1 and not new2 and second == first and len(j.vocab["beer"].results) == 1
            and j.vocab["beer"].state == "shaky")
    T.check("same attempt, different item is a new result", record(j, "water", attempt="dup")[1])
    T.check("produced sticks on the record", j.vocab["beer"].produced and first.produced)
    missed, _ = record(j, "tea", understood=False, produced=True, attempt="m1")
    T.check("a missed word is never 'produced'", not missed.produced and not j.vocab["tea"].produced)
    j.scene = None
    try:
        record(j, "beer", attempt="x")
        T.check("recording without a scene raises", False)
    except ValueError:
        T.check("recording without a scene raises", True)


def test_recall() -> None:
    j = journey_in("bar")
    vocab.note_appearances(j, "bar", ["beer", "water"])
    pose(j, ["beer"], [])
    result, _ = record(j, "beer", attempt="b1")
    T.check("first_try in the scene it was met is not recall", not result.recall)
    assert j.scene is not None
    j.scene.complete = True
    j = enter_scene(j, CONTENT)
    assert j.scene is not None and j.scene.scene_id == "market"
    j.scene.started = True
    result, _ = record(j, "beer", produced=True, attempt="m1")
    T.check("first_try on a word first met in an earlier scene is recall",
            result.outcome == "first_try" and result.recall)
    pose(j, ["water"], ["water"])
    result, _ = record(j, "water", attempt="m2")
    T.check("with_help on an earlier-scene word is not recall",
            result.outcome == "with_help" and not result.recall)
    result, _ = record(j, "noodles", attempt="m3")
    T.check("a word new to this scene is not recall", not result.recall)


def test_presentation() -> None:
    j = journey_in()
    T.check("unseen -> introduce", vocab.presentation(j.vocab.get("beer"), "bar") == "introduce")
    vocab.note_appearances(j, "bar", ["beer"])
    T.check("seen but no result -> still introduce",
            vocab.presentation(j.vocab["beer"], "bar") == "introduce")
    pose(j, ["beer"], [], help_level=2)
    record(j, "beer", attempt="p1")
    T.check("shaky via hint -> highlight", vocab.presentation(j.vocab["beer"], "bar") == "highlight")
    pose(j, ["beer"], ["beer"])
    record(j, "beer", attempt="p2")
    T.check("shaky with a with_help success this scene -> no highlight",
            vocab.presentation(j.vocab["beer"], "bar") == "no_highlight")
    T.check("...but in the next scene it is highlighted again",
            vocab.presentation(j.vocab["beer"], "market") == "highlight")
    pose(j, ["beer"], [])
    record(j, "beer", attempt="p3")
    T.check("mastered -> no support", vocab.presentation(j.vocab["beer"], "bar") == "no_support")
    T.check("guidance text exists for every presentation",
            set(vocab.GUIDANCE) == {"introduce", "highlight", "no_highlight", "no_support",
                                    "theirs"})
    T.check("a customer's line is always 'theirs', whatever the record says",
            vocab.presentation(j.vocab["beer"], "bar", learner_side=True) == "theirs"
            and vocab.presentation(None, "bar", learner_side=True) == "theirs")
    T.check("mastered_items feeds the highlight gate", vocab.mastered_items(j) == {"beer"})


def test_help() -> None:
    j = journey_in()
    pose(j, ["beer", "water", "hello"], ["beer"])
    assert j.scene is not None
    T.check("next help starts at level 1", vocab.next_help(j.scene.exchange).level == 1)  # type: ignore[union-attr]
    first = vocab.request_help(j, CONTENT)
    T.check("level 1 = again: line ids + posed objects, no hint",
            first.level == 1 and first.kind == "again" and first.line_ids == ["s0-t0-l0"]
            and first.highlight_object_ids == ["beer", "water"] and first.hint is None, first)
    second = vocab.request_help(j, CONTENT)
    T.check("level 2 = the intent hint",
            second.level == 2 and second.kind == "hint"
            and second.hint == "Wants to know which drink you want", second)
    third = vocab.request_help(j, CONTENT)
    T.check("help caps at 2", third.level == 2 and j.scene.exchange.help_level == 2
            and vocab.next_help(j.scene.exchange) is None)
    result, _ = record(j, "beer", attempt="h1")
    T.check("a result after the hint is with_hint", result.outcome == "with_hint")
    j.scene.zones["water"] = "gone"
    pose(j, ["water"], [])
    T.check("objects that are gone are not highlighted by help",
            vocab.request_help(j, CONTENT).highlight_object_ids == [])
    for label, mutate in (("unstarted", lambda s: setattr(s, "started", False)),
                          ("complete", lambda s: setattr(s, "complete", True))):
        k = journey_in()
        mutate(k.scene)
        try:
            vocab.request_help(k, CONTENT)
            T.check(f"help refused on a {label} scene", False)
        except ValueError:
            T.check(f"help refused on a {label} scene", True)


if __name__ == "__main__":
    T.run("appearances", test_appearances)
    T.run("outcomes", test_outcomes)
    T.run("state transitions", test_state_transitions)
    T.run("idempotent + produced", test_idempotent_and_produced)
    T.run("recall", test_recall)
    T.run("presentation", test_presentation)
    T.run("help", test_help)
    T.finish()
