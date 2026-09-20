// The transcript, on demand: a slide-over with replay and slow replay per line.
// The narrator and the clues are part of the record; character lines are still never translated.

import { useEffect, useRef } from "react";
import { SLOW_RATE, useGame } from "../store";
import { RubyLine } from "./RubyLine";
import { Echo } from "./Subtitles";

export function HistoryDrawer({ onClose }: { onClose: () => void }) {
  const transcript = useGame((s) => s.transcript);
  const language = useGame((s) => s.language);
  const scene = useGame((s) => s.scene);
  const speaking = useGame((s) => s.speakingLineId);
  const replay = useGame((s) => s.replay);
  const end = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  if (!language) return null;
  const goalLabel = (id?: string) => scene?.goals.find((g) => g.id === id)?.label ?? "";

  return (
    <div className="absolute inset-0 z-40" data-testid="history">
      <button type="button" aria-label="Close history" onClick={onClose} className="fade-in absolute inset-0 h-full w-full cursor-default border-0 bg-black/45" />
      <aside className="drawer-in absolute inset-y-0 right-0 flex w-full max-w-[420px] flex-col border-l border-hair bg-[#0e0f0f]/95 backdrop-blur-xl">
        <header className="flex items-center justify-between px-5 pb-3 pt-5">
          <h2 className="m-0 text-[15px] font-semibold tracking-[-0.01em]">History</h2>
          <button type="button" data-testid="history-close" onClick={onClose} className="border-0 bg-transparent p-0 text-[13px] text-ink-2 hover:text-ink">
            Close
          </button>
        </header>
        <div className="scroll-quiet flex-1 space-y-4 overflow-y-auto px-5 pb-8 pt-2">
          {transcript.map((e, i) => {
            if (e.kind === "npc") {
              const on = speaking === e.line.line_id;
              const prev = transcript[i - 1];
              const opens = !(prev && prev.kind === "npc" && prev.turn === e.turn);
              return (
                <div key={i} data-kind="npc" className={opens ? "" : "!mt-2.5"}>
                  {opens && <div className="mb-2 text-[12px] text-ink-3">{e.line.speaker_name}</div>}
                  <div className="flex items-end justify-between gap-4">
                    <div className={`text-[20px] transition-colors duration-150 ${on ? "text-jade" : "text-ink"}`}>
                      <RubyLine segments={e.line.segments} language={language} />
                    </div>
                    <div className="flex shrink-0 gap-3 pb-0.5">
                      <TextButton testid="replay" onClick={() => replay(e.line, 1)}>
                        Play
                      </TextButton>
                      <TextButton testid="replay-slow" onClick={() => replay(e.line, SLOW_RATE)}>
                        Slowly
                      </TextButton>
                    </div>
                  </div>
                </div>
              );
            }
            if (e.kind === "direction") {
              return (
                <p key={i} data-kind="direction" className="m-0 text-[13px] italic text-ink-3">
                  {e.text}
                </p>
              );
            }
            if (e.kind === "learner") {
              return (
                <div key={i} data-kind="learner" className="flex items-center justify-end gap-1.5 border-t border-hair pt-4 text-[14px] text-ink-2 first:border-0 first:pt-0">
                  <Echo entry={e} locale={language.locale} />
                </div>
              );
            }
            if (e.kind === "narration") {
              return (
                <p key={i} data-kind="narration" className="story m-0 text-[15px] leading-relaxed text-ink-2">
                  {e.text}
                </p>
              );
            }
            if (e.kind === "clue") {
              return (
                <p key={i} data-kind="clue" className="m-0 text-[12px] text-jade">
                  Notebook: {e.clue.title}
                </p>
              );
            }
            if (e.event === "goal_done") {
              return (
                <p key={i} data-kind="goal" className="m-0 text-[12px] text-jade">
                  Done: {goalLabel(e.goal_id)}
                </p>
              );
            }
            return null;
          })}
          {transcript.length === 0 && <p className="m-0 text-[13px] text-ink-3">Nothing has been said yet.</p>}
          <div ref={end} />
        </div>
      </aside>
    </div>
  );
}

function TextButton({ children, onClick, testid }: { children: React.ReactNode; onClick: () => void; testid: string }) {
  return (
    <button type="button" data-testid={testid} onClick={onClick} className="border-0 bg-transparent p-0 text-[12px] font-medium text-ink-2 underline decoration-hair-2 underline-offset-4 transition-colors duration-150 hover:text-ink hover:decoration-ink">
      {children}
    </button>
  );
}
