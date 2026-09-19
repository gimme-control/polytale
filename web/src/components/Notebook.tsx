// The notebook: what you have learned about the STORY. Clues arrive as a brief card,
// leave a badge on the button, and are kept here. Trust has no meter; one sentence
// says how the person in front of you is taking you.

import { useEffect } from "react";
import { useGame } from "../store";

function standing(name: string, trust: number): string {
  if (trust >= 2) return `${name} is on your side.`;
  if (trust === 1) return `${name} is warming to you.`;
  if (trust === 0) return `${name} hasn't made up their mind about you.`;
  return `${name} would like you gone.`;
}

export function ClueToast() {
  const clue = useGame((s) => s.clueToast);
  if (!clue) return null;
  return (
    <div data-testid="clue-toast" role="status" className="rise-in pointer-events-none w-[280px] rounded-[10px] border border-hair-2 bg-[#0e0f0f]/90 px-4 py-3 backdrop-blur-xl">
      <div className="text-[12px] text-jade">Notebook</div>
      <div className="story mt-0.5 text-[17px] leading-snug text-ink">{clue.title}</div>
    </div>
  );
}

export function NotebookDrawer({ onClose }: { onClose: () => void }) {
  const game = useGame((s) => s.game);
  const scene = useGame((s) => s.scene);
  const story = useGame((s) => s.story);
  const progress = useGame((s) => s.progress);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  const clues = game?.clues ?? [];
  return (
    <div className="absolute inset-0 z-40" data-testid="notebook">
      <button type="button" aria-label="Close notebook" onClick={onClose} className="fade-in absolute inset-0 h-full w-full cursor-default border-0 bg-black/45" />
      <aside className="drawer-in absolute inset-y-0 right-0 flex w-full max-w-[420px] flex-col border-l border-hair bg-[#0e0f0f]/95 backdrop-blur-xl">
        <header className="flex items-center justify-between px-6 pb-3 pt-5">
          <h2 className="m-0 text-[15px] font-semibold tracking-[-0.01em]">Notebook</h2>
          <button type="button" data-testid="notebook-close" onClick={onClose} className="border-0 bg-transparent p-0 text-[13px] text-ink-2 hover:text-ink">
            Close
          </button>
        </header>
        <div className="scroll-quiet flex-1 overflow-y-auto px-6 pb-8 pt-2">
          {story && <p className="story m-0 text-[15px] italic leading-relaxed text-ink-3">{story.tagline}</p>}
          {clues.length === 0 ? (
            <p className="m-0 mt-6 text-[13px] text-ink-3">Nothing yet. Show people things. Ask. Pay attention to what changes.</p>
          ) : (
            <ol className="m-0 mt-5 list-none space-y-5 p-0">
              {clues.map((c, i) => (
                <li key={c.id} data-clue={c.id} className="border-t border-hair pt-4">
                  <div className="flex items-baseline gap-3">
                    <span className="text-[12px] tabular-nums text-ink-3">{i + 1}</span>
                    <h3 className="story m-0 text-[19px] font-medium leading-snug text-ink">{c.title}</h3>
                  </div>
                  <p className="story m-0 mt-1.5 pl-[22px] text-[15px] leading-relaxed text-ink-2">{c.text}</p>
                </li>
              ))}
            </ol>
          )}
        </div>
        <footer className="space-y-1 border-t border-hair px-6 py-4 text-[12px] text-ink-3">
          {scene && game && <p data-testid="standing" className="m-0 text-ink-2">{standing(scene.npc.name, game.trust)}</p>}
          {progress && (
            <p data-testid="word-count" className="m-0 tabular-nums">
              {progress.encountered} / {progress.target_count} words met here
            </p>
          )}
        </footer>
      </aside>
    </div>
  );
}
