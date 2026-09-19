// Recap after the launch: observed behaviour from the ledger, never a score.

import { useGame } from "../store";
import type { Recap, RecapProduction } from "../lib/types";
import { supportPhrase } from "./Dialogue";
import { ObjectGlyph } from "./Stage";
import { IconRetry } from "./icons";
import { ArtImage } from "./Art";
import { resolveArt } from "../lib/hooks";

const STAGE_WORDS: Record<string, string> = {
  produced_with_cue: "Said it with support",
  produced_independently: "Said it on your own",
  transferred: "Reused it in a new situation",
  speech_recognized: "Recognized it by ear",
  context_recognized: "Recognized it in context",
};

export function EndCard() {
  const recap = useGame((s) => s.recap);
  const cartridge = useGame((s) => s.cartridge);
  const reset = useGame((s) => s.resetGame);
  if (!recap) {
    return (
      <Shell>
        <div className="py-10 text-center text-muted">Gathering what you did…</div>
      </Shell>
    );
  }
  const prods = recap.productions;
  const key = prods.find((p) => /key/.test(p.concept_id)) ?? prods[0];
  const map = prods.find((p) => p !== key && /map/.test(p.concept_id)) ?? prods.find((p) => p !== key);
  return (
    <Shell>
      <div className="text-[11px] font-bold uppercase tracking-[0.3em] text-brass">Episode complete</div>
      <h2 className="mt-2 font-display text-[40px] font-semibold leading-none text-text sm:text-[52px]">Airborne.</h2>
      <p className="mt-3 text-[15px] text-muted">{cartridge?.name ?? "The Broken Airship"} — here's what you did, straight from the log.</p>

      {recap.recognized.length > 0 && (
        <section className="mt-7" data-testid="recap-recognized">
          <div className="text-[12px] font-semibold uppercase tracking-[0.2em] text-faint">You recognized</div>
          <div className="mt-2.5 flex flex-wrap gap-2.5">
            {recap.recognized.map((r) => (
              <span key={r.concept_id} className="inline-flex items-baseline gap-2 rounded-2xl border border-line-strong bg-white/[0.04] px-4 py-2">
                <span className="jp text-[30px] leading-none text-text">{r.native}</span>
                <span className="text-[16px] text-romaji">{r.romanization}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      {(key || map) && (
        <section className="mt-7 grid gap-3 sm:grid-cols-2" data-testid="recap-compare">
          {key && <MomentCard title="Asking for the key" p={key} objectHint="key" />}
          {map && <MomentCard title="Asking for the map" p={map} objectHint="map" highlight={recap.transfer.achieved} />}
        </section>
      )}

      {recap.lines.length > 0 && (
        <ul className="mt-6 space-y-2" data-testid="recap-lines">
          {recap.lines.map((l, i) => (
            <li key={i} className="flex gap-3 text-[15px] leading-relaxed text-text/90">
              <span className="mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brass" />
              {l}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-8 flex flex-col-reverse items-start gap-4 border-t border-line pt-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-[15px] text-sky" data-testid="recap-next">
          {recap.next_episode}
        </div>
        <button
          type="button"
          onClick={() => void reset({ restart: true })}
          className="inline-flex h-12 items-center gap-2 rounded-full bg-gradient-to-b from-brass-strong to-brass px-6 text-[15px] font-bold text-ink shadow-[0_14px_40px_-12px_rgba(233,180,95,0.8)] hover:brightness-105"
          data-testid="play-again"
        >
          <IconRetry className="h-4 w-4" />
          Play again
        </button>
      </div>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const plate = resolveArt(useGame((s) => s.world?.plate_url));
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center overflow-y-auto bg-ink/45 p-3 backdrop-blur-[6px] sm:items-center sm:p-8" data-testid="end-card">
      <div className="rise-in glass relative my-auto w-full max-w-[780px] overflow-hidden rounded-[28px] shadow-[0_40px_120px_-20px_rgba(0,0,0,0.9)]">
        {/* The launched plate as a banner: the payoff stays in view. */}
        <div className="relative h-36 w-full overflow-hidden sm:h-44">
          <ArtImage src={plate} kind="plate" alt="" className="h-full w-full object-cover object-[50%_22%]" />
          <div className="absolute inset-0 bg-gradient-to-b from-transparent via-[rgba(13,16,25,0.25)] to-[rgb(15,19,29)]" />
        </div>
        <div className="relative -mt-8 px-6 pb-7 sm:-mt-10 sm:px-10 sm:pb-10">{children}</div>
      </div>
    </div>
  );
}

function MomentCard({ title, p, objectHint, highlight }: { title: string; p: RecapProduction; objectHint: string; highlight?: boolean }) {
  const obj = useGame((s) => s.cartridge?.objects.find((o) => o.concept_id === p.concept_id));
  return (
    <div
      className={`rounded-2xl border p-4 ${highlight ? "border-brass/40 bg-brass/[0.07]" : "border-line bg-white/[0.03]"}`}
      data-testid={`moment-${objectHint}`}
    >
      <div className="flex items-center gap-3">
        <div className="h-10 w-10">
          <ObjectGlyph objectId={obj?.id ?? objectHint} iconUrl={obj?.icon_url} />
        </div>
        <div>
          <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-faint">{title}</div>
          <div className="text-[15px] font-semibold text-text">{p.stage ? (STAGE_WORDS[p.stage] ?? "Made yourself understood") : "Finished with a tap"}</div>
        </div>
      </div>
      {p.transcript && (
        <div className="mt-3 rounded-xl bg-ink/40 px-3 py-2">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.2em] text-sky/80">You said</div>
          <div className="jp text-[20px] text-text">{p.transcript}</div>
        </div>
      )}
      <div className="mt-3 inline-flex items-center gap-2 rounded-full bg-white/[0.05] px-3 py-1 text-[12.5px] text-muted">
        <SupportMeter level={p.support_level} />
        {supportPhrase(p.support_level, p.input_mode)}
      </div>
    </div>
  );
}

function SupportMeter({ level }: { level: number }) {
  return (
    <span className="inline-flex items-center gap-[3px]" aria-label={`help used: level ${level} of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span key={i} className={`h-1.5 w-1.5 rounded-full ${i <= level ? "bg-brass" : "bg-white/15"}`} />
      ))}
    </span>
  );
}

export type { Recap };
