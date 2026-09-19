// The chrome during play. Left: where you are and what the story needs from you.
// Centre: the clock and your cash. Right: help, notebook, history, menu.

import { useCallback, useState } from "react";
import { useGame } from "../store";
import { linePlayer } from "../audio/linePlayer";
import { useDismiss } from "../lib/hooks";
import { PersonaSwitch } from "./PersonaSwitch";
import { ClueToast } from "./Notebook";
import type { Difficulty } from "../lib/types";

export function SceneStatus({ children }: { children?: React.ReactNode }) {
  const scene = useGame((s) => s.scene);
  const progress = useGame((s) => s.progress);
  if (!scene) return null;
  const done = new Set(progress?.goals_done ?? []);
  return (
    <div data-testid="scene-status" className="over-art min-w-0 sm:max-w-[340px]">
      <h1 className="m-0 truncate text-[15px] font-semibold leading-6 tracking-[-0.01em] text-ink">{scene.name}</h1>
      {children}
      {/* On a phone the goals run beneath the controls, so they never wrap beside them. */}
      <ul data-testid="goals" className="m-0 mt-2.5 w-max list-none space-y-1 whitespace-nowrap p-0 sm:mt-1.5">
        {scene.goals.map((g) => {
          const ok = done.has(g.id);
          return (
            <li key={g.id} data-goal={g.id} data-done={ok ? "1" : "0"} className="flex items-center gap-2 text-[13px] leading-5">
              <span aria-hidden className={`grid h-[11px] w-[11px] shrink-0 place-items-center rounded-[3px] border transition-colors duration-200 ${ok ? "border-jade bg-jade" : "border-ink-3"}`}>
                {ok && (
                  <svg width="7" height="7" viewBox="0 0 8 8" fill="none" stroke="#0b0c0c" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M1.2 4.2 3.2 6l3.6-4.2" />
                  </svg>
                )}
              </span>
              <span className={`transition-colors duration-200 ${ok ? "text-ink-3 line-through decoration-ink-3" : "text-ink-2"}`}>{g.label}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function Controls({ onHistory, onNotebook }: { onHistory: () => void; onNotebook: () => void }) {
  const progress = useGame((s) => s.progress);
  const helpBusy = useGame((s) => s.helpBusy);
  const phase = useGame((s) => s.phase);
  const requestHelp = useGame((s) => s.requestHelp);
  const toast = useGame((s) => s.toast);
  const unseen = useGame((s) => Math.max(0, (s.game?.clues.length ?? 0) - s.cluesSeen));
  const hasGame = useGame((s) => !!s.game);
  const next = progress?.next_help ?? null;
  const helpOff = !next || helpBusy || phase === "waiting" || phase === "listening" || phase === "transcribing";

  return (
    <div className="pointer-events-auto relative flex shrink-0 flex-col items-end gap-2">
      <div className="flex items-center gap-1 sm:gap-2">
        <button
          type="button"
          data-testid="help-button"
          data-level={progress?.help_level ?? 0}
          disabled={helpOff}
          onClick={() => void requestHelp()}
          aria-label={next ? next.label : "No more help"}
          className="over-art h-9 rounded-[8px] border border-hair bg-glass px-3 text-[13px] font-medium text-ink backdrop-blur-md transition-colors duration-150 hover:border-hair-2 disabled:text-ink-3"
        >
          {/* The server words the step; a phone only has room for the short form. */}
          <span className="hidden sm:inline">{next ? next.label : "No more help"}</span>
          <span className="sm:hidden">{next ? (next.level === 1 ? "Again" : "Hint") : "No help"}</span>
        </button>
        {hasGame && (
          <IconButton testid="notebook-button" label={unseen ? `Notebook, ${unseen} new` : "Notebook"} onClick={onNotebook}>
            <path d="M5 2.75h8.25v12.5H5a1.25 1.25 0 0 1-1.25-1.25V4A1.25 1.25 0 0 1 5 2.75ZM6.75 6h4M6.75 8.75h4" />
            {unseen > 0 && <circle data-testid="notebook-badge" className="badge-in" cx="14.5" cy="3.5" r="3" fill="#9fc3b1" stroke="#0b0c0c" strokeWidth="1.2" style={{ transformOrigin: "14.5px 3.5px" }} />}
          </IconButton>
        )}
        <IconButton testid="history-button" label="History" onClick={onHistory}>
          <path d="M3 4.5h12M3 9h12M3 13.5h7.5" />
        </IconButton>
        <Menu />
      </div>
      {/* Out of the flow, so a clue arriving never squeezes the scene name. */}
      <div className="absolute right-0 top-11">
        <ClueToast />
      </div>
      {toast && (
        <p data-testid="toast" role="status" className="rise-in over-art m-0 text-[12px] text-ink-2">
          {toast}
        </p>
      )}
    </div>
  );
}

function IconButton({ children, onClick, label, testid, pressed }: { children: React.ReactNode; onClick: () => void; label: string; testid: string; pressed?: boolean }) {
  return (
    <button
      type="button"
      data-testid={testid}
      aria-label={label}
      aria-expanded={pressed}
      title={label}
      onClick={onClick}
      className="grid h-9 w-9 place-items-center rounded-[8px] border border-hair bg-glass text-ink backdrop-blur-md transition-colors duration-150 hover:border-hair-2"
    >
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        {children}
      </svg>
    </button>
  );
}

const DIFFICULTIES: { id: Difficulty; label: string }[] = [
  { id: "story", label: "Story" },
  { id: "immersion", label: "Immersion" },
];

function Menu() {
  const [open, setOpen] = useState(false);
  const [volume, setVolume] = useState(linePlayer.volume);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss(open, close);
  const difficulty = useGame((s) => s.game?.difficulty ?? null);
  const setDifficulty = useGame((s) => s.setDifficulty);
  const finishScene = useGame((s) => s.finishScene);
  const restartScene = useGame((s) => s.restartScene);
  const newJourney = useGame((s) => s.newJourney);
  const run = (fn: () => Promise<void>) => () => {
    setOpen(false);
    void fn();
  };

  return (
    <div ref={ref} className="relative">
      <IconButton testid="menu-button" label="Menu" pressed={open} onClick={() => setOpen((o) => !o)}>
        <circle cx="4" cy="9" r="0.9" fill="currentColor" />
        <circle cx="9" cy="9" r="0.9" fill="currentColor" />
        <circle cx="14" cy="9" r="0.9" fill="currentColor" />
      </IconButton>
      {open && (
        <div data-testid="menu" role="menu" className="rise-in absolute right-0 top-11 z-10 w-[264px] rounded-[10px] border border-hair bg-[#0e0f0f]/95 p-1.5 backdrop-blur-xl">
          {difficulty && (
            <>
              <div className="px-2.5 pb-1.5 pt-2 text-[12px] text-ink-3">Difficulty</div>
              <div role="radiogroup" aria-label="Difficulty" data-testid="difficulty-switch" className="mx-1.5 flex h-9 items-center rounded-[8px] border border-hair p-[3px]">
                {DIFFICULTIES.map((d) => (
                  <button
                    key={d.id}
                    type="button"
                    role="radio"
                    aria-checked={difficulty === d.id}
                    data-testid={`difficulty-${d.id}`}
                    data-active={difficulty === d.id ? "1" : "0"}
                    onClick={() => void setDifficulty(d.id)}
                    className={`h-full flex-1 rounded-[6px] border-0 text-[13px] font-medium transition-colors duration-150 ${difficulty === d.id ? "bg-ink text-night" : "bg-transparent text-ink-2 hover:text-ink"}`}
                  >
                    {d.label}
                  </button>
                ))}
              </div>
            </>
          )}
          <div className="px-2.5 pb-1.5 pt-3 text-[12px] text-ink-3">Character mood</div>
          <div className="px-1.5 pb-2">
            <PersonaSwitch full />
          </div>
          <div className="mx-2.5 my-1 h-px bg-hair" />
          <label className="flex items-center justify-between gap-4 px-2.5 py-2.5 text-[13px] text-ink-2">
            Volume
            <input
              data-testid="volume"
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={volume}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                setVolume(v);
                linePlayer.setVolume(v);
              }}
              className="quiet w-[120px]"
            />
          </label>
          <div className="mx-2.5 my-1 h-px bg-hair" />
          <MenuItem testid="finish-scene" onClick={run(finishScene)}>
            Finish scene
          </MenuItem>
          <MenuItem testid="restart-scene" onClick={run(restartScene)}>
            Restart scene
          </MenuItem>
          <MenuItem testid="new-journey" onClick={run(newJourney)}>
            New journey
          </MenuItem>
        </div>
      )}
    </div>
  );
}

function MenuItem({ children, onClick, testid }: { children: React.ReactNode; onClick: () => void; testid: string }) {
  return (
    <button
      type="button"
      role="menuitem"
      data-testid={testid}
      onClick={onClick}
      className="block w-full rounded-[7px] border-0 bg-transparent px-2.5 py-2 text-left text-[13px] text-ink-2 transition-colors duration-150 hover:bg-white/[0.06] hover:text-ink"
    >
      {children}
    </button>
  );
}
