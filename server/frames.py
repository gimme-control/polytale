"""Scheduling for the living scene: text goes first, the picture catches up.

A turn commits an expression and any beat, returns its narration immediately, and only then
does a background task paint the patches. The client asks for each patch by URL; that GET
joins the in-flight bake instead of starting a second one, and if the paint fails, times out
or is switched off, it gets a fully transparent pixel — so the worst case is the base plate,
never a broken or blank scene.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from core.content import Scene, resolve_art_path
from core.frames import FramePlan, FrameView, build_plan, frame_view
from core.state import Journey
from media import frames as painter

log = logging.getLogger("polytale.server.frames")

BakeFn = Callable[[Path, FramePlan], dict[str, Path]]

#: How many finished bakes to remember before forgetting the oldest. Only the task handle is
#: kept; the cutouts themselves live on disk.
TASK_MEMORY = 16


def plate_of(scene: Scene) -> Path:
    """The scene's one base plate. Everything else is a patch over it."""
    return resolve_art_path(scene, scene.art.background)


@dataclass
class FrameService:
    """Per-frame bake tasks, deduplicated by plan key.

    In-memory and single-process, like the journey locks: one uvicorn worker only.
    """

    bake: BakeFn = painter.bake_plan
    _tasks: dict[str, asyncio.Task[dict[str, Path]]] = field(default_factory=dict)

    # ------------------------------------------------------------ what to show

    def plan(self, journey: Journey, scene: Scene) -> tuple[FramePlan, Path] | None:
        """The frame the player should be looking at, or None when the scene does not react."""
        run = journey.scene
        if run is None or not painter.frames_enabled():
            return None
        try:
            plate = plate_of(scene)
            signature = painter.plate_signature(plate)
        except (OSError, ValueError) as exc:  # no plate, no patches: the scene still plays
            log.warning("frames: no base plate for scene %s (%s)", scene.id, exc)
            return None
        plan = build_plan(scene_id=scene.id, plate_sig=signature, anchor=scene.npc.anchor,
                          expression=run.expression, patches=run.patches)
        return plan, plate

    def view(self, journey: Journey, scene: Scene) -> FrameView | None:
        """The frame as a payload, without starting any work (a refresh, a resumed journey)."""
        planned = self.plan(journey, scene)
        if planned is None or planned[0].empty:
            return None
        return frame_view(journey.journey_id, planned[0])

    def start(self, journey: Journey, scene: Scene) -> FrameView | None:
        """Kick off the paint and hand back the frame to promise the client. Never awaits it."""
        planned = self.plan(journey, scene)
        if planned is None or planned[0].empty:
            return None
        plan, plate = planned
        self._task_for(plan, plate)
        return frame_view(journey.journey_id, plan)

    # ------------------------------------------------------------ painting

    def _task_for(self, plan: FramePlan, plate: Path) -> asyncio.Task[dict[str, Path]]:
        """One task per frame, shared by whoever needs it (the turn, then the client's GET)."""
        loop = asyncio.get_running_loop()
        running = self._tasks.get(plan.key)
        if running is not None and running.get_loop() is loop:
            if not running.done():
                return running
            if running.exception() is None:
                return running  # already painted as far as it is going to get
        self._prune()
        task = loop.create_task(asyncio.to_thread(self.bake, plate, plan))
        self._tasks[plan.key] = task
        return task

    def _prune(self) -> None:
        for key in [k for k, t in self._tasks.items() if t.done()][:-TASK_MEMORY]:
            self._tasks.pop(key, None)

    async def layer_file(self, journey: Journey, scene: Scene, layer_id: str) -> Path | None:
        """The cutout for one patch, waiting on the paint in flight. None when it cannot be.

        Only a layer of the CURRENT frame is ever painted on demand, so a stale tab asking for
        an old URL costs nothing.
        """
        planned = self.plan(journey, scene)
        if planned is None or planned[0].layer(layer_id) is None:
            return None
        plan, plate = planned
        path = painter.layer_path(plan.scene_id, layer_id)
        if path.is_file():
            return path
        try:
            await self._task_for(plan, plate)
        except Exception as exc:  # noqa: BLE001 — a failed paint is a transparent patch
            log.warning("frames: bake for %s failed: %s", plan.key, exc)
            return None
        return path if path.is_file() else None
