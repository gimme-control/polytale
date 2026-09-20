"""The story's rules: trust, clue gating, endings. Pure and deterministic.

The GM proposes; these functions decide. Nothing here reads model prose.
"""

from __future__ import annotations

from core.content import Clue, Content, EndingSpec, RevealWhen, Scene
from core.state import Journey


def trust(journey: Journey, scene: Scene) -> int:
    return journey.game.trust.get(scene.id, scene.npc.trust)


def unmet(journey: Journey, scene: Scene, way: RevealWhen) -> list[str]:
    """What one way of revealing a clue still lacks, in words the GM can act on."""
    lacking: list[str] = []
    if way.trust_at_least is not None and trust(journey, scene) < way.trust_at_least:
        lacking.append(f"trust {way.trust_at_least}+ (now {trust(journey, scene)})")
    lacking += [f"flag {f}" for f in way.flags if f not in journey.game.flags]
    return lacking


def can_reveal(journey: Journey, scene: Scene, clue: Clue) -> bool:
    return not clue.reveal_when or any(not unmet(journey, scene, w) for w in clue.reveal_when)


def resolve_ending(journey: Journey, content: Content) -> EndingSpec:
    """The first authored ending whose conditions hold; the last one is the fallback."""
    state = journey.game
    for ending in content.journey.endings:
        when = ending.when
        if (all(c in state.clues for c in when.clues)
                and all(f in state.flags for f in when.flags)):
            return ending
    return content.journey.endings[-1]
