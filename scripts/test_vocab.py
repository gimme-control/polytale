"""Vocabulary rules: appearances, outcomes from the exchange ledger, states, recall, help."""

from __future__ import annotations

from core import vocab
from core.content import load_content
from core.dm import enter_scene
from core.state import Exchange, Journey, new_journey
from scripts.testkit import Checker

T = Checker("test_vocab")
CONTENT = load_content()
SCENE_ID = CONTENT.journey.scenes[0]
A, B, C = CONTENT.scene(SCENE_ID).targets[:3]  # three of this act's words


def journey_in(started: bool = True) -> Journey:
    journey = enter_scene(new_journey(CONTENT, "vocab1", language="zh-CN"), CONTENT, SCENE_ID)
    assert journey.scene is not None
    journey.scene.started = started
    return journey


def pose(journey: Journey, posed: list[str], help_level: int = 0,
         phrasebook: list[str] | None = None) -> None:
    assert journey.scene is not None
    journey.scene.exchange = Exchange(posed_item_ids=posed, help_level=help_level,
                                      phrasebook_item_ids=list(phrasebook or []),
                                      line_ids=["s0-t0-l0"],
                                      intent_hint="Wants you to join in with the chant")


def record(journey: Journey, item: str, understood: bool = True, produced: bool = False,
           attempt: str = "a1"):
    return vocab.record_result(journey, item_id=item, understood=understood, produced=produced,
                               attempt_id=attempt)


def test_appearances() -> None:
    j = journey_in()
    vocab.note_appearances(j, SCENE_ID, [A, B])
    vocab.note_appearances(j, SCENE_ID, [A])
    T.check("appearances count per line", j.vocab[A].appearances == 2
            and j.vocab[B].appearances == 1)
    T.check("appearances never change state",
            j.vocab[A].state == "not_encountered" and j.vocab[A].results == [])
    T.check("first/last scene stamped", j.vocab[A].first_scene == SCENE_ID
            and j.vocab[A].last_scene == SCENE_ID)
    vocab.note_appearances(j, "later", [A])
    T.check("last_scene follows, first_scene sticks",
            j.vocab[A].first_scene == SCENE_ID and j.vocab[A].last_scene == "later")


def test_outcomes() -> None:
    for label, help_level, looked_up, understood, outcome, state in (
        ("understood, no help", 0, False, True, "first_try", "mastered"),
        ("understood, looked it up first", 0, True, True, "with_help", "shaky"),
        ("understood, help level 1", 1, False, True, "with_help", "shaky"),
        ("understood, help level 2", 2, False, True, "with_hint", "shaky"),
        ("hint beats a lookup", 2, True, True, "with_hint", "shaky"),
        ("missed", 0, False, False, "missed", "shaky"),
        ("missed even with help", 2, False, False, "missed", "shaky"),
    ):
        j = journey_in()
        pose(j, [A], help_level, [A] if looked_up else [])
        result, is_new = record(j, A, understood)
        T.check(f"{label} -> {outcome}/{state}",
                is_new and result.outcome == outcome and j.vocab[A].state == state,
                (result, j.vocab[A].state))
    j = journey_in()
    pose(j, [B], phrasebook=[B])
    result, _ = record(j, A)
    T.check("another item's lookup does not count as help", result.outcome == "first_try")


def test_state_transitions() -> None:
    j = journey_in()
    pose(j, [A], help_level=1)
    record(j, A, attempt="a1")
    T.check("with_help leaves it shaky", j.vocab[A].state == "shaky")
    pose(j, [A])
    record(j, A, attempt="a2")
    T.check("a later first_try masters it", j.vocab[A].state == "mastered")
    record(j, A, understood=False, attempt="a3")
    T.check("a mastered item that is missed drops to shaky", j.vocab[A].state == "shaky")
    T.check("results accumulate in order",
            [r.outcome for r in j.vocab[A].results] == ["with_help", "first_try", "missed"])


def test_idempotent_and_produced() -> None:
    j = journey_in()
    pose(j, [A], help_level=1)
    first, new1 = record(j, A, produced=True, attempt="dup")
    pose(j, [A])  # ledger changed; the duplicate must not re-stamp
    second, new2 = record(j, A, understood=False, attempt="dup")
    T.check("duplicate (attempt, item) is idempotent",
            new1 and not new2 and second == first and len(j.vocab[A].results) == 1
            and j.vocab[A].state == "shaky")
    T.check("same attempt, different item is a new result", record(j, B, attempt="dup")[1])
    T.check("produced sticks on the record", j.vocab[A].produced and first.produced)
    missed, _ = record(j, C, understood=False, produced=True, attempt="m1")
    T.check("a missed word is never 'produced'", not missed.produced and not j.vocab[C].produced)
    j.scene = None
    try:
        record(j, A, attempt="x")
        T.check("recording without a scene raises", False)
    except ValueError:
        T.check("recording without a scene raises", True)


def test_recall() -> None:
    j = journey_in()
    vocab.note_appearances(j, SCENE_ID, [A, B])
    pose(j, [A])
    result, _ = record(j, A, attempt="b1")
    T.check("first_try in the scene it was met is not recall", not result.recall)
    # A word first met in an earlier act comes back: code stamps recall, not the model.
    j.record(B).first_scene = "earlier"
    pose(j, [B])
    result, _ = record(j, B, produced=True, attempt="b2")
    T.check("first_try on a word first met in an earlier scene is recall",
            result.outcome == "first_try" and result.recall)
    j.record(C).first_scene = "earlier"
    pose(j, [C], help_level=1)
    result, _ = record(j, C, attempt="b3")
    T.check("with_help on an earlier-scene word is not recall",
            result.outcome == "with_help" and not result.recall)


def test_presentation() -> None:
    j = journey_in()
    T.check("unseen -> introduce", vocab.presentation(j.vocab.get(A), SCENE_ID) == "introduce")
    vocab.note_appearances(j, SCENE_ID, [A])
    T.check("seen but no result -> still introduce",
            vocab.presentation(j.vocab[A], SCENE_ID) == "introduce")
    pose(j, [A], help_level=2)
    record(j, A, attempt="p1")
    T.check("shaky via hint -> support", vocab.presentation(j.vocab[A], SCENE_ID) == "support")
    pose(j, [A], help_level=1)
    record(j, A, attempt="p2")
    T.check("shaky with a with_help success this scene -> unaided",
            vocab.presentation(j.vocab[A], SCENE_ID) == "unaided")
    T.check("...but in another scene it needs support again",
            vocab.presentation(j.vocab[A], "later") == "support")
    pose(j, [A])
    record(j, A, attempt="p3")
    T.check("mastered -> known", vocab.presentation(j.vocab[A], SCENE_ID) == "known")
    T.check("guidance text exists for every presentation",
            set(vocab.GUIDANCE) == {"introduce", "support", "unaided", "known", "theirs"})
    T.check("no guidance still talks about lighting an object up",
            not any("highlight" in g or "object" in g for g in vocab.GUIDANCE.values()),
            vocab.GUIDANCE)
    T.check("a learner's own line is always 'theirs', whatever the record says",
            vocab.presentation(j.vocab[A], SCENE_ID, learner_side=True) == "theirs"
            and vocab.presentation(None, SCENE_ID, learner_side=True) == "theirs")


def test_help() -> None:
    j = journey_in()
    pose(j, [A, B, C])
    assert j.scene is not None
    T.check("next help starts at level 1", vocab.next_help(j.scene.exchange).level == 1)  # type: ignore[union-attr]
    first = vocab.request_help(j)
    T.check("level 1 = again: the line ids to replay, no hint",
            first.level == 1 and first.kind == "again" and first.line_ids == ["s0-t0-l0"]
            and first.hint is None, first)
    T.check("help carries no object highlights any more",
            "highlight" not in first.model_dump_json())
    second = vocab.request_help(j)
    T.check("level 2 = the intent hint",
            second.level == 2 and second.kind == "hint"
            and second.hint == "Wants you to join in with the chant", second)
    third = vocab.request_help(j)
    T.check("help caps at 2", third.level == 2 and j.scene.exchange.help_level == 2
            and vocab.next_help(j.scene.exchange) is None)
    result, _ = record(j, A, attempt="h1")
    T.check("a result after the hint is with_hint", result.outcome == "with_hint")
    for label, mutate in (("unstarted", lambda s: setattr(s, "started", False)),
                          ("complete", lambda s: setattr(s, "complete", True))):
        k = journey_in()
        mutate(k.scene)
        try:
            vocab.request_help(k)
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
