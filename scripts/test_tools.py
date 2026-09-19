"""Tool executors: id validation, deterministic mutation, ERROR receipts. Money, haggling,
trust, clue gating, flags, self-completing goals, `say` validation and the highlight gate."""

from __future__ import annotations

from typing import Any

from core import game, vocab
from core.content import load_content
from core.dm import enter_scene
from core.state import Attempt, ClueEntry, Exchange, Journey, SceneEventEntry, new_journey
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
BAR, MARKET = CONTENT.scene("bar"), CONTENT.scene("market")
ZH = CONTENT.language("zh-CN")


def setup(scene_id: str = "bar", mode: str | None = "text", tapped: str | None = None,
          said: str = "pijiu", romanized: str | None = None) -> tuple[Journey, ToolContext]:
    journey = enter_scene(new_journey(CONTENT, "tools1", language="zh-CN"), CONTENT, scene_id)
    assert journey.scene is not None
    journey.scene.started = True
    attempt = None
    if mode is not None:
        attempt = Attempt(attempt_id="att1", input_mode=mode, transcript=said,  # type: ignore[arg-type]
                          romanized=romanized, tapped_object_id=tapped)
    return journey, ToolContext(scene=CONTENT.scene(scene_id), language=ZH, attempt=attempt,
                                mastered=vocab.mastered_items(journey))


def say_args(*lines: dict, **extra: Any) -> dict[str, Any]:
    return {"lines": list(lines), "narration": "He sets it down and waits.",
            "intent_hint": "Wants to know which drink you want", "mood": "neutral", **extra}


def test_move_object() -> None:
    j, ctx = setup()
    run = j.scene
    assert run is not None
    receipt = execute("move_object", j, {"object_id": "beer", "to_zone": "counter"}, ctx)
    T.check("serve moves display -> counter", not is_error(receipt)
            and run.zones["beer"] == "counter")
    T.check("receipt ends with a NOW line (zones, goals, wallet, trust, clues, flags, mood)",
            receipt.splitlines()[-1].startswith("NOW zones: beer=counter")
            and "goals: ask=open, trail=open" in receipt and "wallet: 60" in receipt
            and "trust: 0" in receipt and "clues: -" in receipt and "mood: neutral" in receipt)
    event = run.transcript[-1]
    T.check("an object_moved event is logged with from/to",
            isinstance(event, SceneEventEntry) and event.model_dump() == {
                "kind": "scene", "turn": 0, "event": "object_moved", "object_id": "beer",
                "from": "display", "to": "counter", "goal_id": None}, event.model_dump())
    n = len(run.transcript)
    again = execute("move_object", j, {"object_id": "beer", "to_zone": "counter"}, ctx)
    T.check("same-zone move is an OK no-op with no event",
            not is_error(again) and "no change" in again and len(run.transcript) == n)
    for label, args in (
        ("unknown object", {"object_id": "whisky", "to_zone": "counter"}),
        ("unknown zone", {"object_id": "beer", "to_zone": "fridge"}),
        ("the v2 zone name 'wallet' is gone", {"object_id": "photo", "to_zone": "wallet"}),
        ("zone with no position for that object", {"object_id": "beer", "to_zone": "npc"}),
        ("missing args", {}),
    ):
        before = dict(run.zones)
        T.check(f"ERROR: {label}; state unchanged",
                is_error(execute("move_object", j, args, ctx)) and run.zones == before)
    T.check("inventory and gone need no position; the photo can be handed over and back",
            not is_error(execute("move_object", j, {"object_id": "beer", "to_zone": "gone"}, ctx))
            and not is_error(execute("move_object", j, {"object_id": "photo", "to_zone": "npc"}, ctx))
            and not is_error(execute("move_object", j, {"object_id": "photo",
                                                        "to_zone": "inventory"}, ctx)))


def test_pay() -> None:
    j, ctx = setup()
    assert j.scene is not None
    receipt = execute("pay", j, {"amount": 20, "for_object_ids": ["beer"]}, ctx)
    T.check("paying moves cash: wallet, spent (journey and scene), paid_for",
            not is_error(receipt) and j.game.wallet == 40 and j.game.spent == 20
            and j.scene.spent == 20 and j.game.paid_for == {"bar": ["beer"]}, receipt)
    T.check("two things in one payment",
            not is_error(execute("pay", j, {"amount": 20.0, "for_object_ids": ["tea", "water"]},
                                 ctx)) and j.game.wallet == 20)
    for label, args in (
        ("amount differs from the prices", {"amount": 25, "for_object_ids": ["tab"]}),
        ("the old tab price", {"amount": 30, "for_object_ids": ["tab"]}),
        ("more than the wallet holds", {"amount": 40, "for_object_ids": ["tab"]}),
        ("something with no price", {"amount": 5, "for_object_ids": ["menu"]}),
        ("unknown object", {"amount": 5, "for_object_ids": ["whisky"]}),
        ("nothing named and not a tip", {"amount": 5, "for_object_ids": []}),
        ("zero", {"amount": 0, "for_object_ids": ["water"]}),
        ("negative", {"amount": -5, "for_object_ids": [], "tip": True}),
        ("not a number", {"amount": "lots", "for_object_ids": ["water"]}),
        ("a tip the wallet cannot cover", {"amount": 21, "for_object_ids": [], "tip": True}),
    ):
        before = j.game.model_dump()
        T.check(f"ERROR: {label}; nothing paid",
                is_error(execute("pay", j, args, ctx)) and j.game.model_dump() == before)
    T.check("the refusal tells the GM what the player has",
            "only has 20" in execute("pay", j, {"amount": 40, "for_object_ids": ["tab"]}, ctx))
    T.check("a tip needs no object; spending the last coin is fine",
            not is_error(execute("pay", j, {"amount": 20, "for_object_ids": [], "tip": True}, ctx))
            and j.game.wallet == 0)
    j, ctx = setup(mode=None)
    T.check("ERROR: nobody pays in the opening",
            is_error(execute("pay", j, {"amount": 5, "for_object_ids": ["water"]}, ctx)))


def test_haggling() -> None:
    j, ctx = setup("market")
    T.check("asking price before any haggling", game.price_of(j, MARKET, "dumplings") == 12)
    for label, amount in (("below the floor", 7), ("above the asking price", 13),
                          ("not a number", None)):
        T.check(f"ERROR: {label}",
                is_error(execute("set_price", j, {"object_id": "dumplings", "amount": amount}, ctx))
                and game.price_of(j, MARKET, "dumplings") == 12)
    T.check("the refusal names the floor so the GM can hold the line",
            "no lower than 8" in execute("set_price", j, {"object_id": "dumplings", "amount": 1},
                                         ctx))
    T.check("the floor itself is allowed",
            not is_error(execute("set_price", j, {"object_id": "dumplings", "amount": 8}, ctx))
            and game.price_of(j, MARKET, "dumplings") == 8)
    T.check("paying uses the haggled price",
            is_error(execute("pay", j, {"amount": 12, "for_object_ids": ["dumplings"]}, ctx))
            and not is_error(execute("pay", j, {"amount": 8, "for_object_ids": ["dumplings"]},
                                     ctx)) and j.game.wallet == 52)
    T.check("ERROR: a fixed price (no floor) cannot be haggled",
            is_error(execute("set_price", j, {"object_id": "water", "amount": 2}, ctx)))
    T.check("ERROR: something with no price",
            is_error(execute("set_price", j, {"object_id": "scarf", "amount": 2}, ctx)))
    bar, bar_ctx = setup("bar")
    T.check("haggled prices are per scene",
            game.price_of(bar, BAR, "beer") == 20 and game.price_of(j, MARKET, "beer") == 10)
    T.check("the bar has nothing to haggle, so it has no set_price tool",
            "set_price" not in [d["name"] for d in declaration_schemas(BAR, ZH)]
            and "set_price" in [d["name"] for d in declaration_schemas(MARKET, ZH)])


def test_trust() -> None:
    j, ctx = setup()
    T.check("trust starts at the character's authored value", game.trust(j, BAR) == 0)
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
        k.game.trust["bar"] = value
        kctx = ToolContext(scene=BAR, language=ZH, attempt=Attempt(
            attempt_id="c", input_mode="text", transcript="x"))
        execute("adjust_trust", k, {"delta": delta, "reason": "clamp"}, kctx)
        T.check(f"trust clamps to -2..3 ({value} {delta:+d} -> {expected})",
                game.trust(k, BAR) == expected)
    k, kctx = setup(mode=None)
    T.check("ERROR: trust cannot move in the opening",
            is_error(execute("adjust_trust", k, {"delta": 1, "reason": "x"}, kctx)))
    T.check("trust is per character", game.trust(j, MARKET) == 0 and game.trust(j, BAR) == 1)
    j.game.flags.append("photo_shown")
    k2ctx = ToolContext(scene=BAR, language=ZH, attempt=ctx.attempt)
    receipt = execute("adjust_trust", j, {"delta": 1, "reason": "toasted"}, k2ctx)
    T.check("the receipt says which clues just became revealable",
            "You may now reveal:" in receipt and "stall" in receipt, receipt)


def test_clue_gating() -> None:
    j, ctx = setup()
    run = j.scene
    assert run is not None
    locked = execute("reveal_clue", j, {"clue_id": "stall"}, ctx)
    T.check("a locked clue is refused: the GM cannot leak it early",
            is_error(locked) and "stays secret" in locked and j.game.clues == []
            and "flag photo_shown" in locked and "trust 2+ (now 0)" in locked, locked)
    T.check("ERROR: unknown clue", is_error(execute("reveal_clue", j, {"clue_id": "nope"}, ctx)))
    j.game.flags.append("photo_shown")
    T.check("the photo alone opens 'regular' but not 'market'",
            not is_error(execute("reveal_clue", j, {"clue_id": "regular"}, ctx))
            and is_error(execute("reveal_clue", j, {"clue_id": "stall"}, ctx)))
    entry = next(e for e in run.transcript if isinstance(e, ClueEntry))
    T.check("a revealed clue lands in the transcript with its notebook text",
            entry.clue.id == "regular" and entry.clue.title == "He knows her"
            and entry.clue.text == BAR.clue("regular").text)  # type: ignore[union-attr]
    n = len(run.transcript)
    T.check("revealing twice is an OK no-op",
            "already known" in execute("reveal_clue", j, {"clue_id": "regular"}, ctx)
            and j.game.clues == ["regular"] and len(run.transcript) == n)

    j.game.trust["bar"] = 1
    T.check("way 3 needs BOTH the baijiu and trust 1",
            is_error(execute("reveal_clue", j, {"clue_id": "stall"}, ctx)))
    j.game.flags.append("drank_baijiu")
    receipt = execute("reveal_clue", j, {"clue_id": "stall"}, ctx)
    T.check("...and opens once both hold; the goal completes itself",
            not is_error(receipt) and "Goal done: trail" in receipt
            and "ALL GOALS DONE" in receipt and run.goals_done == ["ask", "trail"], receipt)

    k, kctx = setup()
    k.game.flags += ["photo_shown"]
    k.game.trust["bar"] = 2
    T.check("way 2: trust alone (with the photo) opens it",
            not is_error(execute("reveal_clue", k, {"clue_id": "stall"}, kctx)))
    m, mctx = setup("market")
    assert m.scene is not None
    m.game.flags.append("photo_shown_lin")
    m.game.trust["market"] = 1
    T.check("paid_at_least counts cash spent in THIS scene",
            is_error(execute("reveal_clue", m, {"clue_id": "gate"}, mctx)))
    m.game.spent = 50  # spent elsewhere does not count
    T.check("...money spent in another act does not count",
            is_error(execute("reveal_clue", m, {"clue_id": "gate"}, mctx)))
    execute("pay", m, {"amount": 12, "for_object_ids": ["dumplings"]}, mctx)
    T.check("...a paying customer with trust 1 gets it",
            not is_error(execute("reveal_clue", m, {"clue_id": "gate"}, mctx)))


def test_flags_and_goals() -> None:
    j, ctx = setup()
    run = j.scene
    assert run is not None
    T.check("ERROR: a flag nobody authored", is_error(execute("set_flag", j, {"flag": "won"}, ctx)))
    T.check("ERROR: another act's flag",
            is_error(execute("set_flag", j, {"flag": "dare_taken"}, ctx)))
    unpaid = execute("set_flag", j, {"flag": "tab_paid"}, ctx)
    T.check("ERROR: tab_paid needs the tab actually paid for",
            is_error(unpaid) and "tab" in unpaid and j.game.flags == [])
    execute("pay", j, {"amount": 40, "for_object_ids": ["tab"]}, ctx)
    paid = execute("set_flag", j, {"flag": "tab_paid"}, ctx)
    T.check("...and is accepted after pay; the receipt lists what it unlocked",
            not is_error(paid) and j.game.flags == ["tab_paid"]
            and "You may now reveal: waited" in paid, paid)
    receipt = execute("set_flag", j, {"flag": "photo_shown"}, ctx)
    T.check("a flag can complete a goal by itself (no complete_goal tool)",
            "Goal done: ask" in receipt and run.goals_done == ["ask"]
            and run.transcript[-1].model_dump()["event"] == "goal_done"
            and "complete_goal" not in [d["name"] for d in declaration_schemas(BAR, ZH)])
    n = len(run.transcript)
    T.check("setting a flag twice is an OK no-op",
            "already set" in execute("set_flag", j, {"flag": "photo_shown"}, ctx)
            and len(run.transcript) == n)
    execute("reveal_clue", j, {"clue_id": "stall"}, ctx)
    T.check("the last goal says the act ends", run.goals_done == ["ask", "trail"])


def test_giveaway_words() -> None:
    j, ctx = setup()
    leak = say_args(lexicon_line(ZH, ["she", "fan_zone"]))
    receipt = execute("say", j, leak, ctx)
    T.check("a locked clue's giveaway word cannot be spoken: the line is refused",
            is_error(receipt) and "still LOCKED" in receipt and ctx.terminal is None, receipt)
    j.game.flags += ["photo_shown", "tab_paid"]
    receipt = execute("say", j, leak, ctx)
    T.check("when the clue CAN come out, saying it without reveal_clue is refused too",
            is_error(receipt) and "call reveal_clue(stall)" in receipt, receipt)
    execute("reveal_clue", j, {"clue_id": "stall"}, ctx)
    T.check("once revealed, the word is free",
            not is_error(execute("say", j, leak, ctx)) and ctx.terminal is not None)
    m, mctx = setup("market")
    T.check("the market's secret has several giveaway words",
            all(is_error(execute("say", m, say_args(lexicon_line(ZH, [w])), mctx))
                for w in ("gate", "number_two", "big_screen")))
    T.check("...but she may talk about the ticket itself before she gives it up",
            not is_error(execute("say", m, say_args(lexicon_line(ZH, ["ticket"], ["ticket"])),
                                 mctx)))
    T.check("a bought flag is a flag (requires_paid)",
            is_error(execute("set_flag", m, {"flag": "flag_bought"}, mctx)))
    T.check("ordinary words are never blocked",
            not is_error(execute("say", m, say_args(lexicon_line(ZH, ["noodles", "spicy"])), mctx)))
    T.check("ERROR: the dare needs food that was paid for (chili on nothing does not count)",
            is_error(execute("set_flag", m, {"flag": "dare_taken"}, mctx)))
    execute("pay", m, {"amount": 15, "for_object_ids": ["noodles"]}, mctx)
    T.check("...ANY one of the listed foods will do",
            not is_error(execute("set_flag", m, {"flag": "dare_taken"}, mctx)))


def test_record_item() -> None:
    j, ctx = setup()
    assert j.scene is not None
    j.scene.exchange = Exchange(posed_item_ids=["beer"], highlighted_item_ids=["beer"])
    receipt = execute("record_item", j, {"item_id": "beer", "result": "understood",
                                         "produced": True}, ctx)
    T.check("outcome comes from the ledger, not the model (highlighted -> with_help)",
            "beer: with_help -> shaky" in receipt, receipt)
    dup = execute("record_item", j, {"item_id": "beer", "result": "missed", "produced": False},
                  ctx)
    T.check("duplicate (attempt, item) is a no-op",
            "already recorded" in dup and len(j.vocab["beer"].results) == 1)
    for label, args in (
        ("non-target item", {"item_id": "noodles", "result": "understood", "produced": False}),
        ("a support word is not a target", {"item_id": "water", "result": "understood",
                                            "produced": True}),
        ("bad result", {"item_id": "tea", "result": "clarified", "produced": False}),
    ):
        T.check(f"ERROR: {label}", is_error(execute("record_item", j, args, ctx)))
    for label, kwargs, item, counted in (
        ("typed romanization without marks", {"said": "PiJiu!"}, "beer", True),
        ("typed in its own script, inside a sentence",
         {"said": ZH.items["want"].text + ZH.items["beer"].text}, "beer", True),
        ("spaced romanization of a phrase", {"said": "ta zai nar?"}, "where", True),
        ("speech: the recognizer's romanization counts even when the characters are off",
         {"mode": "speech", "said": "\u76ae\u7403", "romanized": "pí jiǔ"}, "beer", True),
        ("a support-language word that merely MEANS it", {"said": "hello??"}, "hello", False),
        ("a different word entirely", {"said": "cha"}, "beer", False),
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
    k, kctx = setup(said="hao")
    assert k.scene is not None
    k.scene.exchange = Exchange(posed_item_ids=["beer"])
    execute("record_item", k, {"item_id": "beer", "result": "understood", "produced": False}, kctx)
    T.check("...while answering in the language about a posed word does count",
            k.vocab["beer"].results[0].outcome == "first_try"
            and not k.vocab["beer"].results[0].produced)
    k, kctx = setup(said="hao")
    receipt = execute("record_item", k, {"item_id": "football", "result": "understood",
                                         "produced": False}, kctx)
    T.check("understanding without saying it needs the word to have been in the last lines",
            not is_error(receipt) and "nothing recorded" in receipt and "football" not in k.vocab)
    j, ctx = setup(said="pengyou zai nar")
    assert j.scene is not None
    j.scene.exchange = Exchange(phrasebook_item_ids=["where"])
    execute("record_item", j, {"item_id": "where", "result": "understood", "produced": True}, ctx)
    execute("record_item", j, {"item_id": "friend", "result": "understood", "produced": True}, ctx)
    T.check("a word the player just looked up is stamped with_help; others are not",
            j.vocab["where"].results[0].outcome == "with_help"
            and j.vocab["friend"].results[0].outcome == "first_try")
    j, ctx = setup(mode=None)
    T.check("ERROR: no player attempt (the opening)", is_error(
        execute("record_item", j, {"item_id": "beer", "result": "understood", "produced": False},
                ctx)))
    j, ctx = setup(mode="tap", tapped="beer")
    assert j.scene is not None
    j.scene.exchange = Exchange(posed_item_ids=["tea"])
    receipt = execute("record_item", j, {"item_id": "beer", "result": "understood",
                                         "produced": True}, ctx)
    T.check("a tap on a word that was not in the last lines records nothing (OK, not ERROR)",
            not is_error(receipt) and "nothing recorded" in receipt and "beer" not in j.vocab)
    j.scene.exchange = Exchange(posed_item_ids=["beer"])
    execute("record_item", j, {"item_id": "beer", "result": "understood", "produced": True}, ctx)
    T.check("a tap on a posed word records understanding, never production",
            j.vocab["beer"].results[0].outcome == "first_try"
            and not j.vocab["beer"].results[0].produced)


def test_say() -> None:
    j, ctx = setup()
    good = lexicon_line(ZH, ["beer"], ["beer"])
    receipt = execute("say", j, say_args(good), ctx)
    T.check("valid say is terminal", not is_error(receipt) and ctx.terminal is not None, receipt)
    assert ctx.terminal is not None
    T.check("terminal carries narration, validated lines, hint and mood",
            ctx.terminal["lines"][0]["segments"][0].t == ZH.items["beer"].text
            and ctx.terminal["lines"][0]["item_ids"] == ["beer"]
            and ctx.terminal["lines"][0]["highlight_object_ids"] == ["beer"]
            and ctx.terminal["narration"] == "He sets it down and waits."
            and ctx.terminal["mood"] == "neutral" and "stage_direction" not in ctx.terminal)

    punct = {"segments": [{"t": ZH.items["beer"].text, "r": ZH.items["beer"].roman},
                          {"t": "？", "r": "ignored"}],
             "item_ids": ["beer"], "highlight_object_ids": []}
    j, ctx = setup()
    execute("say", j, say_args(punct), ctx)
    assert ctx.terminal is not None
    T.check("punctuation segments carry no romanization",
            ctx.terminal["lines"][0]["segments"][1].r == "")
    j, ctx = setup()
    execute("say", j, say_args({"segments": [{"t": ZH.items["beer"].text, "r": "PI-JIU"},
                                             {"t": ZH.items["forty"].text, "r": "x"}],
                                "item_ids": [], "highlight_object_ids": ["beer"]}), ctx)
    assert ctx.terminal is not None
    said = ctx.terminal["lines"][0]
    T.check("lexicon words (support words too) take the lexicon's romanization and are tagged",
            [s.r for s in said["segments"]] == [ZH.items["beer"].roman, ZH.items["forty"].roman]
            and said["item_ids"] == ["beer", "forty"])
    word = {"t": ZH.items["tea"].text, "r": ZH.items["tea"].roman}
    j, ctx = setup()
    execute("say", j, say_args({"segments": [word], "item_ids": ["beer", "tea"],
                                "highlight_object_ids": []}), ctx)
    T.check("a tag without its word is dropped by the ledger, not bounced back at the GM",
            ctx.terminal is not None and ctx.terminal["lines"][0]["item_ids"] == ["tea"])
    frame = ZH.items["want"].model_copy(update={"text": "…" + ZH.items["want"].text + "..."})
    T.check("a placeholder in an item's text splits it into spoken parts",
            frame.parts == [ZH.items["want"].text])
    T.check("in-word joiners are part of the word; marks are not words",
            is_clean_word("l'eau") and is_clean_word("rendez-vous") and not is_clean_word("agua?")
            and is_word("20") and not is_word("？"))

    bad_cases: list[tuple[str, dict[str, Any]]] = [
        ("no lines", say_args()),
        ("four lines", say_args(good, good, good, good)),
        ("lines not a list", {**say_args(), "lines": "hello"}),
        ("empty segments", say_args({**good, "segments": []})),
        ("word segment without romanization",
         say_args({"segments": [{"t": "慢", "r": ""}], "item_ids": [],
                   "highlight_object_ids": []})),
        ("word glued to punctuation",
         say_args({**good, "segments": [{"t": ZH.items["beer"].text + "？", "r": "x"}]})),
        ("romanization written into t",
         say_args({**good, "segments": [{"t": ZH.items["beer"].text + "le", "r": "x"}]})),
        ("a foreign word echoed in t", say_args({**good, "segments": [{"t": "AI", "r": "ei ai"}]})),
        ("highlight on a line that does not say the object's word",
         say_args({"segments": [word], "item_ids": ["tea"], "highlight_object_ids": ["beer"]})),
        ("punctuation-only line", say_args({**good, "segments": [{"t": "？", "r": ""}]})),
        ("too many word segments",
         say_args({**good, "segments": good["segments"] + [word] * MAX_WORD_SEGMENTS})),
        ("unknown item id", say_args({**good, "item_ids": ["whisky"]})),
        ("item from another act", say_args({**good, "item_ids": ["noodles"]})),
        ("unknown highlight object", say_args({**good, "highlight_object_ids": ["chili"]})),
        ("missing narration", {**say_args(good), "narration": " "}),
        ("narration far too long", say_args(good, narration="word " * 61)),
        ("missing intent_hint", {**say_args(good), "intent_hint": " "}),
        ("intent_hint too long", {**say_args(good), "intent_hint": "word " * 17}),
        ("unknown mood", say_args(good, mood="furious")),
    ]
    for label, args in bad_cases:
        j, ctx = setup()
        T.check(f"ERROR: {label}", is_error(execute("say", j, args, ctx)) and ctx.terminal is None)
    j, ctx = setup()
    T.check("a 45-word narration (the told limit) and a little slack are accepted", not is_error(
        execute("say", j, say_args(good, narration="word " * 55), ctx)))
    j, ctx = setup()
    ctx.round_errors = ["move_object: ERROR: unknown object_id 'whisky'"]
    T.check("say is refused when another call in the response errored",
            is_error(execute("say", j, say_args(good), ctx)) and ctx.terminal is None)
    j, ctx = setup()
    T.check("unknown tool is an ERROR (incl. the removed complete_goal)",
            is_error(execute("pour", j, {}, ctx))
            and is_error(execute("complete_goal", j, {"goal_id": "ask"}, ctx)))


def test_highlight_gate() -> None:
    j, _ = setup()
    j.record("beer").state = "mastered"
    ctx = ToolContext(scene=BAR, language=ZH, mastered=vocab.mastered_items(j))
    receipt = execute("say", j, say_args(lexicon_line(ZH, ["beer"], ["beer"])), ctx)
    T.check("highlighting a mastered item's object is refused",
            is_error(receipt) and "mastered: present it with no highlight" in receipt)
    T.check("the same line without the highlight passes", not is_error(
        execute("say", j, say_args(lexicon_line(ZH, ["beer"])), ctx)))
    j, ctx = setup()
    assert j.scene is not None
    execute("record_item", j, {"item_id": "beer", "result": "understood", "produced": True}, ctx)
    T.check("gate judges the turn-start record, not a result from this same response",
            j.vocab["beer"].state == "mastered" and not is_error(
                execute("say", j, say_args(lexicon_line(ZH, ["beer"], ["beer"])), ctx)))
    T.check("the character cannot point at what is still in the player's pocket",
            is_error(execute("say", j, say_args(lexicon_line(ZH, ["friend"], ["photo"])), ctx))
            and not is_error(execute("say", j, say_args(lexicon_line(ZH, ["money"], ["money"])),
                                     ctx)))
    execute("move_object", j, {"object_id": "photo", "to_zone": "counter"}, ctx)
    execute("move_object", j, {"object_id": "photo", "to_zone": "inventory"}, ctx)
    ctx.terminal = None
    T.check("...once it has been shown or handed over, it can be lit even back in the pocket",
            not is_error(execute("say", j, say_args(lexicon_line(ZH, ["friend"], ["photo"])), ctx)))
    j.scene.zones["tea"] = "gone"
    ctx.terminal = None
    T.check("an object that is gone cannot be highlighted", is_error(
        execute("say", j, say_args(lexicon_line(ZH, ["tea"], ["tea"])), ctx)))


def test_declarations() -> None:
    decls = {d["name"]: d for d in declaration_schemas(MARKET, ZH)}
    T.check("the game's tools, say last",
            list(decls) == ["move_object", "pay", "adjust_trust", "record_item", "set_price",
                            "reveal_clue", "set_flag", "say"])
    T.check("ids are enums from the scene",
            decls["move_object"]["parameters"]["properties"]["to_zone"]["enum"] == MARKET.zones
            and decls["reveal_clue"]["parameters"]["properties"]["clue_id"]["enum"]
            == ["scarf", "gate"]
            and decls["set_flag"]["parameters"]["properties"]["flag"]["enum"]
            == [f.id for f in MARKET.flags]
            and decls["set_price"]["parameters"]["properties"]["object_id"]["enum"]
            == ["noodles", "dumplings", "beer", "flag"]
            and "scarf" not in decls["pay"]["parameters"]["properties"]["for_object_ids"]["items"][
                "enum"])
    say = decls["say"]["parameters"]
    T.check("say shape: narration, lines, hint, mood (no stage_direction)",
            set(say["required"]) == {"narration", "lines", "intent_hint", "mood"}
            and "stage_direction" not in say["properties"]
            and say["properties"]["lines"]["maxItems"] == 3)
    blob = str(decls)
    T.check("declarations leak no lexicon text and no secrets", not any(
        item.text in blob for item in ZH.items.values()) and "platform 2" not in blob.lower())
    T.check("gemini tool objects build",
            len(tool_declarations(MARKET, ZH)[0].function_declarations) == 8)
    plain = ZH.model_copy(update={"romanization": None})
    j, _ = setup()
    ctx = ToolContext(scene=BAR, language=plain)
    execute("say", j, say_args({"segments": [{"t": ZH.items["beer"].text, "r": "junk"}],
                                "item_ids": ["beer"], "highlight_object_ids": []}), ctx)
    T.check("a language with no romanization never stores r",
            ctx.terminal is not None and ctx.terminal["lines"][0]["segments"][0].r == "")


if __name__ == "__main__":
    T.run("move_object", test_move_object)
    T.run("pay", test_pay)
    T.run("haggling", test_haggling)
    T.run("trust", test_trust)
    T.run("clue gating", test_clue_gating)
    T.run("flags and goals", test_flags_and_goals)
    T.run("giveaway words", test_giveaway_words)
    T.run("record_item", test_record_item)
    T.run("say", test_say)
    T.run("highlight gate", test_highlight_gate)
    T.run("declarations", test_declarations)
    T.finish()
