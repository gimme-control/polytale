"""The story's rules: clock, prices, trust, clue gating, endings. Pure and deterministic.

The GM proposes; these functions decide. Nothing here reads model prose.
"""

from __future__ import annotations

from core.content import Clue, Content, EndingSpec, RevealWhen, Scene
from core.state import Journey


def minutes_left(journey: Journey, content: Content) -> int:
    return max(0, content.journey.clock.total_minutes - journey.game.minutes_used)


def clock_time(journey: Journey, content: Content) -> str:
    """The wall-clock time the story has reached, "HH:MM" (never past the deadline)."""
    clock = content.journey.clock
    now = clock.start_minute + min(journey.game.minutes_used, clock.total_minutes)
    return f"{now // 60 % 24:02d}:{now % 60:02d}"


def spend_minutes(journey: Journey, minutes: int) -> None:
    journey.game.minutes_used += minutes


def trust(journey: Journey, scene: Scene) -> int:
    return journey.game.trust.get(scene.id, scene.npc.trust)


def price_of(journey: Journey, scene: Scene, object_id: str) -> int | None:
    """What an object costs right now: the haggled price if any, else the authored one."""
    obj = scene.object(object_id)
    if obj is None or obj.price is None:
        return None
    return journey.game.prices.get(scene.id, {}).get(object_id, obj.price)


def unmet(journey: Journey, scene: Scene, way: RevealWhen) -> list[str]:
    """What one way of revealing a clue still lacks, in words the GM can act on."""
    lacking: list[str] = []
    if way.trust_at_least is not None and trust(journey, scene) < way.trust_at_least:
        lacking.append(f"trust {way.trust_at_least}+ (now {trust(journey, scene)})")
    lacking += [f"flag {f}" for f in way.flags if f not in journey.game.flags]
    spent = journey.scene.spent if journey.scene is not None else 0
    if way.paid_at_least is not None and spent < way.paid_at_least:
        lacking.append(f"the player has spent {way.paid_at_least}+ here (now {spent})")
    return lacking


def can_reveal(journey: Journey, scene: Scene, clue: Clue) -> bool:
    return not clue.reveal_when or any(not unmet(journey, scene, w) for w in clue.reveal_when)


def resolve_ending(journey: Journey, content: Content) -> EndingSpec:
    """The first authored ending whose conditions hold; the last one is the fallback."""
    game, left = journey.game, minutes_left(journey, content)
    for ending in content.journey.endings:
        when = ending.when
        if (all(c in game.clues for c in when.clues)
                and all(f in game.flags for f in when.flags)
                and (when.clock_left is None or when.clock_left == (left > 0))
                and (when.minutes_left_at_least is None or left >= when.minutes_left_at_least)
                and (when.wallet_at_least is None or game.wallet >= when.wallet_at_least)):
            return ending
    return content.journey.endings[-1]
