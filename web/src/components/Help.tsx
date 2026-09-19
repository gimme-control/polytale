// Help ladder UI. The button says what it will do next (learning.next_help.label);
// the returned HelpCue renders as a small card. After 10 s idle the button gently
// *offers* itself (pulse) — help is never applied automatically.

import { SLOW_RATE, useGame } from "../store";
import type { HelpCue } from "../lib/types";
import { useNow } from "../lib/hooks";
import { IconBulb, IconHand, IconSlow } from "./icons";

const IDLE_OFFER_MS = 10_000;

export function HelpButton({ compact = false }: { compact?: boolean }) {
  const learning = useGame((s) => s.learning);
  const busy = useGame((s) => s.helpBusy);
  const request = useGame((s) => s.requestHelp);
  const mic = useGame((s) => s.mic);
  const speaking = useGame((s) => s.speakingLineId);
  const last = useGame((s) => s.lastActivity);
  const done = useGame((s) => s.episodeComplete);
  const now = useNow(1000);
  const next = learning?.next_help ?? null;
  const idle = mic === "idle" && !speaking && !done && !!next;
  const offering = idle && now - last > IDLE_OFFER_MS;
  const label = next?.label ?? (learning?.active_beat ? "All help shown" : "Help");
  return (
    <button
      type="button"
      onClick={() => void request()}
      disabled={!next || busy || done}
      className={`group relative inline-flex max-w-full items-center gap-2 border font-semibold transition ${
        compact ? "min-h-11 rounded-2xl px-3 py-1.5 text-left text-[12.5px] leading-tight" : "h-11 rounded-full px-4 text-[13.5px]"
      } ${
        offering ? "border-brass/70 bg-brass/15 text-brass-strong" : "border-line-strong bg-white/[0.04] text-muted hover:border-brass/50 hover:text-text"
      } disabled:opacity-40`}
      style={offering ? { animation: "help-offer 1.8s ease-in-out infinite" } : undefined}
      data-testid="help-button"
      data-offering={offering ? "1" : "0"}
      data-level={learning?.help_level ?? 0}
      title={offering ? "Stuck? Help is here when you want it." : undefined}
    >
      <IconBulb className={`h-4 w-4 text-brass ${compact ? "hidden min-[380px]:block" : ""}`} />
      <span className={compact ? "line-clamp-2" : "truncate"}>{label}</span>
      {next && <LadderDots level={learning?.help_level ?? 0} />}
    </button>
  );
}

function LadderDots({ level }: { level: number }) {
  return (
    <span className="ml-0.5 hidden items-center gap-[3px] sm:inline-flex" aria-label={`help level ${level} of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span key={i} className={`h-1.5 w-1.5 rounded-full ${i <= level ? "bg-brass" : "bg-white/15"}`} />
      ))}
    </span>
  );
}

export function HelpCard({ cue }: { cue: HelpCue }) {
  const replay = useGame((s) => s.replay);
  const tapFallback = useGame((s) => s.learning?.tap_fallback ?? false);
  const close = () => useGame.setState({ helpCue: null });
  return (
    <div className="rise-in relative rounded-2xl border border-brass/30 bg-gradient-to-b from-brass/[0.09] to-brass/[0.03] px-4 py-3" data-testid="help-card" data-kind={cue.kind} data-level={cue.level}>
      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-brass">
        <IconBulb className="h-3.5 w-3.5" />
        {cue.label}
        <button type="button" onClick={close} className="ml-auto rounded-full px-2 text-faint hover:text-text" aria-label="Hide help">
          ×
        </button>
      </div>
      <div className="mt-2">
        {cue.kind === "replay_slow" && cue.line && (
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => replay(cue.line!, SLOW_RATE)}
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brass text-ink shadow-[0_6px_20px_-6px_rgba(233,180,95,0.8)]"
              aria-label="Play slowly again"
            >
              <IconSlow className="h-5 w-5" />
            </button>
            <div>
              <div className="jp text-2xl text-text" lang={cue.line.language}>{cue.line.text}</div>
              <div className="text-[14px] text-romaji">{cue.line.romanization}</div>
            </div>
          </div>
        )}
        {cue.kind === "word" && (
          <div className="flex flex-wrap gap-2">
            {(cue.concepts ?? []).map((c) => (
              <span key={c.id} className="inline-flex items-baseline gap-2 rounded-xl border border-line-strong bg-ink/40 px-3 py-1.5">
                <span className="jp text-2xl text-text">{c.native}</span>
                <span className="text-[15px] text-romaji">{c.romanization}</span>
              </span>
            ))}
          </div>
        )}
        {cue.kind === "frame" && cue.frame && (
          <div className="flex flex-wrap items-center gap-3">
            <div className="rounded-xl border border-dashed border-brass/50 bg-ink/40 px-3 py-1.5" data-role="frame">
              <div className="jp text-2xl text-text">{renderBlank(cue.frame.native)}</div>
              <div className="text-[15px] text-romaji">{renderBlank(cue.frame.romanization)}</div>
            </div>
            {(cue.concepts ?? []).map((c) => (
              <span key={c.id} className="inline-flex items-baseline gap-2 rounded-xl border border-line-strong bg-ink/40 px-3 py-1.5">
                <span className="jp text-xl text-text">{c.native}</span>
                <span className="text-[14px] text-romaji">{c.romanization}</span>
              </span>
            ))}
          </div>
        )}
        {cue.kind === "meaning" && <p className="text-[15px] leading-relaxed text-text">{cue.text}</p>}
        {cue.kind === "full" && (
          <div>
            <div className="jp text-[28px] leading-tight text-text">{cue.native}</div>
            <div className="text-[16px] text-romaji">{cue.romanization}</div>
            {cue.translation && <div className="mt-1 text-[14px] text-muted">“{cue.translation}”</div>}
            {tapFallback && (
              <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-white/[0.05] px-3 py-1 text-[12.5px] text-muted">
                <IconHand className="h-3.5 w-3.5 text-brass" />
                Say it out loud — or tap the glowing object in her hand.
              </div>
            )}
          </div>
        )}
        {cue.text && cue.kind !== "meaning" && <p className="mt-1.5 text-[14px] text-muted">{cue.text}</p>}
      </div>
    </div>
  );
}

function renderBlank(s: string) {
  const parts = s.split(/(_{2,})/);
  return parts.map((p, i) =>
    /^_{2,}$/.test(p) ? (
      <span key={i} className="mx-0.5 inline-block w-[2.4em] translate-y-[0.15em] border-b-2 border-brass/80" aria-label="blank" />
    ) : (
      <span key={i}>{p}</span>
    ),
  );
}
