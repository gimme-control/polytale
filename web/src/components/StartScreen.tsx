// Title: the story is the hero. Its art, its name, its premise, how hard you want it,
// and one button.

import { useGame } from "../store";
import { Picture } from "./Picture";
import type { Difficulty } from "../lib/types";

const DIFFICULTIES: { id: Difficulty; label: string; blurb: string }[] = [
  { id: "story", label: "Story", blurb: "The narrator keeps you oriented." },
  { id: "immersion", label: "Immersion", blurb: "You're on your own." },
];

export function StartScreen() {
  const catalog = useGame((s) => s.catalog);
  const story = useGame((s) => s.story ?? s.catalog?.story ?? null);
  const language = useGame((s) => s.language ?? s.catalog?.language ?? null);
  const starting = useGame((s) => s.starting);
  const error = useGame((s) => s.startError);
  const begin = useGame((s) => s.begin);
  const difficulty = useGame((s) => s.chosenDifficulty);
  const chooseDifficulty = useGame((s) => s.chooseDifficulty);
  const art = story?.art_url || catalog?.scenes[0]?.cover_url;

  return (
    <main data-testid="start-screen" className="slow-fade-in absolute inset-0 overflow-hidden">
      <Picture src={art} className="absolute inset-0" />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-[#080909] from-[8%] via-[#080909]/60 via-[52%] to-[#080909]/10" />

      <p data-testid="wordmark" className="over-art absolute left-6 top-6 m-0 text-[15px] font-semibold tracking-[-0.01em] text-ink sm:left-12 sm:top-10">
        Polytale
      </p>

      <div className="absolute inset-x-0 bottom-0 mx-auto w-full max-w-[1180px] px-6 pb-9 sm:px-12 sm:pb-16">
        <h1 data-testid="story-title" className="story over-art m-0 text-[46px] font-medium leading-[1.02] tracking-[-0.02em] text-ink sm:text-[76px]">
          {story?.title ?? "Polytale"}
        </h1>
        <p data-testid="premise" className="story over-art m-0 mt-4 max-w-[560px] text-[17px] leading-[1.55] text-ink/90 sm:mt-5 sm:text-[19px]">
          {story?.premise ?? "Learn a language by needing it."}
        </p>
        {language && (
          <p data-testid="language-line" className="over-art m-0 mt-4 text-[13px] text-ink-2">
            Learn a language by needing it. {language.name} ·{" "}
            <span lang={language.locale} className="target font-normal">
              {language.native_name}
            </span>
          </p>
        )}

        <div role="radiogroup" aria-label="Difficulty" data-testid="difficulty-choice" className="mt-7 flex max-w-[520px] gap-2 sm:mt-9">
          {DIFFICULTIES.map((d) => {
            const on = d.id === difficulty;
            return (
              <button
                key={d.id}
                type="button"
                role="radio"
                aria-checked={on}
                data-testid={`start-difficulty-${d.id}`}
                data-active={on ? "1" : "0"}
                onClick={() => chooseDifficulty(d.id)}
                className={`flex-1 rounded-[10px] border bg-glass px-4 py-3 text-left backdrop-blur-md transition-colors duration-150 ${on ? "border-ink/70" : "border-hair hover:border-hair-2"}`}
              >
                <span className={`block text-[14px] font-semibold ${on ? "text-ink" : "text-ink-2"}`}>{d.label}</span>
                <span className="mt-0.5 block text-[12px] leading-snug text-ink-3">{d.blurb}</span>
              </button>
            );
          })}
        </div>

        <div className="mt-5 flex flex-col gap-4 sm:mt-6 sm:flex-row sm:items-center sm:gap-6">
          <button
            type="button"
            data-testid="begin-button"
            disabled={starting}
            onClick={() => void begin()}
            className="h-12 shrink-0 rounded-[10px] border-0 bg-ink px-9 text-[15px] font-semibold text-night transition-opacity duration-150 hover:opacity-90 disabled:opacity-60"
          >
            {starting ? "One moment…" : "Begin"}
          </button>
          <p className="over-art m-0 max-w-[400px] text-[13px] leading-relaxed text-ink-2">
            Polytale will ask to use your microphone so you can speak. If you'd rather not, decline and type instead.
          </p>
        </div>
        {error && (
          <p data-testid="start-error" role="alert" className="fade-in m-0 mt-4 text-[13px] text-ink">
            {error}
          </p>
        )}
      </div>
    </main>
  );
}
