// Play: the scene fills the viewport and everything else floats over it.

import { useCallback, useMemo, useState } from "react";
import { useGame } from "../store";
import { Scene } from "./Scene";
import { Subtitles } from "./Subtitles";
import { InputBar } from "./InputBar";
import { Controls, SceneStatus } from "./TopBar";
import { Hud } from "./Hud";
import { HistoryDrawer } from "./HistoryDrawer";
import { NotebookDrawer } from "./Notebook";
import { Phrasebook, PhrasebookTab } from "./Phrasebook";
import { useElementSize } from "../lib/hooks";
import { freeSpan, useLayout } from "../lib/layout";

export function PlayView() {
  const scene = useGame((s) => s.scene);
  const openNotebook = useGame((s) => s.openNotebook);
  const [drawer, setDrawer] = useState<"history" | "notebook" | null>(null);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const frame = useLayout((s) => s.frame);
  const vp = useLayout((s) => s.vp);
  const rects = useLayout((s) => s.rects);

  // Where the dialogue goes. On a tall screen the picture sits in the upper part and
  // the turn is captioned directly beneath it. Otherwise it is film subtitles over the
  // lower part of the picture, moved sideways when a served object stands where they
  // would be.
  const caption = !!frame?.letterboxed && vp.h - (frame.top + frame.height) > 330;
  const [blockRef, block] = useElementSize<HTMLDivElement>();
  const span = useMemo(() => {
    if (caption || vp.w < 900) return null;
    return freeSpan(Object.values(rects), { top: vp.h - 104 - Math.max(block.h, 120), bottom: vp.h - 104 }, vp.w, 300, 24, 640);
  }, [caption, rects, vp.w, vp.h, block.h]);
  const compact = vp.h > 0 && vp.h < 520;

  if (!scene) return null;
  return (
    <main data-testid="play-view" data-scene={scene.id} className="slow-fade-in absolute inset-0 overflow-hidden">
      <Scene scene={scene} />
      <header className="pointer-events-none absolute inset-x-0 top-0 z-30 flex items-start justify-between gap-3 px-3 pt-3 sm:px-6 sm:pt-5">
        <SceneStatus>
          <div className="mt-1 sm:hidden">
            <Hud />
          </div>
        </SceneStatus>
        <div className="absolute left-1/2 top-5 hidden -translate-x-1/2 sm:block">
          <Hud />
        </div>
        <Controls
          onHistory={() => setDrawer("history")}
          onNotebook={() => {
            openNotebook();
            setDrawer("notebook");
          }}
        />
      </header>
      {caption && frame && (
        <div className="pointer-events-none absolute inset-x-0 z-20" style={{ top: frame.top + frame.height - 6 }}>
          <Subtitles compact={compact} caption />
        </div>
      )}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex flex-col">
        {!caption && (
          <div ref={blockRef} style={span ? { marginLeft: span.centre - Math.min(820, span.width) / 2, width: Math.min(820, span.width) } : undefined} data-shifted={span ? "1" : "0"}>
            <Subtitles compact={compact} />
          </div>
        )}
        <div className="pt-3 sm:pt-5">
          <InputBar />
        </div>
      </div>
      <PhrasebookTab />
      <Phrasebook />
      {drawer === "history" && <HistoryDrawer onClose={closeDrawer} />}
      {drawer === "notebook" && <NotebookDrawer onClose={closeDrawer} />}
    </main>
  );
}
