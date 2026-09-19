"""Offline art pipeline for Polytale scenes (`content/scenes/<id>/art/`).

Idempotent: every asset is skipped when its output already exists, unless named with
``--force``. Art is generated here once and committed; nothing is drawn at runtime.

    python scripts/generate_art.py                       # make whatever is missing
    python scripts/generate_art.py --list                # assets + status
    python scripts/generate_art.py --only bar            # a whole scene ...
    python scripts/generate_art.py --only bar/obj_beer   # ... or single assets
    python scripts/generate_art.py --force bar/bg_puzzled
    python scripts/generate_art.py --rederive bar/obj_water   # re-key from cached raw, no model call

Asset names are ``<scene>/<file stem>``. ``--force`` / ``--rederive`` only touch the assets they
name; ``--only`` limits what is considered at all.

Raw model outputs (the PNG masters) live in ``cache/art_raw/<scene>/`` (gitignored) and every
image-model call is appended to ``cache/art_raw/calls.jsonl``.

Mood backgrounds need ``npc_region`` in the scene's ``LAYOUT.json`` (the character's upper-body
box, measured by looking at ``bg``): the edited frame is blended into the neutral frame only
inside that feathered box, so the rest of the image is the same pixels and a crossfade cannot
flicker. Until the region exists those assets are deferred.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.matte import (  # noqa: E402
    drop_faint_islands,
    drop_small_islands,
    soft_key_cutout,
    solidify,
    trim_to_subject,
)

SCENES = ROOT / "content" / "scenes"
RAW = ROOT / "cache" / "art_raw"
CALLS_LOG = RAW / "calls.jsonl"

IMAGE_MODEL = "gemini-3-pro-image"
BG_SIZE = (2400, 1350)
COVER_SIZE = (1920, 1080)
WEBP_MAX_BYTES = 600 * 1024
OBJ_MAX_SIDE = 768

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


def _bg_tail(who: str) -> str:
    return (
        f"Exactly ONE person in the image: {who}. No other people, no customers, no reflections "
        f"of people, no hands or body of the viewer. {NO_TEXT} Full-bleed, no border, no frame."
    )


BAR_BG = f"""{STYLE}

FIRST-PERSON point of view of a customer sitting on a bar stool at the counter of a small,
late-night neighbourhood bar in a Chinese city. Eye-level, straight-on, symmetrical-ish framing,
16:9.

THE BARTENDER: a Chinese man in his mid-40s standing directly behind the counter, framed
waist-up, placed at the horizontal CENTRE of the image. Short dark hair with a little grey, light
stubble, a dark charcoal work shirt with the sleeves rolled to the elbows and a dark apron. Calm,
wry, self-possessed. He looks straight at the viewer with a NEUTRAL, relaxed expression, mouth
closed. Both hands rest flat on the far edge of the counter in front of him, empty.

THE BACK WALL behind him: dark wood panelling with ONE long, simple wooden shelf running the full
width of the image at the height of his shoulders, softly lit from above by a hidden warm light
strip. IMPORTANT: the shelf top is almost completely BARE — long clear empty stretches of shelf
to the LEFT and to the RIGHT of the bartender, where props will be added later. Only at the
extreme left end and extreme right end of the shelf is there a small cluster of generic dark
unlabeled bottles and glassware. Nothing on the shelf near the bartender. Above, out of focus, a
second shelf in shadow with a few dark glasses.

THE NEAR COUNTER: a dark, polished, worn wooden bar counter fills the bottom 30% of the frame,
running edge to edge, seen from slightly above. Its surface is completely EMPTY — no glasses, no
coasters, no napkins, no objects at all — and evenly, softly lit so that props can be placed on
it later.

LIGHT: night. Warm tungsten practical lamps, a soft pool of light on the counter, and a faint
magenta-and-teal neon glow spilling in from the street through a window at the far right edge,
without any readable sign.

{_bg_tail("the bartender")}"""

MARKET_BG = f"""{STYLE}

FIRST-PERSON point of view of a customer standing at the counter of a street-food stall in a busy
Chinese night market. Eye-level, straight-on framing, 16:9.

THE VENDOR: a Chinese woman in her mid-50s standing directly behind the stall counter, framed
waist-up, placed at the horizontal CENTRE of the image. Hair tied back, a few grey strands,
weathered capable face, sleeves pushed up, a plain dark indigo apron over a simple shirt. Sharp,
amused, seen-it-all. She looks straight at the viewer with a NEUTRAL, composed expression, mouth
closed. Both hands rest on the far edge of the counter in front of her, empty.

THE STALL: directly behind her, running the FULL WIDTH of the image at the height of her waist
and elbows, is one long stainless-steel back counter (a prep table), warmly lit from above by a
hidden light strip under a dark canvas awning, against a plain dark corrugated-metal back wall.
IMPORTANT: the top of this back counter is almost completely BARE — long clear empty stretches of
steel to the LEFT and to the RIGHT of the vendor, where props will be added later. Only at the
extreme left edge of the image is there a big steaming stock pot (partly cropped by the frame),
its steam rising and catching the light, and only at the extreme right edge a small stack of
plain bamboo steamer baskets. Nothing else on the back counter, nothing near the vendor. Her arms
are NOT spread wide: her hands rest on the near counter close together in front of her body.

THE NEAR COUNTER: a worn stainless-steel stall counter with a wooden front edge fills the bottom
30% of the frame, running edge to edge, seen from slightly above. Its surface is completely
EMPTY — no bowls, no bottles, no chopsticks, no objects at all — and evenly, softly lit so that
props can be placed on it later.

LIGHT: night. A string of warm bare bulbs across the top of the frame, glowing steam. Past the
edges of the stall the market is only darkness with soft round out-of-focus bokeh lights. There
are NO signs, NO billboards, NO banners, NO shopfronts and NO posters anywhere in the background,
not even blurred ones, and no distinguishable people.

{_bg_tail("the vendor")}"""


def _mood_prompt(who: str, change: str) -> str:
    return f"""Edit the attached painting. Keep it IDENTICAL in every respect — same camera, same
framing, same person in exactly the same position and same scale, same clothes, same background,
same counter, same lighting, same colours, same brushwork — and change ONLY {who}'s facial
expression and upper-body gesture:

{change}

{who.capitalize()} stays the same person with the same face, hair and clothing, in the same
place. Do not move, add or remove any object. The counter stays empty. Still exactly one person.
{NO_TEXT}"""


MOODS = {
    "bar": {
        "pleased": _mood_prompt(
            "the bartender",
            "PLEASED — a small, genuine, warm closed-mouth smile reaching his eyes, chin dipped in "
            "a slight approving nod. Hands stay resting on the counter.",
        ),
        "puzzled": _mood_prompt(
            "the bartender",
            "PUZZLED — head tilted slightly to one side, one eyebrow raised, lips slightly pursed, "
            "a questioning look at the viewer; one hand raised in FRONT OF HIS OWN CHEST, elbow "
            "tucked in against his side, palm up and fingers half-open in a small 'sorry, what?' "
            "gesture. That hand stays entirely inside the outline of his torso and apron — it "
            "does NOT reach out sideways past his body. The other hand stays on the counter.",
        ),
    },
    "market": {
        "pleased": _mood_prompt(
            "the vendor",
            "PLEASED — a small, genuine, amused closed-mouth smile with crinkled eyes, chin dipped "
            "in a slight approving nod. Hands stay resting on the counter.",
        ),
        "puzzled": _mood_prompt(
            "the vendor",
            "PUZZLED — head tilted slightly to one side, one eyebrow raised, a sceptical "
            "questioning look at the viewer; one hand raised in FRONT OF HER OWN CHEST, elbow tucked in against "
            "her side, palm up and fingers half-open in a small 'what do you mean?' gesture. That "
            "hand stays entirely inside the outline of her torso and apron — it does NOT reach "
            "out sideways past her body. The other hand stays on the counter.",
        ),
    },
}

COVERS = {
    "bar": f"""{STYLE}

Establishing shot, 16:9: the exterior doorway of a small neighbourhood corner bar on a narrow
side street in a Chinese city, late at night, just after rain. A dark wood-and-glass door and one
steamed-up window glow warm amber from inside, where bottles and a bar counter are only vague
soft shapes. The wet asphalt and paving reflect the warm glow and a little magenta-and-teal
neon from an ABSTRACT neon shape (a simple line or ring, not a letter or word) above the door.
A parked bicycle, a drainpipe, tangled overhead cables, light mist. Inviting, quiet, a little
lonely. Nobody in the street. {NO_TEXT} Full-bleed, no border.""",
    "market": f"""{STYLE}

Establishing shot, 16:9, painted with the same realistic, atmospheric, cinematic finish as a film
still (no ink outlines, no sketch lines): a narrow night-market lane in a Chinese city seen from
its entrance, late evening, just after rain. Street-food stalls under dark canvas awnings recede
into misty distance, strings of bare warm bulbs overhead, thick glowing steam rising from pots
and grills, wet ground reflecting the lights. The nearest stall on the right is the hero: a worn
stainless-steel counter, a big steaming stock pot, stacked plain bowls, bamboo steamers, one warm
hanging lamp. Distant shoppers are only soft out-of-focus silhouettes deep in the haze.
Inviting, lively, a little melancholy. There are NO signs, NO banners, NO boards, NO posters and
NO lantern decorations with markings anywhere — only plain canvas, metal, wood, bulbs and steam.
{NO_TEXT} Full-bleed, no border.""",
}


MEI = (
    "Mei: a Chinese woman in her late twenties with a short dark chin-length bob, warm brown eyes, "
    "a bright open face, wearing a dark wool coat and a chunky knitted scarf in a deep, dark wine-crimson (burgundy) red"
)


def _obj_prompt(subject: str, screen: str, *, hanging: bool = False) -> str:
    shadow = (
        "The prop hangs in mid-air: NO shadow anywhere, no floor."
        if hanging
        else "A small, soft, dark contact shadow directly underneath the prop only."
    )
    return f"""{STYLE}

A single isolated prop for a narrative game, painted in EXACTLY the style, materials and warm
low-key lighting of the attached scene (use the attachment ONLY as a style and lighting reference
— do not paint the scene or any person).

THE PROP: {subject}

View: as seen by someone seated at the counter — three-quarter view from slightly above (about 15
degrees), upright, not tilted. The whole prop is visible, centred, with generous empty margin on
all sides. Lit from above and slightly in front by a warm lamp, with a soft cool rim light. {shadow}

BACKGROUND: a perfectly flat, uniform, evenly lit {SCREEN[screen]} studio screen filling the whole
frame edge to edge. No floor line, no table, no gradient, no vignette, no texture, no reflection
of the prop, no other objects. The prop itself contains no {screen} colour at all.

{NO_TEXT}"""


@dataclass(frozen=True)
class ObjSpec:
    subject: str
    screen: str = "green"
    aspect: str = "1:1"
    opaque: bool = False  # solid prop (photo, card): restore key-hued interior pixels
    hanging: bool = False  # hangs in the air: no floor shadow (any painted one is dropped)
    identity: str = ""  # raw asset whose subject must be matched (sent as a second reference)


OBJECTS: dict[str, dict[str, ObjSpec]] = {
    "bar": {
        "obj_beer": ObjSpec(
            "a cold 330 ml beer bottle of dark AMBER-BROWN glass, full, crown cap on, completely "
            "unlabeled bare glass (no label, no neck foil, no embossing), beaded with fine "
            "condensation droplets, a few running down.",
            aspect="9:16",
        ),
        "obj_water": ObjSpec(
            "a tall, plain, straight-sided clear highball glass filled almost to the top with "
            "still water, no ice, no garnish, no straw; thick glass base, subtle highlights and "
            "refraction.",
            aspect="9:16",
        ),
        "obj_tea": ObjSpec(
            "a small traditional Chinese teapot of dark reddish-brown unglazed Yixing clay with "
            "its lid on, and ONE small matching handle-less clay teacup standing beside it, "
            "filled with amber tea, a faint wisp of steam. Plain surfaces with no engraving.",
            aspect="4:3",
        ),
        "obj_menu": ObjSpec(
            "a CLOSED menu booklet bound in worn dark oxblood-brown leather with stitched edges "
            "and brass corner protectors, standing upright and slightly open like a tent so it "
            "stands by itself. The cover is completely blank leather — no title, no emblem, no "
            "embossing.",
            aspect="3:4",
        ),
        "obj_photo": ObjSpec(
            "a slightly worn instant-camera (polaroid-style) photograph: thick WHITE paper "
            "border, wider at the bottom, softly scuffed corners, one faint crease. The glossy "
            f"picture area shows {MEI}, photographed from the chest up, head thrown back a little, "
            "laughing with real joy, at night, with soft out-of-focus warm amber and red city "
            "lights behind her. The white border is completely blank: no handwriting, no date. "
            "The photograph is shown almost straight-on, rotated about eight degrees, as if lying "
            "on a surface.",
            aspect="4:3",
            opaque=True,
        ),
        "obj_tab": ObjSpec(
            "an unpaid bar tab: a small upright brass bill spike on a round brass base, with "
            "three or four small off-white paper slips impaled on it, the top slip curling "
            "slightly. The slips carry only a few rows of loose wavy pencil scribble — like a "
            "seismograph trace — that are NOT letters, NOT characters and NOT digits. No stamp, "
            "no printed header.",
            aspect="3:4",
        ),
        "obj_baijiu": ObjSpec(
            "a very small, thick-walled clear shot glass filled to the brim with crystal-clear "
            "baijiu liquor, standing beside a small squat WHITE glazed ceramic liquor bottle with "
            "a narrow neck and a plain dark red cloth-wrapped stopper. The bottle is about three "
            "times the height of the glass. Completely unlabeled: bare white glaze, no label, no "
            "seal, no markings.",
            aspect="1:1",
        ),
        "obj_money": ObjSpec(
            "a small loose stack of four used red-and-pink paper banknotes lying flat, fanned "
            "slightly, soft and creased. This is an ABSTRACT PROP currency: the printed design on "
            "every note is ONLY a loose impressionistic wash of red and rose ornamental swirls "
            "and fine wavy guilloche lines, like an unfinished painting. The corners and centre "
            "where numerals or a portrait would normally be are plain pale blank paper. There "
            "are NO numerals, NO digits, NO zeros, NO characters, NO portrait, NO seal and NO "
            "legible marks of any kind on any note.",
            aspect="4:3",
        ),
    },
    "market": {
        "obj_noodles": ObjSpec(
            "a deep plain off-white ceramic bowl with a dark rim, full of hand-pulled wheat "
            "noodles in a rich brown beef broth with slices of beef, a halved soy egg, chopped "
            "scallions and a little chili oil, steam rising; a pair of plain dark wooden "
            "chopsticks resting across the rim. The bowl has no pattern and no blue decoration.",
            screen="blue",
            aspect="4:3",
        ),
        "obj_dumplings": ObjSpec(
            "a plain round off-white ceramic plate with a dark rim holding eight pan-fried "
            "crescent dumplings (potstickers) with golden-brown crisp bottoms, glistening, a "
            "pinch of chopped scallion on top, a faint wisp of steam. The plate has no pattern "
            "and no blue decoration.",
            screen="blue",
            aspect="4:3",
        ),
        "obj_scarf": ObjSpec(
            "a chunky knitted wool scarf in a deep, dark WINE-CRIMSON / burgundy red (around #8a1f2b; "
            "darker and cooler than tomato or brick red, never orange) — EXACTLY the scarf the woman wears "
            "in the second attached image, same colour and same knit — loosely knotted once and "
            "hanging straight down from a single small dark iron wall hook at the very top, its "
            "two fringed ends hanging at slightly different lengths, as if someone had kept it "
            "aside for its owner. Only the hook and the scarf, nothing else. Seen straight-on.",
            aspect="9:16",
            hanging=True,
            identity="bar/obj_photo",
        ),
        "obj_chili": ObjSpec(
            "a squat clear glass jar, lid off, three-quarters full of deep red chili oil with "
            "dark chili flakes and seeds settled in it, a small metal spoon standing in the jar. "
            "Completely unlabeled bare glass.",
            aspect="3:4",
        ),
    },
}

# Full-frame story illustrations: (output path relative to content/, prompt, reference raws).
_MEI_REF = (
    f"THE FRIEND is {MEI} — she is the woman in the attached instant photo: same face, same "
    "haircut, same red scarf. "
)
ILLUSTRATIONS: dict[str, tuple[str, str, list[str]]] = {
    "market/ending_reunited": (
        "scenes/market/art/ending_reunited.webp",
        f"""{STYLE}

FIRST-PERSON point of view, 16:9: you have just run onto an underground metro platform late at
night. The LAST TRAIN stands at the platform on the right, its doors open, warm golden light
spilling out of the carriage across the polished platform tiles. It is INDOORS and dry: no
rain, no falling water, no streaks in the air. {_MEI_REF}She stands a few
metres ahead by the open doors, mid-turn toward the viewer, with a huge relieved, delighted grin,
one arm raised high in a wave, scarf swinging. She is the only person in the image: the carriage
behind her is completely EMPTY (bare seats, nobody inside) and the platform is deserted. There is
NO route map, NO line diagram and NO station strip anywhere — the panels above the platform doors
are plain brushed metal. Cool fluorescent platform light against the warm train glow, motion and joy, cinematic depth of field.
All platform signs, screens, route maps and the train's destination display are blank glowing
panels or abstract colour. {NO_TEXT} Full-bleed, no border.""",
        ["bar/obj_photo"],
    ),
    "market/ending_late": (
        "scenes/market/art/ending_late.webp",
        f"""{STYLE}

FIRST-PERSON point of view, 16:9: the same underground metro platform late at night, now EMPTY
and quiet. On the left the dark tunnel mouth, with the two red tail lights of the departing last
train shrinking into the darkness. {_MEI_REF}She sits on a plain metal platform bench on the
right, turned toward the viewer, shoulders lifted in a shrug, palms up, with a wry, warm,
lopsided smile — 'well, we missed it'. Beside her on the bench sit TWO steaming takeaway paper
bowls with wooden chopsticks laid across them. She is the only person in the image. Cool
fluorescent light, a warm pool of light on the bench, steam catching it. Bittersweet but warm.
All platform signs, screens and route maps are blank glowing panels or abstract colour.
{NO_TEXT} Full-bleed, no border.""",
        ["bar/obj_photo"],
    ),
    "story/title": (
        "title.webp",
        f"""{STYLE}

Title key art, 16:9, for a story set in the world of the two attached paintings (same city, same
finish, same palette): a rain-wet narrow street in a Chinese city late at night, seen from
street level. In the middle distance an ELEVATED RAILWAY crosses the frame on concrete pillars,
and a lit metro train is crossing it, its row of warm windows streaking slightly with motion. On
the right side of the street, the warm amber glow of a small corner bar's fogged window and door
spills onto the pavement. Far down the lane on the left, tiny strings of warm market bulbs and
rising steam. Wet asphalt reflections, tangled overhead cables, mist. Nobody in the street.
COMPOSITION: the top-left third of the image is calm, empty, dark night sky with soft mist and
no cables, no buildings and no detail, reserved for a title. {NO_TEXT} Full-bleed, no border.""",
        ["bar/cover", "market/cover"],
    ),
}
ILLUSTRATION_SIZE = (1920, 1080)
ILLUSTRATION_MAX_BYTES = 350 * 1024

# Market reuses the bar's files byte-for-byte so recall is visually identical.
SHARED = {"market": ["obj_beer", "obj_water", "obj_money", "obj_photo"]}

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


def region_mask(size: tuple[int, int], region: dict) -> Image.Image:
    """Feathered rounded box (plate fractions x0,y0,x1,y1) -> L mask."""
    w, h = size
    box = (region["x0"] * w, region["y0"] * h, region["x1"] * w, region["y1"] * h)
    feather = 0.035 * h
    mask = Image.new("L", size, 0)
    inset = feather * 1.2
    ImageDraw.Draw(mask).rounded_rectangle(
        (box[0] + inset, box[1] + inset, box[2] - inset, box[3] - inset),
        radius=feather * 2,
        fill=255,
    )
    return mask.filter(ImageFilter.GaussianBlur(feather * 0.5))


def match_colour(edit: Image.Image, base: Image.Image, keep: Image.Image) -> Image.Image:
    """Per-channel gain/offset so ``edit`` matches ``base`` where ``keep`` (mask) is 0.

    Edits drift a few levels globally; matching on the untouched area removes any
    tone step along the blend seam.
    """
    e = np.asarray(edit.convert("RGB")).astype(np.float32)
    b = np.asarray(base.convert("RGB")).astype(np.float32)
    outside = np.asarray(keep) < 8
    out = e.copy()
    for c in range(3):
        es, bs = e[..., c][outside], b[..., c][outside]
        gain = float(bs.std() / max(es.std(), 1e-3))
        out[..., c] = (e[..., c] - es.mean()) * gain + bs.mean()
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), mode="RGB")


def load_layout(scene: str) -> dict:
    path = SCENES / scene / "art" / "LAYOUT.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def build_bg(scene: str, prompt: str, rederive: bool) -> None:
    name = f"{scene}/bg"
    raw = load_raw(name) if rederive else None
    if raw is None:
        raw = gen_image(name, prompt)
        save_raw(name, raw)
    q = save_webp(fit_to(raw.convert("RGB"), BG_SIZE), SCENES / scene / "art" / "bg.webp")
    print(f"  webp quality {q}")


def build_mood(scene: str, mood: str, rederive: bool) -> None:
    name = f"{scene}/bg_{mood}"
    base = load_raw(f"{scene}/bg")
    assert base is not None
    base = base.convert("RGB")
    region = load_layout(scene)["npc_region"]
    raw = load_raw(name) if rederive else None
    if raw is None:
        raw = gen_image(name, MOODS[scene][mood], refs=[base])
        save_raw(name, raw)
    # Blend at the master's native size (no re-crop => no misregistration), then
    # apply the same fit as bg.webp.
    edit = fit_to(raw.convert("RGB"), base.size)
    mask = region_mask(base.size, region)
    merged = Image.composite(match_colour(edit, base, mask), base, mask)
    save_webp(fit_to(merged, BG_SIZE), SCENES / scene / "art" / f"bg_{mood}.webp")


def build_cover(scene: str, rederive: bool) -> None:
    name = f"{scene}/cover"
    raw = load_raw(name) if rederive else None
    if raw is None:
        raw = gen_image(name, COVERS[scene])
        save_raw(name, raw)
    save_webp(fit_to(raw.convert("RGB"), COVER_SIZE), SCENES / scene / "art" / "cover.webp")


def build_object(scene: str, stem: str, rederive: bool) -> None:
    name = f"{scene}/{stem}"
    spec = OBJECTS[scene][stem]
    raw = load_raw(name) if rederive else None
    if raw is None:
        style = load_raw(f"{scene}/bg")
        assert style is not None
        refs = [fit_to(style.convert("RGB"), (1600, 900))]
        if spec.identity:
            ident = load_raw(spec.identity)
            assert ident is not None
            refs.append(ident)
        raw = gen_image(
            name,
            _obj_prompt(spec.subject, spec.screen, hanging=spec.hanging),
            refs=refs,
            aspect_ratio=spec.aspect,
        )
        save_raw(name, raw)
    keyed = soft_key_cutout(raw)
    if spec.opaque:
        keyed = solidify(keyed, raw)
    # A hanging prop is one connected thing; a floor shadow painted anyway is a separate island.
    cut = drop_small_islands(drop_faint_islands(keyed), min_frac=0.5 if spec.hanging else 0.01)
    cut = trim_to_subject(cut, alpha_floor=10)
    scale = OBJ_MAX_SIDE / max(cut.size)
    if scale < 1.0:
        cut = cut.resize(
            (max(1, round(cut.width * scale)), max(1, round(cut.height * scale))),
            Image.Resampling.LANCZOS,
        )
    out = SCENES / scene / "art" / f"{stem}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cut.save(out, "PNG", optimize=True)


def build_illustration(name: str, rederive: bool) -> None:
    rel, prompt, ref_names = ILLUSTRATIONS[name]
    raw = load_raw(name) if rederive else None
    if raw is None:
        refs = []
        for ref in ref_names:
            img = load_raw(ref)
            assert img is not None, f"missing raw reference {ref}"
            refs.append(img)
        raw = gen_image(name, prompt, refs=refs)
        save_raw(name, raw)
    save_webp(
        fit_to(raw.convert("RGB"), ILLUSTRATION_SIZE),
        ROOT / "content" / rel,
        max_bytes=ILLUSTRATION_MAX_BYTES,
    )


def copy_shared(scene: str, stem: str) -> None:
    out = SCENES / scene / "art" / f"{stem}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCENES / "bar" / "art" / f"{stem}.png", out)


@dataclass
class Asset:
    name: str
    out: Path
    build: Callable[[bool], None]
    deps: list[str] = field(default_factory=list)  # asset names that must exist first
    needs_region: bool = False


def _assets() -> list[Asset]:
    out: list[Asset] = []
    for scene, bg_prompt in (("bar", BAR_BG), ("market", MARKET_BG)):
        art = SCENES / scene / "art"
        bg = f"{scene}/bg"
        out.append(Asset(bg, art / "bg.webp", lambda r, s=scene, p=bg_prompt: build_bg(s, p, r)))
        for mood in MOODS[scene]:
            out.append(
                Asset(
                    f"{scene}/bg_{mood}",
                    art / f"bg_{mood}.webp",
                    lambda r, s=scene, m=mood: build_mood(s, m, r),
                    [bg],
                    needs_region=True,
                )
            )
        out.append(
            Asset(f"{scene}/cover", art / "cover.webp", lambda r, s=scene: build_cover(s, r))
        )
        for stem in OBJECTS[scene]:
            out.append(
                Asset(
                    f"{scene}/{stem}",
                    art / f"{stem}.png",
                    lambda r, s=scene, st=stem: build_object(s, st, r),
                    [
                        bg,
                        *([OBJECTS[scene][stem].identity] if OBJECTS[scene][stem].identity else []),
                    ],
                )
            )
        for stem in SHARED.get(scene, []):
            out.append(
                Asset(
                    f"{scene}/{stem}",
                    art / f"{stem}.png",
                    lambda r, s=scene, st=stem: copy_shared(s, st),
                    [f"bar/{stem}"],
                )
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
        if a.needs_region and "npc_region" not in load_layout(a.name.split("/")[0]):
            print(f"defer  {a.name}: LAYOUT.json has no npc_region yet")
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
