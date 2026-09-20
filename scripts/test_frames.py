"""The living scene, offline: geometry, cache keys, compositing, the tools and the fallbacks.

Not one image-model call is made. ``media.frames.bake_plan`` takes its single network call as
an argument, so the whole pipeline — crop, edit, feather, cache, composite — runs here against
a painter that just returns pixels.
"""

from __future__ import annotations

import io
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

os.environ["POLYTALE_STATES_DIR"] = tempfile.mkdtemp(prefix="polytale-frames-")

from fastapi.testclient import TestClient
from PIL import Image

from core.content import Anchor, load_content
from core.dm import enter_scene, run_opening, run_turn
from core.frames import (
    BASE_EXPRESSION,
    EXPRESSIONS,
    MAX_BEAT_WORDS,
    MAX_PATCHES,
    REGIONS,
    FramePatch,
    build_plan,
    face_box,
    frame_view,
    region_box,
)
from core.state import Attempt, new_journey
from core.tools import ToolContext, execute, is_error
from media import frames as painter
from scripts.testkit import Checker, FakeClient, call, lexicon_line, reply

T = Checker("test_frames")
CONTENT = load_content()
SCENE = CONTENT.scene(CONTENT.journey.scenes[0])
ZH = CONTENT.language("zh-CN")
ANCHOR = SCENE.npc.anchor
MODELS = ["fake-model"]

CACHE = Path(tempfile.mkdtemp(prefix="polytale-frames-cache-"))
painter.CACHE_DIR = CACHE


# ---------------------------------------------------------------- helpers


def plate(size: tuple[int, int] = (400, 225)) -> Path:
    """A throwaway base plate whose every pixel is different, so a copy is provable."""
    image = Image.new("RGB", size)
    image.putdata([((x * 7) % 256, (y * 11) % 256, (x + y) % 256)
                   for y in range(size[1]) for x in range(size[0])])
    path = Path(tempfile.mkdtemp(prefix="polytale-plate-")) / "bg.png"
    image.save(path, "PNG")
    return path


class Painter:
    """Stands in for the image model: paints the crop flat and remembers what it was given."""

    def __init__(self, colour: tuple[int, int, int] = (255, 0, 0), fail: bool = False) -> None:
        self.colour, self.fail = colour, fail
        self.seen: list[tuple[Image.Image, str]] = []

    def __call__(self, crop_png: bytes, instruction: str) -> bytes:
        image = Image.open(io.BytesIO(crop_png))
        image.load()
        self.seen.append((image, instruction))
        if self.fail:
            raise RuntimeError("the model is having a night off")
        out = io.BytesIO()
        Image.new("RGB", image.size, self.colour).save(out, "PNG")
        return out.getvalue()


def says(*lines: Any, expression: str = BASE_EXPRESSION) -> Any:
    """testkit's ``say`` plus the face: the model commits both in one call."""
    return call("say", lines=list(lines), intent_hint="wants you to join in",
                narration="The room roars at the screen.", expression=expression)


def ctx() -> tuple[Any, ToolContext]:
    journey = enter_scene(new_journey(CONTENT, "fr1", language="zh-CN"), CONTENT)
    attempt = Attempt(attempt_id="a1", input_mode="text", transcript="hao")
    return journey, ToolContext(scene=SCENE, language=ZH, attempt=attempt)


def outside(a: Image.Image, b: Image.Image, box: tuple[int, int, int, int]) -> bool:
    """True when two images agree on every pixel outside ``box``."""
    left, top, right, bottom = box
    pa, pb = a.convert("RGBA").load(), b.convert("RGBA").load()
    for y in range(a.height):
        for x in range(a.width):
            if left <= x < right and top <= y < bottom:
                continue
            if pa[x, y] != pb[x, y]:
                return False
    return True


# ---------------------------------------------------------------- geometry


def test_geometry() -> None:
    face = face_box(ANCHOR)
    T.check("the face box is built around the anchor, not authored anywhere",
            face.left < ANCHOR.x < face.right and face.top < ANCHOR.y < face.bottom,
            face.model_dump())
    T.check("the face box is a head and shoulders, not the whole plate",
            0.1 < face.width < 0.45 and 0.15 < face.height < 0.5, face.model_dump())
    boxes = {r: region_box(r, ANCHOR) for r in REGIONS}
    T.check("every region stays inside the plate",
            all(0 <= b.left and 0 <= b.top and b.right <= 1.0 and b.bottom <= 1.0
                for b in boxes.values()), {r: b.model_dump() for r, b in boxes.items()})
    overlapping = [r for r, b in boxes.items()
                   if b.left < face.right and face.left < b.right
                   and b.top < face.bottom and face.top < b.bottom]
    T.check("only the hands region may graze the face (the face is the expression's)",
            overlapping == ["hands"], overlapping)
    T.check("the face is not a beat region", "face" not in REGIONS)

    high = region_box("counter", Anchor(x=0.5, y=0.05))
    T.check("a high anchor still yields a legal box",
            0 <= high.top and high.bottom <= 1.0 and high.height > 0)
    T.check("an unknown region raises rather than guessing",
            _raises(lambda: region_box("ceiling", ANCHOR)))


def _raises(fn: Any) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


def test_pixel_box() -> None:
    size = (400, 225)
    box = painter.pixel_box(0.25, 0.5, 0.5, 0.25, size)
    T.check("a fractional box becomes whole pixels", box == (100, 112, 300, 169), box)
    huge = painter.pixel_box(-1.0, -1.0, 9.0, 9.0, size)
    T.check("a box that runs off the plate is clamped to it", huge == (0, 0, 400, 225), huge)
    tiny = painter.pixel_box(0.999, 0.999, 0.0001, 0.0001, size)
    T.check("a box is never empty", tiny[2] > tiny[0] and tiny[3] > tiny[1], tiny)


# ---------------------------------------------------------------- plan and cache keys


def test_plan() -> None:
    def plan(sig: str = "sigA", expression: str = "delighted",
             patches: tuple[FramePatch, ...] = ()) -> Any:
        return build_plan(scene_id="bar", plate_sig=sig, anchor=ANCHOR,
                          expression=expression, patches=patches)

    bare = plan(expression=BASE_EXPRESSION)
    T.check("the everyday face is the plate itself: no layers, nothing to paint",
            bare.empty and not bare.layers)
    T.check("an empty plan still has a key", bool(bare.key))

    one = plan()
    T.check("a face is one layer over the plate",
            len(one.layers) == 1 and one.layers[0].kind == "expression"
            and one.layers[0].value == "delighted")
    T.check("the plan is stable: the same scene twice is the same ids",
            [x.id for x in plan().layers] == [x.id for x in one.layers]
            and plan().key == one.key)
    T.check("a different face is a different bake",
            plan(expression="puzzled").layers[0].id != one.layers[0].id)
    T.check("repainting the base plate invalidates every cached cutout",
            plan(sig="sigB").layers[0].id != one.layers[0].id
            and plan(sig="sigB").key != one.key)
    T.check("an unknown face paints nothing rather than something wrong",
            plan(expression="smouldering").empty)

    a = FramePatch(region="counter", change="a full glass stands in front of you")
    b = FramePatch(region="room_right", change="two fans are up on their chairs")
    with_beats = plan(patches=(a, b))
    T.check("beats are painted in order, the face last",
            [x.kind for x in with_beats.layers] == ["beat", "beat", "expression"])
    T.check("a beat is painted in its own region's box",
            with_beats.layers[1].box.model_dump() == region_box("room_right",
                                                                ANCHOR).model_dump())
    T.check("the face bake is shared whatever happened in the room: it comes off the plate",
            with_beats.layers[-1].id == one.layers[0].id)
    T.check("a beat's bake folds in the beats before it (it is painted over them)",
            plan(patches=(a,)).layers[0].id == with_beats.layers[0].id
            and plan(patches=(b,)).layers[0].id != with_beats.layers[1].id)
    T.check("swapping two beats is a different scene",
            [x.id for x in plan(patches=(b, a)).layers]
            != [x.id for x in with_beats.layers])

    view = frame_view("jrn1", with_beats)
    T.check("the view carries a url and a box per layer, in fractions",
            len(view.layers) == 3
            and all(v.url == f"/api/journeys/jrn1/frame/{v.id}" for v in view.layers)
            and all(0 <= v.left and v.width > 0 for v in view.layers), view.model_dump())


# ---------------------------------------------------------------- painting


def test_bake_and_composite() -> None:
    base = plate()
    plan = build_plan(scene_id="bar", plate_sig="sigC", anchor=ANCHOR,
                      expression="roaring", patches=())
    brush = Painter()
    done = painter.bake_plan(base, plan, edit=brush, cache_dir=CACHE)
    T.check("the layer is baked and on disk",
            len(done) == 1 and next(iter(done.values())).is_file())
    crop, instruction = brush.seen[0]
    box = painter.pixel_box(plan.layers[0].box.left, plan.layers[0].box.top,
                            plan.layers[0].box.width, plan.layers[0].box.height, (400, 225))
    T.check("the model is handed the box only, never the plate",
            crop.size == (box[2] - box[0], box[3] - box[1]) and crop.size != (400, 225),
            crop.size)
    T.check("the instruction pins the framing and names one change",
            "same rectangle" in instruction.lower() and "THE ONE CHANGE" in instruction
            and "roaring" in instruction)

    again = Painter()
    painter.bake_plan(base, plan, edit=again, cache_dir=CACHE)
    T.check("a baked face is never painted twice: that is the whole speed story",
            again.seen == [])

    composed = painter.compose(base, plan, cache_dir=CACHE)
    with Image.open(base) as original:
        original.load()
        T.check("every pixel outside the box is the plate, untouched",
                outside(original, composed, box))
        centre = composed.convert("RGBA").getpixel(
            ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))
    T.check("the middle of the box is what the painter returned",
            centre[3] == 255 and centre[0] > 240 and centre[1] < 16 and centre[2] < 16, centre)


def test_beats_stack() -> None:
    base = plate()
    first = FramePatch(region="counter", change="a full glass stands in front of you")
    second = FramePatch(region="counter", change="a scarf lies beside the glass")
    plan = build_plan(scene_id="stack", plate_sig="sigD", anchor=ANCHOR,
                      expression=BASE_EXPRESSION, patches=(first, second))
    brush = Painter(colour=(0, 255, 0))
    painter.bake_plan(base, plan, edit=brush, cache_dir=CACHE)
    T.check("both beats were painted", len(brush.seen) == 2)
    second_crop = brush.seen[1][0].convert("RGB")
    middle = second_crop.getpixel((second_crop.width // 2, second_crop.height // 2))
    T.check("a beat is painted onto the scene as it stands, not onto the bare plate",
            middle == (0, 255, 0), middle)


def test_failure_falls_back() -> None:
    base = plate()
    plan = build_plan(scene_id="sad", plate_sig="sigE", anchor=ANCHOR,
                      expression="moved",
                      patches=(FramePatch(region="counter", change="a glass lands"),))
    done = painter.bake_plan(base, plan, edit=Painter(fail=True), cache_dir=CACHE)
    T.check("nothing is written when the painter fails", done == {})
    composed = painter.compose(base, plan, cache_dir=CACHE)
    with Image.open(base) as original:
        original.load()
        T.check("a failed frame is the base plate, never a broken or blank one",
                outside(original, composed, (0, 0, 0, 0)))

    class OnlyTheFirstFails(Painter):
        def __call__(self, crop_png: bytes, instruction: str) -> bytes:
            self.fail = not self.seen
            return super().__call__(crop_png, instruction)

    done = painter.bake_plan(base, plan, edit=OnlyTheFirstFails(), cache_dir=CACHE)
    T.check("one bad layer does not take the rest of the frame with it",
            len(done) == 1 and plan.layers[1].id in done, sorted(done))


def test_feather() -> None:
    mask = painter.feather_mask((120, 90))
    pixels = mask.load()
    T.check("the middle of a patch is solid", pixels[60, 45] == 255)
    T.check("the corner fades out so the seam does not show", pixels[0, 0] < 40, pixels[0, 0])
    T.check("a very small patch still gets a mask",
            painter.feather_mask((4, 4)).size == (4, 4))


def test_switches() -> None:
    keep = {k: os.environ.get(k) for k in
            ("POLYTALE_FRAMES", "POLYTALE_FRAME_MODEL", "GEMINI_IMAGE_MODEL",
             "POLYTALE_FRAME_TIMEOUT_S")}
    try:
        for key in keep:
            os.environ.pop(key, None)
        T.check("the scene reacts unless it is switched off", painter.frames_enabled())
        for off in ("0", "false", "no", "OFF"):
            os.environ["POLYTALE_FRAMES"] = off
            if painter.frames_enabled():
                T.check(f"POLYTALE_FRAMES={off} switches it off", False)
                break
        else:
            T.check("every spelling of off switches it off", True)
        os.environ["POLYTALE_FRAMES"] = "1"
        T.check("and back on again", painter.frames_enabled())

        T.check("the model defaults to a fast flash image model",
                painter.frame_model() == painter.DEFAULT_MODEL)
        os.environ["GEMINI_IMAGE_MODEL"] = "from-env"
        T.check("it reuses the art key from .env", painter.frame_model() == "from-env")
        os.environ["POLYTALE_FRAME_MODEL"] = "override"
        T.check("and can be overridden on its own", painter.frame_model() == "override")

        T.check("there is always a deadline", painter.frame_timeout_s() > 0)
        os.environ["POLYTALE_FRAME_TIMEOUT_S"] = "7.5"
        T.check("the deadline is configurable", painter.frame_timeout_s() == 7.5)
        os.environ["POLYTALE_FRAME_TIMEOUT_S"] = "nonsense"
        T.check("a nonsense deadline falls back, it does not crash a turn",
                painter.frame_timeout_s() == painter.DEFAULT_TIMEOUT_S)
    finally:
        for key, value in keep.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value


def test_signature() -> None:
    base = plate()
    first = painter.plate_signature(base)
    T.check("the same plate hashes the same way", first == painter.plate_signature(base))
    Image.new("RGB", (400, 225), (9, 9, 9)).save(base, "PNG")
    T.check("a repainted plate is a new signature", painter.plate_signature(base) != first)


def test_transparent_pixel() -> None:
    with Image.open(io.BytesIO(painter.TRANSPARENT_PNG)) as pixel:
        pixel.load()
        T.check("the fallback patch is a real, fully transparent image",
                pixel.size == (1, 1) and pixel.convert("RGBA").getpixel((0, 0)) == (0, 0, 0, 0))


# ---------------------------------------------------------------- the tools


def test_expression_tool() -> None:
    journey, context = ctx()
    args = {"lines": [lexicon_line(ZH, ["cheers"])], "narration": "The room roars.",
            "intent_hint": "wants you to drink"}
    execute("say", journey, {**args, "expression": "laughing"}, context)
    assert context.terminal is not None
    T.check("the model commits the face with the line it belongs to",
            context.terminal["expression"] == "laughing")

    journey, context = ctx()
    execute("say", journey, args, context)
    assert context.terminal is not None
    T.check("an omitted face settles back to neutral, so a puzzled look never sticks",
            context.terminal["expression"] == BASE_EXPRESSION)

    journey, context = ctx()
    receipt = execute("say", journey, {**args, "expression": "smouldering"}, context)
    T.check("a face that is not one of ours is an ERROR receipt, not a guess",
            is_error(receipt) and context.terminal is None
            and all(name in receipt for name in EXPRESSIONS), receipt)


def test_beat_tool() -> None:
    journey, context = ctx()
    receipt = execute("show_beat", journey,
                      {"region": "counter", "change": "a full glass stands in front of you"},
                      context)
    run = journey.scene
    assert run is not None
    T.check("a beat is committed to the scene, not to the prose",
            not is_error(receipt) and [p.region for p in run.patches] == ["counter"], receipt)

    receipt = execute("show_beat", journey, {"region": "hands", "change": "he lifts a scarf"},
                      context)
    T.check("one beat a turn; a second is a no-op, not a bounce",
            not is_error(receipt) and len(run.patches) == 1, receipt)

    journey, context = ctx()
    T.check("an unknown region is an ERROR listing the real ones",
            is_error(execute("show_beat", journey, {"region": "ceiling", "change": "x"},
                             context)))
    T.check("a beat with nothing to see is an ERROR",
            is_error(execute("show_beat", journey, {"region": "counter", "change": " "},
                             context)))
    long = " ".join(["word"] * (MAX_BEAT_WORDS + 1))
    T.check("a beat is a painter's note, not a paragraph",
            is_error(execute("show_beat", journey, {"region": "counter", "change": long},
                             context)))

    journey, _ = ctx()
    run = journey.scene
    assert run is not None
    for i in range(MAX_PATCHES + 2):
        _, context = ctx()
        execute("show_beat", journey, {"region": "counter", "change": f"change {i}"}, context)
    T.check("the room can only change so much before it is a collage",
            len(run.patches) == MAX_PATCHES, len(run.patches))


def test_turn_commits_the_face() -> None:
    journey = enter_scene(new_journey(CONTENT, "fr2", language="zh-CN"), CONTENT)
    script = [reply(says(lexicon_line(ZH, ["hello"]), expression="delighted"))]
    journey, result = run_opening(journey, CONTENT, client=FakeClient(script), models=MODELS)
    run = journey.scene
    assert run is not None
    T.check("the committed turn carries the face into the state", run.expression == "delighted")
    T.check("the engine promises no picture; the server owns the art", result.frame is None)

    script = [reply(call("show_beat", region="counter", change="a full glass lands"),
                    says(lexicon_line(ZH, ["cheers"]), expression=BASE_EXPRESSION))]
    journey, _ = run_turn(journey, CONTENT,
                          {"attempt_id": "a9", "input_mode": "text", "transcript": "nihao"},
                          client=FakeClient(script), models=MODELS)
    run = journey.scene
    assert run is not None
    T.check("a face let go of goes back to neutral", run.expression == BASE_EXPRESSION)
    T.check("the beat is in the ledger, so it survives a reload",
            [p.change for p in run.patches] == ["a full glass lands"])

    from core.prompt import build_snapshot

    snapshot = build_snapshot(journey, SCENE, ZH, None)
    T.check("the snapshot shows the model what is already painted",
            "a full glass lands" in snapshot and "neutral face" in snapshot)


# ---------------------------------------------------------------- the server


def test_server() -> None:
    from core import dm
    from media import tts
    from server.app import Deps, app
    from server.frames import FrameService

    started, release = threading.Event(), threading.Event()
    baked: list[str] = []

    def slow_bake(plate_path: Path, plan: Any) -> dict[str, Path]:
        started.set()
        release.wait(5)  # bounded, so a turn that waits on the picture FAILS instead of hanging
        out: dict[str, Path] = {}
        for layer in plan.layers:
            path = painter.layer_path(plan.scene_id, layer.id, cache_dir=CACHE)
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(path, "WEBP")
            baked.append(layer.id)
            out[layer.id] = path
        return out

    class Client:
        def __init__(self) -> None:
            self.script: list[Any] = []
            self.models = self

        def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
            return self.script.pop(0)

    fake = Client()
    audio = Path(tempfile.mkdtemp(prefix="polytale-frames-audio-"))

    def synth(text: str, **kwargs: Any) -> Any:
        path = audio / "clip.wav"
        path.write_bytes(b"RIFF....WAVEfake")
        return tts.AudioClip(path, "audio/wav", "fake", cached=False)

    from functools import partial

    app.state.deps = Deps(
        run_turn=partial(dm.run_turn, client=fake, models=["fake"]),
        run_opening=partial(dm.run_opening, client=fake, models=["fake"]),
        synthesize=synth,
    )
    app.state.frames = FrameService(bake=slow_bake)
    painter.CACHE_DIR = CACHE
    # One event loop for the whole block: a background paint started by one request has to
    # still be there for the next one, exactly as it is under a single uvicorn worker.
    with TestClient(app) as client:
        _server_checks(client, fake, started, release, baked)


def _server_checks(client: Any, fake: Any, started: Any, release: Any, baked: list[str]) -> None:
    from server.frames import FrameService
    from server.app import app

    body = client.post("/api/journeys", json={}).json()
    jid, hdr = body["journey_id"], {"X-Journey-Token": body["token"]}
    fake.script = [reply(says(lexicon_line(ZH, ["hello"]), expression=BASE_EXPRESSION))]
    opening = client.post(f"/api/journeys/{jid}/scene", json={}, headers=hdr).json()
    T.check("a neutral scene promises no patch and paints nothing",
            opening["frame"] is None and not started.is_set(), opening.get("frame"))

    fake.script = [reply(call("show_beat", region="counter", change="a full glass lands"),
                         says(lexicon_line(ZH, ["cheers"]), expression="delighted"))]
    turn = client.post(f"/api/journeys/{jid}/act", json={"text": "nihao"}, headers=hdr).json()
    frame = turn["frame"]
    T.check("the turn comes back with the words and a promise of the picture",
            frame is not None and frame["expression"] == "delighted"
            and len(frame["layers"]) == 2, frame)
    T.check("NARRATION DID NOT WAIT: the words came back with the paint unfinished",
            baked == [], baked)
    T.check("every layer carries its box in fractions of the plate",
            all(0 <= layer["left"] <= 1 and 0 < layer["width"] <= 1
                for layer in frame["layers"]), frame["layers"])

    state = client.get(f"/api/journeys/{jid}", headers=hdr).json()
    T.check("a refresh finds the same frame, so the scene survives a reload",
            state["frame"]["key"] == frame["key"])

    stale = client.get(f"/api/journeys/{jid}/frame/expr_deadbeef?token={body['token']}")
    T.check("a stale or unknown patch is a transparent pixel: the plate, exactly as it is",
            stale.status_code == 200 and stale.headers["content-type"] == "image/png"
            and stale.content == painter.TRANSPARENT_PNG)
    T.check("a patch without the journey token is refused",
            client.get(f"/api/journeys/{jid}/frame/{frame['layers'][0]['id']}").status_code
            == 403)

    T.check("the paint did start, in the background", started.wait(5))
    release.set()
    got = client.get(f"{frame['layers'][1]['url']}?token={body['token']}")
    T.check("the client's request joins the paint already in flight and gets the cutout",
            got.status_code == 200 and got.headers["content-type"] == "image/webp"
            and len(baked) == 2, (got.status_code, baked))
    T.check("a served cutout may be cached hard: its id is a hash of what it is",
            "immutable" in got.headers.get("cache-control", ""))

    # A painter that always fails must still leave the player looking at the scene.
    def broken(plate_path: Path, plan: Any) -> dict[str, Path]:
        raise RuntimeError("no credits tonight")

    app.state.frames = FrameService(bake=broken)
    fake.script = [reply(says(lexicon_line(ZH, ["friend"]), expression="puzzled"))]
    turn = client.post(f"/api/journeys/{jid}/act", json={"text": "nihao"}, headers=hdr).json()
    layer = turn["frame"]["layers"][-1]  # the face: the earlier beat is already on disk
    fell_back = client.get(f"{layer['url']}?token={body['token']}")
    T.check("a painter that fails outright still leaves the plate on screen",
            fell_back.status_code == 200 and fell_back.content == painter.TRANSPARENT_PNG)

    os.environ["POLYTALE_FRAMES"] = "0"
    try:
        fake.script = [reply(says(lexicon_line(ZH, ["cheers"]), expression="laughing"))]
        off = client.post(f"/api/journeys/{jid}/act", json={"text": "nihao"},
                          headers=hdr).json()
        T.check("switched off, the scene is simply the painting and the game plays on",
                off["frame"] is None and off["lines"], off.get("frame"))
    finally:
        os.environ.pop("POLYTALE_FRAMES", None)


if __name__ == "__main__":
    T.run("region geometry", test_geometry)
    T.run("pixel boxes", test_pixel_box)
    T.run("the frame plan and its cache keys", test_plan)
    T.run("baking and compositing", test_bake_and_composite)
    T.run("beats stack on the scene as it stands", test_beats_stack)
    T.run("a failed paint falls back to the plate", test_failure_falls_back)
    T.run("feathered seams", test_feather)
    T.run("env switches", test_switches)
    T.run("plate signature", test_signature)
    T.run("the transparent fallback", test_transparent_pixel)
    T.run("say carries the face", test_expression_tool)
    T.run("show_beat", test_beat_tool)
    T.run("a committed turn keeps the face and the beat", test_turn_commits_the_face)
    T.run("the server: text first, picture later", test_server)
    T.finish()
