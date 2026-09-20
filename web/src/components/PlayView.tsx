// Play: the painting fills the viewport and ONE centred column sits over it, holding
// everything the learner reads or touches — the scene name and goals, the controls,
// the turn (narration, the character's line, its romanization) and the input bar.
// Nothing is pinned to a viewport corner, so the screen reads as one column at any
// width instead of chrome scattered into the edges.

import { useCallback, useState } from "react";
import { useGame } from "../store";
import { Scene } from "./Scene";
import { Subtitles } from "./Subtitles";
import { InputBar } from "./InputBar";
import { Controls, SceneStatus } from "./TopBar";
import { HistoryDrawer } from "./HistoryDrawer";
import { NotebookDrawer } from "./Notebook";
import { Phrasebook } from "./Phrasebook";
import { useElementSize } from "../lib/hooks";

export function PlayView() {
  const scene = useGame((s) => s.scene);
  const openNotebook = useGame((s) => s.openNotebook);
  const [drawer, setDrawer] = useState<"history" | "notebook" | null>(null);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const [columnRef, column] = useElementSize<HTMLDivElement>();
  const [headerRef, header] = useElementSize<HTMLElement>();

  // A very short window (a phone on its side) only has room for the line being spoken.
  const compact = column.h > 0 && column.h < 520;

  if (!scene) return null;
  return (
    <main data-testid="play-view" data-scene={scene.id} className="slow-fade-in absolute inset-0 overflow-hidden">
      <Scene scene={scene} topInset={header.h + 16} />
      <div
        ref={columnRef}
        data-testid="stage-column"
        className="pointer-events-none absolute inset-0 z-20 mx-auto flex h-full w-full max-w-[900px] flex-col px-4 sm:px-6"
      >
        <header ref={headerRef} className="flex shrink-0 items-start justify-between gap-3 pt-4 sm:pt-6">
          <SceneStatus />
          <Controls
            onHistory={() => setDrawer("history")}
            onNotebook={() => {
              openNotebook();
              setDrawer("notebook");
            }}
          />
        </header>
        {/* The painting breathes here; the turn and the input stay together at the foot. */}
        <div className="min-h-0 flex-1" />
        <Subtitles compact={compact} />
        <InputBar />
      </div>
      <Phrasebook />
      {drawer === "history" && <HistoryDrawer onClose={closeDrawer} />}
      {drawer === "notebook" && <NotebookDrawer onClose={closeDrawer} />}
    </main>
  );
}
