"""Polytale REST API. Run: ``uvicorn server.app:app --port 8100`` from ``polytale/``.

Text first, media later: a turn returns its lines immediately and starts synthesizing their
audio in the background; the client's audio GET joins that work through the TTS per-key lock.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

import media
from core import dm
from core.content import CONTENT_ROOT, Scene, resolve_art_path
from core.state import Attempt, Journey, Line
from core.views import (
    art_url,
    find_line,
    language_view,
    progress_view,
    public_state,
    story_view,
)
from core.vocab import request_help
from media import frames as painter
from media import stt, tts
from server.frames import FrameService
from server.sessions import BadToken, JourneyNotFound, JourneyStore, content

log = logging.getLogger("polytale.server")

DEFAULT_LANGUAGE = os.environ.get("POLYTALE_LANGUAGE", "zh-CN")
MAX_AUDIO_BYTES = 5 * 1024 * 1024
AUDIO_MIMES = {"audio/wav", "audio/x-wav", "audio/wave", "audio/webm", "audio/ogg",
               "audio/mp4", "audio/mpeg"}
# A hung model call must not pin the journey lock; the Gemini client has its own timeout too.
TURN_TIMEOUT_S = float(os.environ.get("POLYTALE_TURN_TIMEOUT_S", "45"))


@dataclass
class Deps:
    """Side-effecting collaborators, swappable in tests."""

    run_turn: Callable[..., tuple[Journey, dm.TurnResult]] = dm.run_turn
    run_opening: Callable[..., tuple[Journey, dm.TurnResult]] = dm.run_opening
    transcribe: Callable[..., stt.TranscriptionResult] = stt.transcribe
    synthesize: Callable[..., tts.AudioClip] = tts.synthesize


app = FastAPI(title="Polytale")
app.state.store = JourneyStore()
app.state.deps = Deps()
app.state.frames = FrameService()


def _store(request: Request) -> JourneyStore:
    return request.app.state.store


def _deps(request: Request) -> Deps:
    return request.app.state.deps


def _frames(request: Request) -> FrameService:
    return request.app.state.frames


def _scene_of(journey: Journey) -> Scene | None:
    return content().scene(journey.scene.scene_id) if journey.scene is not None else None


def _state(request: Request, journey: Journey) -> dict[str, Any]:
    """PublicState with the scene's current frame attached (no painting is started)."""
    state = public_state(journey, content())
    scene = _scene_of(journey)
    if scene is not None:
        state.frame = _frames(request).view(journey, scene)
    return _dump(state)


def _journey(request: Request, jid: str, token: str | None) -> Journey:
    try:
        return _store(request).authorize(jid, token)
    except JourneyNotFound:
        raise HTTPException(404, "journey not found") from None
    except BadToken:
        raise HTTPException(403, "bad journey token") from None


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True)


def _voice(journey: Journey) -> dict[str, Any]:
    """The scene character's own voice."""
    assert journey.scene is not None
    return content().scene(journey.scene.scene_id).npc.voice.model_dump()


async def _run_model(request: Request, fn: Callable[..., Any], *args: Any) -> Any:
    """Run a DM call off the event loop; map its failures to HTTP errors (state untouched)."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=TURN_TIMEOUT_S)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except dm.OutOfCredits as exc:
        log.error("model provider out of credits: %s", exc)
        raise HTTPException(402, "The AI account behind this demo is out of credits. "
                                 "Top up the Gemini API key, then try again.") from None
    except (dm.TurnError, TimeoutError) as exc:
        log.warning("turn failed: %s", exc)
        raise HTTPException(502, "that didn't go through — send it again") from None


def _prewarm(request: Request, journey: Journey, lines: list[Line]) -> None:
    """Start TTS for fresh lines so the client's audio GET is (nearly) a cache hit."""
    synth, voice = _deps(request).synthesize, _voice(journey)

    async def one(text: str) -> None:
        try:
            await asyncio.to_thread(synth, text, language=journey.language, voice=voice)
        except Exception as exc:  # the audio GET retries and reports; text stays usable
            log.warning("prewarm failed: %s", exc)

    for line in lines:
        asyncio.get_running_loop().create_task(one(line.text))


def _promise_frame(request: Request, journey: Journey, result: dm.TurnResult) -> None:
    """Start painting the scene and tell the client where to collect it.

    The turn is already decided: this only ever adds a URL to the payload. Nothing here
    blocks, and nothing here can fail the turn.
    """
    scene = _scene_of(journey)
    if scene is None:
        return
    try:
        result.frame = _frames(request).start(journey, scene)
    except Exception as exc:  # noqa: BLE001 — the scene simply does not react this turn
        log.warning("frame not started: %s", exc)


# ------------------------------------------------------------------------- catalog


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, **media.speech_status(), "language": DEFAULT_LANGUAGE}


@app.get("/api/catalog")
def catalog() -> dict[str, Any]:
    c = content()
    return {
        "story": _dump(story_view(c)),
        "language": _dump(language_view(c.language(DEFAULT_LANGUAGE))),
        "languages": [{"locale": lang.locale, "name": lang.name,
                       "native_name": lang.native_name}
                      for lang in sorted(c.languages.values(), key=lambda x: x.locale)],
        "scenes": [{"id": s.id, "name": s.name, "tagline": s.tagline, "intro": s.intro,
                    "cover_url": art_url(s.id, s.art.cover)}
                   for s in (c.scene(sid) for sid in c.journey.scenes)],
    }


@app.get("/api/story/art")
def story_art() -> FileResponse:
    """The story's title art (``journey.json`` → ``art``, confined to the content root)."""
    rel = content().journey.art
    file = (CONTENT_ROOT / rel).resolve()
    if not rel or not file.is_relative_to(CONTENT_ROOT.resolve()) or not file.is_file():
        raise HTTPException(404, "no title art")
    return FileResponse(file, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/scenes/{scene_id}/art/{path:path}")
def art(scene_id: str, path: str) -> FileResponse:
    scene = content().scenes.get(scene_id)
    if scene is None:
        raise HTTPException(404, "unknown scene")
    try:
        file = resolve_art_path(scene, path)
    except ValueError:
        raise HTTPException(404, "art not found") from None
    if not file.is_file():
        raise HTTPException(404, "art not found")
    return FileResponse(file, headers={"Cache-Control": "public, max-age=3600"})


# ------------------------------------------------------------------------ journeys


class CreateBody(BaseModel):
    language: str | None = None


class SceneBody(BaseModel):
    scene_id: str | None = None
    restart: bool = False


class ActBody(BaseModel):
    attempt_id: str | None = None
    text: str | None = None


@app.post("/api/journeys")
def create_journey(request: Request, body: CreateBody) -> dict[str, Any]:
    try:
        journey, token = _store(request).create(language=body.language or DEFAULT_LANGUAGE)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"journey_id": journey.journey_id, "token": token,
            "state": _dump(public_state(journey, content()))}


@app.get("/api/journeys/{jid}")
def get_journey(request: Request, jid: str,
                x_journey_token: str | None = Header(None)) -> dict[str, Any]:
    return _state(request, _journey(request, jid, x_journey_token))


@app.post("/api/journeys/{jid}/scene")
async def enter_scene(request: Request, jid: str, body: SceneBody,
                      x_journey_token: str | None = Header(None)) -> dict[str, Any]:
    """Enter the next (or named) scene and play the character's opening turn."""
    lock = _store(request).lock(jid)
    if lock.locked():
        raise HTTPException(409, "a turn is already in progress")
    async with lock:
        journey = _journey(request, jid, x_journey_token)
        if journey.game.ending_id is not None:
            raise HTTPException(409, "the story has ended")
        in_play = journey.scene is not None and journey.scene.started and not journey.scene.complete
        if in_play and not body.restart:
            raise HTTPException(409, "a scene is in progress")
        try:
            entered = dm.enter_scene(journey, content(), body.scene_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        new_journey, result = await _run_model(request, _deps(request).run_opening,
                                               entered, content())
        _store(request).save(new_journey)
    _prewarm(request, new_journey, result.lines)
    _promise_frame(request, new_journey, result)
    return _dump(result)


@app.post("/api/journeys/{jid}/transcribe")
async def transcribe(
    request: Request,
    jid: str,
    audio: UploadFile = File(...),
    client_recording_id: str = Form(""),
    x_journey_token: str | None = Header(None),
) -> dict[str, Any]:
    journey = _journey(request, jid, x_journey_token)
    mime = (audio.content_type or "").split(";")[0].strip().lower()
    if mime not in AUDIO_MIMES:
        raise HTTPException(415, f"unsupported audio type {mime!r}")
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "recording too large")
    if not data:
        raise HTTPException(400, "empty recording")
    # The language comes from server state, never from the client.
    lang = content().language(journey.language)
    hint = stt.LanguageHint(lang.locale, lang.name,
                            lang.romanization.system if lang.romanization else None)
    try:
        result = await asyncio.to_thread(_deps(request).transcribe, data, mime,
                                         target=hint, support_locale="en-US")
    except media.SpeechTimeout:
        raise HTTPException(504, "transcription timed out — try again") from None
    except media.SpeechError as exc:
        log.warning("stt failed: %s", exc)
        raise HTTPException(503, "transcription unavailable — try again or type") from None

    attempt_id = f"a-{uuid.uuid4().hex[:12]}"
    async with _store(request).lock(jid):
        fresh = _journey(request, jid, x_journey_token)
        fresh.attempts[attempt_id] = Attempt(
            attempt_id=attempt_id, input_mode="speech", transcript=result.transcript,
            romanized=result.romanized, detected_languages=list(result.detected_languages),
            confidence=result.confidence,
        )
        _store(request).save(fresh)
    return {
        "attempt_id": attempt_id,
        "client_recording_id": client_recording_id,
        "transcript": result.transcript,
        "romanized": result.romanized,
        "detected_languages": list(result.detected_languages),
        "confidence": result.confidence,
        "requires_confirmation": stt.needs_confirmation(result),
        "provider": result.provider,
    }


def _attempt_from(journey: Journey, body: ActBody) -> dict[str, Any]:
    given = [v is not None for v in (body.attempt_id, body.text)]
    if sum(given) != 1:
        raise HTTPException(422, "send exactly one of attempt_id, text")
    if body.attempt_id is not None:
        pending = journey.attempts.get(body.attempt_id)
        if pending is None:
            raise HTTPException(404, "unknown attempt")
        if pending.consumed:
            raise HTTPException(409, "attempt already used")
        if not pending.transcript.strip():
            raise HTTPException(422, "nothing was heard in that recording")
        return pending.model_dump()
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(422, "empty text")
    return {"attempt_id": f"a-{uuid.uuid4().hex[:12]}", "input_mode": "text",
            "transcript": text[:300]}


@app.post("/api/journeys/{jid}/act")
async def act(request: Request, jid: str, body: ActBody,
              x_journey_token: str | None = Header(None)) -> dict[str, Any]:
    lock = _store(request).lock(jid)
    if lock.locked():
        raise HTTPException(409, "a turn is already in progress")
    async with lock:
        journey = _journey(request, jid, x_journey_token)
        if journey.scene is None or not journey.scene.started:
            raise HTTPException(409, "no scene in play")
        if journey.scene.complete:
            raise HTTPException(409, "scene complete")
        attempt = _attempt_from(journey, body)
        new_journey, result = await _run_model(request, _deps(request).run_turn,
                                               journey, content(), attempt)
        _store(request).save(new_journey)
    _prewarm(request, new_journey, result.lines)
    _promise_frame(request, new_journey, result)
    return _dump(result)


@app.post("/api/journeys/{jid}/help")
async def help_(request: Request, jid: str,
                x_journey_token: str | None = Header(None)) -> dict[str, Any]:
    async with _store(request).lock(jid):
        journey = _journey(request, jid, x_journey_token)
        try:
            given = request_help(journey)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        _store(request).save(journey)
    return {"help": _dump(given), "progress": _dump(progress_view(journey, content()))}


@app.post("/api/journeys/{jid}/finish")
async def finish(request: Request, jid: str,
                 x_journey_token: str | None = Header(None)) -> dict[str, Any]:
    async with _store(request).lock(jid):
        journey = _journey(request, jid, x_journey_token)
        try:
            summary = dm.finish_scene(journey, content())
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        _store(request).save(journey)
    return _dump(summary)


async def _audio(request: Request, journey: Journey, text: str, what: str) -> FileResponse:
    try:
        clip = await asyncio.to_thread(_deps(request).synthesize, text,
                                       language=journey.language, voice=_voice(journey))
    except media.SpeechError as exc:
        log.warning("tts failed for %s: %s", what, exc)
        raise HTTPException(503, "audio unavailable") from None
    return FileResponse(clip.path, media_type=clip.mime,
                        headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/journeys/{jid}/lines/{line_id}/audio")
async def line_audio(request: Request, jid: str, line_id: str,
                     token: str | None = Query(None),
                     x_journey_token: str | None = Header(None)) -> FileResponse:
    journey = _journey(request, jid, token or x_journey_token)
    line = find_line(journey, line_id)
    if line is None:
        raise HTTPException(404, "line not found")
    return await _audio(request, journey, line.text, line_id)


@app.get("/api/journeys/{jid}/frame/{layer_id}")
async def frame_layer(request: Request, jid: str, layer_id: str,
                      token: str | None = Query(None),
                      x_journey_token: str | None = Header(None)) -> Response:
    """One patch of the living scene, as a cutout the client lays over the base plate.

    It waits on the paint the turn already started. Anything that goes wrong — switched off,
    timed out, refused, a stale URL — comes back as a transparent pixel, which draws the
    plate exactly as it is. The player never sees a broken or blank scene.
    """
    journey = _journey(request, jid, token or x_journey_token)
    scene = _scene_of(journey)
    path = None
    if scene is not None:
        try:
            path = await _frames(request).layer_file(journey, scene, layer_id)
        except Exception as exc:  # noqa: BLE001 — the plate is always a safe answer
            log.warning("frame layer %s failed: %s", layer_id, exc)
    if path is None:
        return Response(painter.TRANSPARENT_PNG, media_type="image/png",
                        headers={"Cache-Control": "no-store"})
    # The id is a hash of the plate and the change, so this file can never mean anything else.
    return FileResponse(path, media_type="image/webp",
                        headers={"Cache-Control": "private, max-age=86400, immutable"})


@app.get("/api/journeys/{jid}/items/{item_id}/audio")
async def item_audio(request: Request, jid: str, item_id: str,
                     token: str | None = Query(None),
                     x_journey_token: str | None = Header(None)) -> FileResponse:
    """The bare word, for the summary screen. Refused during play: it would reveal the list."""
    journey = _journey(request, jid, token or x_journey_token)
    if journey.scene is None or not journey.scene.complete:
        raise HTTPException(409, "available on the summary only")
    if item_id not in content().scene(journey.scene.scene_id).targets:
        raise HTTPException(404, "item not in this scene")
    return await _audio(request, journey, content().language(journey.language).items[item_id].text,
                        item_id)


@app.post("/api/journeys/{jid}/reset")
async def reset(request: Request, jid: str,
                x_journey_token: str | None = Header(None)) -> dict[str, Any]:
    async with _store(request).lock(jid):
        journey = _journey(request, jid, x_journey_token)
        fresh = _store(request).reset(journey)
    return _dump(public_state(fresh, content()))


if os.environ.get("POLYTALE_SERVE_WEB") == "1":
    from server.spa import mount_spa

    mount_spa(app, ROOT / "web" / "dist")
