"""Offline art pipeline for Polytale scenes (`content/scenes/<id>/art/`).

Idempotent: every asset is skipped when its output already exists, unless named with
``--force``. Art is generated here once and committed; nothing is drawn at runtime.

    python scripts/generate_art.py                       # make whatever is missing
    python scripts/generate_art.py --list                # assets + status
    python scripts/generate_art.py --only bar            # a whole scene ...
    python scripts/generate_art.py --only bar/cover      # ... or single assets
    python scripts/generate_art.py --force bar/bg
    python scripts/generate_art.py --rederive bar/cover  # rebuild from cached raw, no model call

Asset names are ``<scene>/<file stem>``. ``--force`` / ``--rederive`` only touch the assets they
name; ``--only`` limits what is considered at all.

Raw model outputs (the PNG masters) live in ``cache/art_raw/<scene>/`` (gitignored) and every
image-model call is appended to ``cache/art_raw/calls.jsonl``.
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

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCENES = ROOT / "content" / "scenes"
RAW = ROOT / "cache" / "art_raw"
CALLS_LOG = RAW / "calls.jsonl"

IMAGE_MODEL = "gemini-3-pro-image"
BG_SIZE = (2400, 1350)
COVER_SIZE = (1920, 1080)
WEBP_MAX_BYTES = 600 * 1024

# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

STYLE = (
    "Mature, cinematic, stylized-realism digital painting — premium narrative-game / graphic-novel "
    "key art for an adult audience. Realistic adult proportions and anatomy, real materials (worn "
    "wood, brushed steel, glass, fabric), moody motivated lighting, restrained desaturated palette "
    "with a few warm accents, subtle painterly brushwork, shallow depth-of-field cues, film grain. "
    "NOT a cartoon, NOT anime, NOT a children's storybook, no whimsy, no exaggerated features."
)

NO_TEXT = (
    "STRICT: absolutely no text of any kind anywhere — no letters, no Chinese or other characters, "
    "no numbers, no logos, no labels, no signage writing, no watermarks, no signature. Bottles and "
    "jars are unlabeled; any sign, poster, menu board or neon is blank or a purely abstract shape."
)

SCREEN = {
    "green": "pure saturated chroma-key GREEN (#00ff00)",
    "blue": "pure saturated chroma-key BLUE (#0000ff)",
}


NO_BRAND = (
    "GENERIC FOOTBALL ONLY: no official tournament branding of any kind — no federation or "
    "cup marks, no trophy, no mascots, no real team crests or national emblems, no sponsor logos, "
    "no recognisable real people. Every jersey, scarf, flag and pennant is a plain colour block "
    "or plain stripes with NO crest, NO number and NO lettering."
)

# Sent with the asset's own previous raw when one exists, so a re-dress keeps the same person
# and the same composition (object spots survive) instead of inventing a new scene.
PRIOR = (
    "The attached painting is the PREVIOUS version of this exact image. Repaint it: keep the "
    "same camera, framing and composition, every surface in the same place and, above all, the "
    "SAME PERSON — identical face, age, hair, build and pose. Wherever the description below "
    "differs from the attachment (clothing, set dressing, lighting, background), the "
    "description wins.\n\n"
)


def _bg_tail(who: str) -> str:
    return (
        f"Exactly ONE person in the image: {who}. No other people, no customers, no reflections "
        f"of people, no hands or body of the viewer. {NO_BRAND} {NO_TEXT} Full-bleed, no border, "
        "no frame."
    )


BAR_BG = f"""{STYLE}

FIRST-PERSON point of view of a customer sitting on a bar stool at the counter of a small,
late-night neighbourhood bar in a Chinese city, on the night of a huge football final. Eye-level,
straight-on, symmetrical-ish framing, 16:9.

THE BARTENDER: a Chinese man in his mid-40s standing directly behind the counter, framed
waist-up, placed at the horizontal CENTRE of the image. Short dark hair with a little grey, light
stubble. Tonight he wears a PLAIN deep-red short-sleeved football jersey — one flat colour with a
simple darker collar, no crest, no number, no lettering, no stripes, no logo — under his dark
apron. Calm, wry, self-possessed. He looks straight at the viewer with a NEUTRAL, relaxed
expression, mouth closed. Both hands rest flat on the far edge of the counter in front of him,
empty.

THE BACK WALL behind him: dark wood panelling with a long back counter inside a warmly lit alcove
(hidden warm light strip above it) running behind him at the height of his elbows. IMPORTANT: the
back counter top is almost completely BARE — long clear empty stretches to the LEFT and to the
RIGHT of the bartender, where props will be added later. There are NO bottles and NO objects on
the back counter at all: BOTH ends of it are bare, lit, empty wood (if a previous version shows a
cluster of bottles standing at the left end of the back counter, REMOVE it and paint the bare
counter and the lit alcove wall behind it). Above the alcove, a dark shelf in shadow
carries a few generic dark bottles of bare glass and dark glasses at its far left only.

MATCH-NIGHT DRESSING: a string of small PLAIN triangular pennants in mixed flat colours (red,
white, yellow, blue) is draped along the front edge of that upper shelf, and two PLAIN knitted
football scarves in simple red-and-white bar stripes are pinned flat to the shelf edge above the
alcove, one at the far left and one right of centre. Nothing hangs low enough to cover the back
counter.

THE RIGHT WALL: at the right of the frame the dark wood-panelled side wall comes forward. From
the top of the frame down to the height of the back counter — roughly the right-hand sixth of the
frame — it is one clean, plain, EMPTY stretch of dark wood panelling: no window, no neon, no door,
no shelf, no picture, no decoration, nothing mounted on it. There is NO television, NO screen,
NO monitor and NO bracket anywhere in the image, not even partly cropped at a corner (one is
composited later).

THE NEAR COUNTER: a dark, polished, worn wooden bar counter fills the bottom 27% of the frame,
running edge to edge, seen from slightly above. Its surface is completely EMPTY — no glasses, no
coasters, no napkins, no objects at all — and evenly, softly lit so that props can be placed on
it later.

LIGHT: night. Warm tungsten practical lamps and a soft pool of light on the counter, against a
faint cool bluish-white flicker falling in from OUTSIDE the frame beyond the top-right corner (its
source is never visible), rimming the bartender's shoulder and the right side of the room.

{_bg_tail("the bartender")}"""

COVERS = {
    "bar": f"""{STYLE}

Establishing shot, 16:9: the exterior doorway of a small neighbourhood corner bar on a narrow
side street in a Chinese city, late at night, just after rain, on the night of a huge football
final. A dark wood-and-glass door and one steamed-up window glow warm amber from inside, where
bottles and a bar counter are only vague soft shapes, and a cool blue-white television glow
flickers through the fogged glass from high inside. Through the fogged glass NOTHING is legible:
only soft amber shapes and that cool glow — no red shapes, no sign and no poster inside, and no
poster or notice on the outside walls either. A PLAIN knitted football scarf in red-and-white
bar stripes hangs in the window, and a string of small PLAIN triangular pennants in mixed flat
colours runs across the facade. The wet asphalt and paving reflect the warm glow and a little
magenta-and-teal neon from an ABSTRACT neon ring (a simple ring, not a letter or word) above the
door. A parked bicycle, a drainpipe, tangled overhead cables, light mist. Inviting, expectant.
Nobody in the street. {NO_BRAND} {NO_TEXT} Full-bleed, no border.""",
}

MEI = (
    "Mei: a Chinese woman in her late twenties with a short dark chin-length bob, warm brown eyes, "
    "a bright open face, wearing a dark wool coat and a knitted FOOTBALL SCARF in plain "
    "red-and-white bar stripes (no crest, no lettering) round her neck"
)


_MEI_REF = f"THE FRIEND is {MEI}. "
_CROWD = (
    "The crowd are anonymous fans seen mostly from behind or as backlit silhouettes, in plain "
    "flat-coloured shirts and plain red-and-white bar-striped scarves. THE FLAGS ARE NOT NATIONAL "
    "FLAGS: every flag in the image is EITHER one single flat colour (all red, or all white) OR "
    "the supporters' flag QUARTERED in red and white (four plain rectangles, red top-left and "
    "bottom-right, white the other two). No flag has two or three bands or stripes, no flag has "
    "any blue, green or yellow, no flag carries an emblem. The buildings around the square are "
    "dark, plain, out-of-focus facades with a few lit windows only: NO shop signs, NO banners, "
    "NO posters, NO billboards, NO emblems on them. "
)
# Sent with an illustration's own previous raw, so a fix keeps the people and the staging.
ILLUSTRATION_PRIOR = (
    "The FIRST attached image is the PREVIOUS version of this exact painting. Repaint it: keep "
    "the same camera, composition, light and people in the same poses — above all the woman in "
    "the foreground keeps the IDENTICAL face, haircut, scarf, coat, pose and drink. Wherever the "
    "description below differs from it (flags, signs, set dressing), the description wins.\n\n"
)
_BIG_SCREEN = (
    "a GIANT OUTDOOR LED SCREEN on a truss tower, showing only a floodlit green football pitch "
    "from a high broadcast camera angle with tiny players as specks — NO scoreboard, NO clock, "
    "NO caption, NO channel logo, NO graphics on it"
)
ILLUSTRATIONS: dict[str, tuple[str, str, list[str]]] = {
    "bar/ending_kickoff": (
        "scenes/bar/art/ending_kickoff.webp",
        f"""{STYLE}

FIRST-PERSON point of view, 16:9: you are standing in a packed outdoor FAN ZONE in a Chinese city
at night, at the moment of kickoff of a huge football final. Ahead, above the heads of the crowd,
{_BIG_SCREEN}. Red flare smoke drifts through the floodlights and confetti hangs in the air.
{_CROWD}{_MEI_REF}She is RIGHT BESIDE the viewer in the near foreground on the right, turning
toward the viewer with a huge, delighted grin, holding out a plain plastic cup of beer to the
viewer. She is the only person whose face is clearly seen. Euphoric, electric, warm skin tones
against the cool screen light, cinematic depth of field. {NO_BRAND} {NO_TEXT} Full-bleed, no
border.""",
        [],
    ),
    "bar/ending_late": (
        "scenes/bar/art/ending_late.webp",
        f"""{STYLE}

FIRST-PERSON point of view, 16:9: you arrive late at a packed outdoor FAN ZONE in a Chinese city at
night, at the exact moment of a GOAL. The whole crowd is mid-eruption — jumping, arms thrown up,
beer spraying, confetti and red flare smoke — backlit by {_BIG_SCREEN}. {_CROWD}{_MEI_REF}She
has spotted the viewer: in the near foreground she pushes out of the crowd toward the viewer,
laughing out loud, one arm punched up in the air, the other hand holding out a bare amber beer
bottle with no label to the viewer. She is the only person whose face is clearly seen. Joyful
chaos, motion blur at the edges, warm skin tones against the cool screen light. {NO_BRAND}
{NO_TEXT} Full-bleed, no border.""",
        [],
    ),
    "story/title": (
        "title.webp",
        f"""{STYLE}

Title key art, 16:9, for a story set in the world of the attached painting (same city, same
finish, same palette): a rain-wet narrow street in a Chinese city on the night of a huge football
final, seen from street level. Strings of small PLAIN triangular pennants in mixed flat colours
criss-cross the lane overhead. At the far END of the street, the cool blue-white glow of a giant
outdoor screen — only a blurred, overexposed rectangle of light with no readable content — and a
dense crowd as tiny soft silhouettes with raised arms, flare smoke catching the light. On the
RIGHT side of the street, the warm amber glow of a small corner bar's fogged window and door
spills onto the pavement. On the LEFT side, the bare bulbs, steam and steel of a street-food
stall. Wet asphalt reflections, mist. Nobody close to the camera.
COMPOSITION: the top-left third of the image is calm, empty, dark night sky with soft mist and
no cables, no pennants, no buildings and no detail, reserved for a title. {NO_BRAND} {NO_TEXT}
Full-bleed, no border.""",
        ["bar/cover"],
    ),
}
ILLUSTRATION_SIZE = (1920, 1080)
ILLUSTRATION_MAX_BYTES = 350 * 1024

# Market reuses the bar's files byte-for-byte so recall is visually identical.

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
            http_options=types.HttpOptions(timeout=300_000),
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
    refs: list[Image.Image] | None = None,
    aspect_ratio: str = "16:9",
    image_size: str = "2K",
    retries: int = 2,
) -> Image.Image:
    """One image-model call (retried on empty/failed responses) -> PIL image."""
    from google.genai import types

    model = os.environ.get("ART_IMAGE_MODEL", IMAGE_MODEL)
    contents: list = [_ref_part(r) for r in refs or []]
    contents.append(prompt)
    cfg = types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=aspect_ratio, image_size=image_size),
    )
    last_err = ""
    for attempt in range(retries + 1):
        t0 = time.monotonic()
        try:
            resp = _get_client().models.generate_content(model=model, contents=contents, config=cfg)
            data = _extract_image_bytes(resp)
            err = None if data else "no image in response"
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


# --------------------------------------------------------------------------- #
# Image helpers
# --------------------------------------------------------------------------- #


def raw_path(name: str) -> Path:
    return RAW / f"{name}.png"


def save_raw(name: str, img: Image.Image) -> None:
    path = raw_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")


def load_raw(name: str) -> Image.Image | None:
    path = raw_path(name)
    if not path.is_file():
        return None
    img = Image.open(path)
    img.load()
    return img


def fit_to(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Cover-fit to ``size`` (centred crop)."""
    if img.size == size:
        return img
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    nw, nh = max(tw, round(img.width * scale)), max(th, round(img.height * scale))
    big = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left, top = (nw - tw) // 2, (nh - th) // 2
    return big.crop((left, top, left + tw, top + th))


def save_webp(img: Image.Image, path: Path, *, max_bytes: int = WEBP_MAX_BYTES) -> int:
    """Lossy WebP under ``max_bytes``: quality steps down from 86; returns the quality used."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb = img.convert("RGB")
    for quality in (86, 82, 78, 74, 70, 64, 58):
        rgb.save(path, "WEBP", quality=quality, method=6)
        if path.stat().st_size <= max_bytes:
            return quality
    return quality


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def build_bg(scene: str, prompt: str, rederive: bool) -> None:
    name = f"{scene}/bg"
    raw = load_raw(name) if rederive else None
    if raw is None:
        prior = load_raw(name)
        raw = gen_image(name, (PRIOR if prior else "") + prompt, refs=[prior] if prior else None)
        save_raw(name, raw)
    q = save_webp(fit_to(raw.convert("RGB"), BG_SIZE), SCENES / scene / "art" / "bg.webp")
    print(f"  webp quality {q}")


def build_cover(scene: str, rederive: bool) -> None:
    name = f"{scene}/cover"
    raw = load_raw(name) if rederive else None
    if raw is None:
        prior = load_raw(name)
        prompt = COVERS[scene]
        if prior:
            prompt = (
                "The attached painting is the PREVIOUS version of this place: keep the same "
                "street, building and viewpoint, and apply the description below.\n\n" + prompt
            )
        raw = gen_image(name, prompt, refs=[prior] if prior else None)
        save_raw(name, raw)
    save_webp(fit_to(raw.convert("RGB"), COVER_SIZE), SCENES / scene / "art" / "cover.webp")


def build_illustration(name: str, rederive: bool) -> None:
    rel, prompt, ref_names = ILLUSTRATIONS[name]
    raw = load_raw(name) if rederive else None
    if raw is None:
        prior = load_raw(name)
        refs = [prior] if prior else []
        for ref in ref_names:
            img = load_raw(ref)
            assert img is not None, f"missing raw reference {ref}"
            refs.append(img)
        raw = gen_image(name, (ILLUSTRATION_PRIOR if prior else "") + prompt, refs=refs)
        save_raw(name, raw)
    save_webp(
        fit_to(raw.convert("RGB"), ILLUSTRATION_SIZE),
        ROOT / "content" / rel,
        max_bytes=ILLUSTRATION_MAX_BYTES,
    )


@dataclass
class Asset:
    name: str
    out: Path
    build: Callable[[bool], None]
    deps: list[str] = field(default_factory=list)  # asset names that must exist first


def _assets() -> list[Asset]:
    out: list[Asset] = []
    for scene, bg_prompt in (("bar", BAR_BG),):
        art = SCENES / scene / "art"
        bg = f"{scene}/bg"
        out.append(Asset(bg, art / "bg.webp", lambda r, s=scene, p=bg_prompt: build_bg(s, p, r)))
        out.append(
            Asset(f"{scene}/cover", art / "cover.webp", lambda r, s=scene: build_cover(s, r))
        )
    for name, (rel, _prompt, ref_names) in ILLUSTRATIONS.items():
        out.append(
            Asset(
                name,
                ROOT / "content" / rel,
                lambda r, n=name: build_illustration(n, r),
                list(ref_names),
            )
        )
    return out


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--force", nargs="*", default=[], help="assets (or scenes) to regenerate")
    ap.add_argument("--only", nargs="*", default=[], help="limit to these assets (or scenes)")
    ap.add_argument(
        "--rederive",
        nargs="*",
        default=[],
        help="rebuild these outputs from cached raw generations (no model call)",
    )
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    assets = _assets()
    by_name = {a.name: a for a in assets}
    scenes = {a.name.split("/")[0] for a in assets}

    def expand(tokens: list[str]) -> set[str]:
        names: set[str] = set()
        for tok in tokens:
            if tok in scenes:
                names |= {n for n in by_name if n.startswith(f"{tok}/")}
            elif tok in by_name:
                names.add(tok)
            else:
                ap.error(
                    f"unknown asset {tok!r}; choose from {sorted(scenes)} or {sorted(by_name)}"
                )
        return names

    force, only, rederive_set = expand(args.force), expand(args.only), expand(args.rederive)

    if args.list:
        for a in assets:
            status = "ok" if a.out.is_file() else "missing"
            print(f"{a.name:24s} {status:8s} {a.out.relative_to(ROOT)}")
        return 0

    for a in assets:
        if only and a.name not in only:
            continue
        rederive = a.name in rederive_set
        if a.out.is_file() and a.name not in force and not rederive:
            print(f"skip   {a.name} (exists)")
            continue
        missing = [d for d in a.deps if not by_name[d].out.is_file()]
        if missing:
            print(f"defer  {a.name}: missing deps {missing}")
            continue
        print(f"build  {a.name}{' (rederive)' if rederive else ''} …")
        t0 = time.monotonic()
        a.build(rederive)
        with Image.open(a.out) as im:
            size = im.size
        kb = a.out.stat().st_size / 1024
        print(f"done   {a.name} {size[0]}x{size[1]} {kb:.0f} KB in {time.monotonic() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
