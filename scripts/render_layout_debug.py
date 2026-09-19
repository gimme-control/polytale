"""Composite every object cutout onto its scene background from `art/LAYOUT.json` for review.

    python scripts/render_layout_debug.py [scene ...]

Writes `content/scenes/<id>/art/debug_layout.png`, three stacked panels:
  1. every object at its `display` spot (+ money at `npc`), clean, on the neutral background
  2. every object at its `counter` spot, clean, on the puzzled background (worst-case gesture)
  3. all boxes outlined: display (cyan), counter (yellow), npc (magenta), npc_region, npc_anchor

Placement matches the web stage: x,y = object centre-BOTTOM, h = object height / bg height, width
from the cutout's own aspect. Exits non-zero when two boxes in the same zone overlap or a box
leaves the frame, so a layout edit cannot silently collide.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "content" / "scenes"
PANEL_W = 1200
COLOURS = {"display": (0, 255, 255), "counter": (255, 230, 0), "npc": (255, 0, 255)}


def box_px(art: Path, obj: str, pos: dict, size: tuple[int, int]) -> tuple[int, int, int, int]:
    W, H = size
    with Image.open(art / f"obj_{obj}.png") as im:
        aspect = im.width / im.height
    h = pos["h"] * H
    w = h * aspect
    return (round(pos["x"] * W - w / 2), round(pos["y"] * H - h), round(w), round(h))


def place(canvas: Image.Image, art: Path, obj: str, pos: dict) -> None:
    x, y, w, h = box_px(art, obj, pos, canvas.size)
    sprite = Image.open(art / f"obj_{obj}.png").convert("RGBA")
    canvas.alpha_composite(sprite.resize((max(1, w), max(1, h)), Image.Resampling.LANCZOS), (x, y))


def check(art: Path, layout: dict, size: tuple[int, int]) -> list[str]:
    problems: list[str] = []
    W, H = size
    for zone in ("display", "counter"):
        boxes = {
            o: box_px(art, o, p[zone], size) for o, p in layout["objects"].items() if zone in p
        }
        names = sorted(boxes)
        for name, (x, y, w, h) in boxes.items():
            if x < 0 or y < 0 or x + w > W or y + h > H:
                problems.append(f"{zone}: {name} leaves the frame")
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                ax, ay, aw, ah = boxes[a]
                bx, by, bw, bh = boxes[b]
                if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                    problems.append(f"{zone}: {a} overlaps {b}")
    return problems


def render(scene: str) -> list[str]:
    art = SCENES / scene / "art"
    layout = json.loads((art / "LAYOUT.json").read_text(encoding="utf-8"))
    objects = layout["objects"]
    neutral = Image.open(art / "bg.webp").convert("RGBA")
    puzzled_path = art / "bg_puzzled.webp"
    puzzled = Image.open(puzzled_path).convert("RGBA") if puzzled_path.is_file() else neutral.copy()
    size = neutral.size

    shelf = neutral.copy()
    for obj, pos in objects.items():
        if "display" in pos:
            place(shelf, art, obj, pos["display"])
        elif "npc" in pos:
            place(shelf, art, obj, pos["npc"])

    served = puzzled.copy()
    # Far-to-near so nearer props draw over farther ones, as the stage would.
    for obj, pos in sorted(objects.items(), key=lambda kv: kv[1].get("counter", {}).get("y", 0)):
        if "counter" in pos:
            place(served, art, obj, pos["counter"])

    boxes = neutral.copy()
    d = ImageDraw.Draw(boxes)
    W, H = size
    for obj, pos in objects.items():
        for zone, colour in COLOURS.items():
            if zone in pos:
                x, y, w, h = box_px(art, obj, pos[zone], size)
                d.rectangle((x, y, x + w, y + h), outline=colour + (255,), width=5)
                d.text((x + 6, y + 4), obj, fill=colour + (255,), font_size=30)
    if "npc_region" in layout:
        r = layout["npc_region"]
        d.rectangle(
            (r["x0"] * W, r["y0"] * H, r["x1"] * W, r["y1"] * H), outline=(255, 255, 255, 255)
        )
    ax, ay = layout["npc_anchor"]["x"] * W, layout["npc_anchor"]["y"] * H
    d.ellipse((ax - 14, ay - 14, ax + 14, ay + 14), outline=(255, 60, 60, 255), width=6)

    ph = round(PANEL_W * H / W)
    sheet = Image.new("RGB", (PANEL_W, ph * 3))
    for i, panel in enumerate((shelf, served, boxes)):
        sheet.paste(
            panel.convert("RGB").resize((PANEL_W, ph), Image.Resampling.LANCZOS), (0, i * ph)
        )
    out = art / "debug_layout.png"
    sheet.save(out, "PNG", optimize=True)
    print(f"wrote {out.relative_to(ROOT)} {sheet.size}")
    return [f"{scene}: {p}" for p in check(art, layout, size)]


def main() -> int:
    scenes = sys.argv[1:] or sorted(
        p.parent.parent.name for p in SCENES.glob("*/art/LAYOUT.json")
    )
    problems: list[str] = []
    for scene in scenes:
        problems += render(scene)
    for p in problems:
        print(f"PROBLEM {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
