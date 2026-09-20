"""The painter: bakes one small patch of the scene plate with the image-edit model.

The model never sees the whole plate and never returns it. It is handed ONE cropped
rectangle and asked for that rectangle back; the result is pasted into a transparent canvas
the size of the plate's patch box and written to disk as a cutout. The client lays that
cutout over the untouched plate, so every pixel outside the box is not merely unchanged but
never re-sent — which is what stops the background drifting from frame to frame.

Bakes are cached under ``cache/frames/<scene_id>/<layer id>.webp``. A layer id folds in a
hash of the plate's bytes, so a new base plate is simply a new set of ids and the old cutouts
are never served again.

``bake_plan`` takes its one network call as an argument (``edit=``), so every test drives the
whole pipeline without spending a credit.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from core.frames import EXPRESSION_LOOKS, FrameLayer, FramePlan

log = logging.getLogger("polytale.frames")

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "cache" / "frames"

DEFAULT_MODEL = "gemini-3.1-flash-image"
DEFAULT_TIMEOUT_S = 30.0
#: Ask for a small output: this is one rectangle of a plate, and speed is the point.
EDIT_IMAGE_SIZE = "1K"
#: Aspect ratios the image model accepts; the crop is matched to the nearest one.
ASPECTS: tuple[tuple[str, float], ...] = (
    ("21:9", 21 / 9), ("16:9", 16 / 9), ("3:2", 3 / 2), ("4:3", 4 / 3), ("5:4", 5 / 4),
    ("1:1", 1.0), ("4:5", 4 / 5), ("3:4", 3 / 4), ("2:3", 2 / 3), ("9:16", 9 / 16),
)
#: Soft edge on every patch, as a fraction of its shortest side: it hides the seam where the
#: repaint meets the plate without touching anything outside the box.
FEATHER_FRACTION = 0.05
MIN_FEATHER_PX = 6

WEBP_QUALITY = 90

#: A patch that could not be painted. Fully transparent: the plate shows through unchanged.
TRANSPARENT_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


class FrameError(RuntimeError):
    """The patch could not be painted. Callers fall back to the plate."""


# ---------------------------------------------------------------- configuration


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def frames_enabled() -> bool:
    """Whether the scene reacts at all (env ``POLYTALE_FRAMES``; on by default)."""
    return _flag("POLYTALE_FRAMES", True)


def frame_model() -> str:
    """The image-edit model. A fast flash image model, not the slow art-pipeline one."""
    for name in ("POLYTALE_FRAME_MODEL", "GEMINI_IMAGE_MODEL"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return DEFAULT_MODEL


def frame_timeout_s() -> float:
    raw = os.environ.get("POLYTALE_FRAME_TIMEOUT_S", "").strip()
    try:
        return max(1.0, float(raw)) if raw else DEFAULT_TIMEOUT_S
    except ValueError:
        return DEFAULT_TIMEOUT_S


# ---------------------------------------------------------------- plate identity


_signatures: dict[Path, tuple[tuple[float, int], str]] = {}


def plate_signature(plate: Path) -> str:
    """Short hash of the plate's bytes, memoised by mtime and size.

    Every layer id is keyed to this, so repainting the scene's art invalidates every cached
    patch at once and nothing stale is ever composited onto the new plate.
    """
    plate = Path(plate)
    stat = plate.stat()
    stamp = (stat.st_mtime, stat.st_size)
    cached = _signatures.get(plate)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    digest = hashlib.sha256(plate.read_bytes()).hexdigest()[:16]
    _signatures[plate] = (stamp, digest)
    return digest


# ---------------------------------------------------------------- instructions


KEEP = (
    "This image is one cropped rectangle out of a larger painted scene in a narrative game. "
    "Return that SAME rectangle, repainted, at the same framing and scale. Everything must "
    "stay identical except the one change named below: the same person with the same face "
    "shape, age, hair, skin and build, the same clothing, the same objects in the same "
    "places, the same camera, the same painting style, the same colours and lighting, and "
    "the same content touching each of the four edges so it still lines up with the rest of "
    "the painting. Do not zoom, crop, pan or reframe. Do not add text, letters, numbers, "
    "logos or watermarks."
)


def instruction_for(layer: FrameLayer) -> str:
    """What the painter is asked to change in this rectangle."""
    if layer.kind == "expression":
        look = EXPRESSION_LOOKS.get(layer.value, layer.value)
        return (
            f"{KEEP} Do not add or remove a person.\n\nTHE ONE CHANGE: the person's facial "
            f"expression is now {look}. Their head stays in exactly the same position at the "
            "same size and angle; only the face itself changes."
        )
    return (
        f"{KEEP}\n\nTHE ONE CHANGE: {layer.value.rstrip('.')}. Show it plainly and keep it "
        "inside this rectangle. Nothing else in the rectangle moves."
    )


# ---------------------------------------------------------------- image helpers


def pixel_box(box_left: float, box_top: float, box_width: float, box_height: float,
              size: tuple[int, int]) -> tuple[int, int, int, int]:
    """A fractional box as whole pixels inside ``size``, never empty, never out of bounds."""
    width, height = size
    left = max(0, min(width - 1, round(box_left * width)))
    top = max(0, min(height - 1, round(box_top * height)))
    right = max(left + 1, min(width, round((box_left + box_width) * width)))
    bottom = max(top + 1, min(height, round((box_top + box_height) * height)))
    return left, top, right, bottom


def closest_aspect(width: int, height: int) -> str:
    ratio = width / max(1, height)
    return min(ASPECTS, key=lambda item: abs(item[1] - ratio))[0]


def cover_fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale to fill ``size`` and centre-crop, so a returned aspect wobble costs the edges."""
    if image.size == size:
        return image
    target_w, target_h = size
    scale = max(target_w / image.width, target_h / image.height)
    wide, tall = max(target_w, round(image.width * scale)), max(target_h, round(image.height * scale))
    grown = image.resize((wide, tall), Image.Resampling.LANCZOS)
    left, top = (wide - target_w) // 2, (tall - target_h) // 2
    return grown.crop((left, top, left + target_w, top + target_h))


def feather_mask(size: tuple[int, int]) -> Image.Image:
    """An alpha mask that is solid in the middle and fades out at the rectangle's border."""
    width, height = size
    pad = max(MIN_FEATHER_PX, round(min(width, height) * FEATHER_FRACTION))
    pad = min(pad, max(1, min(width, height) // 3))
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle((pad, pad, width - 1 - pad, height - 1 - pad), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(pad / 2))


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------- the one live call

EditFn = Callable[[bytes, str], bytes]


def _extract_image(response: object) -> bytes | None:
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None) if inline is not None else None
            if data:
                return data if isinstance(data, bytes) else bytes(data)
    return None


_client = None


def _get_client():  # type: ignore[no-untyped-def]
    """A client of our own, with the frame deadline: a hung paint must not outlive the turn."""
    global _client
    if _client is None:
        from google import genai
        from google.genai import types

        _client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=int(frame_timeout_s() * 1000)),
        )
    return _client


def edit_region(crop_png: bytes, instruction: str) -> bytes:
    """THE seam: one image-edit call on one rectangle. Everything else in this module is local.

    Raises ``FrameError`` on any failure, including an empty response, so the caller can fall
    back to the plate rather than show a broken patch.
    """
    from google.genai import types

    with Image.open(io.BytesIO(crop_png)) as probe:
        aspect = closest_aspect(*probe.size)
    started = time.monotonic()
    try:
        response = _get_client().models.generate_content(
            model=frame_model(),
            contents=[types.Part.from_bytes(data=crop_png, mime_type="image/png"), instruction],
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect, image_size=EDIT_IMAGE_SIZE),
            ),
        )
    except Exception as exc:  # provider errors are opaque; the plate is always a safe answer
        raise FrameError(f"image edit failed: {exc}") from exc
    data = _extract_image(response)
    log.info("frame: edit %s in %.1fs (%s)", aspect, time.monotonic() - started,
             "ok" if data else "no image")
    if not data:
        raise FrameError("image edit returned no image")
    return data


# ---------------------------------------------------------------- baking


def layer_path(scene_id: str, layer_id: str, *, cache_dir: Path | None = None) -> Path:
    """Where one cutout lives. ``cache_dir`` is looked up at call time so a test can move it."""
    return Path(cache_dir if cache_dir is not None else CACHE_DIR) / scene_id / f"{layer_id}.webp"


def paste_layer(frame: Image.Image, patch: Image.Image,
                box: tuple[int, int, int, int]) -> Image.Image:
    """Composite one RGBA cutout onto a copy of ``frame`` — this is what the client does."""
    out = frame.convert("RGBA")
    out.alpha_composite(patch.convert("RGBA"), (box[0], box[1]))
    return out


def bake_layer(frame: Image.Image, layer: FrameLayer, path: Path, *, edit: EditFn) -> Image.Image:
    """Paint one rectangle of ``frame`` and write it as a feathered cutout. Returns the cutout.

    ``frame`` is the scene as it stands (plate plus the layers already painted), so a beat is
    always painted onto the pixels the player is actually looking at.
    """
    box = pixel_box(layer.box.left, layer.box.top, layer.box.width, layer.box.height, frame.size)
    size = (box[2] - box[0], box[3] - box[1])
    crop = frame.convert("RGB").crop(box)
    with Image.open(io.BytesIO(edit(_png_bytes(crop), instruction_for(layer)))) as raw:
        raw.load()
        painted = cover_fit(raw.convert("RGB"), size)
    patch = painted.convert("RGBA")
    patch.putalpha(feather_mask(size))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    patch.save(tmp, "WEBP", quality=WEBP_QUALITY, method=4)
    os.replace(tmp, path)
    return patch


def load_layer(path: Path) -> Image.Image | None:
    if not path.is_file():
        return None
    try:
        image = Image.open(path)
        image.load()
        return image.convert("RGBA")
    except Exception as exc:  # a half-written or corrupt cutout is simply not a cutout
        log.warning("frame: unreadable cutout %s (%s)", path.name, exc)
        return None


def bake_plan(plate: Path, plan: FramePlan, *, edit: EditFn = edit_region,
              cache_dir: Path | None = None) -> dict[str, Path]:
    """Make sure every layer of ``plan`` is on disk. Returns the ones that are.

    Layers are painted in plan order onto a working copy of the plate, because a beat is
    painted over the beats before it. A layer that fails is skipped and the ones after it are
    still attempted: a frame degrades patch by patch, never all at once.
    """
    done: dict[str, Path] = {}
    with Image.open(plate) as opened:
        opened.load()
        frame = opened.convert("RGBA")
    for layer in plan.layers:
        path = layer_path(plan.scene_id, layer.id, cache_dir=cache_dir)
        patch = load_layer(path)
        if patch is None:
            try:
                patch = bake_layer(frame, layer, path, edit=edit)
            except Exception as exc:  # noqa: BLE001 — every failure ends at the plate
                log.warning("frame: layer %s (%s) not painted: %s", layer.id, layer.kind, exc)
                continue
        done[layer.id] = path
        box = pixel_box(layer.box.left, layer.box.top, layer.box.width, layer.box.height,
                        frame.size)
        frame = paste_layer(frame, patch, box)
    return done


def compose(plate: Path, plan: FramePlan, *, cache_dir: Path | None = None) -> Image.Image:
    """The whole frame as one image, for tests and dumps. The client composites in the DOM."""
    with Image.open(plate) as opened:
        opened.load()
        frame = opened.convert("RGBA")
    for layer in plan.layers:
        patch = load_layer(layer_path(plan.scene_id, layer.id, cache_dir=cache_dir))
        if patch is None:
            continue
        box = pixel_box(layer.box.left, layer.box.top, layer.box.width, layer.box.height,
                        frame.size)
        frame = paste_layer(frame, patch, box)
    return frame
