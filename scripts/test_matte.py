"""Offline tests for tools/matte.py on synthetic images (no network).

Run: python scripts/test_matte.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.matte import (  # noqa: E402
    PROMPT_KEY_RGB,
    drop_faint_islands,
    drop_small_islands,
    key_like_mask,
    matte_cutout,
    purge_key,
    remove_hairlines,
    soft_key_cutout,
    solidify,
    trim_to_subject,
)

FIGURE_RGB = (180, 90, 50)  # rust-orange "jumpsuit"
DARK_RGB = (30, 30, 34)  # near-black detail inside the figure


def _synthetic(bg: tuple[int, int, int], *, soft_edge: bool = True) -> Image.Image:
    """400x600 field with a figure: body ellipse, dark belt, legs with a gap."""
    img = Image.new("RGB", (400, 600), bg)
    d = ImageDraw.Draw(img)
    d.ellipse((140, 60, 260, 180), fill=FIGURE_RGB)  # head
    d.rectangle((130, 170, 270, 380), fill=FIGURE_RGB)  # torso
    d.rectangle((130, 300, 270, 330), fill=DARK_RGB)  # dark belt
    d.rectangle((135, 380, 190, 560), fill=FIGURE_RGB)  # left leg
    d.rectangle((210, 380, 265, 560), fill=FIGURE_RGB)  # right leg (gap 190..210)
    if soft_edge:
        # Anti-aliased edges blend figure into key, like a real generation.
        img = img.filter(ImageFilter.GaussianBlur(1.2))
    return img


def _alpha(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGBA"))[..., 3]


def test_mint_background_is_removed() -> None:
    out = matte_cutout(_synthetic(PROMPT_KEY_RGB))
    a = _alpha(out)
    assert out.mode == "RGBA"
    # Trimmed: result is roughly the figure bbox (130..270 x 60..560) + small pad.
    assert 135 <= out.width <= 160, out.size
    assert 495 <= out.height <= 520, out.size
    # Corners are transparent.
    for y, x in ((0, 0), (0, -1), (-1, 0), (-1, -1)):
        assert a[y, x] == 0, (y, x, a[y, x])
    # Torso center opaque.
    cy, cx = out.height // 2 - 40, out.width // 2
    assert a[cy, cx] == 255


def test_dark_interior_survives() -> None:
    out = matte_cutout(_synthetic(PROMPT_KEY_RGB))
    a = _alpha(out)
    # Belt row (y=315 in source ≈ 315-60+pad in crop) must stay opaque.
    belt_y = 315 - 60 + 2
    row = a[belt_y, 10 : out.width - 10]
    assert (row == 255).mean() > 0.95, row


def test_leg_gap_is_transparent() -> None:
    out = matte_cutout(_synthetic(PROMPT_KEY_RGB))
    a = _alpha(out)
    gap_x = 200 - 130 + 2  # source x=200 in crop coords (bbox starts ~x=128)
    gap_y = 480 - 60 + 2
    assert a[gap_y, gap_x - 2 : gap_x + 3].max() < 40, a[gap_y, gap_x - 3 : gap_x + 4]


def test_white_background() -> None:
    out = matte_cutout(_synthetic((255, 255, 255)))
    a = _alpha(out)
    assert a[0, 0] == 0 and a[-1, -1] == 0
    assert a[out.height // 2, out.width // 2] == 255


def test_off_key_background_is_sampled() -> None:
    # Model painted a slightly different green than asked; corners are sampled.
    out = matte_cutout(_synthetic((20, 235, 60)))
    a = _alpha(out)
    assert a[0, 0] == 0
    assert 135 <= out.width <= 160


def test_no_green_fringe_on_rim() -> None:
    out = matte_cutout(_synthetic(PROMPT_KEY_RGB, soft_edge=True))
    arr = np.asarray(out).astype(np.int16)
    visible = arr[..., 3] > 30
    fringe = visible & key_like_mask(arr)
    assert fringe.sum() == 0, int(fringe.sum())


def test_enclosed_key_pocket_purged() -> None:
    # A thin opaque mint sliver sealed inside the figure (as the flood leaves
    # between touching legs) plus a blended ring around it.
    img = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((50, 20, 150, 280), fill=FIGURE_RGB + (255,))
    d.rectangle((98, 120, 101, 220), fill=PROMPT_KEY_RGB + (255,))
    blend = tuple((f + k) // 2 for f, k in zip(FIGURE_RGB, PROMPT_KEY_RGB))
    d.rectangle((97, 118, 97, 222), fill=blend + (255,))
    out = purge_key(img, PROMPT_KEY_RGB)
    a = _alpha(out)
    assert a[170, 99] == 0 and a[170, 100] == 0
    arr = np.asarray(out).astype(np.int16)
    assert (key_like_mask(arr) & (a > 30)).sum() == 0
    assert a[170, 70] == 255 and a[170, 130] == 255  # body untouched


def test_hairlines_removed_solid_kept() -> None:
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((10, 10, 60, 60), fill=(200, 100, 50, 255))  # solid body
    d.line((70, 5, 70, 95), fill=(90, 90, 90, 120), width=1)  # faint scribble
    d.line((80, 5, 80, 95), fill=(90, 90, 90, 255), width=1)  # solid thin detail
    a = _alpha(remove_hairlines(img, width=2))
    assert a[50, 70] == 0
    assert a[50, 80] == 255 and a[35, 35] == 255 and a[10, 10] == 255


def _screen_scene(key: tuple[int, int, int]) -> Image.Image:
    """Opaque amber block, a 50% 'glass' pane and a contact shadow on a chroma screen."""
    img = Image.new("RGB", (300, 300), key)
    d = ImageDraw.Draw(img)
    d.rectangle((40, 60, 120, 240), fill=(170, 90, 30))  # opaque amber bottle
    glass = tuple((k + w) // 2 for k, w in zip(key, (235, 235, 235)))
    d.rectangle((180, 60, 260, 240), fill=glass)  # pane: half key, half near-white
    shadow = tuple(int(k * 0.5) for k in key)
    d.rectangle((40, 241, 120, 250), fill=shadow)  # darker key under the bottle
    return img


def test_soft_key_green_glass_and_shadow() -> None:
    out = np.asarray(soft_key_cutout(_screen_scene((0, 255, 0)))).astype(int)
    a = out[..., 3]
    assert a[5, 5] == 0 and a[150, 150] == 0  # backdrop gone
    assert a[150, 80] == 255 and tuple(out[150, 80, :3]) == (170, 90, 30)  # solid kept exact
    assert 90 <= a[150, 220] <= 170, a[150, 220]  # glass is semi-transparent
    r, g, b = out[150, 220, :3]
    assert g <= max(r, b) and min(r, b) > 200, (r, g, b)  # de-spilled back to near-white
    assert 90 <= a[245, 80] <= 170 and out[245, 80, :3].max() < 25  # shadow = translucent black


def test_soft_key_dim_glass_stays_neutral() -> None:
    # Glass that dims the screen and adds a grey sheen must key to neutral grey,
    # not magenta (the failure when colour is recovered with the levelled alpha).
    img = Image.new("RGB", (120, 120), (0, 255, 0))
    ImageDraw.Draw(img).rectangle((30, 30, 90, 90), fill=(40, 240, 40))
    out = np.asarray(soft_key_cutout(img)).astype(int)
    r, g, b, a = out[60, 60]
    assert 0 < a < 80, a
    assert abs(r - b) <= 6 and g <= max(r, b) and max(r, b) - g <= 12, (r, g, b)


def test_soft_key_blue_keeps_greens() -> None:
    img = _screen_scene((0, 0, 255))
    ImageDraw.Draw(img).rectangle((130, 100, 170, 140), fill=(90, 160, 60))  # scallion green
    out = np.asarray(soft_key_cutout(img)).astype(int)
    assert out[5, 5, 3] == 0
    assert out[120, 150, 3] == 255 and tuple(out[120, 150, :3]) == (90, 160, 60)


def test_soft_key_rejects_non_screen() -> None:
    for bg in ((240, 240, 240), (200, 30, 30), (40, 40, 40)):
        try:
            soft_key_cutout(Image.new("RGB", (64, 64), bg))
        except ValueError:
            continue
        raise AssertionError(f"accepted backdrop {bg}")


def test_faint_haze_dropped_attached_steam_kept() -> None:
    img = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((250, 300, 350, 500), fill=(150, 80, 40, 255))  # solid cup
    d.rectangle((280, 200, 320, 299), fill=(255, 255, 255, 60))  # steam touching the cup
    d.rectangle((40, 60, 560, 90), fill=(255, 255, 255, 30))  # detached screen-lighting band
    a = _alpha(drop_faint_islands(img))
    assert a[75, 300] == 0, "detached haze must go"
    assert a[250, 300] == 60, "steam attached to the solid must stay"
    assert a[400, 300] == 255


def test_solidify_restores_key_hued_print() -> None:
    # A white-bordered photo whose picture contains a green light, shot on green.
    img = Image.new("RGB", (300, 300), (0, 255, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((60, 60, 240, 240), fill=(240, 240, 235))
    d.rectangle((80, 80, 220, 200), fill=(30, 30, 60))
    d.ellipse((130, 120, 170, 160), fill=(40, 230, 90))  # green bokeh inside the print
    d.rectangle((60, 241, 240, 250), fill=(0, 120, 0))  # contact shadow outside it
    keyed = soft_key_cutout(img)
    assert _alpha(keyed)[140, 150] < 120, "precondition: the keyer punches the green light"
    out = np.asarray(solidify(keyed, img)).astype(int)
    assert tuple(out[140, 150]) == (40, 230, 90, 255)
    assert out[5, 5, 3] == 0 and 60 < out[245, 150, 3] < 200  # backdrop gone, shadow kept
    assert out[61, 61, 3] > 0 and out[150, 70, 3] == 255


def test_islands_and_trim_padding() -> None:
    img = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((100, 100, 199, 249), fill=(200, 150, 60, 255))  # main subject
    d.rectangle((10, 10, 12, 12), fill=(255, 255, 255, 255))  # stray speck
    cleaned = drop_small_islands(img)
    assert _alpha(cleaned)[11, 11] == 0
    trimmed = trim_to_subject(cleaned, pad=8)
    assert trimmed.size == (100 + 16, 150 + 16), trimmed.size
    a = _alpha(trimmed)
    assert a[0, 0] == 0 and a[8, 8] == 255 and a[-9, -9] == 255 and a[-1, -1] == 0


def test_trim_ignores_faint_alpha() -> None:
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    img.putpixel((1, 1), (255, 0, 0, 4))  # near-invisible dust
    ImageDraw.Draw(img).rectangle((40, 40, 59, 59), fill=(0, 0, 255, 255))
    assert trim_to_subject(img).size == (20, 20)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
