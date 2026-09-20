"""The turn loop with a scripted fake Gemini client: opening, a scripted playthrough to every
ending, retries, nudges, failures, help, persistence and payload hygiene."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from core import views, vocab
from core.content import Content, load_content
from core.dm import TurnError, TurnResult, enter_scene, finish_scene, run_opening, run_turn
from core.state import Journey, load_journey, new_journey, save_journey
from scripts.testkit import Checker, FakeClient, call, lexicon_line, reply, say, text_reply

T = Checker("test_dm_offline")
CONTENT = load_content()
SCENE_ID = CONTENT.journey.scenes[0]
BAR = CONTENT.scene(SCENE_ID)
MODELS = ["fake-model"]


def attempt(i: int, text: str = "", mode: str = "text") -> dict:
    return {"attempt_id": f"att{i}", "input_mode": mode, "transcript": text}


def opened(locale: str = "zh-CN", jid: str = "off1", content: Content = CONTENT) -> Journey:
    language = content.language(locale)
    journey = enter_scene(new_journey(content, jid, language=locale), content)
    script = [reply(say(lexicon_line(language, ["hello"]),
                        lexicon_line(language, ["cheers"])))]
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


def found_mei(locale: str, content: Content = CONTENT) -> tuple[Journey, list[TurnResult]]:
    """The whole demo: show the photo, join the chant, earn the gate."""
    language = content.language(locale)
    journey = enter_scene(new_journey(content, f"gold-{locale}", language=locale), content)
    script = [
        reply(say(lexicon_line(language, ["hello"]), lexicon_line(language, ["cheers"]))),
        reply(call("set_flag", flag="photo_shown"), call("reveal_clue", clue_id="regular"),
              say(lexicon_line(language, ["friend"]))),
        reply(call("record_item", item_id="where", result="understood", produced=True),
              say(lexicon_line(language, ["left"]), narration="He is not telling. Not yet.")),
        reply(call("record_item", item_id="go_team", result="understood", produced=True),
              call("set_flag", flag="chanted"),
              call("adjust_trust", delta=1, reason="sang the chant"),
              call("reveal_clue", clue_id="waited"), call("reveal_clue", clue_id="gate"),
              say(lexicon_line(language, ["she", "fan_zone"]))),
    ]
    where, go_team = language.items["where"], language.items["go_team"]
    attempts = [
        attempt(1, language.items["hello"].roman or language.items["hello"].text),
        attempt(2, where.roman or where.text),
        attempt(3, go_team.roman or go_team.text),
    ]
    return play(journey, content, script, attempts, opening=True)


def _snapshot_of(journey: Journey, att: dict[str, Any]) -> str:
    language = CONTENT.language(journey.language)
    client = FakeClient([reply(say(lexicon_line(language, ["cheers"])))])
    run_turn(journey, CONTENT, att, client=client, models=MODELS)
    return client.models.calls[0]["contents"][0].parts[0].text


def _system_of(journey: Journey) -> str:
    language = CONTENT.language(journey.language)
    client = FakeClient([reply(say(lexicon_line(language, ["cheers"])))])
    run_turn(journey, CONTENT, attempt(90, "hao"), client=client, models=MODELS)
    return client.models.calls[0]["config"].system_instruction


# ---------------------------------------------------------------- tests


def test_opening() -> None:
    zh = CONTENT.language("zh-CN")
    j0 = enter_scene(new_journey(CONTENT, "off1", language="zh-CN"), CONTENT)
    assert j0.scene is not None
    T.check("a new journey starts with empty ledgers and no resources to spend",
            j0.game.model_dump() == {"trust": {}, "clues": [], "flags": [],
                                     "ending_id": None}, j0.game.model_dump())
    T.check("enter_scene prepares an unstarted run", not j0.scene.started
            and j0.scene.scene_id == SCENE_ID and j0.scene.goals_done == [])
    client = FakeClient([reply(say(lexicon_line(zh, ["hello"]),
                                   lexicon_line(zh, ["cheers", "goal"]),
                                   narration="The whole room is already shouting."))])
    j, result = run_opening(j0, CONTENT, client=client, models=MODELS)
    run = j.scene
    assert run is not None
    T.check("opening is a real model call and does not mutate its input",
            len(client.models.calls) == 1 and not j0.scene.started and j0.vocab == {})
    T.check("TurnResult has the streamlined contract's keys", set(result.model_dump()) == {
        "turn", "lines", "narration", "events", "progress", "scene_complete",
        "summary", "game", "ending", "latency_ms", "dictionary", "heard", "frame"},
        sorted(result.model_dump()))
    T.check("the engine promises no picture: the server owns the art", result.frame is None)
    line = result.lines[1]
    # The audio url is fingerprinted with the words it speaks, because line ids restart at
    # s0-t0-l0 and a browser must not replay a cached clip under a new subtitle.
    T.check("line ids are s{scene}-t{turn}-l{i} with journey audio urls",
            [ln.line_id for ln in result.lines] == ["s0-t0-l0", "s0-t0-l1"]
            and line.audio_url.startswith("/api/journeys/off1/lines/s0-t0-l1/audio?v=")
            and line.audio_url != result.lines[0].audio_url, line.audio_url)
    T.check("code derives text (no separator) and romanization (spaced)",
            line.text == zh.items["cheers"].text + zh.items["goal"].text
            and line.romanization == f"{zh.items['cheers'].roman} {zh.items['goal'].roman}")
    T.check("a line carries no highlight ids any more",
            "highlight" not in result.model_dump_json())
    T.check("events: narration then npc lines",
            [e.kind for e in result.events] == ["narration", "npc", "npc"]
            and result.narration == "The whole room is already shouting.")
    # posed follows the scene's vocabulary order (scene.item_ids), not the order the
    # character happened to say them: the second line says cheers+goal, and 'goal' is the
    # earlier target, so it is posed first.
    posed_in_scene_order = [i for i in BAR.item_ids if i in {"hello", "cheers", "goal"}]
    T.check("exchange ledger: posed, line ids, hint",
            run.exchange.posed_item_ids == posed_in_scene_order == ["hello", "goal", "cheers"]
            and run.exchange.intent_hint != "")

    sent = client.models.calls[0]
    snapshot, system = sent["contents"][0].parts[0].text, sent["config"].system_instruction
    T.check("system prompt carries the GM brief, the place, wants and secrets",
            CONTENT.journey.gm_brief in system and BAR.setting in system
            and BAR.npc.wants in system and BAR.npc.secrets in system
            and zh.items["hello"].text in system and "nihao" in system)
    T.check("system prompt names the character's role and never a bartender's job",
            BAR.npc.role in system and "counter to an adult" not in system)
    T.check("snapshot: the one narration rule first, then trust",
            snapshot.startswith("NARRATION RULE") and "trust: 0 (range -2..3)" in snapshot)
    T.check("snapshot: every clue with its status; locked ones say what they need",
            any(ln.strip().startswith("gate |") and "LOCKED, still needs:" in ln
                and "flag photo_shown" in ln for ln in snapshot.splitlines())
            and "events to flag when they happen" in snapshot)
    T.check("snapshot: this act's words and the plain words to lean on",
            "WORDS OF THIS ACT" in snapshot and "other plain words you can lean on" in snapshot)
    for gone in ("cash", "wallet", "minutes left", "MODE", "mood", "objects ("):
        T.check(f"snapshot no longer carries {gone!r}", gone not in snapshot)
    for label, bad in (("second opening", j), ("no scene", new_journey(CONTENT, "x",
                                                                      language="zh-CN"))):
        try:
            run_opening(bad, CONTENT, client=FakeClient([]), models=MODELS)
            T.check(f"{label} raises", False)
        except ValueError:
            T.check(f"{label} raises", True)


def test_ending_found() -> None:
    j, results = found_mei("zh-CN")
    assert j.scene is not None
    photo, final = results[1], results[-1]
    T.check("a player turn logs the learner entry, then what the character committed",
            [e.kind for e in photo.events] == ["learner", "scene", "clue", "narration", "npc"],
            [e.kind for e in photo.events])
    T.check("the learner entry carries no tap fields",
            "tapped_object_id" not in photo.events[0].model_dump())
    T.check("showing the photo: flag, clue in the notebook, first goal done",
            [c.id for c in photo.game.clues] == ["regular"]
            and photo.progress.goals_done == ["ask"])
    T.check("the last clue completes the act and resolves the ending on that turn",
            final.scene_complete and final.ending is not None and final.ending.id == "found"
            and j.game.ending_id == "found" and final.summary is not None
            and final.summary.next_scene is None)
    assert final.ending is not None
    T.check("ending payload: art url and stats with no clock or cash",
            final.ending.art_url is not None
            and final.ending.art_url.startswith(f"/api/scenes/{SCENE_ID}/art/")
            and set(final.ending.stats.model_dump())
            == {"clues", "words_mastered", "words_shaky"}
            and final.ending.stats.clues == 3
            and final.ending.stats.words_mastered >= 1, final.ending.stats.model_dump())
    T.check("trust moved and is reported", final.game.trust == 1)
    T.check("outcomes are stamped by code",
            j.vocab["where"].state == "mastered" and j.vocab["go_team"].state == "mastered")
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
            state.ending is not None and state.ending.id == "found"
            and state.story.title == CONTENT.journey.title and state.summary is not None
            and state.summary.next_scene is None
            and [c.status for c in state.scenes] == ["done"])


def test_ending_outside() -> None:
    zh = CONTENT.language("zh-CN")
    j = opened()
    j, results = play(j, CONTENT, [reply(say(lexicon_line(zh, ["cheers"])))],
                      [attempt(1, "ganbei")])
    T.check("an ordinary turn ends nothing", not results[-1].scene_complete
            and results[-1].ending is None)
    summary = finish_scene(j, CONTENT)
    T.check("giving up resolves the fallback ending (no clue, no gate)",
            j.game.ending_id == "outside" and summary.next_scene is None
            and j.scene is not None and j.scene.complete)
    ending = views.ending_view(j, CONTENT)
    T.check("the fallback ending still has its text and stats",
            ending is not None and ending.id == "outside" and ending.text
            and ending.stats.clues == 0)


def test_attempts() -> None:
    T.check("typed input is quoted", 'the player types "nihao"'
            in _snapshot_of(opened(), attempt(1, "nihao")))
    spoken = _snapshot_of(opened(), {"attempt_id": "sp1", "input_mode": "speech",
                                     "transcript": "X", "romanized": "jia you",
                                     "confidence": 0.41})
    T.check("speech carries its sound, the recognizer's text and LOW CONFIDENCE",
            "it sounded like: jia you" in spoken and 'wrote it as "X"' in spoken
            and "confidence 0.41 LOW CONFIDENCE" in spoken)
    for label, att in (("empty transcript", attempt(5, "  ")),
                       ("a tap attempt is no longer an input mode",
                        {"attempt_id": "t1", "input_mode": "tap", "transcript": "x"})):
        try:
            run_turn(opened(), CONTENT, att, client=FakeClient([]), models=MODELS)
            T.check(f"{label}: rejected before any model call", False)
        except (ValueError, Exception) as exc:  # pydantic rejects the mode, dm rejects the text
            T.check(f"{label}: rejected before any model call", "attempt" in str(exc).lower()
                    or "input_mode" in str(exc) or isinstance(exc, ValueError), exc)
    T.check("the character is told it knows nothing about the stranger",
            "WHAT THEY DO NOT KNOW" in _system_of(opened()))


def test_error_then_retry() -> None:
    zh = CONTENT.language("zh-CN")
    j = opened()
    client = FakeClient([
        reply(call("reveal_clue", clue_id="gate"), say(lexicon_line(zh, ["fan_zone"]))),
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
    never = [reply(call("reveal_clue", clue_id="gate"), say(lexicon_line(zh, ["cheers"])))] * 6
    try:
        run_turn(j, CONTENT, attempt(2, "hao"), client=FakeClient(list(never)), models=MODELS)
        T.check("six failing rounds raise TurnError", False)
    except TurnError:
        T.check("six failing rounds raise TurnError", True)
    client = FakeClient([text_reply("Sure! She went to the fan zone."),
                         reply(say(lexicon_line(zh, ["cheers"])))])
    j3, result = run_turn(j, CONTENT, attempt(3, "ta zai nar"), client=client, models=MODELS)
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
        ("flagged, then prose forever",
         [reply(call("set_flag", flag="photo_shown")),
          text_reply("x"), text_reply("y"), text_reply("z")], MODELS),
    ):
        try:
            run_turn(j, CONTENT, attempt(1, "nihao"), client=FakeClient(script), models=models)
            T.check(f"{label}: raises TurnError", False)
        except TurnError:
            T.check(f"{label}: raises TurnError", True)
        T.check(f"{label}: journey untouched (ledgers, attempts)",
                j.model_dump_json() == before and "att1" not in j.attempts)
    client = FakeClient([RuntimeError("429 rate limit"), reply(say(lexicon_line(zh, ["cheers"])))])
    j2, _ = run_turn(j, CONTENT, attempt(1, "nihao"), client=client, models=["m1", "m2"])
    T.check("a transient error cascades to the next model",
            [c["model"] for c in client.models.calls] == ["m1", "m2"])
    try:
        run_turn(j2, CONTENT, attempt(1, "again"), client=FakeClient([]), models=MODELS)
        T.check("a consumed attempt raises", False)
    except ValueError:
        T.check("a consumed attempt raises", True)


def test_help() -> None:
    zh = CONTENT.language("zh-CN")
    j = opened()
    given = vocab.request_help(j)
    T.check("help level 1 replays the last lines and offers no object highlights",
            given.level == 1 and given.kind == "again" and given.line_ids
            and "highlight" not in given.model_dump_json())
    client = FakeClient([reply(call("record_item", item_id="hello", result="understood",
                                    produced=True), say(lexicon_line(zh, ["cheers"])))])
    j2, _ = run_turn(j, CONTENT, attempt(1, "ni hao"), client=client, models=MODELS)
    T.check("help level 1 stamps with_help; help resets when the character speaks",
            j2.vocab["hello"].results[0].outcome == "with_help"
            and j2.scene is not None and j2.scene.exchange.help_level == 0)


def test_persistence_and_restart() -> None:
    spaced = CONTENT.model_copy(deep=True)
    spaced.languages["zh-CN"].word_spacing = True
    zh = spaced.language("zh-CN")
    j = enter_scene(new_journey(spaced, "sp1", language="zh-CN"), spaced)
    j, result = run_opening(j, spaced, models=MODELS, client=FakeClient(
        [reply(say(lexicon_line(zh, ["cheers", "goal"])))]))
    T.check("word_spacing joins segments with spaces",
            result.lines[0].text == f"{zh.items['cheers'].text} {zh.items['goal'].text}")
    with tempfile.TemporaryDirectory() as tmp:
        done, _ = found_mei("zh-CN")
        save_journey(done, Path(tmp))
        T.check("save/load round-trips the whole journey (ledgers, clue entries)",
                load_journey(done.journey_id, Path(tmp)) == done
                and not list(Path(tmp).rglob("*.tmp")))
    restart = enter_scene(opened(), CONTENT)
    T.check("re-entering an incomplete act restarts it and archives nothing",
            restart.scene is not None and not restart.scene.started and restart.history == [])
    named = enter_scene(new_journey(CONTENT, "n1", language="zh-CN"), CONTENT, SCENE_ID)
    T.check("the act can be entered by name",
            named.scene is not None and named.scene.scene_id == SCENE_ID)
    try:
        enter_scene(new_journey(CONTENT, "n2", language="zh-CN"), CONTENT, "market")
        T.check("an unknown act raises", False)
    except ValueError:
        T.check("an unknown act raises", True)


def test_heard_meanings() -> None:
    """The word bank is tappable, so a word in it without a meaning is useless.

    He speaks like a person: most of what he says is not on the scene's 25-word list, and the
    list's own gloss describes the listed FORM, not the one he inflected.
    """
    es = CONTENT.language("es-ES")
    journey = enter_scene(new_journey(CONTENT, "heard1", language="es-ES"), CONTENT)
    off_list = {"segments": [{"t": "¿", "r": "", "g": ""},
                             {"t": "Qué", "r": "", "g": "what"},
                             {"t": "miras", "r": "", "g": "you look at"},
                             {"t": "el", "r": "", "g": "the"},
                             {"t": "móvil", "r": "", "g": "the phone"},
                             {"t": "?", "r": "", "g": ""}],
                "item_ids": []}
    inflected = {"segments": [{"t": "amigo", "r": "", "g": "friend (male)"}], "item_ids": []}
    listed = lexicon_line(es, ["friend"])  # "amiga", exactly as the lexicon writes it
    journey, _ = play(journey, CONTENT,
                      [reply(say(off_list, inflected, listed))], [], opening=True)
    heard = {w.text: w.gloss for w in views.public_state(journey, CONTENT).heard}
    T.check("a word off the scene's list still reaches the player with its meaning",
            heard.get("móvil") == "the phone" and heard.get("el") == "the", heard)
    T.check("the small words are glossed too, not just the nouns",
            all(heard.get(w) for w in ("Qué", "miras")), heard)
    T.check("punctuation is never a word in the bank",
            "¿" not in heard and "?" not in heard, heard)
    T.check("an inflected form takes HIS meaning, not the listed form's",
            heard.get("amigo") == "friend (male)", heard)
    T.check("the listed form itself still teaches the lexicon's gloss",
            heard.get(es.items["friend"].text) == es.items["friend"].gloss, heard)
    T.check("no heard word is ever blank",
            all(g for g in heard.values()), heard)


def test_payload_hygiene() -> None:
    zh = CONTENT.language("zh-CN")
    j, results = found_mei("zh-CN")
    mid = results[2]
    secrets = [BAR.npc.secrets, BAR.npc.wants, CONTENT.journey.gm_brief,
               BAR.clue("gate").text]  # type: ignore[union-attr]
    k = opened()
    state = views.public_state(k, CONTENT)
    payloads = {"public_state": state, "turn_result": mid, "help(1)": vocab.request_help(k)}
    said = [zh.items[key].text for key in ("hello", "cheers", "friend", "left")]
    unspoken = [i.text for i in zh.items.values() if not any(i.text in t for t in said)]
    for name, payload in payloads.items():
        T.check(f"{name}: no GM secrets", not any(s in payload.model_dump_json()
                                                  for s in secrets), name)
        # Word meanings during play live in exactly two fields, and both are one WORD at a
        # time: `dictionary` (the scene's vocabulary, for looking up) and `heard` (the words
        # he has actually said). Everywhere else the lexicon still reaches the player only
        # through lines the character has spoken.
        rest = payload.model_dump_json(exclude={"dictionary", "heard"})
        T.check(f"{name}: no gloss key, no unspoken lexicon text outside the dictionary",
                '"gloss"' not in rest and not any(t in rest for t in unspoken), name)
    T.check("every heard word is one word he really said, and every one has a meaning",
            all(w.text and " " not in w.text.strip() for w in state.heard)
            and all(w.gloss for w in state.heard),
            [(w.text, w.gloss) for w in state.heard])
    T.check("every dictionary entry is one word of this scene, glossed on its own",
            [w.item_id for w in state.dictionary] and all(
                w.item_id in BAR.item_ids and w.text == zh.items[w.item_id].text
                and w.gloss == zh.items[w.item_id].gloss for w in state.dictionary),
            [w.item_id for w in state.dictionary])
    assert state.scene is not None
    T.check("scene view is the room and the goals, never items or objects",
            set(state.scene.model_dump()) == {
                "id", "name", "tagline", "intro", "background_url", "cover_url", "npc", "goals",
                "target_count"}, sorted(state.scene.model_dump()))
    T.check("game view mirrors the surviving ledgers only",
            state.game.model_dump() == {"trust": 0, "clues": []}
            and state.ending is None)
    T.check("public state carries no persona, zones or mood",
            set(views.public_state(k, CONTENT).model_dump())
            == {"journey_id", "language", "scene", "started", "turn", "transcript", "progress",
                "scene_complete", "summary", "scenes", "story", "game", "ending", "dictionary",
                "heard", "frame"},
            sorted(views.public_state(k, CONTENT).model_dump()))
    fresh = views.public_state(new_journey(CONTENT, "f1", language="zh-CN"), CONTENT)
    T.check("a journey with no scene yet has a clean public state",
            fresh.scene is None and fresh.story.premise == CONTENT.journey.premise
            and [c.status for c in fresh.scenes] == ["next"])
    T.check("find_line resolves spoken lines only",
            views.find_line(k, "s0-t0-l1") is not None and views.find_line(k, "s0-t9-l0") is None)
    T.check("the journey itself keeps no removed ledger",
            not any(key in j.model_dump_json()
                    for key in ("wallet", "minutes_used", "difficulty", "persona_id", "prices",
                                "paid_for", "unsupported_offers")))


if __name__ == "__main__":
    T.run("opening", test_opening)
    T.run("ending: found", test_ending_found)
    T.run("ending: outside", test_ending_outside)
    T.run("attempts", test_attempts)
    T.run("error then retry", test_error_then_retry)
    T.run("failure keeps state", test_failure_keeps_state)
    T.run("help", test_help)
    T.run("persistence and restart", test_persistence_and_restart)
    T.run("heard meanings", test_heard_meanings)
    T.run("payload hygiene", test_payload_hygiene)
    T.finish()
