// The turn as you read it: first the narrator (the story's voice, in prose), then the
// character's lines as film subtitles, appearing one at a time as they are spoken
// (current line bright, earlier ones dimmed). Your own move is echoed like a game log.
// Character lines are never translated.

import { useMemo } from "react";
import { useGame } from "../store";
import { RubyLine } from "./RubyLine";
import type { Language, LearnerEntry, Line } from "../lib/types";

export function Subtitles({ compact = false }: { compact?: boolean }) {
  const transcript = useGame((s) => s.transcript);
  const hidden = useGame((s) => s.hidden);
  const speaking = useGame((s) => s.speakingLineId);
  const language = useGame((s) => s.language);
  const phase = useGame((s) => s.phase);
  const pending = useGame((s) => s.pending);
  const help = useGame((s) => s.help);
  const shownAt = useGame((s) => s.learnerShownAt);
  const scene = useGame((s) => s.scene);

  const exchange = useMemo(() => {
    let turn = -1;
    for (const e of transcript) if (e.kind === "npc" || e.kind === "narration") turn = Math.max(turn, e.turn);
    const lines: Line[] = [];
    let prose: { text: string; narrator: boolean } | null = null;
    let learner: LearnerEntry | null = null;
    for (const e of transcript) {
      if (e.turn !== turn) continue;
      if (e.kind === "npc") lines.push(e.line);
      else if (e.kind === "narration") prose = { text: e.text, narrator: true };
      else if (e.kind === "direction" && !prose) prose = { text: e.text, narrator: false };
      else if (e.kind === "learner") learner = e;
    }
    return { turn, lines, prose, learner };
  }, [transcript]);

  if (!language) return null;
  const waiting = phase === "waiting" || phase === "error";
  const shown = exchange.lines.filter((l) => !hidden[l.line_id]);
  const currentId = speaking && shown.some((l) => l.line_id === speaking) ? speaking : shown[shown.length - 1]?.line_id;
  const visible = compact ? shown.filter((l) => l.line_id === currentId) : shown;
  const mine = waiting ? pending : shownAt && Date.now() - shownAt < 4500 ? exchange.learner : null;
  const hint = help?.kind === "hint" && help.hint && !waiting ? help.hint : null;

  return (
    <div data-testid="subtitles" className="pointer-events-none mx-auto flex w-full max-w-[720px] shrink-0 flex-col items-center gap-2 text-center sm:gap-2.5">
      {!waiting && exchange.prose && !(compact && visible.length > 0) && (
        <p
          key={exchange.turn}
          data-testid={exchange.prose.narrator ? "narration" : undefined}
          data-role={exchange.prose.narrator ? "narration" : "direction"}
          className={`story slow-fade-in over-art m-0 max-w-[600px] text-balance ${
            exchange.prose.narrator ? "pb-1 text-[17px] leading-[1.5] text-ink sm:text-[19px]" : "text-[14px] italic leading-snug text-ink-2"
          }`}
        >
          {exchange.prose.text}
        </p>
      )}

      {hint && (
        <p data-testid="help-hint" className="rise-in over-art m-0 max-w-[520px] text-[13px] leading-snug text-jade">
          {hint}
        </p>
      )}

      {!waiting &&
        visible.map((l) => {
          const current = l.line_id === currentId;
          return (
            <p
              key={l.line_id}
              data-testid="subtitle-line"
              data-line={l.line_id}
              data-current={current ? "1" : "0"}
              className={`rise-in over-art m-0 transition-[color,font-size] duration-200 ease-out ${
                current ? "text-[28px] text-ink sm:text-[34px]" : "text-[20px] text-ink-3 sm:text-[24px]"
              }`}
            >
              <RubyLine segments={l.segments} language={language} dim={!current} />
            </p>
          );
        })}

      {mine && (
        <p
          key={mine.attempt_id + mine.transcript}
          data-testid="learner-line"
          className={`over-art m-0 flex items-center gap-1.5 self-center text-[14px] text-ink-2 ${waiting ? "rise-in" : "linger"}`}
        >
          <Echo entry={mine} language={language} />
        </p>
      )}

      {phase === "waiting" && (
        <div data-testid="thinking" aria-label={`${scene?.npc.name ?? "They"} is thinking`} className="thinking fade-in py-3">
          <span />
          <span />
          <span />
        </div>
      )}
    </div>
  );
}

/** "You say ...": your move, the way a game log would put it.
 *  The learner reads romanization over everything the character says, so their own line
 *  carries it too — otherwise a typed word echoes back with nothing to read. It is hidden
 *  when it would only repeat the line (already-romanized typing, or a Latin script). */
export function Echo({ entry, language }: { entry: LearnerEntry; language: Language }) {
  const roman = entry.romanized?.trim();
  const showRoman =
    language.romanization_label != null &&
    !!roman &&
    roman.toLowerCase() !== entry.transcript.trim().toLowerCase();
  return (
    <>
      <span className="text-ink-3">You say</span>
      <span lang={language.locale} className="target font-normal">
        {entry.transcript}
      </span>
      {showRoman && <span data-role="romanization" className="text-[13px] text-ink-3">{roman}</span>}
    </>
  );
}
