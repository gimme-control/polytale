"""The character's turn loop: one Gemini call per round, typed tools, deterministic commits.

``run_opening`` and ``run_turn`` work on a deep copy and return ``(new_journey, TurnResult)``;
on any exception the caller keeps its original journey (the attempt stays unconsumed).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel

from core import game, gemini, vocab
from core.content import Content
from core.prompt import build_snapshot, build_system_prompt
from core.state import (
    Attempt,
    Entry,
    Exchange,
    Journey,
    LearnerEntry,
    Line,
    NarrationEntry,
    NpcEntry,
    SceneRun,
    Summary,
    line_audio_url,
)
from core.summary import build_summary
from core.tools import (
    TERMINAL_TOOL,
    ToolContext,
    complete_ready_goals,
    execute,
    is_error,
    tool_declarations,
)
from core.views import Ending, GameView, Progress, ending_view, game_view, progress_view

log = logging.getLogger("polytale.dm")

MAX_ROUNDS = 6
MAX_NUDGES = 2


class TurnError(RuntimeError):
    """The turn could not be completed; the caller keeps the previous journey."""


class OutOfCredits(TurnError):
    """The model provider refused for billing reasons; retrying cannot help until it is funded."""


class TurnResult(BaseModel):
    turn: int
    lines: list[Line]
    narration: str | None
    mood: str
    zones: dict[str, str]
    events: list[Entry]  # every transcript entry this turn added, in order
    progress: Progress
    scene_complete: bool
    summary: Summary | None
    game: GameView
    ending: Ending | None  # set on the turn that resolves the story
    latency_ms: int


# ---------------------------------------------------------------- scene flow


def enter_scene(journey: Journey, content: Content, scene_id: str | None = None) -> Journey:
    """A NEW journey positioned at a fresh, unstarted scene (the input is not mutated).

    Default target: the scene in play when it is incomplete (a restart), else the next one in
    journey order. A completed previous scene's summary is archived into ``history``.
    """
    if journey.game.ending_id is not None:
        raise ValueError("the story has ended")
    working = journey.model_copy(deep=True)
    order = content.journey.scenes
    previous = working.scene
    if scene_id is not None:
        if scene_id not in order:
            raise ValueError(f"unknown scene {scene_id!r}")
        index = order.index(scene_id)
    else:
        index = working.scene_index + (1 if previous is not None and previous.complete else 0)
        if index >= len(order):
            raise ValueError("the journey has no further scene")
    if previous is not None and previous.complete:
        working.history.append(build_summary(working, content))
    scene = content.scene(order[index])
    if previous is None or previous.scene_id != scene.id:
        game.spend_minutes(working, scene.travel_minutes)  # getting there costs clock
    working.scene_index = index
    working.scene = SceneRun(scene_id=scene.id, zones={o.id: o.zone for o in scene.objects})
    return working


def _close_act(journey: Journey, content: Content) -> None:
    """Mark the act complete and resolve the ending when the story is over (in place).

    The story is over when the last act's goals are done, or the clock has run out in any act.
    """
    run = journey.scene
    assert run is not None
    run.complete = True
    last = journey.scene_index == len(content.journey.scenes) - 1
    if journey.game.ending_id is None and (last or game.minutes_left(journey, content) == 0):
        journey.game.ending_id = game.resolve_ending(journey, content).id


def finish_scene(journey: Journey, content: Content) -> Summary:
    """End the scene in play now (in place) and return its summary."""
    if journey.scene is None or not journey.scene.started:
        raise ValueError("no scene in play")
    _close_act(journey, content)
    return build_summary(journey, content)


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
                raise OutOfCredits(gemini.friendly_api_error(exc)) from exc
            log.warning("dm: model %s failed (%s); cascading", model, gemini.error_kind(exc))
    raise TurnError("model call failed on every model: " + " | ".join(errors[-3:]))


# ---------------------------------------------------------------- loop


def _run_loop(
    working: Journey,
    content: Content,
    snapshot: str,
    ctx: ToolContext,
    client: Any,
    models: list[str],
    trace: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=build_system_prompt(content, ctx.scene, ctx.language),
        tools=tool_declarations(ctx.scene, ctx.language),
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
        reply = getattr(candidate, "content", None) if candidate is not None else None
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
                raise TurnError("the model replied without tool calls after nudges")
            nudges += 1
            text = _visible_text(parts)
            log.warning("dm: prose-only reply (%d chars); nudging (%d/%d)", len(text), nudges,
                        MAX_NUDGES)
            contents.append(
                reply if reply is not None and parts
                else types.Content(role="model", parts=[types.Part(text=text or "(no reply)")])
            )
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part(text=(
                        "Your reply had no tool calls. Commit the turn with tool calls now: "
                        f"scene tools as needed, then {TERMINAL_TOOL}."
                    ))],
                )
            )
            continue

        contents.append(reply)
        ctx.round_errors = []
        receipts: dict[int, str] = {}
        # Non-terminal calls run first so `say` sees this round's errors.
        order = sorted(range(len(calls)), key=lambda i: calls[i].name == TERMINAL_TOOL)
        for i in order:
            call = calls[i]
            name = call.name or ""
            args = dict(call.args or {})
            if name == TERMINAL_TOOL and ctx.terminal is not None:
                receipt = f"ERROR: {TERMINAL_TOOL} was already delivered in this response"
            else:
                receipt = execute(name, working, args, ctx)
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
    raise TurnError(f"the model exceeded {MAX_ROUNDS} rounds without a valid {TERMINAL_TOOL}")


# ---------------------------------------------------------------- commit


def _commit(
    working: Journey, content: Content, ctx: ToolContext, terminal: dict[str, Any],
    transcript_start: int, started_at: float,
) -> TurnResult:
    run = working.scene
    assert run is not None
    turn, scene, language = run.turn, ctx.scene, ctx.language
    joiner = " " if language.word_spacing else ""
    lines = [
        Line(
            line_id=(line_id := f"s{working.scene_index}-t{turn}-l{i}"),
            speaker_name=scene.npc.display_name(language.locale),
            segments=spec["segments"],
            text=joiner.join(s.t for s in spec["segments"]),
            romanization=" ".join(s.r for s in spec["segments"] if s.r),
            item_ids=spec["item_ids"],
            highlight_object_ids=spec["highlight_object_ids"],
            audio_url=line_audio_url(working.journey_id, line_id),
        )
        for i, spec in enumerate(terminal["lines"])
    ]
    narration = terminal["narration"] or None
    if narration:
        run.transcript.append(NarrationEntry(turn=turn, text=narration))
    run.transcript += [NpcEntry(turn=turn, line=line) for line in lines]

    own_object = {o.item_id for o in scene.objects}
    posed: list[str] = []
    highlighted: list[str] = []
    for line in lines:
        vocab.note_appearances(working, scene.id, line.item_ids)
        posed += line.item_ids
        highlighted += [scene.object(oid).item_id  # type: ignore[union-attr]
                        for oid in line.highlight_object_ids]
        if line.highlight_object_ids:  # a lit line also supports its object-less words
            highlighted += [i for i in line.item_ids if i not in own_object]
    for item_id in ctx.owed:  # an owed word came back with no highlight: one pass offered
        if item_id in posed and item_id not in highlighted:
            run.unsupported_offers[item_id] = run.unsupported_offers.get(item_id, 0) + 1
    run.exchange = Exchange(
        posed_item_ids=list(dict.fromkeys(posed)),
        highlighted_item_ids=list(dict.fromkeys(highlighted)),
        line_ids=[line.line_id for line in lines],
        intent_hint=terminal["intent_hint"],
    )
    run.mood = terminal["mood"]
    run.started = True
    run.turn = turn + 1
    if ctx.attempt is not None:  # the clock ticks in code, once per player turn
        game.spend_minutes(working, content.journey.clock.minutes_per_turn)
    complete_ready_goals(working, scene)
    resolved_before = working.game.ending_id
    if (all(g.id in run.goals_done for g in scene.goals)
            or game.minutes_left(working, content) == 0):
        _close_act(working, content)
    ended = working.game.ending_id is not None and resolved_before is None
    return TurnResult(
        turn=turn, lines=lines, narration=narration, mood=run.mood, zones=dict(run.zones),
        events=list(run.transcript[transcript_start:]),
        progress=progress_view(working, content),
        scene_complete=run.complete,
        summary=build_summary(working, content) if run.complete else None,
        game=game_view(working, content),
        ending=ending_view(working, content) if ended else None,
        latency_ms=int((time.monotonic() - started_at) * 1000),
    )


def _play(
    journey: Journey, content: Content, attempt: Attempt | None, *,
    client: Any, models: list[str] | None, trace: list[dict[str, Any]] | None,
) -> tuple[Journey, TurnResult]:
    started_at = time.monotonic()
    working = journey.model_copy(deep=True)
    run = working.scene
    assert run is not None
    scene, language = content.scene(run.scene_id), content.language(working.language)
    persona = content.persona(working.persona_id) or content.personas[0]
    snapshot = build_snapshot(working, content, scene, language, persona, attempt)
    transcript_start = len(run.transcript)
    if attempt is not None:
        attempt.consumed, attempt.turn = True, run.turn
        working.attempts[attempt.attempt_id] = attempt
        run.transcript.append(
            LearnerEntry(
                turn=run.turn, attempt_id=attempt.attempt_id, input_mode=attempt.input_mode,
                transcript=attempt.transcript, romanized=attempt.romanized,
                tapped_object_id=attempt.tapped_object_id, action_id=attempt.action_id,
            )
        )
    ctx = ToolContext(scene=scene, language=language, attempt=attempt,
                      mastered=vocab.mastered_items(working),
                      owed=tuple(vocab.owed_items(working, scene)))
    terminal = _run_loop(
        working, content, snapshot, ctx,
        client if client is not None else gemini.get_client(),
        models or gemini.model_cascade(),
        trace,
    )
    return working, _commit(working, content, ctx, terminal, transcript_start, started_at)


def run_opening(
    journey: Journey, content: Content, *, client: Any = None,
    models: list[str] | None = None, trace: list[dict[str, Any]] | None = None,
) -> tuple[Journey, TurnResult]:
    """The character opens the scene (a real model turn with no learner input)."""
    if journey.scene is None:
        raise ValueError("no scene entered: enter_scene first")
    if journey.scene.started:
        raise ValueError("scene already started")
    return _play(journey, content, None, client=client, models=models, trace=trace)


def run_turn(
    journey: Journey, content: Content, attempt: Attempt | dict[str, Any], *,
    client: Any = None, models: list[str] | None = None,
    trace: list[dict[str, Any]] | None = None,
) -> tuple[Journey, TurnResult]:
    """Play one learner attempt. Returns ``(new_journey, TurnResult)``.

    ``attempt``: ``{attempt_id, input_mode: speech|text|tap, transcript, romanized?,
    detected_languages?, confidence?, tapped_object_id?, action_id?}``. Raises ValueError for a bad attempt
    or a scene that is not in play, TurnError when the model fails; the input journey is never
    mutated.
    """
    run = journey.scene
    if run is None or not run.started:
        raise ValueError("scene not started: run_opening first")
    if run.complete:
        raise ValueError("scene is complete: enter the next scene")
    raw = attempt.model_dump() if isinstance(attempt, Attempt) else dict(attempt)
    record = Attempt.model_validate(
        {k: v for k, v in raw.items() if k in Attempt.model_fields and k not in ("consumed", "turn")}
    )
    existing = journey.attempts.get(record.attempt_id)
    if existing is not None and existing.consumed:
        raise ValueError(f"attempt {record.attempt_id} was already consumed")
    if record.input_mode == "tap":
        tapped = content.scene(run.scene_id).object(record.tapped_object_id or "")
        if tapped is None:
            raise ValueError(f"tap attempt names unknown object {record.tapped_object_id!r}")
        record.action_id = record.action_id or "point"
        if record.action_id not in tapped.actions:
            raise ValueError(f"{tapped.id} cannot be used with {record.action_id!r}; "
                             f"its verbs are {', '.join(tapped.actions)}")
    elif not record.transcript.strip():
        raise ValueError("speech/text attempt has an empty transcript")
    return _play(journey, content, record, client=client, models=models, trace=trace)
