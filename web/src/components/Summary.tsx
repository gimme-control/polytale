// End of scene. The first and only place the word list appears: target text,
// romanization, gloss, how each one went, tap to hear. Words that came back from an
// earlier scene with no help are called out first; that is the proof of learning.

import { useState } from "react";
import { api } from "../lib/api";
import { linePlayer } from "../audio/linePlayer";
import { useGame } from "../store";
import { Picture } from "./Picture";
import { PhraseLine } from "./Phrasebook";
import type { Ending, ItemState, SummaryItem } from "../lib/types";

const STATE_LABEL: Record<ItemState, string> = { mastered: "mastered", shaky: "shaky", not_encountered: "not met" };
const OUTCOME: Record<string, string> = {
  first_try: "first try",
  with_help: "needed a repeat",
  with_hint: "needed a hint",
  missed: "missed",
};

function howItWent(item: SummaryItem): string {
  if (!item.outcomes.length) return item.heard ? "not yet used" : "";
  const seen: string[] = [];
  for (const o of item.outcomes) {
    const label = OUTCOME[o] ?? o;
    if (seen[seen.length - 1] !== label) seen.push(label);
  }
  return seen.slice(-3).join(", then ");
}

export function Summary() {
  const summary = useGame((s) => s.summary);
  const language = useGame((s) => s.language);
  const scenes = useGame((s) => s.scenes);
  const ending = useGame((s) => s.ending);
  const phrases = useGame((s) => s.summary?.phrasebook ?? s.phrasebook);
  const game = useGame((s) => s.game);
  const chooseDifficulty = useGame((s) => s.chooseDifficulty);
  const playPhrase = useGame((s) => s.playPhrase);
  const continueJourney = useGame((s) => s.continueJourney);
  const newJourney = useGame((s) => s.newJourney);
  const [busy, setBusy] = useState(false);
  if (!language || (!summary && !ending)) return null;
  if (!summary) return <main data-testid="summary" className="slow-fade-in scroll-quiet absolute inset-0 overflow-y-auto bg-sheet">{ending && <EndingHero ending={ending} />}</main>;
  const other = game?.difficulty === "immersion" ? "story" : "immersion";

  const recalled = summary.items.filter((i) => summary.recalled.includes(i.item_id));
  const earlier = scenes.filter((s) => s.status === "done" && s.id !== summary.scene_id).map((s) => s.name);
  const from = earlier.length ? earlier.join(" and ") : "an earlier scene";
  const c = summary.counts;
  const showRoman = language.romanization_label != null;

  return (
    <main data-testid="summary" className="slow-fade-in scroll-quiet absolute inset-0 overflow-y-auto bg-sheet">
      {ending && <EndingHero ending={ending} />}
      <div className="mx-auto w-full max-w-[760px] px-5 pb-10 pt-12 sm:px-8 sm:pt-20">
        <p className="m-0 text-[14px] text-ink-2">{summary.scene_name}</p>
        <h1 className="m-0 mt-2 text-[30px] font-semibold leading-tight tracking-[-0.025em] sm:text-[38px]">What you picked up</h1>
        <p data-testid="summary-counts" className="m-0 mt-3 text-[14px] tabular-nums text-ink-2">
          {c.mastered} mastered · {c.shaky} shaky{c.heard ? ` · ${c.heard} heard` : ""} · {c.not_encountered} not met
        </p>

        {recalled.length > 0 && (
          <section data-testid="recall-callout" className="mt-9 border-l-2 border-jade pl-5">
            <p className="m-0 text-[14px] text-jade">Came back from {from}, no hints</p>
            <p lang={language.locale} className="target m-0 mt-2 text-[26px] leading-snug text-ink sm:text-[30px]">
              {recalled.map((i) => i.text).join(" · ")}
            </p>
          </section>
        )}

        {summary.lines.length > 0 && (
          <section data-testid="summary-lines" className="mt-9 space-y-1.5">
            {summary.lines.map((l, i) => (
              <p key={i} className="m-0 text-[15px] leading-relaxed text-ink-2">
                {l}
              </p>
            ))}
          </section>
        )}

        {phrases.length > 0 && (
          <section data-testid="summary-phrases" className="mt-10">
            <h2 className="m-0 text-[14px] font-normal text-ink-2">Your phrases</h2>
            <ul className="m-0 mt-2 list-none border-t border-hair p-0">
              {phrases.map((p) => (
                <li key={p.phrase_id} className="border-b border-hair">
                  <button type="button" data-testid="summary-phrase" onClick={() => playPhrase(p)} title="Hear it" className="flex w-full flex-wrap items-end justify-between gap-x-6 gap-y-1 border-0 bg-transparent px-0 py-3.5 text-left hover:bg-white/[0.03]">
                    <PhraseLine phrase={p} language={language} size="sm" />
                    <span className="story text-[14px] italic text-ink-3">“{p.source}”</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <ul data-testid="word-list" className="m-0 mt-10 list-none border-t border-hair p-0">
          {summary.items.map((item) => (
            <WordRow key={item.item_id} item={item} locale={language.locale} showRoman={showRoman} />
          ))}
        </ul>

      </div>
      <div className="sticky bottom-0 border-t border-hair bg-sheet/92 backdrop-blur-md">
        <div className="mx-auto flex w-full max-w-[760px] flex-wrap items-center gap-x-6 gap-y-3 px-5 py-4 sm:px-8 sm:py-5">
          {summary.next_scene ? (
            <button
              type="button"
              data-testid="continue-button"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                void continueJourney().finally(() => setBusy(false));
              }}
              className="h-12 rounded-[10px] border-0 bg-ink px-7 text-[15px] font-semibold text-night transition-opacity duration-150 hover:opacity-90 disabled:opacity-60"
            >
              Continue to {summary.next_scene.name}
            </button>
          ) : null}
          <button
            type="button"
            data-testid="start-over"
            onClick={() => void newJourney()}
            className={
              summary.next_scene
                ? "border-0 bg-transparent p-0 text-[14px] text-ink-2 underline decoration-hair-2 underline-offset-4 hover:text-ink"
                : "h-12 rounded-[10px] border-0 bg-ink px-7 text-[15px] font-semibold text-night hover:opacity-90"
            }
          >
            {ending ? "Play again" : "Start over"}
          </button>
          {ending && (
            <button
              type="button"
              data-testid="play-other"
              onClick={() => {
                chooseDifficulty(other);
                void newJourney();
              }}
              className="border-0 bg-transparent p-0 text-[14px] text-ink-2 underline decoration-hair-2 underline-offset-4 hover:text-ink"
            >
              Try {other === "immersion" ? "Immersion" : "Story mode"}
            </button>
          )}
        </div>
      </div>
    </main>
  );
}

function Mark({ state }: { state: ItemState }) {
  // filled / half / empty
  return (
    <span aria-hidden className="relative block h-[10px] w-[10px] shrink-0 overflow-hidden rounded-full border border-ink-2">
      {state !== "not_encountered" && <span className={`absolute inset-y-0 left-0 bg-ink ${state === "mastered" ? "w-full" : "w-1/2"}`} />}
    </span>
  );
}

function WordRow({ item, locale, showRoman }: { item: SummaryItem; locale: string; showRoman: boolean }) {
  const journeyId = useGame((s) => s.journeyId);
  const token = useGame((s) => s.token);
  const [playing, setPlaying] = useState(false);
  const unmet = item.state === "not_encountered";
  const play = async () => {
    if (!journeyId || !token || playing) return;
    setPlaying(true);
    try {
      await linePlayer.playClip(await api.itemAudio(journeyId, token, item.item_id, item.audio_url));
    } catch {
      /* audio is optional; the word is still on screen */
    } finally {
      setPlaying(false);
    }
  };
  return (
    <li className="border-b border-hair">
      <button
        type="button"
        data-testid="word-row"
        data-item={item.item_id}
        data-state={item.state}
        data-recall={item.recall ? "1" : "0"}
        onClick={() => void play()}
        title="Hear it"
        className={`group grid w-full grid-cols-[14px_minmax(0,1fr)] items-center gap-x-4 border-0 bg-transparent px-0 py-4 text-left transition-colors duration-150 hover:bg-white/[0.03] sm:grid-cols-[14px_minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1.2fr)] ${unmet ? "opacity-55" : ""}`}
      >
        <Mark state={item.state} />
        <span className="flex min-w-0 items-baseline gap-3">
          <span lang={locale} className={`target text-[24px] leading-none transition-colors duration-150 ${playing ? "text-jade" : "text-ink"}`}>
            {item.text}
          </span>
          {showRoman && item.roman && <span className="truncate text-[14px] text-ink-2">{item.roman}</span>}
        </span>
        <span data-role="gloss" className="col-start-2 mt-1 text-[14px] text-ink-2 sm:col-start-auto sm:mt-0">
          {item.gloss}
        </span>
        <span className="col-start-2 mt-0.5 text-[13px] text-ink-3 sm:col-start-auto sm:mt-0 sm:text-right">
          <span className="text-ink-2">{unmet && item.heard ? "heard" : STATE_LABEL[item.state]}</span>
          {howItWent(item) && <span> · {howItWent(item)}</span>}
          {item.recall && <span className="text-jade"> · recalled</span>}
        </span>
      </button>
    </li>
  );
}

/** The ending: art, title, the last of the prose, and what it cost you. */
function EndingHero({ ending }: { ending: Ending }) {
  const symbol = useGame((s) => s.language?.currency_symbol ?? "");
  const st = ending.stats;
  return (
    <section data-testid="ending" data-ending={ending.id} className="relative flex min-h-[92%] flex-col justify-end overflow-hidden">
      <Picture src={ending.art_url || undefined} className="absolute inset-0" />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-[#101111] from-[4%] via-[#101111]/70 via-[46%] to-[#101111]/10" />
      <div className="relative mx-auto w-full max-w-[760px] px-5 pb-12 pt-40 sm:px-8 sm:pb-16">
        <p className="over-art m-0 text-[14px] text-ink-2">The end</p>
        <h1 data-testid="ending-title" className="story over-art m-0 mt-2 text-[44px] font-medium leading-[1.04] tracking-[-0.02em] sm:text-[64px]">
          {ending.title}
        </h1>
        <p data-testid="ending-text" className="story over-art m-0 mt-5 max-w-[600px] text-[18px] leading-[1.6] text-ink/90 sm:text-[20px]">
          {ending.text}
        </p>
        <dl data-testid="ending-stats" className="m-0 mt-9 flex flex-wrap gap-x-10 gap-y-4">
          <Stat label={st.minutes_left > 0 ? "to spare" : "too late"} value={st.minutes_left > 0 ? `${st.minutes_left} min` : "0 min"} />
          <Stat label="left in your pocket" value={`${symbol}${st.wallet}`} />
          <Stat label={st.clues === 1 ? "clue found" : "clues found"} value={String(st.clues)} />
          <Stat label="words that stuck" value={String(st.words_mastered)} />
        </dl>
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dd className="m-0 text-[24px] font-semibold tabular-nums tracking-[-0.02em] text-ink">{value}</dd>
      <dt className="mt-0.5 text-[12px] text-ink-3">{label}</dt>
    </div>
  );
}
