"""Chroma-backdrop matte: generated figure on a flat field -> clean RGBA cutout.

Adapted from Arbitale's ``core/board/character_matte.py`` (copied, not imported).
The image model never hits an exact key colour and a global RGB threshold punches
holes in dark clothes, so the backdrop is removed by an edge flood of whatever flat
field the model actually painted: interior near-key pixels stay in the figure.

Public API:
    matte_cutout(img)            -> RGBA cropped tight to the subject (2px pad)
    trim_to_subject(img, pad)    -> RGBA cropped to alpha bbox + padding
    PROMPT_KEY_RGB               -> the chroma field to ask the model for
"""

from __future__ import annotations

from collections import deque

import numpy as np
from PIL import Image, ImageFilter

# Mint chroma asked for in the gen prompt (dark keys collide with clothing).
PROMPT_KEY_RGB = (42, 212, 160)
_HARD_TOL = 28.0
_SOFT_TOL = 48.0
# Keys darker than this are clothing-coloured; flooding them punches holes.
_MIN_KEY_LUMA = 45.0
_ANALYSIS_MAX_EDGE = 384


def sample_backdrop_rgb(arr: np.ndarray) -> tuple[int, int, int]:
    """Median RGB of the four corner patches — the field the model actually used."""
    h, w = arr.shape[:2]
    pw, ph = max(2, w // 20), max(2, h // 20)
    patches = [
        arr[0:ph, 0:pw, :3],
        arr[0:ph, w - pw : w, :3],
        arr[h - ph : h, 0:pw, :3],
        arr[h - ph : h, w - pw : w, :3],
    ]
    samples = np.concatenate([p.reshape(-1, 3) for p in patches], axis=0)
    med = np.median(samples, axis=0)
    return int(med[0]), int(med[1]), int(med[2])


def _color_dist(rgb: np.ndarray, key: tuple[int, int, int]) -> np.ndarray:
    kr, kg, kb = key
    d = np.abs(rgb[..., 0].astype(np.int16) - kr)
    d += np.abs(rgb[..., 1].astype(np.int16) - kg)
    d += np.abs(rgb[..., 2].astype(np.int16) - kb)
    return d.astype(np.float32) / 3.0


def _luma(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _pick_key(rgb: np.ndarray) -> tuple[int, int, int]:
    """Prefer the candidate that matches the most edge pixels (flat field).

    Dark keys are rejected: a black studio field is the same color as a cloak,
    and flooding it punches holes through the figure.
    """
    sampled = sample_backdrop_rgb(rgb)
    seen: set[tuple[int, int, int]] = set()
    scored: list[tuple[float, float, tuple[int, int, int]]] = []
    for key in (sampled, PROMPT_KEY_RGB, (255, 255, 255), (0, 0, 0)):
        if key in seen:
            continue
        seen.add(key)
        dist = _color_dist(rgb, key)
        edge = np.concatenate([dist[0, :], dist[-1, :], dist[:, 0], dist[:, -1]])
        frac = float((edge <= _HARD_TOL).mean())
        scored.append((frac, _luma(key), key))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    bright = [item for item in scored if item[1] >= _MIN_KEY_LUMA]
    if bright:
        return bright[0][2]
    return PROMPT_KEY_RGB


# Connectivity analyses (floods, connected components) are pure-Python BFS, so
# they run on a bounded downsampled copy; per-pixel alpha/despill math stays
# full-resolution. Area thresholds are fractions of the mask, so they scale.


def _shrink_mask(mask: np.ndarray, max_edge: int = _ANALYSIS_MAX_EDGE) -> np.ndarray | None:
    """Downsampled copy of a boolean mask, or None when it is already small."""
    h, w = mask.shape
    longest = max(h, w)
    if longest <= max_edge:
        return None
    scale = max_edge / longest
    sw, sh = max(2, round(w * scale)), max(2, round(h * scale))
    img = Image.fromarray(mask.astype(np.uint8) * 255)
    small = img.resize((sw, sh), Image.Resampling.NEAREST)
    return np.asarray(small) > 127


def _grow_mask(small: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Upsample a downsampled boolean mask back to ``shape``."""
    h, w = shape
    img = Image.fromarray(small.astype(np.uint8) * 255)
    big = img.resize((w, h), Image.Resampling.NEAREST)
    return np.asarray(big) > 127


def _edge_flood(allowed: np.ndarray) -> np.ndarray:
    """True pixels of ``allowed`` reachable (4-connected) from the frame edge."""
    h, w = allowed.shape
    reached = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()

    def seed(x: int, y: int) -> None:
        if 0 <= x < w and 0 <= y < h and allowed[y, x] and not reached[y, x]:
            reached[y, x] = True
            q.append((x, y))

    for x in range(w):
        seed(x, 0)
        seed(x, h - 1)
    for y in range(h):
        seed(0, y)
        seed(w - 1, y)
    while q:
        x, y = q.popleft()
        seed(x - 1, y)
        seed(x + 1, y)
        seed(x, y - 1)
        seed(x, y + 1)
    return reached


def _flood_background(dist: np.ndarray, *, hard_tol: float) -> np.ndarray:
    """Background = near-key pixels reachable from the frame edge.

    Interior near-key pixels (dark cloak, hair) are NOT reached, so they stay
    in the figure. That is the whole point versus a global color threshold.

    Near-key is morphologically opened before the flood so 1px texture
    corridors (herringbone, grain) cannot leak the backdrop into clothes.
    The flood itself runs on a bounded downsampled mask; the result is
    re-confined to the full-resolution near-key predicate.
    """
    near = dist <= hard_tol
    opened = _erode(near, times=2)
    small = _shrink_mask(opened)
    if small is not None:
        bg = _grow_mask(_dilate(_edge_flood(small), times=1), opened.shape) & opened
    else:
        bg = _edge_flood(opened)
    # Opening shrunk the backdrop; dilate it back but never into far pixels.
    return _dilate(bg, times=2) & near


def _dilate(mask: np.ndarray, times: int = 2) -> np.ndarray:
    out = mask
    for _ in range(times):
        nxt = out.copy()
        nxt[1:, :] |= out[:-1, :]
        nxt[:-1, :] |= out[1:, :]
        nxt[:, 1:] |= out[:, :-1]
        nxt[:, :-1] |= out[:, 1:]
        out = nxt
    return out


def _erode(mask: np.ndarray, times: int = 2) -> np.ndarray:
    return ~_dilate(~mask, times)


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    """Keep True pixels and any False islands fully enclosed by True.

    Mint stains inside a coat are enclosed; the open gap between standing
    legs is not, so it still keys as backdrop. Reachability runs on a bounded
    downsampled mask for large images.
    """
    small = _shrink_mask(mask)
    if small is not None:
        holes_small = ~small & ~_edge_flood(~small)
        return mask | _grow_mask(holes_small, mask.shape)
    inv = ~mask
    return mask | (inv & ~_edge_flood(inv))


def _components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    """4-connected True components of a (bounded-size) mask, as cell lists."""
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=bool)
    out: list[list[tuple[int, int]]] = []
    for y0 in range(h):
        row = mask[y0]
        for x0 in range(w):
            if not row[x0] or seen[y0, x0]:
                continue
            q: deque[tuple[int, int]] = deque([(x0, y0)])
            seen[y0, x0] = True
            cells: list[tuple[int, int]] = [(x0, y0)]
            while q:
                x, y = q.popleft()
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((nx, ny))
                        cells.append((nx, ny))
            out.append(cells)
    return out


def _largest_cc(mask: np.ndarray) -> np.ndarray:
    """Keep the largest True connected component (4-connected).

    Connectivity is decided on a bounded downsampled copy for large images;
    the winning component is grown back and confined to the original mask so
    full-resolution edges stay exact.
    """
    small = _shrink_mask(mask)
    work = small if small is not None else mask
    cells_by_comp = _components(work)
    if not cells_by_comp:
        return mask
    best = max(cells_by_comp, key=len)
    comp = np.zeros(work.shape, dtype=bool)
    for x, y in best:
        comp[y, x] = True
    if small is None:
        return comp
    return _grow_mask(_dilate(comp, times=1), mask.shape) & mask


def key_like_mask(arr: np.ndarray) -> np.ndarray:
    """Pixels that carry the chroma key: green OR cyan, i.e. not red.

    Measured on real cutouts the fringe sits around (20, 52, 46) with green and
    blue equal: a DARK teal. An absolute brightness gate misses it, so key on
    the hue relationship and keep only a floor low enough to spare black ink.

    Exported so the de-spill and anything that MEASURES de-spill share one
    definition; two copies drift and the measurement starts reporting clean.
    """
    r = arr[..., 0].astype(np.int16)
    g = arr[..., 1].astype(np.int16)
    b = arr[..., 2].astype(np.int16)
    # Teal (blue riding with green) OR plain green: where the mint blends into
    # dark ink the blue drops out first, leaving a (66, 107, 74)-style edge that
    # a teal-only test passed as clean.
    return (g > r + 18) & ((b > r + 8) | (g > b + 18)) & (g > 28)


# Key islands narrower than this (px) are left alone: a painted detail, not
# backdrop seen through a gap. Enforced by eroding before growing back.
_ISLAND_MIN_RADIUS = 4
# In `_color_dist` units, measured on 22 baked cutouts: backdrop left between
# stool legs sits 6-9 from the mint key; the nearest real garments (pale blue
# scrubs, a pale hospital gown) sit 50-58. Seeds must be within 25; the island
# then grows through pixels within 40, which takes the blended ring around it
# and still stops short of those garments.
_ISLAND_KEY_TOL = 25.0
_ISLAND_GROW_TOL = 40.0


def clear_key_islands(
    img: Image.Image,
    key: tuple[int, int, int] = PROMPT_KEY_RGB,
    *,
    tol: float = _ISLAND_KEY_TOL,
    grow_tol: float = _ISLAND_GROW_TOL,
    min_radius: int = _ISLAND_MIN_RADIUS,
) -> Image.Image:
    """Cut out opaque patches of the chroma key enclosed by the figure.

    The edge flood cannot reach backdrop framed by a stool's legs and rungs,
    and `_fill_holes` then counts it as part of the body, so a seated figure
    ships with a mint panel under the seat. Seeds are pixels close to the key
    that survive an erosion (so only wide regions qualify); they then grow
    back through key-coloured pixels, taking the blended ring with them.
    Full resolution throughout: growing a downsampled mask back left a blocky
    ring that de-spill turned into grey outlines.
    """
    arr = np.asarray(img.convert("RGBA")).copy()
    alpha = arr[..., 3]
    solid = alpha >= 250
    if not solid.any():
        return img
    dist = _color_dist(arr[..., :3], key)
    seeds = _erode(solid & (dist <= tol), times=min_radius)
    if not seeds.any():
        return img
    passable = (alpha > 0) & (dist <= grow_tol)
    region = seeds
    for _ in range(min_radius + 6):
        grown = _dilate(region, times=1) & passable
        if np.array_equal(grown, region):
            break
        region = grown
    arr[..., 3] = np.where(region, 0, alpha)
    return Image.fromarray(arr, mode="RGBA")


def despill_rim(img: Image.Image) -> Image.Image:
    """Neutralise the chroma key's colour cast on a finished cutout's edge.

    The un-premultiply in `matte_cutout` removes the key's linear contribution,
    but alpha is softened AFTER it, and the flood can bake a ring of backdrop
    into full alpha. On the map that edge is a pixel wide and invisible; a comic
    panel zooms 3-4x and it reads as a teal outline tracing the silhouette.

    This only ever rewrites COLOUR, never alpha. An earlier version deleted
    key-like boundary pixels, which is not idempotent: on a cool-toned garment
    each pass exposed a new boundary ring that the next pass also deleted, and
    repeated runs ate a character's trousers completely. Desaturating the cast
    fixes the fringe, keeps the silhouette, and is safe to run any number of
    times.
    """
    arr = np.asarray(img.convert("RGBA")).astype(np.int16)
    alpha = arr[..., 3]
    solid = alpha >= 250
    soft = (alpha > 0) & (alpha < 250)
    if solid.any():
        pad = np.pad(~solid, 1, constant_values=True)
        touching_open = pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]
        boundary = (solid & touching_open) | soft
    else:
        boundary = soft
    target = boundary & key_like_mask(arr)
    if not target.any():
        return img

    # Pull green and blue down to just above red: the cast goes, the luminance
    # and the edge stay, so the figure keeps its outline against any plate.
    r = arr[..., 0]
    g = arr[..., 1]
    b = arr[..., 2]
    arr[..., 1] = np.where(target, np.minimum(g, r + 6), g)
    arr[..., 2] = np.where(target, np.minimum(b, r + 6), b)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="RGBA")


def matte_cutout(image: Image.Image) -> Image.Image:
    """Edge-flood the backdrop, soft-fringe alpha, despill, then crop to the figure."""
    src = image.convert("RGBA")
    arr = np.array(src)
    rgb = arr[..., :3]
    key = _pick_key(rgb)
    if _luma(key) < _MIN_KEY_LUMA:
        # Dark field ≈ dark clothes. Do not flood; keep the figure intact.
        bbox = src.getbbox()
        return src.crop(bbox) if bbox else src
    dist = _color_dist(rgb, key)
    core = _largest_cc(dist > _HARD_TOL)
    solid = _fill_holes(core)
    # Near-key islands between legs / under a stool never touch the frame edge,
    # so an edge flood leaves a mint blob. Treat near-key pixels outside the
    # filled figure as backdrop — not mint stains enclosed in the body.
    edge_bg = _flood_background(dist, hard_tol=_HARD_TOL)
    island_bg = (dist <= _HARD_TOL) & ~solid
    bg = (edge_bg | island_bg) & ~solid
    # Model-painted mint outlines sit on the silhouette. Eat chroma that
    # touches backdrop, but do not punch the torso.
    halo = _dilate(bg, times=2) & (dist <= _SOFT_TOL)
    protected = _erode(solid, times=2)
    bg = (bg | halo) & ~protected
    if float(bg.mean()) > 0.97 or float(bg.mean()) < 0.02:
        # Flood leaked into the figure, or nothing keyed — leave opaque and crop.
        bbox = src.getbbox()
        return src.crop(bbox) if bbox else src

    alpha = np.where(bg, 0, 255).astype(np.uint8)
    fringe = _dilate(bg, times=1) & ~bg
    span = max(_SOFT_TOL - _HARD_TOL, 1.0)
    t = np.clip((dist - _HARD_TOL) / span, 0.0, 1.0)
    alpha[fringe] = (t[fringe] * 255.0).astype(np.uint8)

    # Un-premultiply the key out of anti-aliased edge pixels (despill).
    a = alpha.astype(np.float32) / 255.0
    a3 = a[..., None]
    kr, kg, kb = (float(key[0]), float(key[1]), float(key[2]))
    key_arr = np.array([kr, kg, kb], dtype=np.float32)
    recovered = (rgb.astype(np.float32) - key_arr * (1.0 - a3)) / np.maximum(a3, 1e-4)
    recovered = np.clip(recovered, 0, 255)
    rgb_out = np.where(a3 > 0.02, recovered, 0).astype(np.uint8)

    out = np.dstack([rgb_out, alpha])
    img = Image.fromarray(out, mode="RGBA")
    # Soften the binary stair-step without eating the figure.
    blur = img.split()[3].filter(ImageFilter.GaussianBlur(radius=0.4))
    img.putalpha(blur)
    img = clear_key_islands(img, key)
    img = despill_rim(img)
    bbox = img.getbbox()
    if bbox:
        pad = 2
        x0, y0, x1, y1 = bbox
        x0 = max(0, x0 - pad)
        y0 = max(0, y0 - pad)
        x1 = min(img.width, x1 + pad)
        y1 = min(img.height, y1 + pad)
        img = img.crop((x0, y0, x1, y1))
    return img


def trim_to_subject(img: Image.Image, pad: int = 0, *, alpha_floor: int = 8) -> Image.Image:
    """Crop to pixels with alpha > ``alpha_floor`` plus ``pad`` transparent px per side.

    Near-invisible specks (alpha <= floor) are zeroed first so they cannot
    inflate the bounding box.
    """
    rgba = img.convert("RGBA")
    arr = np.array(rgba)
    arr[..., 3] = np.where(arr[..., 3] <= alpha_floor, 0, arr[..., 3])
    rgba = Image.fromarray(arr, mode="RGBA")
    bbox = rgba.getbbox()
    if not bbox:
        return rgba
    cropped = rgba.crop(bbox)
    if pad <= 0:
        return cropped
    out = Image.new("RGBA", (cropped.width + 2 * pad, cropped.height + 2 * pad), (0, 0, 0, 0))
    out.paste(cropped, (pad, pad))
    return out


def drop_small_islands(img: Image.Image, *, min_frac: float = 0.01) -> Image.Image:
    """Remove opaque specks smaller than ``min_frac`` of the largest component.

    The model sometimes paints stray sparks/dust off the figure; they survive the
    flood as tiny islands and would inflate the trim box.
    """
    rgba = img.convert("RGBA")
    arr = np.array(rgba)
    opaque = arr[..., 3] > 8
    if not opaque.any():
        return rgba
    small = _shrink_mask(opaque)
    work = small if small is not None else opaque
    comps = _components(work)
    if len(comps) <= 1:
        return rgba
    biggest = max(len(c) for c in comps)
    keep = np.zeros(work.shape, dtype=bool)
    for cells in comps:
        if len(cells) >= biggest * min_frac:
            for x, y in cells:
                keep[y, x] = True
    if small is not None:
        keep = _grow_mask(_dilate(keep, times=2), opaque.shape)
    arr[..., 3] = np.where(keep, arr[..., 3], 0)
    return Image.fromarray(arr, mode="RGBA")


def purge_key(
    img: Image.Image,
    key: tuple[int, int, int],
    *,
    hard_tol: float = 36.0,
    soft_tol: float = 70.0,
) -> Image.Image:
    """Global chroma cleanup for subjects that contain NO key-coloured material.

    The edge flood deliberately spares enclosed near-key pockets (so dark cloth
    survives), but a narrow gap between legs can be sealed off and ships as a
    mint sliver. When the subject is known not to contain the key hue, any
    pixel near the key is backdrop: alpha 0 within ``hard_tol``, a linear ramp
    up to ``soft_tol`` for key-like (green/teal-cast) pixels, then de-spill.
    """
    arr = np.array(img.convert("RGBA"))
    rgb = arr[..., :3]
    dist = _color_dist(rgb, key)
    alpha = arr[..., 3].astype(np.float32)
    keyish = key_like_mask(arr)
    hard = dist <= hard_tol
    ramp = keyish & (dist > hard_tol) & (dist < soft_tol)
    t = np.clip((dist - hard_tol) / max(soft_tol - hard_tol, 1.0), 0.0, 1.0)
    alpha = np.where(hard, 0.0, alpha)
    alpha = np.where(ramp, np.minimum(alpha, t * 255.0), alpha)
    arr[..., 3] = alpha.astype(np.uint8)
    return despill_rim(Image.fromarray(arr, mode="RGBA"))


def remove_hairlines(img: Image.Image, *, width: int = 1, max_alpha: int = 220) -> Image.Image:
    """Delete thin (<= ~2*width px) semi-transparent scribbles left by de-spill.

    A morphological opening of the visible mask drops structures narrower than
    the structuring element; only pixels that are ALSO semi-transparent
    (alpha < ``max_alpha``) are removed, so solid painted detail is never cut.
    """
    arr = np.array(img.convert("RGBA"))
    alpha = arr[..., 3]
    visible = alpha > 8
    opened = _dilate(_erode(visible, times=width), times=width)
    thin = visible & ~opened & (alpha < max_alpha)
    arr[..., 3] = np.where(thin, 0, alpha)
    return Image.fromarray(arr, mode="RGBA")
