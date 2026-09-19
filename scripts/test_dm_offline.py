"""The turn loop with a scripted fake Gemini client: opening, a scripted playthrough to every
ending, the clock, verbs, retries, nudges, failures, the highlight gate, recall across acts,
difficulty, persistence and payload hygiene."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from core import game, views, vocab
from core.content import Content, load_content
from core.dm import TurnError, TurnResult, enter_scene, finish_scene, run_opening, run_turn
from core.state import (
    Journey,
    load_journey,
    new_journey,
    save_journey,
    set_difficulty,
    set_persona,
)
from scripts.testkit import Checker, FakeClient, call, lexicon_line, reply, say, text_reply

T = Checker("test_dm_offline")
CONTENT = load_content()
MODELS = ["fake-model"]


def attempt(i: int, text: str = "", mode: str = "text", tapped: str | None = None,
            action: str | None = None) -> dict:
    return {"attempt_id": f"att{i}", "input_mode": mode, "transcript": text,
            "tapped_object_id": tapped, "action_id": action}


def verb(i: int, action: str, object_id: str) -> dict:
    return attempt(i, mode="tap", tapped=object_id, action=action)


def opened(locale: str = "zh-CN", jid: str = "off1", content: Content = CONTENT) -> Journey:
    language = content.language(locale)
    journey = enter_scene(new_journey(content, jid, language=locale), content)
    script = [reply(say(lexicon_line(language, ["hello"]),
                        lexicon_line(language, ["beer"], ["beer"]), mood="pleased"))]
    journey, _ = run_opening(journey, content, client=FakeClient(script), models=MODELS)
    return journey


def play(journey: Journey, content: Content, script: list[Any], attempts: list[dict],
         opening: bool = False) -> tuple[Journey, list[TurnResult]]:
    client = FakeClient(script)
    results: list[TurnResult] = []
    if opening:
        journey, result = run_opening(journey, content, client=client, models=MODELS)
        results.append(result)
    for att in attempts:
        journey, result = run_turn(journey, content, att, client=client, models=MODELS)
        results.append(result)
    assert client.models.script == [], "script not consumed"
    return journey, results


def bar_by_tab(locale: str, content: Content = CONTENT) -> tuple[Journey, list[TurnResult]]:
    """Act 1 the fast way: show the photo, pay Mei's tab, get pointed to the night market."""
    language = content.language(locale)
    journey = enter_scene(new_journey(content, f"gold-{locale}", language=locale), content)
    script = [
        reply(say(lexicon_line(language, ["hello"]), lexicon_line(language, ["beer"], ["beer"]))),
        reply(call("move_object", object_id="photo", to_zone="counter"),
              call("set_flag", flag="photo_shown"), call("reveal_clue", clue_id="regular"),
              say(lexicon_line(language, ["friend"], ["photo"]))),
        reply(call("record_item", item_id="where", result="understood", produced=True),
              say(lexicon_line(language, ["left"]), narration="He is not telling. Not yet.")),
        reply(call("pay", amount=40, for_object_ids=["tab"]), call("set_flag", flag="tab_paid"),
              call("adjust_trust", delta=1, reason="paid her tab"),
              call("move_object", object_id="tab", to_zone="gone"),
              call("reveal_clue", clue_id="waited"), call("reveal_clue", clue_id="stall"),
              say(lexicon_line(language, ["she", "fan_zone"]), mood="pleased")),
    ]
    attempts = [verb(1, "show", "photo"),
                attempt(2, language.items["where"].roman or language.items["where"].text),
                verb(3, "pay", "tab")]
    return play(journey, content, script, attempts, opening=True)


def market_by_dare(journey: Journey, locale: str, content: Content = CONTENT,
                   stall: int = 0) -> tuple[Journey, list[TurnResult]]:
    """Act 2: show the photo, haggle for dumplings, take the spicy dare, get platform 2.
    ``stall`` idle turns first, to burn clock."""
    language = content.language(locale)
    journey = enter_scene(journey, content)
    idle = [reply(say(lexicon_line(language, ["noodles"], ["noodles"])))] * stall
    script = [
        reply(say(lexicon_line(language, ["noodles"], ["noodles"]),
                  lexicon_line(language, ["dumplings"], ["dumplings"]))),
        *idle,
        reply(call("move_object", object_id="photo", to_zone="counter"),
              call("set_flag", flag="photo_shown_lin"), call("reveal_clue", clue_id="scarf"),
              say(lexicon_line(language, ["friend", "scarf"], ["scarf"]))),
        reply(call("record_item", item_id="too_expensive", result="understood", produced=True),
              call("set_price", object_id="dumplings", amount=8),
              say(lexicon_line(language, ["eight", "kuai"]))),
        reply(call("pay", amount=8, for_object_ids=["dumplings"]),
              call("move_object", object_id="dumplings", to_zone="counter"),
              call("move_object", object_id="chili", to_zone="counter"),
              say(lexicon_line(language, ["spicy"], ["chili"]))),
        reply(call("set_flag", flag="dare_taken"), call("adjust_trust", delta=1, reason="the dare"),
              call("move_object", object_id="chili", to_zone="gone"),
              call("move_object", object_id="scarf", to_zone="inventory"),
              call("move_object", object_id="ticket", to_zone="inventory"),
              call("reveal_clue", clue_id="gate"),
              say(lexicon_line(language, ["gate", "number_two", "big_screen"]), mood="pleased")),
    ]
    text = language.items["too_expensive"]
    attempts = [*[attempt(100 + k, "?") for k in range(stall)], verb(11, "show", "photo"),
                attempt(12, text.roman or text.text), attempt(13, "hao"), verb(14, "eat", "chili")]
    return play(journey, content, script, attempts, opening=True)


# ---------------------------------------------------------------- tests


def test_opening() -> None:
    zh = CONTENT.language("zh-CN")
    j0 = enter_scene(new_journey(CONTENT, "off1", language="zh-CN"), CONTENT)
    assert j0.scene is not None
    T.check("a new journey starts with the story's wallet and a full clock",
            j0.game.wallet == 60 and game.minutes_left(j0, CONTENT) == 75
            and j0.game.difficulty == "story")
    T.check("enter_scene prepares authored zones: photo and money in the inventory",
            j0.scene.zones["photo"] == "inventory" and j0.scene.zones["money"] == "inventory"
            and j0.scene.zones["tab"] == "display" and not j0.scene.started)
    client = FakeClient([reply(say(lexicon_line(zh, ["hello"]),
                                   lexicon_line(zh, ["beer", "tea"], ["beer", "tea"]),
                                   narration="Rain on the glass. He looks up.", mood="pleased"))])
    j, result = run_opening(j0, CONTENT, client=client, models=MODELS)
    run = j.scene
    assert run is not None
    T.check("opening is a real model call and does not mutate its input",
            len(client.models.calls) == 1 and not j0.scene.started and j0.vocab == {})
    T.check("TurnResult has the v3 contract's keys", set(result.model_dump()) == {
        "turn", "lines", "narration", "mood", "zones", "events", "progress", "scene_complete",
        "summary", "game", "ending", "latency_ms"})
    T.check("the opening costs no clock", result.game.clock.minutes_left == 75
            and result.game.clock.time == "19:45" and result.game.clock.minutes_total == 75)
    line = result.lines[1]
    T.check("line ids are s{scene}-t{turn}-l{i} with journey audio urls",
            [ln.line_id for ln in result.lines] == ["s0-t0-l0", "s0-t0-l1"]
            and line.audio_url == "/api/journeys/off1/lines/s0-t0-l1/audio")
    T.check("code derives text (no separator) and romanization (spaced)",
            line.text == zh.items["beer"].text + zh.items["tea"].text
            and line.romanization == f"{zh.items['beer'].roman} {zh.items['tea'].roman}")
    T.check("events: narration then npc lines",
            [e.kind for e in result.events] == ["narration", "npc", "npc"]
            and result.narration == "Rain on the glass. He looks up.")
    T.check("exchange ledger: posed, highlighted, line ids, hint",
            run.exchange.posed_item_ids == ["hello", "beer", "tea"]
            and run.exchange.highlighted_item_ids == ["beer", "tea"]
            and run.exchange.intent_hint != "" and run.exchange.phrasebook_item_ids == [])

    sent = client.models.calls[0]
    snapshot, system = sent["contents"][0].parts[0].text, sent["config"].system_instruction
    bar = CONTENT.scene("bar")
    T.check("system prompt carries the GM brief, the place, wants and secrets",
            CONTENT.journey.gm_brief in system and bar.setting in system
            and bar.npc.wants in system and bar.npc.secrets in system
            and zh.items["beer"].text in system and "pijiu" in system)
    T.check("snapshot: difficulty rule first, persona, clock, cash, trust",
            snapshot.startswith("STORY MODE")
            and CONTENT.persona("warm").prompt in snapshot  # type: ignore[union-attr]
            and "75 minutes left" in snapshot and "cash 60" in snapshot
            and "trust: 0" in snapshot and "carrying: photo, money" in snapshot)
    T.check("snapshot: every clue with its status; locked ones say what they need",
            any(ln.strip().startswith("stall |") and "LOCKED, still needs:" in ln
                and "flag photo_shown" in ln for ln in snapshot.splitlines())
            and "events to flag when they happen" in snapshot)
    T.check("snapshot: objects with price, where they can go and the player's verbs",
            any(ln.strip().startswith("tab |") and "| 40 |" in ln and "point, pay" in ln
                for ln in snapshot.splitlines())
            and "other plain words you can lean on" in snapshot)
    for label, bad in (("second opening", j), ("no scene", new_journey(CONTENT, "x",
                                                                       language="zh-CN"))):
        try:
            run_opening(bad, CONTENT, client=FakeClient([]), models=MODELS)
            T.check(f"{label} raises", False)
        except ValueError:
            T.check(f"{label} raises", True)


def test_ending_kickoff() -> None:
    j, bar = bar_by_tab("zh-CN")
    assert j.scene is not None
    photo, pay = bar[1], bar[3]
    T.check("a verb is a turn: the learner entry carries the action",
            photo.events[0].model_dump()["action_id"] == "show"
            and [e.kind for e in photo.events]
            == ["learner", "scene", "scene", "clue", "narration", "npc"])
    T.check("showing the photo: flag, clue in the notebook, first goal done",
            [c.id for c in photo.game.clues] == ["regular"]
            and photo.progress.goals_done == ["ask"] and photo.zones["photo"] == "counter")
    T.check("each player turn costs 3 minutes", [r.game.clock.minutes_left for r in bar]
            == [75, 72, 69, 66] and pay.game.clock.time == "19:54")
    T.check("paying the tab: cash, trust, both clues, act complete, no ending yet",
            pay.game.wallet == 20 and pay.game.trust == 1
            and [c.id for c in pay.game.clues] == ["regular", "waited", "stall"]
            and pay.scene_complete and pay.summary is not None and pay.ending is None
            and pay.summary.next_scene is not None and pay.summary.next_scene.id == "market")
    j, market = market_by_dare(j, "zh-CN")
    assert j.scene is not None
    T.check("walking to the market costs 9 minutes; trust and prices start fresh there",
            market[0].game.clock.minutes_left == 57 and market[0].game.trust == 0
            and market[0].game.prices["dumplings"] == 12 and market[0].game.wallet == 20)
    T.check("haggling shows in the prices; paying uses it",
            market[2].game.prices["dumplings"] == 8 and market[3].game.wallet == 12)
    final = market[-1]
    T.check("the dare opens platform 2: last act complete, the ending resolves on that turn",
            final.scene_complete and final.ending is not None and final.ending.id == "kickoff"
            and final.ending.title == "Kickoff" and j.game.ending_id == "kickoff")
    assert final.ending is not None
    T.check("ending payload: art url and stats",
            final.ending.art_url == "/api/scenes/market/art/art/ending_kickoff.webp"
            and final.ending.stats.model_dump() == {
                "minutes_left": 45, "wallet": 12, "clues": 5,
                "words_mastered": final.ending.stats.words_mastered,
                "words_shaky": final.ending.stats.words_shaky}
            and final.ending.stats.words_mastered >= 1)
    T.check("the scarf travels with the player", final.zones["scarf"] == "inventory")
    T.check("recall across acts is still stamped by code",
            j.vocab["where"].state == "mastered" and j.vocab["where"].first_scene == "bar")
    for label, fn in (("a turn", lambda: run_turn(j, CONTENT, attempt(99, "hi"),
                                                  client=FakeClient([]), models=MODELS)),
                      ("another scene", lambda: enter_scene(j, CONTENT))):
        try:
            fn()
            T.check(f"after the ending, {label} raises", False)
        except ValueError:
            T.check(f"after the ending, {label} raises", True)
    state = views.public_state(j, CONTENT)
    T.check("public state carries the ending, the story and no next scene",
            state.ending is not None and state.ending.id == "kickoff"
            and state.story.title == "Kickoff" and state.summary is not None
            and state.summary.next_scene is None
            and [c.status for c in state.scenes] == ["done", "done"])


def test_ending_late_and_outside() -> None:
    j, _ = bar_by_tab("zh-CN")
    j, market = market_by_dare(j, "zh-CN", stall=14)  # 57 - 14*3 - 4*3 = 3 minutes left
    T.check("the same path with the clock nearly gone ends 'First Goal' (ticket, but late)",
            market[-1].ending is not None and market[-1].ending.id == "late"
            and market[-1].game.clock.minutes_left == 3)

    zh = CONTENT.language("zh-CN")
    j = opened()
    idle = reply(say(lexicon_line(zh, ["beer"])))
    j, results = play(j, CONTENT, [idle] * 25, [attempt(i, "?") for i in range(25)])
    last = results[-1]
    T.check("25 idle turns run the clock out: the act ends and the fallback ending resolves",
            last.scene_complete and last.ending is not None and last.ending.id == "outside"
            and last.game.clock.minutes_left == 0 and last.game.clock.time == "21:00"
            and not results[-2].scene_complete)
    final_snapshot_client = FakeClient([idle])
    k = opened()
    k.game.minutes_used = 72
    run_turn(k, CONTENT, attempt(1, "?"), client=final_snapshot_client, models=MODELS)
    T.check("the GM is told when the clock runs out with this turn",
            "THE CLOCK RUNS OUT WITH THIS TURN" in
            final_snapshot_client.models.calls[0]["contents"][0].parts[0].text)
    T.check("an ordinary turn carries no such notice", "THE CLOCK RUNS OUT" not in
            _snapshot_of(opened(), attempt(1, "?")))


def test_ending_outside() -> None:
    zh = CONTENT.language("zh-CN")
    j, _ = bar_by_tab("zh-CN")
    j = enter_scene(j, CONTENT)
    j.game.minutes_used = 75 - 6  # two turns left
    script = [
        reply(say(lexicon_line(zh, ["noodles"], ["noodles"]))),
        reply(call("set_flag", flag="scarf_noticed"), call("reveal_clue", clue_id="scarf"),
              say(lexicon_line(zh, ["scarf"], ["scarf"]))),
        reply(call("set_flag", flag="ticket_grabbed"),
              call("adjust_trust", delta=-1, reason="grabbed at the ticket"),
              say(lexicon_line(zh, ["no_want"]))),
    ]
    j, results = play(j, CONTENT, script, [verb(21, "point", "scarf"), verb(22, "take", "ticket")],
                      opening=True)
    T.check("clock out with no ticket: the text-only fallback (fail forward, never a dead end)",
            results[-1].ending is not None and results[-1].ending.id == "outside"
            and results[-1].ending.art_url is not None
            and results[-1].ending.art_url.endswith("ending_late.webp")
            and results[-1].game.trust == -1 and results[-1].zones["ticket"] == "display")
    k, _ = bar_by_tab("zh-CN")
    k = enter_scene(k, CONTENT)
    k, _ = play(k, CONTENT, [reply(say(lexicon_line(zh, ["noodles"], ["noodles"])))], [],
                opening=True)
    summary = finish_scene(k, CONTENT)
    T.check("finishing the last act by hand also resolves an ending",
            k.game.ending_id == "outside" and summary.next_scene is None)
    early = opened()
    finish_scene(early, CONTENT)
    T.check("finishing act 1 early does NOT end the story",
            early.game.ending_id is None and early.scene is not None and early.scene.complete)


def _snapshot_of(journey: Journey, att: dict[str, Any]) -> str:
    zh = CONTENT.language(journey.language)
    client = FakeClient([reply(say(lexicon_line(zh, ["beer"])))])
    run_turn(journey, CONTENT, att, client=client, models=MODELS)
    return client.models.calls[0]["contents"][0].parts[0].text


def test_verbs_and_attempts() -> None:
    T.check("a verb reads as a move", "[the player shows you photo]"
            in _snapshot_of(opened(), verb(1, "show", "photo")))
    T.check("paying reads as an offer", "[the player offers to pay: tab]"
            in _snapshot_of(opened(), verb(1, "pay", "tab")))
    T.check("a bare tap is pointing", "[the player points at tea]"
            in _snapshot_of(opened(), attempt(1, mode="tap", tapped="tea")))
    T.check("typed input is quoted", 'the player types "pijiu"'
            in _snapshot_of(opened(), attempt(1, "pijiu")))
    spoken = _snapshot_of(opened(), {"attempt_id": "sp1", "input_mode": "speech",
                                     "transcript": "X", "romanized": "yao shui",
                                     "confidence": 0.41})
    T.check("speech carries its sound, the recognizer's text and LOW CONFIDENCE",
            "it sounded like: yao shui" in spoken and 'wrote it as "X"' in spoken
            and "confidence 0.41 LOW CONFIDENCE" in spoken)
    for label, att in (("a verb the object does not have", verb(2, "eat", "photo")),
                       ("an unknown verb", verb(3, "juggle", "beer")),
                       ("tap on an unknown object", verb(4, "point", "whisky")),
                       ("empty transcript", attempt(5, "  "))):
        try:
            run_turn(opened(), CONTENT, att, client=FakeClient([]), models=MODELS)
            T.check(f"{label}: ValueError before any model call", False)
        except ValueError:
            T.check(f"{label}: ValueError before any model call", True)


def test_unpaid_is_remembered() -> None:
    zh = CONTENT.language("zh-CN")
    j, _ = play(opened(), CONTENT, [reply(call("move_object", object_id="beer", to_zone="counter"),
                                          say(lexicon_line(zh, ["beer", "twenty", "kuai"])))],
                [attempt(1, "pijiu")])
    snapshot = _snapshot_of(j, verb(2, "drink", "beer"))
    T.check("served-but-unpaid is put in front of the GM every turn",
            "SERVED BUT NOT YET PAID FOR: beer (20)" in snapshot)
    j, _ = play(j, CONTENT, [reply(call("pay", amount=20, for_object_ids=["beer"]),
                                   call("move_object", object_id="beer", to_zone="gone"),
                                   say(lexicon_line(zh, ["thanks"])))], [attempt(3, "qian")])
    T.check("...and disappears once it is paid (even after it is drunk)",
            "SERVED BUT NOT YET PAID" not in _snapshot_of(j, attempt(4, "xiexie")))
    T.check("the character is told it knows nothing about the stranger",
            "WHAT THEY DO NOT KNOW" in _system_of(j))


def _system_of(journey: Journey) -> str:
    zh = CONTENT.language(journey.language)
    client = FakeClient([reply(say(lexicon_line(zh, ["beer"])))])
    run_turn(journey, CONTENT, attempt(90, "?"), client=client, models=MODELS)
    return client.models.calls[0]["config"].system_instruction


def test_error_then_retry() -> None:
    zh = CONTENT.language("zh-CN")
    j = opened()
    client = FakeClient([
        reply(call("reveal_clue", clue_id="stall"), say(lexicon_line(zh, ["fan_zone"]))),
        reply(say(lexicon_line(zh, ["left"]))),
    ])
    trace: list[dict[str, Any]] = []
    j2, result = run_turn(j, CONTENT, attempt(1, "ta zai nar"), client=client, models=MODELS,
                          trace=trace)
    T.check("an early leak is refused and costs one more round, not the turn",
            len(client.models.calls) == 2 and "stays secret" in trace[0]["calls"][0]["receipt"]
            and trace[0]["calls"][-1]["receipt"].startswith("ERROR: say rejected")
            and result.game.clues == [] and not result.scene_complete)
    T.check("the refused line never reaches the transcript",
            zh.items["fan_zone"].text not in j2.model_dump_json())
    never = [reply(call("reveal_clue", clue_id="stall"), say(lexicon_line(zh, ["beer"])))] * 6
    try:
        run_turn(j, CONTENT, attempt(2, "x"), client=FakeClient(list(never)), models=MODELS)
        T.check("six failing rounds raise TurnError", False)
    except TurnError:
        T.check("six failing rounds raise TurnError", True)
    client = FakeClient([text_reply("Sure! She went to the market."),
                         reply(say(lexicon_line(zh, ["beer"], ["beer"])))])
    j3, result = run_turn(j, CONTENT, attempt(3, "where is she"), client=client, models=MODELS)
    T.check("a prose-only reply is nudged, never shown",
            len(client.models.calls) == 2 and "Sure!" not in j3.model_dump_json())


def test_failure_keeps_state() -> None:
    zh = CONTENT.language("zh-CN")
    j = opened()
    before = j.model_dump_json()
    for label, script, models in (
        ("every model down", [RuntimeError("503 unavailable"), RuntimeError("503 unavailable")],
         ["m1", "m2"]),
        ("credits exhausted", [RuntimeError("Your credits are depleted")], ["m1", "m2"]),
        ("paid, then prose forever",
         [reply(call("pay", amount=20, for_object_ids=["beer"])),
          text_reply("x"), text_reply("y"), text_reply("z")], MODELS),
    ):
        try:
            run_turn(j, CONTENT, attempt(1, "pijiu"), client=FakeClient(script), models=models)
            T.check(f"{label}: raises TurnError", False)
        except TurnError:
            T.check(f"{label}: raises TurnError", True)
        T.check(f"{label}: journey untouched (cash, clock, attempt)",
                j.model_dump_json() == before and "att1" not in j.attempts)
    client = FakeClient([RuntimeError("429 rate limit"), reply(say(lexicon_line(zh, ["beer"])))])
    j2, _ = run_turn(j, CONTENT, attempt(1, "pijiu"), client=client, models=["m1", "m2"])
    T.check("a transient error cascades to the next model",
            [c["model"] for c in client.models.calls] == ["m1", "m2"])
    try:
        run_turn(j2, CONTENT, attempt(1, "again"), client=FakeClient([]), models=MODELS)
        T.check("a consumed attempt raises", False)
    except ValueError:
        T.check("a consumed attempt raises", True)


def test_difficulty_persona_help() -> None:
    zh = CONTENT.language("zh-CN")
    j = opened()
    vocab.request_help(j, CONTENT)
    set_persona(j, CONTENT, "brisk")
    set_difficulty(j, "immersion")
    client = FakeClient([reply(call("record_item", item_id="hello", result="understood",
                                    produced=True), say(lexicon_line(zh, ["beer"])))])
    j2, result = run_turn(j, CONTENT, attempt(1, "ni hao"), client=client, models=MODELS)
    snapshot = client.models.calls[0]["contents"][0].parts[0].text
    T.check("difficulty switches the narration rule from the next turn",
            snapshot.startswith("IMMERSION MODE") and "STORY MODE" not in snapshot
            and result.game.difficulty == "immersion")
    T.check("persona switch applies from the next reply",
            CONTENT.persona("brisk").prompt in snapshot)  # type: ignore[union-attr]
    T.check("help level 1 stamps with_help; help resets when the character speaks",
            j2.vocab["hello"].results[0].outcome == "with_help"
            and j2.scene is not None and j2.scene.exchange.help_level == 0)
    for bad in ("hard", ""):
        try:
            set_difficulty(j, bad)
            T.check(f"unknown difficulty {bad!r} raises", False)
        except ValueError:
            T.check(f"unknown difficulty {bad!r} raises", True)


def test_fading_is_soft() -> None:
    zh = CONTENT.language("zh-CN")
    j = opened()
    j, _ = play(j, CONTENT, [reply(call("record_item", item_id="beer", result="understood",
                                        produced=True), say(lexicon_line(zh, ["beer"])))],
                [attempt(1, "pijiu")])
    T.check("a with_help word is owed an unsupported pass", vocab.owed_items(
        j, CONTENT.scene("bar")) == ["beer"])
    j.game.flags += ["photo_shown", "tab_paid"]
    client = FakeClient([reply(call("reveal_clue", clue_id="stall"),
                               say(lexicon_line(zh, ["fan_zone"])))])
    j2, result = run_turn(j, CONTENT, attempt(2, "ta zai nar"), client=client, models=MODELS)
    snapshot = client.models.calls[0]["contents"][0].parts[0].text
    T.check("...which is a soft line in the snapshot and NEVER gates the story (no v2 nudge)",
            "Never bend the story for it" in snapshot and len(client.models.calls) == 1
            and result.scene_complete and j2.vocab["beer"].state == "shaky")


def test_highlight_gate_in_loop() -> None:
    zh = CONTENT.language("zh-CN")
    j = opened()
    j.record("beer").state = "mastered"
    client = FakeClient([reply(say(lexicon_line(zh, ["beer"], ["beer"]))),
                         reply(say(lexicon_line(zh, ["beer"])))])
    trace: list[dict[str, Any]] = []
    _, result = run_turn(j, CONTENT, attempt(1, "pijiu"), client=client, models=MODELS,
                         trace=trace)
    T.check("highlighting a mastered word is refused, the retry lands",
            "mastered: present it with no highlight" in trace[0]["calls"][0]["receipt"]
            and len(client.models.calls) == 2 and result.lines[0].highlight_object_ids == [])


def test_persistence_and_restart() -> None:
    spaced = CONTENT.model_copy(deep=True)
    spaced.languages["zh-CN"].word_spacing = True
    zh = spaced.language("zh-CN")
    j = enter_scene(new_journey(spaced, "sp1", language="zh-CN"), spaced)
    j, result = run_opening(j, spaced, models=MODELS, client=FakeClient(
        [reply(say(lexicon_line(zh, ["beer", "tea"])))]))
    T.check("word_spacing joins segments with spaces",
            result.lines[0].text == f"{zh.items['beer'].text} {zh.items['tea'].text}")
    with tempfile.TemporaryDirectory() as tmp:
        done, _ = bar_by_tab("zh-CN")
        save_journey(done, Path(tmp))
        T.check("save/load round-trips the whole journey (game ledgers, clue and verb entries)",
                load_journey(done.journey_id, Path(tmp)) == done
                and not list(Path(tmp).rglob("*.tmp")))
    restart = enter_scene(opened(), CONTENT)
    T.check("re-entering an incomplete act restarts it: no archive, no travel cost",
            restart.scene is not None and not restart.scene.started and restart.history == []
            and game.minutes_left(restart, CONTENT) == 75)
    named = enter_scene(new_journey(CONTENT, "n1", language="zh-CN"), CONTENT, "market")
    T.check("a named act can be entered directly (and costs its travel time)",
            named.scene is not None and named.scene.scene_id == "market"
            and game.minutes_left(named, CONTENT) == 66)


def test_payload_hygiene() -> None:
    zh = CONTENT.language("zh-CN")
    j, results = bar_by_tab("zh-CN")
    mid = results[2]
    secrets = [CONTENT.scene("bar").npc.secrets, CONTENT.scene("bar").npc.wants,
               CONTENT.journey.gm_brief, CONTENT.scene("bar").clue("stall").text]  # type: ignore[union-attr]
    k = opened()
    state = views.public_state(k, CONTENT)
    payloads = {"public_state": state.model_dump_json(), "turn_result": mid.model_dump_json(),
                "help(1)": vocab.request_help(k, CONTENT).model_dump_json()}
    said = [zh.items[key].text for key in ("hello", "beer", "friend", "left")]
    unspoken = [i.text for i in zh.items.values() if not any(i.text in t for t in said)]
    for name, blob in payloads.items():
        T.check(f"{name}: no GM secrets, no gloss key, no unspoken lexicon text",
                not any(s in blob for s in secrets) and '"gloss"' not in blob
                and not any(t in blob for t in unspoken))
    T.check("scene view exposes verbs with labels, never item ids or targets",
            state.scene is not None and '"item_id"' not in state.scene.model_dump_json()
            and [a.model_dump() for a in state.scene.objects[8].actions]
            == [{"id": "show", "label": "Show"}, {"id": "give", "label": "Give"}])
    T.check("game view mirrors the ledgers",
            state.game.model_dump() == {
                "wallet": 60, "clock": {"label": "Kickoff", "time": "19:45",
                                        "minutes_left": 75, "minutes_total": 75},
                "trust": 0, "clues": [], "difficulty": "story",
                "prices": {"beer": 20, "water": 5, "tea": 15, "baijiu": 15, "tab": 40}}
            and state.phrasebook == [] and state.ending is None)
    fresh = views.public_state(new_journey(CONTENT, "f1", language="zh-CN"), CONTENT)
    T.check("a journey with no scene yet has a clean public state",
            fresh.scene is None and fresh.game.wallet == 60 and fresh.game.prices == {}
            and fresh.story.premise == CONTENT.journey.premise
            and [c.status for c in fresh.scenes] == ["next", "locked"])
    T.check("find_line resolves spoken lines only",
            views.find_line(k, "s0-t0-l1") is not None and views.find_line(k, "s0-t9-l0") is None)


if __name__ == "__main__":
    T.run("opening", test_opening)
    T.run("ending: kickoff", test_ending_kickoff)
    T.run("endings: late and clock-out", test_ending_late_and_outside)
    T.run("ending: outside", test_ending_outside)
    T.run("verbs and attempts", test_verbs_and_attempts)
    T.run("unpaid is remembered", test_unpaid_is_remembered)
    T.run("error then retry", test_error_then_retry)
    T.run("failure keeps state", test_failure_keeps_state)
    T.run("difficulty, persona, help", test_difficulty_persona_help)
    T.run("fading is soft", test_fading_is_soft)
    T.run("highlight gate in loop", test_highlight_gate_in_loop)
    T.run("persistence and restart", test_persistence_and_restart)
    T.run("payload hygiene", test_payload_hygiene)
    T.finish()
