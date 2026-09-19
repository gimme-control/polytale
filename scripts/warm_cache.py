"""Pre-synthesize every authored NPC line (opening + help-ladder lines) before a demo.

Generated DM lines are prewarmed by the server as each turn commits; authored lines are known
ahead of time, so the first thing a judge hears never waits on TTS.
Run: PYTHONPATH=. python scripts/warm_cache.py [cartridge_id ...]
"""

from __future__ import annotations

import sys
import time

from dotenv import load_dotenv

from core.cartridge import LineSpec, list_cartridges, load_cartridge
from media.tts import synthesize
from scripts.testkit import ROOT

load_dotenv(ROOT / ".env")


def authored_lines(cartridge_id: str) -> list[LineSpec]:
    cart = load_cartridge(cartridge_id)
    lines = list(cart.opening.spoken_lines)
    if cart.language_learning:
        for beat in cart.language_learning.learning_beats:
            lines += [h.line for h in beat.help if h.line is not None]
    return lines


def main() -> None:
    ids = sys.argv[1:] or [c["id"] for c in list_cartridges()]
    failed = 0
    for cid in ids:
        cart = load_cartridge(cid)
        for line in authored_lines(cid):
            npc = cart.npc(line.speaker)
            t0 = time.monotonic()
            try:
                clip = synthesize(line.text, language=line.language,
                                  voice=npc.voice.model_dump() if npc else {})
            except Exception as exc:
                failed += 1
                print(f"FAIL {cid} {line.text!r}: {exc}")
                continue
            state = "cached" if clip.cached else f"synthesized {time.monotonic() - t0:.1f}s"
            print(f"ok   {cid} {line.text!r} [{clip.provider}, {state}]")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
