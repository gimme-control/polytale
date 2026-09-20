"""The living scene: which face the character wears, and what visibly changed in the room.

Pure bookkeeping and geometry. Nothing here opens an image, calls a model or touches the
network: ``media/frames.py`` paints, ``server/frames.py`` schedules, and this module decides
WHAT a frame is made of.

A frame is never a new painting. It is the scene's one base plate plus a few small patches,
each confined to a rectangle derived from the character's anchor. Everything outside those
rectangles is the untouched plate, which is what keeps the background from drifting between
turns: the model is not shown it and cannot repaint it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from core.content import Anchor

# ---------------------------------------------------------------- expressions

BASE_EXPRESSION = "neutral"

#: The faces the character can wear. Small on purpose: each one is baked ONCE per plate and
#: then read from disk forever, so the set is the whole cost of the feature.
EXPRESSIONS: tuple[str, ...] = (
    BASE_EXPRESSION,
    "delighted",
    "laughing",
    "puzzled",
    "moved",
    "roaring",
    "conspiratorial",
)

#: What each face MEANS, for the game master choosing one (support language).
EXPRESSION_NOTES: dict[str, str] = {
    "neutral": "their everyday face",
    "delighted": "warm and pleased, grinning at the player",
    "laughing": "laughing out loud at something",
    "puzzled": "did not understand a word of that",
    "moved": "touched, sentimental, suddenly serious",
    "roaring": "shouting at the screen — something happened in the match",
    "conspiratorial": "leaning in, letting the player in on something",
}

#: What each face LOOKS like, for the painter.
EXPRESSION_LOOKS: dict[str, str] = {
    "delighted": (
        "open and delighted: a wide warm smile with the teeth showing, eyes crinkled at the "
        "corners, eyebrows lifted"
    ),
    "laughing": (
        "laughing out loud: head tipped back a little, mouth open in a laugh, eyes squeezed "
        "almost shut, cheeks raised"
    ),
    "puzzled": (
        "puzzled and a little amused: eyebrows drawn together, head tilted, mouth slightly "
        "open, not unkind"
    ),
    "moved": (
        "moved: the face softened, eyes bright and a little wet, mouth closed, on the edge of "
        "a smile"
    ),
    "roaring": (
        "roaring at something off to the side: mouth wide open mid-shout, eyes blazing, chin "
        "up, neck tensed"
    ),
    "conspiratorial": (
        "conspiratorial: chin lowered, one eyebrow raised, a small crooked grin, eyes narrowed "
        "and fixed on the viewer"
    ),
}

# ---------------------------------------------------------------- regions

#: Where a one-off visible beat may land. The face is not one of them: the face belongs to
#: the expression, which is cached, and a beat would fight it.
REGIONS: tuple[str, ...] = ("counter", "hands", "room_left", "room_right")

REGION_NOTES: dict[str, str] = {
    "counter": "the surface between you and them, and your own side of it",
    "hands": "their hands, arms and what they are holding",
    "room_left": "the room to their left, behind them",
    "room_right": "the room to their right, behind them",
}

FACE_REGION = "face"

MAX_BEAT_WORDS = 22
MAX_PATCHES = 8

# Half-width and the reach above and below the anchor, as fractions of the plate. The anchor
# is the character's mouth, so the box runs from above the hairline to below the collar.
_FACE_HALF_WIDTH = 0.135
_FACE_ABOVE = 0.165
_FACE_BELOW = 0.175


class Box(BaseModel):
    """A rectangle in plate fractions, origin top-left."""

    left: float
    top: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height


def _box(left: float, top: float, right: float, bottom: float) -> Box:
    left, right = max(0.0, min(1.0, left)), max(0.0, min(1.0, right))
    top, bottom = max(0.0, min(1.0, top)), max(0.0, min(1.0, bottom))
    return Box(left=left, top=top, width=max(0.02, right - left),
               height=max(0.02, bottom - top))


def face_box(anchor: Anchor) -> Box:
    """Head and shoulders around the character's anchor (their mouth)."""
    return _box(anchor.x - _FACE_HALF_WIDTH, anchor.y - _FACE_ABOVE,
                anchor.x + _FACE_HALF_WIDTH, anchor.y + _FACE_BELOW)


def region_box(region: str, anchor: Anchor) -> Box:
    """The rectangle a beat region owns. Unknown regions raise; callers validate first.

    ``counter``, ``room_left`` and ``room_right`` never overlap the face box, so a beat
    cannot fight the cached expression. ``hands`` may graze its lower edge, and the face is
    always drawn last.
    """
    if region == FACE_REGION:
        return face_box(anchor)
    if region == "counter":
        return _box(0.06, 0.64, 0.94, 1.0)
    if region == "hands":
        return _box(0.22, anchor.y + 0.13, 0.78, anchor.y + 0.52)
    if region == "room_left":
        return _box(0.0, 0.0, anchor.x - _FACE_HALF_WIDTH - 0.02, 0.72)
    if region == "room_right":
        return _box(anchor.x + _FACE_HALF_WIDTH + 0.02, 0.0, 1.0, 0.72)
    raise ValueError(f"unknown region {region!r}")


# ---------------------------------------------------------------- the frame


class FramePatch(BaseModel):
    """One committed beat: a short description of what changed, and where it shows."""

    region: str
    change: str


LayerKind = Literal["expression", "beat"]


@dataclass(frozen=True)
class FrameLayer:
    """One patch to paint and composite. ``id`` is content-addressed, so it is also its URL."""

    id: str
    kind: LayerKind
    region: str
    box: Box
    #: the expression name, or the beat's description
    value: str


@dataclass(frozen=True)
class FramePlan:
    """Everything needed to paint the frame the player should be looking at."""

    key: str
    scene_id: str
    expression: str
    layers: tuple[FrameLayer, ...] = field(default=())

    @property
    def empty(self) -> bool:
        return not self.layers

    def layer(self, layer_id: str) -> FrameLayer | None:
        return next((one for one in self.layers if one.id == layer_id), None)


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def build_plan(
    *, scene_id: str, plate_sig: str, anchor: Anchor, expression: str,
    patches: list[FramePatch] | tuple[FramePatch, ...] = (),
) -> FramePlan:
    """The layers for one frame, in paint order: beats as they happened, then the face.

    A beat's id folds in every beat before it, because a beat is painted onto the frame as it
    stood — so two runs that share a prefix share those bakes, and a later beat never reuses a
    patch baked over different pixels. The expression's id folds in only the plate, because it
    is always painted from the plate's own face box: baked once per plate, read from disk ever
    after.
    """
    layers: list[FrameLayer] = []
    trail = plate_sig
    for patch in patches:
        trail = _hash(trail, patch.region, patch.change)
        layers.append(FrameLayer(
            id=f"beat_{trail}", kind="beat", region=patch.region,
            box=region_box(patch.region, anchor), value=patch.change,
        ))
    if expression != BASE_EXPRESSION and expression in EXPRESSIONS:
        layers.append(FrameLayer(
            id=f"expr_{_hash(plate_sig, expression)}", kind="expression", region=FACE_REGION,
            box=face_box(anchor), value=expression,
        ))
    key = _hash(plate_sig, *(one.id for one in layers)) if layers else f"plate_{plate_sig}"
    return FramePlan(key=key, scene_id=scene_id, expression=expression, layers=tuple(layers))


class FrameLayerView(BaseModel):
    """One patch as the client draws it: an image and where it sits on the plate."""

    id: str
    url: str
    left: float
    top: float
    width: float
    height: float


class FrameView(BaseModel):
    """The frame to show. ``layers`` empty means the base plate, exactly as it is."""

    key: str
    expression: str
    layers: list[FrameLayerView] = Field(default_factory=list)


def frame_layer_url(journey_id: str, layer_id: str) -> str:
    """Relative patch URL; the client appends the journey token."""
    return f"/api/journeys/{journey_id}/frame/{layer_id}"


def frame_view(journey_id: str, plan: FramePlan) -> FrameView:
    return FrameView(
        key=plan.key,
        expression=plan.expression,
        layers=[
            FrameLayerView(
                id=one.id, url=frame_layer_url(journey_id, one.id),
                left=one.box.left, top=one.box.top,
                width=one.box.width, height=one.box.height,
            )
            for one in plan.layers
        ],
    )
