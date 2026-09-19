// The turn as you read it: first the narrator (the story's voice, in prose), then the
// character's lines as film subtitles, appearing one at a time as they are spoken
// (current line bright, earlier ones dimmed). Your own move is echoed like a game log.
// Character lines are never translated; in Story mode the narrator may give the gist.

import { useMemo } from "react";
import { useGame } from "../store";
import { RubyLine } from "./RubyLine";
import type { LearnerEntry, Line, SceneView } from "../lib/types";

export function Subtitles({ compact = false, caption = false }: { compact?: boolean; caption?: boolean }) {
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
  // A very short window (a phone on its side) only has room for the line being spoken.
  const visible = compact ? shown.filter((l) => l.line_id === currentId) : shown;
  const mine = waiting ? pending : shownAt && Date.now() - shownAt < 4500 ? exchange.learner : null;
  const hint = help?.kind === "hint" && help.hint && !waiting ? help.hint : null;

  return (
    <div data-testid="subtitles" data-placement={caption ? "caption" : "subtitle"} className="pointer-events-none mx-auto flex w-full max-w-[820px] flex-col items-center gap-2 px-5 text-center sm:gap-2.5">
      {!waiting && exchange.prose && !(compact && visible.length > 0) && (
        <p
          key={exchange.turn}
          data-testid={exchange.prose.narrator ? "narration" : undefined}
          data-role={exchange.prose.narrator ? "narration" : "direction"}
          className={`story slow-fade-in over-art m-0 max-w-[600px] text-balance ${
            exchange.prose.narrator ? "pb-1 text-[17px] leading-[1.5] text-ink/90 sm:text-[19px]" : "text-[14px] italic leading-snug text-ink-3"
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
          key={mine.attempt_id + mine.transcript + (mine.tapped_object_id ?? "") + (mine.action_id ?? "")}
          data-testid="learner-line"
          className={`over-art m-0 flex items-center gap-1.5 text-[14px] text-ink-2 ${caption ? "self-center" : "self-end"} ${waiting ? "rise-in" : "linger"}`}
        >
          <Echo entry={mine} scene={scene} locale={language.locale} />
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

/** "You show [the photo]", "You say ...": your move, the way a game log would put it. */
export function Echo({ entry, scene, locale }: { entry: LearnerEntry; scene: SceneView | null; locale: string }) {
  if (entry.input_mode !== "tap") {
    return (
      <>
        <span className="text-ink-3">You say</span>
        <span lang={locale} className="target font-normal">
          {entry.transcript}
        </span>
      </>
    );
  }
  const object = scene?.objects.find((o) => o.id === entry.tapped_object_id);
  const verb = object?.actions?.find((a) => a.id === entry.action_id)?.label.toLowerCase();
  return (
    <span className="flex items-center gap-1.5" data-pointed={entry.tapped_object_id ?? ""} data-action={entry.action_id ?? "point"}>
      <span className="text-ink-3">You</span>
      <span>{verb && verb !== "point" ? verb : "point at"}</span>
      {object && <img src={object.art_url} alt="" className="h-6 w-auto" />}
    </span>
  );
}
