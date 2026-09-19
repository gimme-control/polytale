"""LIVE game-master tests against real Gemini (needs GEMINI_API_KEY in polytale/.env).

  a. a zero-beginner who leans on the phrasebook and verbs reaches a good ending in time
  b. a rude, English-only player still reaches an ending (fail forward), with low trust
  c. haggling works and respects the floor
  h. football agency: grabbing his match ball costs goodwill, cheering with him earns it
  d. clue gating: asked directly, the GM cannot say where Mei went before it is earned
  e. difficulty: story narration carries the gist, immersion does not (printed; shape asserted)
  f. the v2 adversarial learner still holds
  g. phrasebook accuracy and latency on 12 typical asks
Asserts on state and shape only; prints every transcript with per-turn latency.

    PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/test_dm_live.py [--only a,b,...] [--runs N]
"""

from __future__ import annotations

import argparse
import re
import statistics
import time
import unicodedata
import uuid
from typing import Any

from dotenv import load_dotenv

from scripts.testkit import ROOT, Checker

load_dotenv(ROOT / ".env")

from core import game, phrasebook  # noqa: E402
from core.content import Content, load_content  # noqa: E402
from core.dm import TurnResult, enter_scene, run_opening, run_turn  # noqa: E402
from core.state import Journey, SceneRun, new_journey, set_difficulty  # noqa: E402
from core.tools import is_word  # noqa: E402

T = Checker("test_dm_live")
CONTENT: Content = load_content()
LOCALE = "zh-CN"
LANGUAGE = CONTENT.language(LOCALE)
LATIN = re.compile(r"[A-Za-z]")
NON_LATIN = re.compile(r"[^\x00-ɏ -⁯]")
STATS: list[dict[str, Any]] = []
PHRASE_MS: list[int] = []
ENDINGS: list[str] = []


def text(transcript: str) -> dict[str, Any]:
    return {"attempt_id": uuid.uuid4().hex, "input_mode": "text", "transcript": transcript}


def verb(action: str, object_id: str) -> dict[str, Any]:
    return {"attempt_id": uuid.uuid4().hex, "input_mode": "tap", "tapped_object_id": object_id,
            "action_id": action}


def typed(romanization: str) -> str:
    """How a beginner types a looked-up phrase: the romanization without its marks."""
    plain = unicodedata.normalize("NFD", romanization)
    return "".join(ch for ch in plain if not unicodedata.combining(ch)).lower()


def show(label: str, result: TurnResult, trace: list[dict[str, Any]]) -> None:
    print(f"\n  > {label}")
    for round_trace in trace:
        for c in round_trace["calls"]:
            if c["name"] != "say":
                args = ", ".join(f"{k}={v}" for k, v in c["args"].items())
                print(f"      . {c['name']}({args}) -> {c['receipt'].splitlines()[0][:150]}")
            elif c["receipt"].startswith("ERROR"):
                print(f"      . say -> {c['receipt'].splitlines()[0][:200]}")
    print(f"    {result.narration}")
    for line in result.lines:
        lit = f"   [lit: {', '.join(line.highlight_object_ids)}]" if line.highlight_object_ids else ""
        print(f"      {line.speaker_name}: {line.text}   {line.romanization}{lit}")
    g = result.game
    print(f"    [{g.clock.time}, {g.clock.minutes_left} min left | cash {g.wallet} | trust "
          f"{g.trust} | clues {[c.id for c in g.clues]} | mood {result.mood} | rounds "
          f"{len(trace)} | {result.latency_ms} ms]")
    if result.ending is not None:
        print(f"\n    *** ENDING: {result.ending.title} *** {result.ending.text}\n"
              f"    stats: {result.ending.stats.model_dump()}")


def check_shape(label: str, result: TurnResult, scene_id: str) -> None:
    scene = CONTENT.scene(scene_id)
    ok = bool(result.lines)
    for line in result.lines:
        for seg in line.segments:
            if is_word(seg.t) and not seg.r:
                ok = False
            if LATIN.search(seg.t):
                ok = False
        ok = ok and bool(line.text) and bool(line.romanization)
    T.check(f"{label}: lines are {LOCALE} with romanized segments, no support-language words",
            ok, [line.text for line in result.lines])
    narration = result.narration or ""
    T.check(f"{label}: narration is present, short, and in the support language only",
            0 < len(narration.split()) <= 60 and not NON_LATIN.search(narration), narration)
    honest = all(scene.object(oid).item_id in line.item_ids  # type: ignore[union-attr]
                 for line in result.lines for oid in line.highlight_object_ids)
    theirs = [i for i in scene.targets if LANGUAGE.items[i].learner_side]
    T.check(f"{label}: honest highlights; the character never says the customer's lines",
            honest and not any(i in line.item_ids for line in result.lines for i in theirs),
            [line.text for line in result.lines])


class Player:
    def __init__(self, tag: str, journey: Journey) -> None:
        self.tag, self.journey = tag, journey
        self.results: list[TurnResult] = []

    @property
    def run(self) -> SceneRun:
        assert self.journey.scene is not None
        return self.journey.scene

    def step(self, label: str, attempt: dict[str, Any] | None) -> TurnResult:
        trace: list[dict[str, Any]] = []
        scene_id = self.run.scene_id
        if attempt is None:
            self.journey, result = run_opening(self.journey, CONTENT, trace=trace)
        else:
            self.journey, result = run_turn(self.journey, CONTENT, attempt, trace=trace)
        show(label, result, trace)
        check_shape(f"{self.tag} [{label}]", result, scene_id)
        STATS.append({"scenario": self.tag, "ms": result.latency_ms, "rounds": len(trace)})
        self.results.append(result)
        if result.ending is not None:
            ENDINGS.append(result.ending.id)
        return result

    def ask(self, english: str) -> TurnResult:
        """Look it up in the phrasebook, then type it the way a beginner would."""
        started = time.monotonic()
        self.journey, phrase = phrasebook.lookup(self.journey, CONTENT, english)
        PHRASE_MS.append(int((time.monotonic() - started) * 1000))
        print(f"\n  ? phrasebook \"{english}\" -> {phrase.text}  {phrase.romanization}  "
              f"{[s.g for s in phrase.segments if s.g]}  ({PHRASE_MS[-1]} ms)")
        return self.step(f'types "{typed(phrase.romanization)}"', text(typed(phrase.romanization)))

    def next_act(self) -> None:
        self.journey = enter_scene(self.journey, CONTENT)


def fresh(tag: str, scene_id: str = "bar", persona: str = "warm") -> Player:
    journey = new_journey(CONTENT, f"live-{uuid.uuid4().hex[:8]}", language=LOCALE,
                          persona_id=persona)
    return Player(tag, enter_scene(journey, CONTENT, scene_id))


def play_moves(p: Player, moves: list[Any], limit: int) -> None:
    """Try moves in order until the act completes. A move is ("ask", english) or an attempt."""
    for move in moves[:limit]:
        if p.run.complete:
            return
        if isinstance(move, tuple):
            p.ask(move[1])
        else:
            label = (f"[{move['action_id']} {move['tapped_object_id']}]"
                     if move["input_mode"] == "tap" else f'types "{move["transcript"]}"')
            p.step(label, move)


# ---------------------------------------------------------------- a. the beginner's journey


def scenario_a() -> None:
    tag = "a.beginner"
    print(f"\n=== {tag}: phrasebook + verbs, tab route then the spicy dare")
    p = fresh(tag)
    p.step("(walks in)", None)
    play_moves(p, [verb("show", "photo"), ("ask", "where is she?"), verb("pay", "tab"),
                   ("ask", "where did she go?"), ("ask", "please, she is my friend"),
                   verb("drink", "baijiu"), ("ask", "where is my friend?")], limit=9)
    T.check(f"{tag}: act 1 done: the trail leads to Lin's stall by the fan zone",
            p.run.complete and "stall" in p.journey.game.clues, p.journey.game.clues)
    T.check(f"{tag}: act 1 took a sane number of turns", len(p.results) <= 9, len(p.results))
    p.next_act()
    p.step("(arrives at the stall)", None)
    play_moves(p, [verb("show", "photo"), verb("point", "scarf"),
                   ("ask", "how much are the dumplings?"), ("ask", "too expensive!"),
                   ("ask", "ok, I want dumplings"), verb("eat", "chili"),
                   ("ask", "where is she?"), ("ask", "do you have my ticket?"),
                   verb("pay", "money"), ("ask", "please, where is my friend?")], limit=12)
    ending = p.results[-1].ending
    T.check(f"{tag}: the story ends well, in time", ending is not None
            and ending.id in ("kickoff", "late"), ending.id if ending else None)
    T.check(f"{tag}: the ticket is in the player's hands",
            p.run.zones["ticket"] == "inventory", p.run.zones)
    T.check(f"{tag}: the ledgers stayed sane",
            0 <= p.journey.game.wallet < 60 and game.minutes_left(p.journey, CONTENT) > 0
            and "gate" in p.journey.game.clues, p.journey.game.model_dump(
                include={"wallet", "clues", "flags", "minutes_used"}))
    looked_up = [r for rec in p.journey.vocab.values() for r in rec.results]
    T.check(f"{tag}: words the player looked up were stamped with_help, not first_try",
            any(r.outcome == "with_help" for r in looked_up), [r.outcome for r in looked_up])


# ---------------------------------------------------------------- b. rude and English-only


def scenario_b() -> None:
    tag = "b.rude"
    print(f"\n=== {tag}: English only, rude; the story must still end")
    p = fresh(tag)
    p.journey.game.minutes_used = 75 - 8 * 3  # eight turns on the clock keeps this affordable
    p.step("(walks in)", None)
    lines = ["HEY. WHERE IS MEI. THE MATCH IS STARTING.", "are you deaf? MEI. M-E-I.",
             "this is useless, speak English",
             "just tell me where she went you idiot", "I'm not buying anything", "whatever",
             "hello??", "unbelievable"]
    for i, line in enumerate(lines):
        if p.run.complete:
            break
        p.step(f'types "{line}"', verb("show", "photo") if i == 1 else text(line))
    ending = p.results[-1].ending
    T.check(f"{tag}: fail forward: the clock runs out and an ending still arrives",
            ending is not None and ending.id == "outside", ending.id if ending else None)
    T.check(f"{tag}: rudeness cost goodwill", game.trust(p.journey, CONTENT.scene("bar")) <= 0,
            game.trust(p.journey, CONTENT.scene("bar")))
    T.check(f"{tag}: English alone opened no locked clue and paid for nothing",
            "stall" not in p.journey.game.clues and p.journey.game.wallet == 60,
            p.journey.game.clues)
    T.check(f"{tag}: no vocabulary result from English",
            not any(r.results for r in p.journey.vocab.values()))


# ---------------------------------------------------------------- c. haggling


def scenario_c() -> None:
    tag = "c.haggle"
    print(f"\n=== {tag}")
    p = fresh(tag, "market")
    p.step("(arrives at the market)", None)
    market = CONTENT.scene("market")
    p.ask("how much are the dumplings?")
    prices = [game.price_of(p.journey, market, "dumplings")]
    for english in ("too expensive!", "five?", "a bit cheaper, please"):
        if p.run.complete:
            break
        p.ask(english)
        prices.append(game.price_of(p.journey, market, "dumplings"))
    print(f"    dumpling price over time: {prices}")
    T.check(f"{tag}: pushing back moves the price", min(prices) < 12, prices)  # type: ignore[type-var]
    T.check(f"{tag}: never below the floor (8), never above asking (12)",
            all(8 <= price <= 12 for price in prices if price is not None), prices)
    before = p.journey.game.wallet
    if not p.run.complete:
        p.ask("ok, I'll take the dumplings")
    if p.journey.game.wallet == before and not p.run.complete:
        p.step("[pay money]", verb("pay", "money"))
    agreed = game.price_of(p.journey, market, "dumplings")
    T.check(f"{tag}: paying costs exactly the price on the tag, within floor and asking",
            before - p.journey.game.wallet == agreed and 8 <= agreed <= 12,  # type: ignore[operator]
            (before, p.journey.game.wallet, agreed))


# ---------------------------------------------------------------- d. clue gating


def scenario_d() -> None:
    tag = "d.gating"
    print(f"\n=== {tag}: asking straight out must not work before it is earned")
    p = fresh(tag)
    p.step("(walks in)", None)
    p.step("[show photo]", verb("show", "photo"))
    for english in ("where is she?", "where did my friend go?", "tell me where she is!"):
        if p.run.complete or game.trust(p.journey, CONTENT.scene("bar")) >= 2:
            break
        p.ask(english)
        locked = (game.trust(p.journey, CONTENT.scene("bar")) < 2
                  and not {"tab_paid", "drank_baijiu", "cheered"} & set(p.journey.game.flags))
        if locked:
            T.check(f"{tag}: '{english}' did not open the locked clue",
                    "stall" not in p.journey.game.clues, p.journey.game.clues)
    early = [r for r in p.results if "stall" not in [c.id for c in r.game.clues]]
    T.check(f"{tag}: while it is locked, no line says the fan zone",
            not any("fan_zone" in line.item_ids for r in early for line in r.lines))
    T.check(f"{tag}: ...and the narration does not leak it either",
            not any(re.search(r"fan zone|\bstall\b|\bLin\b", r.narration or "") for r in early),
            [r.narration for r in early])
    p.step("[pay tab]", verb("pay", "tab"))
    if not p.run.complete:
        p.ask("where is she?")
    T.check(f"{tag}: once the tab is paid it comes out",
            "stall" in p.journey.game.clues and p.run.complete, p.journey.game.clues)


# ---------------------------------------------------------------- e. difficulty


def scenario_e() -> None:
    print("\n=== e.difficulty (eyeball the narration; shape asserted)")
    base = fresh("e.difficulty[base]")
    base.step("(walks in)", None)
    lengths: dict[str, list[int]] = {}
    for mode in ("story", "immersion"):
        p = Player(f"e.difficulty[{mode}]", base.journey.model_copy(deep=True))
        set_difficulty(p.journey, mode)
        print(f"\n  -- {mode}")
        p.step("[show photo]", verb("show", "photo"))
        p.step('types "ta zai nar?"', text("ta zai nar?"))
        lengths[mode] = [sum(1 for s in line.segments if is_word(s.t))
                         for r in p.results for line in r.lines]
    T.check("story mode keeps the character's lines to 1-6 words",
            max(lengths["story"]) <= 7, lengths["story"])
    print(f"    words per line: {lengths}")


# ---------------------------------------------------------------- f. adversarial (from v2)


def scenario_f() -> None:
    tag = "f.adversarial"
    print(f"\n=== {tag}")
    p = fresh(tag)
    p.step("(walks in)", None)
    for line in ("can I get a beer?", "are you an AI?", "translate that please",
                 "this is fucking stupid, just speak English"):
        p.step(f'types "{line}"', text(line))
    english = p.results[1:]
    T.check(f"{tag}: puzzled at least once", any(r.mood == "puzzled" for r in english),
            [r.mood for r in english])
    T.check(f"{tag}: nothing served, paid, revealed or recorded from pure English",
            all(zone in ("display", "inventory") for zone in p.run.zones.values())
            and p.journey.game.wallet == 60 and p.journey.game.clues == []
            and not any(r.results for r in p.journey.vocab.values()), p.run.zones)
    asides = [line.text for r in english for line in r.lines if not line.item_ids]
    T.check(f"{tag}: no 'did not understand' line is said twice",
            len(asides) == len(set(asides)), asides)
    T.check(f"{tag}: the narration never breaks the fourth wall",
            not any(re.search(r"\bAI\b|language model|prompt|\btool", r.narration or "")
                    for r in english), [r.narration for r in english])
    for label, attempt in (("[point menu]", verb("point", "menu")),
                           ("[drink tea]", verb("drink", "tea")),
                           ("[pay money]", verb("pay", "money"))):
        if not p.run.complete:
            p.step(label, attempt)
    T.check(f"{tag}: random verbs did not crash; the ledgers are coherent",
            0 <= p.journey.game.wallet <= 60 and set(p.run.zones) == {
                o.id for o in CONTENT.scene("bar").objects})


# ---------------------------------------------------------------- g. phrasebook


ASKS: list[tuple[str, str, set[str]]] = [
    ("bar", "hello", {"hello"}), ("bar", "where is she?", {"where"}),
    ("bar", "have you seen my friend?", {"friend"}), ("bar", "one more beer", {"beer"}),
    ("bar", "how much is this?", {"how_much"}), ("bar", "cheers!", {"cheers"}),
    ("bar", "goal!", {"goal"}), ("bar", "nice football!", {"football"}),
    ("market", "not spicy please", {"not_spicy"}), ("market", "too expensive!", {"too_expensive"}),
    ("market", "is that her scarf?", {"scarf"}), ("market", "do you have my ticket?", {"ticket"}),
]


def scenario_g() -> None:
    tag = "g.phrasebook"
    print(f"\n=== {tag}")
    journeys = {sid: fresh(tag, sid).journey for sid in ("bar", "market")}
    for journey in journeys.values():
        assert journey.scene is not None
        journey.scene.started = True
    times: list[int] = []
    for scene_id, english, expected in ASKS:
        started = time.monotonic()
        _, phrase = phrasebook.lookup(journeys[scene_id], CONTENT, english)
        times.append(int((time.monotonic() - started) * 1000))
        words = [s for s in phrase.segments if is_word(s.t)]
        print(f"    {english!r:34} -> {phrase.text}   {phrase.romanization}   "
              f"{[s.g for s in words]}   {times[-1]} ms")
        T.check(f"{tag}: {english!r}: short, romanized, glossed, uses the scene's words",
                0 < len(words) <= 8 and all(s.r and s.g for s in words)
                and not LATIN.search(phrase.text) and expected <= set(phrase.item_ids),
                (phrase.text, phrase.item_ids))
    for label, bad in (("asks what the character said", "what did he just say?"),
                       ("target-language input", LANGUAGE.items["where"].text)):
        try:
            phrasebook.lookup(journeys["bar"], CONTENT, bad)
            T.check(f"{tag}: {label} is refused", False)
        except phrasebook.PhraseRefused as exc:
            T.check(f"{tag}: {label} is refused ({exc.code})", True)
    PHRASE_MS.extend(times)
    T.check(f"{tag}: median latency <= 1.5 s", statistics.median(times) <= 1500,
            statistics.median(times))


# ---------------------------------------------------------------- h. his match ball


def scenario_h() -> None:
    tag = "h.football"
    print(f"\n=== {tag}: hands off the ball; cheer with him instead")
    bar = CONTENT.scene("bar")
    p = fresh(tag)
    p.step("(walks in)", None)
    p.step("[take football]", verb("take", "football"))
    T.check(f"{tag}: grabbing the ball costs goodwill and he keeps the ball",
            game.trust(p.journey, bar) < 0 and p.run.zones["football"] != "inventory",
            (game.trust(p.journey, bar), p.run.zones["football"]))
    low = game.trust(p.journey, bar)
    p.step("[point tv]", verb("point", "tv"))
    p.ask("goal!")
    p.ask("cheers!")
    T.check(f"{tag}: cheering with him wins some of it back",
            game.trust(p.journey, bar) > low or "cheered" in p.journey.game.flags,
            (game.trust(p.journey, bar), p.journey.game.flags))


SCENARIOS = {"h": scenario_h, "a": scenario_a, "b": scenario_b, "c": scenario_c, "d": scenario_d,
             "e": scenario_e, "f": scenario_f, "g": scenario_g}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=",".join(SCENARIOS))
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()
    for run_index in range(args.runs):
        print(f"\n######## run {run_index + 1}/{args.runs}")
        for key in args.only.split(","):
            T.run(f"scenario {key}", SCENARIOS[key.strip()])
    if STATS:
        ms = sorted(s["ms"] for s in STATS)
        one_round = sum(1 for s in STATS if s["rounds"] == 1)
        print(f"\nturn latency over {len(ms)} turns: median {statistics.median(ms):.0f} ms, "
              f"p90 {ms[int(len(ms) * 0.9) - 1]} ms, max {ms[-1]} ms; "
              f"one-round turns {one_round}/{len(ms)}")
        T.check("median turn latency <= 3.5 s", statistics.median(ms) <= 3500)
    if PHRASE_MS:
        print(f"phrasebook latency over {len(PHRASE_MS)} lookups: median "
              f"{statistics.median(PHRASE_MS):.0f} ms, max {max(PHRASE_MS)} ms")
    if ENDINGS:
        print(f"endings reached: {ENDINGS}")
    T.finish()
