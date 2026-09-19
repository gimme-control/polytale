// Main play view. Desktop: stage (largest surface) + mic dock on the left,
// dialogue panel on the right. Phone: stage on top, dialogue, dock pinned below.

import { useEffect, useState } from "react";
import { useGame } from "../store";
import { Stage } from "./Stage";
import { DialoguePanel } from "./Dialogue";
import { MicDock } from "./MicDock";
import { CornerMenu, InventoryTray, ObjectiveChip, Wordmark } from "./Hud";
import { EndCard } from "./EndCard";

function useIsMobile() {
  const q = "(max-width: 900px)";
  const [m, setM] = useState(() => window.matchMedia(q).matches);
  useEffect(() => {
    const mq = window.matchMedia(q);
    const on = () => setM(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return m;
}

export function PlayView() {
  const mobile = useIsMobile();
  const showEnd = useGame((s) => s.showEnd);
  const name = useGame((s) => s.cartridge?.name);
  const touch = useGame((s) => s.touch);

  if (mobile) {
    return (
      <main className="flex h-full w-full flex-col bg-ink" onPointerDown={touch} data-testid="play-view" data-layout="mobile">
        <header className="flex h-12 shrink-0 items-center justify-between px-4">
          <Wordmark />
          <CornerMenu />
        </header>
        <div className="relative aspect-[16/10] w-full shrink-0">
          <Stage compact />
          <div className="absolute bottom-2 left-2">
            <InventoryTray compact />
          </div>
        </div>
        <div className="shrink-0 px-3 pt-3">
          <ObjectiveChip className="w-full justify-between" compact />
        </div>
        <div className="min-h-0 flex-1">
          <DialoguePanel mobile />
        </div>
        <div className="shrink-0 border-t border-line bg-night/90 pb-[env(safe-area-inset-bottom)]">
          <MicDock compact />
        </div>
        {showEnd && <EndCard />}
      </main>
    );
  }

  return (
    <main className="grid h-full w-full grid-cols-[minmax(0,1fr)_clamp(380px,32vw,480px)] bg-ink" onPointerDown={touch} data-testid="play-view" data-layout="desktop">
      <div className="relative flex min-h-0 min-w-0 flex-col">
        <div className="relative min-h-0 flex-1">
          <Stage />
          <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-4 p-5">
            <div className="pointer-events-auto flex min-w-0 flex-col items-start gap-3">
              <div className="flex items-center gap-3">
                <Wordmark />
                {name && <span className="font-display text-[15px] italic text-text/70">{name}</span>}
              </div>
              <ObjectiveChip />
            </div>
            <div className="pointer-events-auto">
              <CornerMenu />
            </div>
          </div>
          <div className="absolute bottom-5 left-5">
            <InventoryTray />
          </div>
        </div>
        <div className="shrink-0 border-t border-line bg-gradient-to-b from-night to-ink">
          <MicDock />
        </div>
      </div>
      <aside className="min-h-0 border-l border-line bg-panel/95">
        <DialoguePanel />
      </aside>
      {showEnd && <EndCard />}
    </main>
  );
}
