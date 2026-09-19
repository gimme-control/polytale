"""Offline art pipeline for the Broken Airship cartridge.

Idempotent: every asset is skipped when its output already exists, unless named
with ``--force``. Art is generated here once and committed; it is never generated
at runtime.

    python scripts/generate_art.py                    # make whatever is missing
    python scripts/generate_art.py --force engineer   # regenerate one asset
    python scripts/generate_art.py --only icon_key    # consider only these assets
    python scripts/generate_art.py --list             # show assets + status

Raw model outputs are kept in ``cache/art_raw/`` (gitignored) so matting / crops
can be re-derived with ``--rederive`` without new model calls. Every image-model
call is appended to ``cache/art_raw/calls.jsonl``.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.matte import (  # noqa: E402
    PROMPT_KEY_RGB,
    drop_small_islands,
    matte_cutout,
    purge_key,
    remove_hairlines,
    sample_backdrop_rgb,
    trim_to_subject,
)

ART = ROOT / "cartridges" / "broken-airship-ja" / "art"
RAW = ROOT / "cache" / "art_raw"
CALLS_LOG = RAW / "calls.jsonl"
LAYOUT = ART / "LAYOUT.json"

PRO_MODEL = "gemini-3-pro-image"
PLATE_MAX_BYTES = 4 * 1024 * 1024
KEY_HEX = "#{:02x}{:02x}{:02x}".format(*PROMPT_KEY_RGB)

# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

STYLE = (
    "Hand-painted storybook concept art in a Studio Ghibli-adjacent style: soft gouache and "
    "watercolour brushwork, visible painterly texture, gentle cel-like shapes, warm golden "
    "lantern light against cool slate-blue storm shadows, dusk. Cinematic, cosy, adventurous."
)

NO_TEXT = (
    "Absolutely no text, letters, numbers, signs with writing, logos, watermarks, signatures, "
    "captions or UI anywhere in the image."
)

PLATE_BASE_PROMPT = f"""{STYLE}

A wide 16:9 establishing shot of a small grassy cliff-top airfield at dusk. Eye-level camera,
slightly elevated, looking along the cliff edge.

LEFT and CENTRE of the frame: a charming grounded airship resting on the grass — a plump
patched-canvas balloon envelope above a wooden gondola hull with brass trim, rivets and two
propellers at the stern (propellers still). It is moored with thick ropes to iron stakes in the
grass. On the side of the wooden hull, facing the viewer, clearly visible at roughly the middle
of the frame: a small square BRASS ENGINE PANEL — a closed brass hatch with rivets around its
edge and a round brass keyhole lock plate. The hatch is shut and locked. It must be easy to
spot and not hidden by ropes or crates.

Behind the airship, slightly left: a small weathered wooden workshop shed with a tin roof,
warm lantern light glowing from its open door and window, a few crates, a barrel and coiled
rope nearby. Warm hanging lanterns on posts along the airfield.

RIGHT THIRD of the frame: clear, open, flat grassy ground in the foreground/midground, empty
of objects, with room for a standing person to be composited later (do NOT paint any person).
The grass is one continuous, unbroken meadow from the airship to the right edge — no cracks,
trenches, fissures, ledges or steps dividing the ground; the airship and the open right-hand
ground are on the same level plateau so someone could walk straight from one to the other. The
cliff drop and the sea are only in the background beyond the far edge of the plateau.

Sky: dusk gradient with warm amber near the ground light; on the horizon beyond the cliff, dark
towering storm clouds rolling in over the sea, a hint of distant lightning glow, wind bending
the grass.

No people, no animals, no characters, no silhouettes of people anywhere. {NO_TEXT}
Full-bleed painting edge to edge, no border, no frame."""

PLATE_PANEL_OPEN_PROMPT = f"""This is an edit of the attached painting. Keep the image IDENTICAL —
same camera, composition, airship, shed, lanterns, sky, storm, colours, lighting and brushwork —
and change ONLY ONE small thing:

The small brass engine panel hatch on the side of the airship's wooden hull is now SWUNG OPEN on
its hinge. Inside the opened hatch: warm glowing brass engine machinery — gears, copper pipes, a
small glowing amber core — casting a soft orange light onto the hatch door and the nearby hull.

Do not move, add or remove anything else. Do not change the airship's position or shape. No
people. {NO_TEXT}"""

PLATE_LAUNCHED_PROMPT = f"""Repaint the attached painting as the moment AFTER TAKE-OFF. Same
place, same camera angle, same shed, lanterns, fence, cliff, sea, grass, crates, colour palette
and painterly style.

THE BIG CHANGE — the airship is NO LONGER ON THE GROUND. The whole airship (balloon envelope and
wooden hull together) has risen high into the sky and drifted toward the upper-right: the bottom
of its wooden hull is now clearly ABOVE the distant horizon line, with open sky visible under
the hull, and it is a bit smaller because it is farther away. Its propellers spin with circular
motion blur, a warm glow shines from the open engine hatch, and the loose mooring ropes dangle
from the hull in the wind.

On the ground where the airship used to sit: now EMPTY meadow — flattened grass in an oval
shape, the iron mooring stakes still in the ground with the cut/dropped rope ends lying slack
on the grass. You can now see the grass, fence and cliff that the hull used to cover.

The storm on the horizon is parting a little: a gap in the dark clouds with a shaft of warm
golden light breaking through behind the rising airship. Wind streaks in the grass.

No people anywhere. {NO_TEXT}"""

ENGINEER_PROMPT = f"""Character sprite in EXACTLY the painterly style, palette and warm lantern
lighting of the attached painting (use it only as a style reference — do not paint the scene).

One single full-body character, head to toe, entire figure visible including both feet, centred,
standing on nothing: a young Japanese woman, early twenties, airship engineer. Short dark bob
haircut with a few loose strands, brass aviator goggles pushed up on her head, friendly
determined expression with a small confident smile. Oil-stained rust-orange work jumpsuit with
the sleeves rolled up to the elbows, a smudge of grease on one cheek, a brown leather tool belt
with a wrench, screwdriver and small pouches, sturdy brown work boots.

Pose: three-quarter view, body and face turned toward the LEFT of the image, one hand raised
slightly in front of her at chest height, palm up, as if presenting or holding up a small object
(hand empty). The other arm relaxed at her side. Natural anatomy: exactly two arms, two hands,
five fingers each, two legs.

Background: a perfectly flat, uniform, solid chroma-key mint green ({KEY_HEX}) filling the whole
frame edge to edge. No floor, no shadow, no gradient, no vignette, no scenery, no outline or
white border around the figure. Nothing else in the image. {NO_TEXT}"""

PORTRAIT_PROMPT = f"""Head-and-shoulders dialogue portrait of the SAME character as in the
attached image (same face, same short dark bob, same brass goggles on her head, same rust-orange
jumpsuit collar, same grease smudge), in the same painterly storybook style. Square framing,
face slightly turned to the left, friendly determined smile, looking at the viewer. Background:
a soft painted blur of warm amber lantern light and dusky blue-grey sky, out of focus. Nothing
else. {NO_TEXT}"""

ICON_KEY_PROMPT = f"""A single game item icon in EXACTLY the painterly storybook style of the
attached painting (style reference only — do not paint the scene): an ornate antique brass
engine key, large decorative bow with a gear-shaped cutout, long shaft, chunky bit with teeth,
warm golden highlights and soft painted shading, slightly tilted diagonally. The whole key is
visible and centred with generous margin.

Background: a perfectly flat, uniform, solid chroma-key mint green ({KEY_HEX}) edge to edge.
No shadow, no gradient, no border, no outline, no other objects. {NO_TEXT}"""

ICON_MAP_PROMPT = f"""A single game item icon in EXACTLY the painterly storybook style of the
attached painting (style reference only — do not paint the scene): a rolled-up aged parchment
route map, cream and tan paper curling at the ends, tied around the middle with a bright red silk
ribbon in a bow, a small glimpse of faint inked coastline lines on the curl (only abstract lines,
no writing). Slightly tilted diagonally. The whole object visible and centred with generous
margin.

Background: a perfectly flat, uniform, solid chroma-key mint green ({KEY_HEX}) edge to edge.
No shadow, no gradient, no border, no outline, no other objects. {NO_TEXT}"""

COVER_PROMPT = f"""A NEW painting — not a copy of the attached one. The attached painting
only defines the world: reuse its airship design (patched cream-and-ochre canvas balloon, wooden
boat-shaped hull with brass trim, rear propeller, brass engine hatch), its painterly storybook
style and its dusk palette.

Compose a cinematic 16:9 title-card key art: a dramatic LOW-ANGLE, close three-quarter view of
the airship from near its bow, the balloon towering and filling the upper-left two thirds of the
frame, the hull just above the grass on the cliff-top, lantern light warming the wood, mooring
ropes taut in the wind, grass and a few leaves blowing. The huge dark storm with lightning rolls
in from the sea at the right, backlit by a golden sunset glow on the horizon. Leave calm,
uncluttered sky in the upper-right corner. Epic, hopeful, adventurous mood. No people.
{NO_TEXT} Full-bleed painting, no border.
"""


# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types

        _client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=240_000),
        )
    return _client


def _log_call(entry: dict) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    with CALLS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _ref_part(img: Image.Image):
    from google.genai import types

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png")


def gen_image(
    name: str,
    prompt: str,
    *,
    model: str,
    refs: list[Image.Image] | None = None,
    aspect_ratio: str = "16:9",
    image_size: str = "2K",
    retries: int = 2,
) -> Image.Image:
    """One image-model call (with retry on empty/failed responses) -> PIL image."""
    from google.genai import types

    contents: list = [_ref_part(r) for r in refs or []]
    contents.append(prompt)
    cfg = types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=aspect_ratio, image_size=image_size),
    )
    last_err: str = ""
    for attempt in range(retries + 1):
        t0 = time.monotonic()
        try:
            resp = _get_client().models.generate_content(
                model=model, contents=contents, config=cfg
            )
            data = _extract_image_bytes(resp)
            err = None if data else f"no image in response: {_response_text(resp)[:200]}"
        except Exception as exc:  # noqa: BLE001 — network/API errors are retried
            data, err = None, f"{type(exc).__name__}: {exc}"[:300]
        _log_call(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "asset": name,
                "model": model,
                "attempt": attempt,
                "ok": bool(data),
                "seconds": round(time.monotonic() - t0, 1),
                "error": err,
            }
        )
        if data:
            img = Image.open(io.BytesIO(data))
            img.load()
            return img
        last_err = err or ""
        print(f"  [{name}] attempt {attempt} failed: {last_err}")
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{name}: image generation failed: {last_err}")


def _extract_image_bytes(response) -> bytes | None:
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None) if inline is not None else None
            if data:
                return data if isinstance(data, bytes) else bytes(data)
    return None


def _response_text(response) -> str:
    out: list[str] = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "text", None):
                out.append(part.text)
    return " ".join(out)


# --------------------------------------------------------------------------- #
# Save helpers
# --------------------------------------------------------------------------- #


def save_raw(name: str, img: Image.Image) -> Path:
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"{name}.png"
    img.save(path, "PNG")
    return path


def load_raw(name: str) -> Image.Image | None:
    path = RAW / f"{name}.png"
    if not path.is_file():
        return None
    img = Image.open(path)
    img.load()
    return img


def save_plate(img: Image.Image, path: Path) -> None:
    """Opaque plate PNG under PLATE_MAX_BYTES (downscale if needed) + WebP sibling."""
    rgb = img.convert("RGB")
    path.parent.mkdir(parents=True, exist_ok=True)
    work = rgb
    while True:
        work.save(path, "PNG", optimize=True)
        if path.stat().st_size <= PLATE_MAX_BYTES or work.width <= 1600:
            break
        scale = 0.9
        work = work.resize(
            (round(work.width * scale), round(work.height * scale)), Image.Resampling.LANCZOS
        )
    rgb_webp = work
    rgb_webp.save(path.with_suffix(".webp"), "WEBP", quality=90, method=6)


def save_rgba(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)


def fit_to(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resize an edit to the base plate's exact size (cover-fit, centred)."""
    if img.size == size:
        return img
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    nw, nh = round(img.width * scale), round(img.height * scale)
    big = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left, top = (nw - tw) // 2, (nh - th) // 2
    return big.crop((left, top, left + tw, top + th))


def masked_merge(
    base: Image.Image, edit: Image.Image, center: tuple[float, float], radius: float
) -> Image.Image:
    """Keep ``base`` everywhere except a feathered circle (plate fractions) from ``edit``.

    Guarantees a localized edit: model drift outside the hatch is discarded.
    """
    w, h = base.size
    mask = Image.new("L", (w, h), 0)
    cx, cy, r = center[0] * w, center[1] * h, radius * h
    ImageDraw.Draw(mask).ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(r * 0.18))
    return Image.composite(edit.convert("RGB"), base.convert("RGB"), mask)


def load_layout() -> dict:
    if LAYOUT.is_file():
        return json.loads(LAYOUT.read_text(encoding="utf-8"))
    return {}


# --------------------------------------------------------------------------- #
# Assets
# --------------------------------------------------------------------------- #


@dataclass
class Asset:
    name: str
    out: Path
    deps: list[str] = field(default_factory=list)
    build: Callable[[bool], None] | None = None  # arg: rederive-only (no model call)


def _open(path: Path) -> Image.Image:
    img = Image.open(path)
    img.load()
    return img


def _model_for(asset: str) -> str:
    override = os.environ.get(f"ART_MODEL_{asset.upper()}")
    if override:
        return override
    if asset in {"plate_base", "engineer", "cover"}:
        return PRO_MODEL
    if asset in {"plate_panel_open", "plate_launched"}:
        return PRO_MODEL
    return os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")


def build_plate_base(rederive: bool) -> None:
    raw = load_raw("plate_base") if rederive else None
    if raw is None:
        raw = gen_image("plate_base", PLATE_BASE_PROMPT, model=_model_for("plate_base"))
        save_raw("plate_base", raw)
    save_plate(raw, ART / "plate_base.png")


def build_panel_open(rederive: bool) -> None:
    base = _open(ART / "plate_base.png").convert("RGB")
    raw = load_raw("plate_panel_open") if rederive else None
    if raw is None:
        raw = gen_image(
            "plate_panel_open",
            PLATE_PANEL_OPEN_PROMPT,
            model=_model_for("plate_panel_open"),
            refs=[base],
        )
        save_raw("plate_panel_open", raw)
    edit = fit_to(raw.convert("RGB"), base.size)
    hot = load_layout().get("hotspots", {}).get("fx.engine_panel")
    if hot:
        # Localize: only the hatch region comes from the edit (radius padded for glow).
        edit = masked_merge(base, edit, (hot["x"], hot["y"]), hot["r"] * 2.4)
    save_plate(edit, ART / "plate_panel_open.png")


def build_launched(rederive: bool) -> None:
    base = _open(ART / "plate_base.png").convert("RGB")
    raw = load_raw("plate_launched") if rederive else None
    if raw is None:
        raw = gen_image(
            "plate_launched",
            PLATE_LAUNCHED_PROMPT,
            model=_model_for("plate_launched"),
            refs=[base],
        )
        save_raw("plate_launched", raw)
    save_plate(fit_to(raw.convert("RGB"), base.size), ART / "plate_launched.png")


def _cutout(raw: Image.Image, pad: int) -> Image.Image:
    import numpy as np

    key = sample_backdrop_rgb(np.asarray(raw.convert("RGB")))
    cut = matte_cutout(raw)
    # Our subjects (orange jumpsuit, brass, parchment) never contain mint, so
    # enclosed mint pockets (the gap between the legs) are backdrop too.
    cut = purge_key(cut, key)
    cut = remove_hairlines(cut, width=2)
    cut = drop_small_islands(cut)
    return trim_to_subject(cut, pad=pad)


def build_engineer(rederive: bool) -> None:
    raw = load_raw("engineer") if rederive else None
    if raw is None:
        style = _open(ART / "plate_base.png")
        raw = gen_image(
            "engineer",
            ENGINEER_PROMPT,
            model=_model_for("engineer"),
            refs=[style],
            aspect_ratio="9:16",
        )
        save_raw("engineer", raw)
    cut = _cutout(raw, pad=12)
    # The model paints her turned to image-right; the stage needs her facing the
    # airship on the left. Mirroring is lossless for this design (no text/logos).
    cut = cut.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    # Feet at the bottom: drop the bottom padding so y=height is the sole line.
    cut = cut.crop((0, 0, cut.width, cut.height - 10))
    save_rgba(cut, ART / "engineer.png")


def build_portrait(rederive: bool) -> None:
    raw = load_raw("engineer_portrait") if rederive else None
    if raw is None:
        sprite = _open(ART / "engineer.png")
        # Flatten onto a neutral field: transparent refs read as white stickers.
        flat = Image.new("RGB", sprite.size, (92, 88, 82))
        flat.paste(sprite, mask=sprite.split()[3])
        raw = gen_image(
            "engineer_portrait",
            PORTRAIT_PROMPT,
            model=_model_for("engineer_portrait"),
            refs=[flat],
            aspect_ratio="1:1",
            image_size="1K",
        )
        save_raw("engineer_portrait", raw)
    out = raw.convert("RGB")
    side = min(out.size)
    out = out.crop(((out.width - side) // 2, (out.height - side) // 2,
                    (out.width + side) // 2, (out.height + side) // 2))
    if side > 768:
        out = out.resize((768, 768), Image.Resampling.LANCZOS)
    save_rgba(out, ART / "engineer_portrait.png")


def _build_icon(name: str, prompt: str, rederive: bool) -> None:
    raw = load_raw(name) if rederive else None
    if raw is None:
        style = _open(ART / "plate_base.png")
        raw = gen_image(
            name, prompt, model=_model_for(name), refs=[style], aspect_ratio="1:1", image_size="1K"
        )
        save_raw(name, raw)
    cut = _cutout(raw, pad=0)
    # Contain-fit in a 512 square with a small transparent margin.
    box = 512
    inner = box - 2 * 20
    scale = min(inner / cut.width, inner / cut.height)
    cut = cut.resize(
        (max(1, round(cut.width * scale)), max(1, round(cut.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    canvas.paste(cut, ((box - cut.width) // 2, (box - cut.height) // 2), cut)
    save_rgba(canvas, ART / f"{name}.png")


def build_cover(rederive: bool) -> None:
    raw = load_raw("cover") if rederive else None
    if raw is None:
        base = _open(ART / "plate_base.png")
        raw = gen_image("cover", COVER_PROMPT, model=_model_for("cover"), refs=[base])
        save_raw("cover", raw)
    save_plate(raw, ART / "cover.png")


ASSETS: list[Asset] = [
    Asset("plate_base", ART / "plate_base.png", [], build_plate_base),
    Asset("plate_panel_open", ART / "plate_panel_open.png", ["plate_base"], build_panel_open),
    Asset("plate_launched", ART / "plate_launched.png", ["plate_base"], build_launched),
    Asset("engineer", ART / "engineer.png", ["plate_base"], build_engineer),
    Asset("engineer_portrait", ART / "engineer_portrait.png", ["engineer"], build_portrait),
    Asset(
        "icon_key",
        ART / "icon_key.png",
        ["plate_base"],
        lambda r: _build_icon("icon_key", ICON_KEY_PROMPT, r),
    ),
    Asset(
        "icon_map",
        ART / "icon_map.png",
        ["plate_base"],
        lambda r: _build_icon("icon_map", ICON_MAP_PROMPT, r),
    ),
    Asset("cover", ART / "cover.png", ["plate_base"], build_cover),
]


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--force", nargs="*", default=[], help="asset names to regenerate")
    ap.add_argument("--only", nargs="*", default=[], help="limit to these asset names")
    ap.add_argument(
        "--rederive",
        nargs="*",
        default=[],
        help="rebuild these outputs from cached raw generations (no model call)",
    )
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    names = {a.name for a in ASSETS}
    for n in [*args.force, *args.only, *args.rederive]:
        if n not in names:
            ap.error(f"unknown asset {n!r}; choose from {sorted(names)}")

    if args.list:
        for a in ASSETS:
            status = "ok" if a.out.is_file() else "missing"
            print(f"{a.name:20s} {status:8s} {a.out.relative_to(ROOT)}")
        return 0

    for a in ASSETS:
        if args.only and a.name not in args.only:
            continue
        rederive = a.name in args.rederive
        if a.out.is_file() and a.name not in args.force and not rederive:
            print(f"skip   {a.name} (exists)")
            continue
        missing = [d for d in a.deps if not (ART / f"{d}.png").is_file()]
        if missing:
            print(f"defer  {a.name}: missing deps {missing}")
            continue
        print(f"build  {a.name}{' (rederive)' if rederive else ''} …")
        t0 = time.monotonic()
        assert a.build is not None
        a.build(rederive)
        with Image.open(a.out) as im:
            size = im.size
        print(f"done   {a.name} {size[0]}x{size[1]} in {time.monotonic() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
