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

MARKET_BG = f"""{STYLE}

FIRST-PERSON point of view of a customer standing at the counter of a street-food stall in a busy
Chinese night market, on the night of a huge football final. Eye-level, straight-on framing, 16:9.

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

MATCH-NIGHT DRESSING: the stall stands on the edge of a FAN ZONE on the night of a huge football
final. Strings of small PLAIN triangular pennants in mixed flat colours hang overhead with the
bare bulbs. At the extreme LEFT edge of the frame, beside the stock pot, a glass jar holds three
or four small PLAIN hand-flags on wooden sticks (flat red and white, no emblem) as set dressing —
nowhere near the clear stretches of the back counter.

LIGHT AND BACKGROUND: night. A string of warm bare bulbs across the top of the frame, glowing
steam. Past the left edge of the stall, far down the lane, the cool blue-white glow of a GIANT
OUTDOOR SCREEN — only a soft, blurred, overexposed rectangle of light with no readable content —
and in front of it a dense crowd as tiny soft out-of-focus silhouettes and bokeh, a few raised
arms and plain scarves. There are NO signs, NO billboards, NO banners with markings, NO
shopfronts and NO posters anywhere in the background, not even blurred ones, and no
distinguishable people.

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
    "market": f"""{STYLE}

Establishing shot, 16:9, painted with the same realistic, atmospheric, cinematic finish as a film
still (no ink outlines, no sketch lines): a narrow night-market lane in a Chinese city seen from
its entrance, late evening, just after rain, on the night of a huge football final. Street-food
stalls under dark canvas awnings recede into misty distance, strings of bare warm bulbs and small
PLAIN triangular pennants in mixed flat colours overhead, thick glowing steam rising from pots and
grills, wet ground reflecting the lights. The nearest stall on the right is the hero: a worn
stainless-steel counter, a big steaming stock pot, stacked plain bowls, bamboo steamers, one warm
hanging lamp. At the far end of the lane the FAN ZONE: the cool blue-white glow of a giant outdoor
screen — only a blurred, overexposed rectangle of light with no readable content — and a dense
crowd as soft out-of-focus silhouettes with raised arms and plain scarves. Electric, inviting.
There are NO signs, NO banners with markings, NO boards and NO posters anywhere — only plain
canvas, metal, wood, bulbs, pennants and steam. {NO_BRAND} {NO_TEXT} Full-bleed, no border.""",
}

MEI = (
    "Mei: a Chinese woman in her late twenties with a short dark chin-length bob, warm brown eyes, "
    "a bright open face, wearing a dark wool coat and a knitted FOOTBALL SCARF in plain "
    "red-and-white bar stripes (no crest, no lettering) round her neck"
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
            "lights behind her. She is the SAME WOMAN as in the second attached image (same face, "
            "same haircut); only her scarf is as described here. The white border is completely "
            "blank: no handwriting, no date. The photograph is shown almost straight-on, rotated "
            "about eight degrees, as if lying on a surface.",
            aspect="4:3",
            opaque=True,
            identity="bar/obj_photo",
        ),
        "obj_football": ObjSpec(
            "a classic leather match football — traditional pattern of white hexagons and black "
            "pentagons — scuffed and worn from real play, resting on a small turned dark-wood "
            "display stand with a shallow cup, clearly a prized keepsake. The ball is completely "
            "unbranded: no logo, no lettering, no signature, no printing of any kind.",
            aspect="1:1",
        ),
        "obj_tv": ObjSpec(
            "a wall-mounted flat-screen television with a thin black bezel on a short black "
            "swivel bracket, turned slightly so the screen faces a little to the viewer's left, "
            "seen from slightly below. The screen is ON and shows a floodlit green football "
            "pitch from a high broadcast camera angle, with its white line markings and tiny "
            "players as small specks in plain flat-coloured kits, dark stands around it. The "
            "picture has NO scoreboard, NO clock, NO caption, NO channel logo and NO graphics. "
            "The bezel has no brand mark. Only the television and its bracket, nothing else.",
            screen="blue",
            aspect="16:9",
            opaque=True,
            hanging=True,
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
            "a knitted football supporter's scarf in PLAIN red-and-white bar stripes — EXACTLY the "
            "scarf the woman wears in the second attached image, same two colours, same stripe "
            "width, same knit — with white-and-red fringed ends, loosely knotted once and hanging "
            "straight down from a single small dark iron wall hook at the very top, its two ends "
            "at slightly different lengths, as if someone had kept it aside for its owner. The "
            "scarf carries NO crest, NO lettering and NO emblem: stripes only. Only the hook and "
            "the scarf, nothing else. Seen straight-on.",
            aspect="9:16",
            hanging=True,
            identity="bar/obj_photo",
        ),
        "obj_ticket": ObjSpec(
            "a big-match ticket and its wristband: one glossy rectangular card ticket with a "
            "slight curl, its design made ONLY of bold abstract diagonal colour bands in red, "
            "white and gold with a shimmering silver holographic foil strip down one edge and a "
            "perforated stub, plus a flat woven fabric wristband in the same red and white laid "
            "as an open strip behind it. Both are held together at the top by one plain wooden "
            "clothes-peg, as if pegged up for safe keeping. There is NO text, NO digits, NO "
            "barcode, NO QR code, NO seat details, NO logo and NO emblem anywhere — where print "
            "would be there are only plain colour bands. Seen straight-on.",
            aspect="3:4",
            opaque=True,
            hanging=True,
        ),
        "obj_flag": ObjSpec(
            "a small supporter's hand-waver flag on a thin round wooden stick: a rectangular "
            "cloth flag QUARTERED in plain red and white (four plain rectangles, red top-left and "
            "bottom-right, white the other two), rippling slightly, the stick leaning about "
            "twenty degrees. The flag carries NO emblem, NO crest, NO lettering and NO stars: "
            "four flat colour fields only. Only the flag and its stick, nothing else.",
            aspect="3:4",
            hanging=True,
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
    "haircut, same striped scarf. "
)
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
    "market/ending_kickoff": (
        "scenes/market/art/ending_kickoff.webp",
        f"""{STYLE}

FIRST-PERSON point of view, 16:9: you are standing in a packed outdoor FAN ZONE in a Chinese city
at night, at the moment of kickoff of a huge football final. Ahead, above the heads of the crowd,
{_BIG_SCREEN}. Red flare smoke drifts through the floodlights and confetti hangs in the air.
{_CROWD}{_MEI_REF}She is RIGHT BESIDE the viewer in the near foreground on the right, turning
toward the viewer with a huge, delighted grin, holding out a plain plastic cup of beer to the
viewer. She is the only person whose face is clearly seen. Euphoric, electric, warm skin tones
against the cool screen light, cinematic depth of field. {NO_BRAND} {NO_TEXT} Full-bleed, no
border.""",
        ["bar/obj_photo"],
    ),
    "market/ending_late": (
        "scenes/market/art/ending_late.webp",
        f"""{STYLE}

FIRST-PERSON point of view, 16:9: you arrive late at a packed outdoor FAN ZONE in a Chinese city at
night, at the exact moment of a GOAL. The whole crowd is mid-eruption — jumping, arms thrown up,
beer spraying, confetti and red flare smoke — backlit by {_BIG_SCREEN}. {_CROWD}{_MEI_REF}She
has spotted the viewer: in the near foreground she pushes out of the crowd toward the viewer,
laughing out loud, one arm punched up in the air, the other hand holding out a bare amber beer
bottle with no label to the viewer. She is the only person whose face is clearly seen. Joyful
chaos, motion blur at the edges, warm skin tones against the cool screen light. {NO_BRAND}
{NO_TEXT} Full-bleed, no border.""",
        ["bar/obj_photo"],
    ),
    "story/title": (
        "title.webp",
        f"""{STYLE}

Title key art, 16:9, for a story set in the world of the two attached paintings (same city, same
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
        prior = load_raw(name)
        raw = gen_image(name, (PRIOR if prior else "") + prompt, refs=[prior] if prior else None)
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


def build_object(scene: str, stem: str, rederive: bool) -> None:
    name = f"{scene}/{stem}"
    spec = OBJECTS[scene][stem]
    raw = load_raw(name) if rederive else None
    if raw is None:
        style = load_raw(f"{scene}/bg")
        assert style is not None
        refs = [fit_to(style.convert("RGB"), (1600, 900))]
        if spec.identity:
            # May be the asset's own previous raw (a re-dress of the same subject).
            ident = load_raw(spec.identity)
            assert ident is not None or spec.identity == name, f"missing raw {spec.identity}"
            if ident is not None:
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


def _identity_deps(scene: str, stem: str) -> list[str]:
    ident = OBJECTS[scene][stem].identity
    return [ident] if ident and ident != f"{scene}/{stem}" else []


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
                    [bg, *_identity_deps(scene, stem)],
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
