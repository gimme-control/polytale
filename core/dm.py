"""DM turn loop: one Gemini call per round, typed tools, deterministic commits.

`run_turn` and `run_opening` work on a deep copy and return ``(new_state, TurnResult)``;
on any exception the caller keeps its original state (the attempt stays unconsumed).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from core import gemini, ledger
from core.cartridge import Cartridge
from core.prompt import build_snapshot, build_system_prompt
from core.recap import build_recap
from core.state import (
    Attempt,
    EvidenceEntry,
    GameState,
    NarrationEntry,
    NpcEntry,
    PlayerEntry,
    SpokenLine,
)
from core.tools import TERMINAL_TOOL, ToolContext, execute, is_error, tool_declarations
from core.views import world_view

log = logging.getLogger("polytale.dm")

MAX_ROUNDS = 6
MAX_NUDGES = 2


class TurnError(RuntimeError):
    """The turn could not be completed; the caller keeps the previous state."""


# ---------------------------------------------------------------- response helpers


def _candidate(response: Any) -> Any:
    candidates = getattr(response, "candidates", None) or []
    return candidates[0] if candidates else None


def _parts(candidate: Any) -> list[Any]:
    content = getattr(candidate, "content", None) if candidate is not None else None
    return list(getattr(content, "parts", None) or [])


def _visible_text(parts: list[Any]) -> str:
    return "".join(
        getattr(p, "text", None) or ""
        for p in parts
        if not getattr(p, "thought", False) and not getattr(p, "function_call", None)
    ).strip()


def _generate(client: Any, models: list[str], contents: list[Any], config: Any) -> tuple[Any, str]:
    """One generate_content call, cascading across models on errors."""
    errors: list[str] = []
    for model in models:
        try:
            return client.models.generate_content(model=model, contents=contents, config=config), model
        except Exception as exc:  # provider errors are opaque; classify and cascade
            errors.append(f"{model}: {exc}")
            if gemini.error_kind(exc) == "credits":
                raise TurnError(gemini.friendly_api_error(exc)) from exc
            log.warning("dm: model %s failed (%s); cascading", model, gemini.error_kind(exc))
    raise TurnError("DM call failed on every model: " + " | ".join(errors[-3:]))


# ---------------------------------------------------------------- loop


def _run_loop(
    working: GameState,
    cartridge: Cartridge,
    snapshot: str,
    ctx: ToolContext,
    client: Any,
    models: list[str],
    trace: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=build_system_prompt(cartridge),
        tools=tool_declarations(cartridge),
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.ANY
            )
        ),
        thinking_config=gemini.thinking_config(types),
    )
    contents: list[Any] = [types.Content(role="user", parts=[types.Part(text=snapshot)])]
    nudges = 0
    for round_index in range(MAX_ROUNDS):
        started = time.monotonic()
        response, model = _generate(client, models, contents, config)
        candidate = _candidate(response)
        content = getattr(candidate, "content", None) if candidate is not None else None
        parts = _parts(candidate)
        calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
        round_trace: dict[str, Any] = {
            "round": round_index, "model": model,
            "ms": int((time.monotonic() - started) * 1000), "calls": [],
        }
        if trace is not None:
            trace.append(round_trace)

        if not calls:
            if nudges >= MAX_NUDGES:
                raise TurnError("DM replied without tool calls after nudges")
            nudges += 1
            text = _visible_text(parts)
            log.warning("dm: prose-only reply (%d chars); nudging (%d/%d)", len(text), nudges,
                        MAX_NUDGES)
            contents.append(
                content if content is not None and parts
                else types.Content(role="model", parts=[types.Part(text=text or "(no reply)")])
            )
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part(text=(
                        "Your reply had no tool calls. Commit the turn with tool calls now: "
                        "world/ledger tools as needed, then deliver_narration."
                    ))],
                )
            )
            continue

        contents.append(content)
        ctx.round_errors = []
        receipts: dict[int, str] = {}
        # Non-terminal calls run first so deliver_narration sees this round's errors.
        order = sorted(range(len(calls)), key=lambda i: calls[i].name == TERMINAL_TOOL)
        for i in order:
            call = calls[i]
            name = call.name or ""
            args = dict(call.args or {})
            if name == TERMINAL_TOOL and ctx.terminal is not None:
                receipt = "ERROR: narration was already delivered in this response"
            else:
                receipt = execute(name, working, cartridge, args, ctx)
            if is_error(receipt) and name != TERMINAL_TOOL:
                ctx.round_errors.append(f"{name}: {receipt.splitlines()[0]}")
            receipts[i] = receipt
            round_trace["calls"].append({"name": name, "args": args, "receipt": receipt})
        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=getattr(call, "id", None),
                            name=call.name or "",
                            response={"result": receipts[i]},
                        )
                    )
                    for i, call in enumerate(calls)
                ],
            )
        )
        if ctx.terminal is not None:
            return ctx.terminal
    raise TurnError(f"DM exceeded {MAX_ROUNDS} rounds without a valid deliver_narration")


# ---------------------------------------------------------------- commit


def _commit(
    working: GameState,
    cartridge: Cartridge,
    ctx: ToolContext,
    terminal: dict[str, Any],
    transcript_start: int,
    started_at: float,
) -> dict[str, Any]:
    turn = ctx.turn
    lines = [
        SpokenLine.build(cartridge, working.session_id, f"t{turn}-l{i}", spec)
        for i, spec in enumerate(terminal["spoken_lines"])
    ]
    narration = terminal["narration"]
    if narration:
        working.transcript.append(NarrationEntry(turn=turn, text=narration))
    for line in lines:
        working.transcript.append(NpcEntry(turn=turn, line=line))
    ledger.note_spoken_lines(working, cartridge, lines)
    working.turn = turn + 1
    evidence = [
        e.model_dump() for e in working.transcript[transcript_start:]
        if isinstance(e, EvidenceEntry)
    ]
    return {
        "turn": turn,
        "narration": narration,
        "spoken_lines": [line.model_dump() for line in lines],
        "world": world_view(working, cartridge),
        "learning": ledger.learning_view(working, cartridge),
        "evidence": evidence,
        "episode_complete": working.episode_complete,
        "recap": build_recap(working, cartridge) if working.episode_complete else None,
        "latency_ms": int((time.monotonic() - started_at) * 1000),
    }


def _attempt(state: GameState, cartridge: Cartridge, raw: dict[str, Any]) -> Attempt:
    attempt = Attempt.model_validate(
        {k: v for k, v in raw.items() if k in Attempt.model_fields and k != "consumed"}
    )
    existing = state.attempts.get(attempt.attempt_id)
    if existing is not None and existing.consumed:
        raise ValueError(f"attempt {attempt.attempt_id} was already consumed")
    if attempt.input_mode == "tap":
        if cartridge.object(attempt.tapped_object_id or "") is None:
            raise ValueError(f"tap attempt names unknown object {attempt.tapped_object_id!r}")
    elif not attempt.transcript.strip():
        raise ValueError("speech/text attempt has an empty transcript")
    return attempt


def run_turn(
    state: GameState,
    cartridge: Cartridge,
    attempt: dict[str, Any],
    *,
    client: Any = None,
    models: list[str] | None = None,
    trace: list[dict[str, Any]] | None = None,
) -> tuple[GameState, dict[str, Any]]:
    """Play one player attempt through the DM. Returns ``(new_state, TurnResult)``.

    ``attempt``: ``{attempt_id, input_mode: speech|text|tap, transcript, romanized?,
    detected_languages?, confidence?, tapped_object_id?}``. Raises ValueError for a bad
    attempt / unstarted session and TurnError when the model fails; the input state is
    never mutated.
    """
    started_at = time.monotonic()
    if not state.started:
        raise ValueError("session not started: run_opening first")
    working = state.model_copy(deep=True)
    record = _attempt(working, cartridge, attempt)
    turn = working.turn
    snapshot = build_snapshot(working, cartridge, record.model_dump())
    record.consumed, record.turn = True, turn
    working.attempts[record.attempt_id] = record
    transcript_start = len(working.transcript)
    working.transcript.append(
        PlayerEntry(
            turn=turn, attempt_id=record.attempt_id, input_mode=record.input_mode,
            transcript=record.transcript, romanized=record.romanized,
            tapped_object_id=record.tapped_object_id,
        )
    )
    ctx = ToolContext(turn=turn, attempt=record)
    terminal = _run_loop(
        working, cartridge, snapshot, ctx,
        client if client is not None else gemini.get_client(),
        models or gemini.model_cascade(),
        trace,
    )
    return working, _commit(working, cartridge, ctx, terminal, transcript_start, started_at)


def run_opening(state: GameState, cartridge: Cartridge) -> tuple[GameState, dict[str, Any]]:
    """Apply the authored opening through the same executors (no model call)."""
    started_at = time.monotonic()
    if state.started:
        raise ValueError("session already started")
    working = state.model_copy(deep=True)
    ctx = ToolContext(turn=working.turn)
    transcript_start = len(working.transcript)
    opening = cartridge.opening
    for action in opening.actions:
        receipt = execute(action.tool, working, cartridge, dict(action.args), ctx)
        if is_error(receipt):
            raise TurnError(f"opening action {action.tool} failed: {receipt}")
    receipt = execute(
        TERMINAL_TOOL, working, cartridge,
        {
            "narration": opening.narration,
            "spoken_lines": [line.model_dump() for line in opening.spoken_lines],
        },
        ctx,
    )
    if ctx.terminal is None:
        raise TurnError(f"opening narration invalid: {receipt}")
    working.started = True
    return working, _commit(working, cartridge, ctx, ctx.terminal, transcript_start, started_at)
