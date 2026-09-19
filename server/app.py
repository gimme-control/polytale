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
from fastapi.responses import FileResponse
from pydantic import BaseModel

import media
from core import dm
from core.cartridge import CartridgeError, list_cartridges, resolve_art_path
from core.ledger import learning_view, request_help
from core.recap import build_recap
from core.state import Attempt, GameState
from core.views import find_line, public_state
from media import stt, tts
from server.sessions import BadToken, SessionNotFound, SessionStore, cartridge

log = logging.getLogger("polytale.server")

MAX_AUDIO_BYTES = 5 * 1024 * 1024
AUDIO_MIMES = {"audio/wav", "audio/x-wav", "audio/wave", "audio/webm", "audio/ogg",
               "audio/mp4", "audio/mpeg"}
# A hung model call must not pin the session lock; the Gemini client has its own timeout too.
TURN_TIMEOUT_S = float(os.environ.get("POLYTALE_TURN_TIMEOUT_S", "45"))


@dataclass
class Deps:
    """Side-effecting collaborators, swappable in tests."""

    run_turn: Callable[..., tuple[GameState, dict[str, Any]]] = dm.run_turn
    transcribe: Callable[..., stt.TranscriptionResult] = stt.transcribe
    synthesize: Callable[..., tts.AudioClip] = tts.synthesize


app = FastAPI(title="Polytale")
app.state.store = SessionStore()
app.state.deps = Deps()


def _store(request: Request) -> SessionStore:
    return request.app.state.store


def _deps(request: Request) -> Deps:
    return request.app.state.deps


def _session(request: Request, sid: str, token: str | None) -> GameState:
    try:
        return _store(request).authorize(sid, token)
    except SessionNotFound:
        raise HTTPException(404, "session not found") from None
    except BadToken:
        raise HTTPException(403, "bad session token") from None


def _prewarm(request: Request, state: GameState, lines: list[dict[str, Any]]) -> None:
    """Start TTS for freshly delivered lines so the client's audio GET is (nearly) a cache hit."""
    synth = _deps(request).synthesize
    cart = cartridge(state.cartridge_id)
    for line in lines:
        npc = cart.npc(line["speaker"])
        voice = npc.voice.model_dump() if npc else {}

        async def one(text: str = line["text"], lang: str = line["language"],
                      voice: dict = voice) -> None:
            try:
                await asyncio.to_thread(synth, text, language=lang, voice=voice)
            except Exception as exc:  # the audio GET retries and reports; text stays usable
                log.warning("prewarm failed: %s", exc)

        asyncio.get_running_loop().create_task(one())


# ------------------------------------------------------------------------- catalog


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, **media.speech_status()}


@app.get("/api/cartridges")
def cartridges() -> list[dict[str, Any]]:
    return list_cartridges()


@app.get("/api/cartridges/{cid}/art/{path:path}")
def art(cid: str, path: str) -> FileResponse:
    try:
        cart = cartridge(cid)
    except (CartridgeError, FileNotFoundError):
        raise HTTPException(404, "unknown cartridge") from None
    file = resolve_art_path(cart, path)
    if file is None or not file.is_file():
        raise HTTPException(404, "art not found")
    return FileResponse(file, headers={"Cache-Control": "public, max-age=3600"})


# ------------------------------------------------------------------------ sessions


class CreateBody(BaseModel):
    cartridge_id: str


class ActBody(BaseModel):
    attempt_id: str | None = None
    text: str | None = None
    tap_object_id: str | None = None


@app.post("/api/sessions")
def create_session(request: Request, body: CreateBody) -> dict[str, Any]:
    try:
        state, token = _store(request).create(body.cartridge_id)
    except (CartridgeError, FileNotFoundError):
        raise HTTPException(404, "unknown cartridge") from None
    cart = cartridge(state.cartridge_id)
    return {"session_id": state.session_id, "token": token, "state": public_state(state, cart)}


@app.get("/api/sessions/{sid}")
def get_session(request: Request, sid: str,
                x_session_token: str | None = Header(None)) -> dict[str, Any]:
    state = _session(request, sid, x_session_token)
    return public_state(state, cartridge(state.cartridge_id))


@app.post("/api/sessions/{sid}/start")
async def start(request: Request, sid: str,
                x_session_token: str | None = Header(None)) -> dict[str, Any]:
    async with _store(request).lock(sid):
        state = _session(request, sid, x_session_token)
        if state.started:
            raise HTTPException(409, "already started")
        new_state, result = dm.run_opening(state, cartridge(state.cartridge_id))
        _store(request).save(new_state)
    _prewarm(request, new_state, result["spoken_lines"])
    return result


@app.post("/api/sessions/{sid}/transcribe")
async def transcribe(
    request: Request,
    sid: str,
    audio: UploadFile = File(...),
    client_recording_id: str = Form(""),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    state = _session(request, sid, x_session_token)
    mime = (audio.content_type or "").split(";")[0].strip().lower()
    if mime not in AUDIO_MIMES:
        raise HTTPException(415, f"unsupported audio type {mime!r}")
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "recording too large")
    if not data:
        raise HTTPException(400, "empty recording")
    ll = cartridge(state.cartridge_id).language_learning
    target = ll.target_locale if ll else "en-US"
    support = ll.support_locale if ll else "en-US"
    try:
        result = await asyncio.to_thread(
            _deps(request).transcribe, data, mime, target_locale=target, support_locale=support
        )
    except media.SpeechTimeout:
        raise HTTPException(504, "transcription timed out — try again") from None
    except media.SpeechError as exc:
        log.warning("stt failed: %s", exc)
        raise HTTPException(503, "transcription unavailable — try again or type") from None

    attempt_id = f"a-{uuid.uuid4().hex[:12]}"
    # Locale comes from server state; the pending attempt is the trusted transcript record.
    async with _store(request).lock(sid):
        fresh = _session(request, sid, x_session_token)
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


def _attempt_from(state: GameState, body: ActBody) -> dict[str, Any]:
    given = [v is not None for v in (body.attempt_id, body.text, body.tap_object_id)]
    if sum(given) != 1:
        raise HTTPException(422, "send exactly one of attempt_id, text, tap_object_id")
    if body.attempt_id is not None:
        pending = state.attempts.get(body.attempt_id)
        if pending is None:
            raise HTTPException(404, "unknown attempt")
        if pending.consumed:
            raise HTTPException(409, "attempt already used")
        if not pending.transcript.strip():
            raise HTTPException(422, "nothing was heard in that recording")
        return pending.model_dump()
    new_id = f"a-{uuid.uuid4().hex[:12]}"
    if body.text is not None:
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "empty text")
        return {"attempt_id": new_id, "input_mode": "text", "transcript": text[:500]}
    return {"attempt_id": new_id, "input_mode": "tap", "transcript": "",
            "tapped_object_id": body.tap_object_id}


@app.post("/api/sessions/{sid}/act")
async def act(request: Request, sid: str, body: ActBody,
              x_session_token: str | None = Header(None)) -> dict[str, Any]:
    lock = _store(request).lock(sid)
    if lock.locked():
        raise HTTPException(409, "a turn is already in progress")
    async with lock:
        state = _session(request, sid, x_session_token)
        if not state.started:
            raise HTTPException(409, "session not started")
        if state.episode_complete:
            raise HTTPException(409, "episode complete")
        attempt = _attempt_from(state, body)
        cart = cartridge(state.cartridge_id)
        try:
            new_state, result = await asyncio.wait_for(
                asyncio.to_thread(_deps(request).run_turn, state, cart, attempt),
                timeout=TURN_TIMEOUT_S,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except (dm.TurnError, TimeoutError) as exc:
            # State is untouched and a voice attempt stays pending, so the learner can resend.
            log.warning("turn failed: %s", exc)
            raise HTTPException(502, "the story stalled — send that again") from None
        _store(request).save(new_state)
    _prewarm(request, new_state, result["spoken_lines"])
    return result


@app.post("/api/sessions/{sid}/help")
async def help_(request: Request, sid: str,
                x_session_token: str | None = Header(None)) -> dict[str, Any]:
    async with _store(request).lock(sid):
        state = _session(request, sid, x_session_token)
        cart = cartridge(state.cartridge_id)
        cue = request_help(state, cart)
        if cue is None:
            raise HTTPException(409, "no active learning beat")
        _store(request).save(state)
    line = cue.get("line")
    if line:
        _prewarm(request, state, [line])
    return {"cue": cue, "learning": learning_view(state, cart)}


@app.get("/api/sessions/{sid}/lines/{line_id}/audio")
async def line_audio(request: Request, sid: str, line_id: str,
                     token: str | None = Query(None),
                     x_session_token: str | None = Header(None)) -> FileResponse:
    state = _session(request, sid, token or x_session_token)
    cart = cartridge(state.cartridge_id)
    line = find_line(state, cart, line_id)
    if line is None:
        raise HTTPException(404, "line not found")
    npc = cart.npc(line.speaker)
    try:
        clip = await asyncio.to_thread(
            _deps(request).synthesize, line.text, language=line.language,
            voice=npc.voice.model_dump() if npc else {},
        )
    except media.SpeechError as exc:
        log.warning("tts failed for %s: %s", line_id, exc)
        raise HTTPException(503, "audio unavailable") from None
    return FileResponse(clip.path, media_type=clip.mime,
                        headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/sessions/{sid}/recap")
def recap(request: Request, sid: str,
          x_session_token: str | None = Header(None)) -> dict[str, Any]:
    state = _session(request, sid, x_session_token)
    if not state.episode_complete:
        raise HTTPException(409, "episode not complete")
    return build_recap(state, cartridge(state.cartridge_id))


@app.post("/api/sessions/{sid}/reset")
async def reset(request: Request, sid: str,
                x_session_token: str | None = Header(None)) -> dict[str, Any]:
    async with _store(request).lock(sid):
        state = _session(request, sid, x_session_token)
        fresh = _store(request).reset(state)
    return public_state(fresh, cartridge(fresh.cartridge_id))


if os.environ.get("POLYTALE_SERVE_WEB") == "1":
    from server.spa import mount_spa

    mount_spa(app, ROOT / "web" / "dist")
