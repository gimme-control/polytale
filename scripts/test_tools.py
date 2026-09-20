"""Tool executors: id validation, deterministic mutation, ERROR receipts. Trust, clue gating,
flags, self-completing goals, `say` validation."""

from __future__ import annotations

from typing import Any

from core import game
from core.content import load_content
from core.dm import enter_scene
from core.state import Attempt, ClueEntry, Exchange, Journey, new_journey
from core.frames import EXPRESSIONS
from core.tools import (
    MAX_WORD_SEGMENTS,
    ToolContext,
    declaration_schemas,
    execute,
    is_clean_word,
    is_error,
    is_word,
    tool_declarations,
)
from scripts.testkit import Checker, lexicon_line

T = Checker("test_tools")
CONTENT = load_content()
SCENE_ID = CONTENT.journey.scenes[0]
BAR = CONTENT.scene(SCENE_ID)
ZH = CONTENT.language("zh-CN")


def setup(mode: str | None = "text", said: str = "ni hao",
          romanized: str | None = None) -> tuple[Journey, ToolContext]:
    journey = enter_scene(new_journey(CONTENT, "tools1", language="zh-CN"), CONTENT, SCENE_ID)
    assert journey.scene is not None
    journey.scene.started = True
    attempt = None
    if mode is not None:
        attempt = Attempt(attempt_id="att1", input_mode=mode, transcript=said,  # type: ignore[arg-type]
                          romanized=romanized)
    return journey, ToolContext(scene=BAR, language=ZH, attempt=attempt)


def say_args(*lines: dict, **extra: Any) -> dict[str, Any]:
    return {"lines": list(lines), "narration": "The room roars at the screen.",
            "intent_hint": "Wants you to join in with the chant", **extra}


def test_now_line() -> None:
    j, ctx = setup()
    receipt = execute("adjust_trust", j, {"delta": 1, "reason": "joined in"}, ctx)
    now = receipt.splitlines()[-1]
    T.check("the NOW line carries goals, trust, clues and flags only",
            now.startswith("NOW goals: ") and "ask=open" in now and "trail=open" in now
            and "trust: 1" in now and "clues: -" in now and "flags: -" in now, now)
    for gone in ("zones", "wallet", "mood", "price"):
        T.check(f"the NOW line no longer mentions {gone}", gone not in now, now)


def test_trust() -> None:
    j, ctx = setup()
    T.check("trust starts at the character's authored value", game.trust(j, BAR) == BAR.npc.trust)
    receipt = execute("adjust_trust", j, {"delta": 1, "reason": "said thanks"}, ctx)
    T.check("trust moves by one", not is_error(receipt) and game.trust(j, BAR) == 1)
    again = execute("adjust_trust", j, {"delta": 1, "reason": "again"}, ctx)
    T.check("only once per turn (OK no-op, no wasted round)",
            not is_error(again) and "already moved" in again and game.trust(j, BAR) == 1)
    for label, args in (("delta 2", {"delta": 2, "reason": "x"}),
                        ("delta 0", {"delta": 0, "reason": "x"}),
                        ("no reason", {"delta": 1, "reason": " "}),
                        ("not a number", {"delta": "up", "reason": "x"})):
        k, kctx = setup()
        T.check(f"ERROR: {label}", is_error(execute("adjust_trust", k, args, kctx))
                and game.trust(k, BAR) == 0)
    k, _ = setup()
    for value, delta, expected in ((3, 1, 3), (-2, -1, -2), (2, 1, 3), (-1, -1, -2)):
        k.game.trust[SCENE_ID] = value
        kctx = ToolContext(scene=BAR, language=ZH, attempt=Attempt(
            attempt_id="c", input_mode="text", transcript="x"))
        execute("adjust_trust", k, {"delta": delta, "reason": "clamp"}, kctx)
        T.check(f"trust clamps to -2..3 ({value} {delta:+d} -> {expected})",
                game.trust(k, BAR) == expected)
    k, kctx = setup(mode=None)
    T.check("ERROR: trust cannot move in the opening",
            is_error(execute("adjust_trust", k, {"delta": 1, "reason": "x"}, kctx)))
    m, mctx = setup()
    m.game.flags.append("photo_shown")
    receipt = execute("adjust_trust", m, {"delta": 1, "reason": "toasted"}, mctx)
    T.check("the receipt says which clues just became revealable",
            "You may now reveal:" in receipt and "waited" in receipt, receipt)


def test_clue_gating() -> None:
    j, ctx = setup()
    run = j.scene
    assert run is not None
    locked = execute("reveal_clue", j, {"clue_id": "gate"}, ctx)
    T.check("a locked clue is refused: the GM cannot leak it early",
            is_error(locked) and "stays secret" in locked and j.game.clues == []
            and "flag photo_shown" in locked and "trust 2+ (now 0)" in locked, locked)
    T.check("ERROR: unknown clue", is_error(execute("reveal_clue", j, {"clue_id": "nope"}, ctx)))
    j.game.flags.append("photo_shown")
    T.check("the photo alone opens 'regular' but not 'gate'",
            not is_error(execute("reveal_clue", j, {"clue_id": "regular"}, ctx))
            and is_error(execute("reveal_clue", j, {"clue_id": "gate"}, ctx)))
    entry = next(e for e in run.transcript if isinstance(e, ClueEntry))
    T.check("a revealed clue lands in the transcript with its notebook text",
            entry.clue.id == "regular"
            and entry.clue.text == BAR.clue("regular").text)  # type: ignore[union-attr]
    n = len(run.transcript)
    T.check("revealing twice is an OK no-op",
            "already known" in execute("reveal_clue", j, {"clue_id": "regular"}, ctx)
            and j.game.clues == ["regular"] and len(run.transcript) == n)

    j.game.trust[SCENE_ID] = 1
    T.check("trust 1 with only the photo is still not enough for the last clue",
            is_error(execute("reveal_clue", j, {"clue_id": "gate"}, ctx)))
    j.game.flags.append("chanted")
    receipt = execute("reveal_clue", j, {"clue_id": "gate"}, ctx)
    T.check("...joining the chant at trust 1 opens it; the goal completes itself",
            not is_error(receipt) and "Goal done: trail" in receipt
            and "ALL GOALS DONE" in receipt and run.goals_done == ["ask", "trail"], receipt)

    k, kctx = setup()
    k.game.flags.append("photo_shown")
    k.game.trust[SCENE_ID] = 2
    T.check("trust alone (with the photo) is another way in",
            not is_error(execute("reveal_clue", k, {"clue_id": "gate"}, kctx)))
    T.check("every clue of this act offers at least one authored way in",
            all(c.reveal_when for c in BAR.clues))


def test_flags_and_goals() -> None:
    j, ctx = setup()
    run = j.scene
    assert run is not None
    T.check("ERROR: a flag nobody authored", is_error(execute("set_flag", j, {"flag": "won"}, ctx)))
    receipt = execute("set_flag", j, {"flag": "photo_shown"}, ctx)
    T.check("a flag can complete a goal by itself (no complete_goal tool)",
            "Goal done: ask" in receipt and run.goals_done == ["ask"]
            and run.transcript[-1].model_dump()["event"] == "goal_done"
            and "complete_goal" not in [d["name"] for d in declaration_schemas(BAR, ZH)])
    T.check("...and the receipt lists what it unlocked",
            "You may now reveal: regular" in receipt, receipt)
    n = len(run.transcript)
    T.check("setting a flag twice is an OK no-op",
            "already set" in execute("set_flag", j, {"flag": "photo_shown"}, ctx)
            and len(run.transcript) == n)
    j.game.trust[SCENE_ID] = 2
    execute("reveal_clue", j, {"clue_id": "gate"}, ctx)
    T.check("the last goal ends the act", run.goals_done == ["ask", "trail"])


def test_giveaway_words() -> None:
    j, ctx = setup()
    leak = say_args(lexicon_line(ZH, ["she", "fan_zone"]))
    receipt = execute("say", j, leak, ctx)
    T.check("a locked clue's giveaway word cannot be spoken: the line is refused",
            is_error(receipt) and "still LOCKED" in receipt and ctx.terminal is None, receipt)
    j.game.flags += ["photo_shown"]
    j.game.trust[SCENE_ID] = 2
    receipt = execute("say", j, leak, ctx)
    T.check("when the clue CAN come out, saying it without reveal_clue is refused too",
            is_error(receipt) and "call reveal_clue(gate)" in receipt, receipt)
    execute("reveal_clue", j, {"clue_id": "gate"}, ctx)
    T.check("once revealed, the word is free",
            not is_error(execute("say", j, leak, ctx)) and ctx.terminal is not None)
    k, kctx = setup()
    T.check("ordinary words are never blocked",
            not is_error(execute("say", k, say_args(lexicon_line(ZH, ["hello", "mate"])), kctx)))


def test_record_item() -> None:
    j, ctx = setup(said="ni hao")
    assert j.scene is not None
    j.scene.exchange = Exchange(posed_item_ids=["hello"])
    receipt = execute("record_item", j, {"item_id": "hello", "result": "understood",
                                         "produced": True}, ctx)
    T.check("outcome comes from the ledger, not the model (no help -> first_try)",
            "hello: first_try -> mastered" in receipt, receipt)
    dup = execute("record_item", j, {"item_id": "hello", "result": "missed", "produced": False},
                  ctx)
    T.check("duplicate (attempt, item) is a no-op",
            "already recorded" in dup and len(j.vocab["hello"].results) == 1)
    for label, args in (
        ("a support word is not a target", {"item_id": "scarf", "result": "understood",
                                            "produced": True}),
        ("an item nobody authored", {"item_id": "whisky", "result": "understood",
                                     "produced": False}),
        ("bad result", {"item_id": "thanks", "result": "clarified", "produced": False}),
    ):
        T.check(f"ERROR: {label}", is_error(execute("record_item", j, args, ctx)))
    for label, kwargs, item, counted in (
        ("typed romanization without marks", {"said": "JiaYou!"}, "go_team", True),
        ("typed in its own script, inside a sentence",
         {"said": ZH.items["team"].text + ZH.items["go_team"].text}, "go_team", True),
        ("spaced romanization of a phrase", {"said": "zai nar?"}, "where", True),
        ("speech: the recognizer's romanization counts even when the characters are off",
         {"mode": "speech", "said": "加油啦", "romanized": "jiā yóu"}, "go_team", True),
        ("a support-language word that merely MEANS it", {"said": "hello??"}, "hello", False),
        ("a different word entirely", {"said": "xiexie"}, "go_team", False),
    ):
        k, kctx = setup(**kwargs)  # type: ignore[arg-type]
        execute("record_item", k, {"item_id": item, "result": "understood", "produced": True},
                kctx)
        T.check(f"produced is checked against the player's own input: {label}",
                (item in k.vocab) == counted, k.vocab.get(item))
    k, kctx = setup(said="unbelievable")
    assert k.scene is not None
    k.scene.exchange = Exchange(posed_item_ids=["hello"])
    receipt = execute("record_item", k, {"item_id": "hello", "result": "understood",
                                         "produced": False}, kctx)
    T.check("input with no word of the language shows nothing, even for a word just posed",
            "nothing recorded" in receipt and "hello" not in k.vocab, receipt)
    k, kctx = setup(said="dui")
    assert k.scene is not None
    k.scene.exchange = Exchange(posed_item_ids=["cheers"])
    execute("record_item", k, {"item_id": "cheers", "result": "understood", "produced": False},
            kctx)
    T.check("...while answering in the language about a posed word does count",
            k.vocab["cheers"].results[0].outcome == "first_try"
            and not k.vocab["cheers"].results[0].produced)
    k, kctx = setup(said="dui")
    receipt = execute("record_item", k, {"item_id": "goal", "result": "understood",
                                         "produced": False}, kctx)
    T.check("understanding without saying it needs the word to have been in the last lines",
            not is_error(receipt) and "nothing recorded" in receipt and "goal" not in k.vocab)
    j, ctx = setup(mode=None)
    T.check("ERROR: no player attempt (the opening)", is_error(
        execute("record_item", j, {"item_id": "hello", "result": "understood", "produced": False},
                ctx)))


def test_say() -> None:
    j, ctx = setup()
    good = lexicon_line(ZH, ["cheers"])
    receipt = execute("say", j, say_args(good), ctx)
    T.check("valid say is terminal", not is_error(receipt) and ctx.terminal is not None, receipt)
    assert ctx.terminal is not None
    T.check("terminal carries narration, validated lines, the hint and the face (no highlights)",
            ctx.terminal["lines"][0]["segments"][0].t == ZH.items["cheers"].text
            and ctx.terminal["lines"][0]["item_ids"] == ["cheers"]
            and ctx.terminal["narration"] == "The room roars at the screen."
            and ctx.terminal["expression"] == "neutral"
            and set(ctx.terminal) == {"lines", "narration", "intent_hint", "expression"},
            sorted(ctx.terminal))

    punct = {"segments": [{"t": ZH.items["cheers"].text, "r": ZH.items["cheers"].roman,
                           "g": "cheers"},
                          {"t": "！", "r": "ignored", "g": "ignored"}],
             "item_ids": ["cheers"]}
    j, ctx = setup()
    execute("say", j, say_args(punct), ctx)
    assert ctx.terminal is not None
    T.check("punctuation segments carry no romanization and no meaning",
            ctx.terminal["lines"][0]["segments"][1].r == ""
            and ctx.terminal["lines"][0]["segments"][1].g == "")
    j, ctx = setup()
    execute("say", j, say_args({"segments": [{"t": ZH.items["cheers"].text, "r": "GAN-BEI",
                                              "g": "cheers"},
                                             {"t": ZH.items["team"].text, "r": "x",
                                              "g": "the team"}],
                                "item_ids": []}), ctx)
    assert ctx.terminal is not None
    said = ctx.terminal["lines"][0]
    T.check("lexicon words (support words too) take the lexicon's romanization and are tagged",
            [s.r for s in said["segments"]] == [ZH.items["cheers"].roman, ZH.items["team"].roman]
            and said["item_ids"] == ["cheers", "team"])
    T.check("a word he made up keeps the meaning he gave it",
            [s.g for s in said["segments"]] == ["cheers", "the team"])
    word = {"t": ZH.items["thanks"].text, "r": ZH.items["thanks"].roman, "g": "thanks"}
    j, ctx = setup()
    execute("say", j, say_args({"segments": [word], "item_ids": ["cheers", "thanks"]}), ctx)
    T.check("a tag without its word is dropped by the ledger, not bounced back at the GM",
            ctx.terminal is not None and ctx.terminal["lines"][0]["item_ids"] == ["thanks"])
    frame = ZH.items["where"].model_copy(update={"text": "…" + ZH.items["where"].text + "..."})
    T.check("a placeholder in an item's text splits it into spoken parts",
            frame.parts == [ZH.items["where"].text])
    T.check("in-word joiners are part of the word; marks are not words",
            is_clean_word("l'eau") and is_clean_word("rendez-vous") and not is_clean_word("agua?")
            and is_word("20") and not is_word("？"))

    bad_cases: list[tuple[str, dict[str, Any]]] = [
        ("no lines", say_args()),
        ("four lines", say_args(good, good, good, good)),
        ("lines not a list", {**say_args(), "lines": "hello"}),
        ("empty segments", say_args({**good, "segments": []})),
        ("word segment without romanization",
         say_args({"segments": [{"t": "慢", "r": "", "g": "slow"}], "item_ids": []})),
        ("word segment with no meaning at all",
         say_args({"segments": [{"t": "慢", "r": "màn", "g": " "}], "item_ids": []})),
        ("a gloss long enough to be the line's meaning",
         say_args({"segments": [{"t": "慢", "r": "màn",
                                 "g": "what are you looking at on the phone"}],
                   "item_ids": []})),
        ("word glued to punctuation",
         say_args({**good, "segments": [{"t": ZH.items["cheers"].text + "！", "r": "x",
                                         "g": "cheers"}]})),
        ("romanization written into t",
         say_args({**good, "segments": [{"t": ZH.items["cheers"].text + "le", "r": "x",
                                         "g": "cheers"}]})),
        ("a foreign word echoed in t",
         say_args({**good, "segments": [{"t": "AI", "r": "ei ai", "g": "a machine"}]})),
        ("punctuation-only line", say_args({**good, "segments": [{"t": "？", "r": "", "g": ""}]})),
        ("too many word segments",
         say_args({**good, "segments": good["segments"] + [word] * MAX_WORD_SEGMENTS})),
        ("unknown item id", say_args({**good, "item_ids": ["whisky"]})),
        ("missing narration", {**say_args(good), "narration": " "}),
        ("narration far too long", say_args(good, narration="word " * 61)),
        ("missing intent_hint", {**say_args(good), "intent_hint": " "}),
        ("intent_hint too long", {**say_args(good), "intent_hint": "word " * 17}),
    ]
    for label, args in bad_cases:
        j, ctx = setup()
        T.check(f"ERROR: {label}", is_error(execute("say", j, args, ctx)) and ctx.terminal is None)
    j, ctx = setup()
    T.check("a 45-word narration (the told limit) and a little slack are accepted", not is_error(
        execute("say", j, say_args(good, narration="word " * 55), ctx)))
    j, ctx = setup()
    ctx.round_errors = ["set_flag: ERROR: unknown flag 'won'"]
    T.check("say is refused when another call in the response errored",
            is_error(execute("say", j, say_args(good), ctx)) and ctx.terminal is None)
    j, ctx = setup()
    T.check("an unknown tool is an ERROR (incl. every removed tool)",
            all(is_error(execute(name, j, args, ctx)) for name, args in (
                ("pour", {}),
                ("complete_goal", {"goal_id": "ask"}),
                ("move_object", {"object_id": "beer", "to_zone": "counter"}),
                ("pay", {"amount": 5, "for_object_ids": []}),
                ("set_price", {"object_id": "beer", "amount": 5}))))


def test_declarations() -> None:
    decls = {d["name"]: d for d in declaration_schemas(BAR, ZH)}
    T.check("the game's tools, say last",
            list(decls) == ["adjust_trust", "record_item", "reveal_clue", "set_flag",
                            "show_beat", "say"],
            list(decls))
    T.check("ids are enums from the scene",
            decls["reveal_clue"]["parameters"]["properties"]["clue_id"]["enum"]
            == [c.id for c in BAR.clues]
            and decls["set_flag"]["parameters"]["properties"]["flag"]["enum"]
            == [f.id for f in BAR.flags]
            and decls["record_item"]["parameters"]["properties"]["item_id"]["enum"]
            == BAR.targets)
    say = decls["say"]["parameters"]
    T.check("say shape: narration, lines, hint, expression (no mood, no stage_direction)",
            set(say["required"]) == {"narration", "lines", "intent_hint", "expression"}
            and "mood" not in say["properties"] and "stage_direction" not in say["properties"]
            and say["properties"]["expression"]["enum"] == list(EXPRESSIONS)
            and say["properties"]["lines"]["maxItems"] == 3)
    line_props = say["properties"]["lines"]["items"]["properties"]
    T.check("a line is segments + item_ids only",
            set(line_props) == {"segments", "item_ids"}, sorted(line_props))
    blob = str(decls)
    T.check("declarations leak no lexicon text and no secrets", not any(
        item.text in blob for item in ZH.items.values()) and "gate 2" not in blob.lower())
    T.check("gemini tool objects build",
            len(tool_declarations(BAR, ZH)[0].function_declarations) == 6)
    plain = ZH.model_copy(update={"romanization": None})
    j, _ = setup()
    ctx = ToolContext(scene=BAR, language=plain)
    execute("say", j, say_args({"segments": [{"t": ZH.items["cheers"].text, "r": "junk",
                                              "g": "cheers"}],
                                "item_ids": ["cheers"]}), ctx)
    T.check("a language with no romanization never stores r, but still carries the meaning",
            ctx.terminal is not None and ctx.terminal["lines"][0]["segments"][0].r == ""
            and ctx.terminal["lines"][0]["segments"][0].g == "cheers")


if __name__ == "__main__":
    T.run("now line", test_now_line)
    T.run("trust", test_trust)
    T.run("clue gating", test_clue_gating)
    T.run("flags and goals", test_flags_and_goals)
    T.run("giveaway words", test_giveaway_words)
    T.run("record_item", test_record_item)
    T.run("say", test_say)
    T.run("declarations", test_declarations)
    T.finish()
