"""Composite the engineer + hotspots from art/LAYOUT.json onto the plates for review.

    python scripts/render_layout_debug.py

Writes art/debug_layout.png (base plate, panel-open plate and launched plate side by
side in a column, each at half size) — the web stage places things exactly this way:
sprite feet-centre at (engineer.x, engineer.y), height = engineer.height * plate height.
Hotspot radii are fractions of plate HEIGHT.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "cartridges" / "broken-airship-ja" / "art"


def compose(
    plate_path: Path, layout: dict, *, show_sprite: bool = True, state: str | None = None
) -> Image.Image:
    hotspots = dict(layout["hotspots"])
    if state:
        override = layout.get("state_overrides", {}).get(state, {}).get("hotspots", {})
        hotspots.update(override)
        if state == "launched":
            hotspots.pop("fx.engine_panel", None)
    plate = Image.open(plate_path).convert("RGBA")
    W, H = plate.size
    d = ImageDraw.Draw(plate)
    eng = layout["engineer"]
    if show_sprite:
        sprite = Image.open(ART / "engineer.png").convert("RGBA")
        sh = round(eng["height"] * H)
        sw = round(sprite.width * sh / sprite.height)
        sprite = sprite.resize((sw, sh), Image.Resampling.LANCZOS)
        fx, fy = eng["x"] * W, eng["y"] * H
        plate.alpha_composite(sprite, (round(fx - sw / 2), round(fy - sh)))
        d = ImageDraw.Draw(plate)
        d.line((fx - 40, fy, fx + 40, fy), fill=(255, 0, 255, 255), width=4)
    for name, hs in hotspots.items():
        cx, cy, r = hs["x"] * W, hs["y"] * H, hs["r"] * H
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(0, 255, 255, 255), width=6)
        d.text((cx - r, cy - r - 30), name, fill=(0, 255, 255, 255), font_size=28)
    anc = layout["held_object_anchor"]
    ax, ay = anc["x"] * W, anc["y"] * H
    if show_sprite:
        key = Image.open(ART / "icon_key.png").convert("RGBA").resize((110, 110))
        plate.alpha_composite(key, (round(ax - 55), round(ay - 55)))
        d = ImageDraw.Draw(plate)
        d.text(
            (ax - 160, ay - 95),
            "OVERLAY icon @ held_object_anchor",
            fill=(255, 255, 0, 255),
            font_size=26,
        )
    d.ellipse((ax - 10, ay - 10, ax + 10, ay + 10), outline=(255, 255, 0, 255), width=4)
    return plate


def main() -> int:
    layout = json.loads((ART / "LAYOUT.json").read_text(encoding="utf-8"))
    panels = [
        compose(ART / "plate_base.png", layout),
        compose(ART / "plate_panel_open.png", layout),
        compose(ART / "plate_launched.png", layout, state="launched"),
    ]
    w, h = panels[0].width // 2, panels[0].height // 2
    sheet = Image.new("RGB", (w, h * len(panels)), (0, 0, 0))
    for i, p in enumerate(panels):
        sheet.paste(p.convert("RGB").resize((w, h), Image.Resampling.LANCZOS), (0, i * h))
    out = ART / "debug_layout.png"
    sheet.save(out, "PNG", optimize=True)
    print(f"wrote {out} {sheet.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
