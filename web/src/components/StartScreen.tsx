// Title: the story is the hero. Its art, its name, its premise, the language you want
// to need it in, and one button.

import { useGame } from "../store";
import { Picture } from "./Picture";

export function StartScreen() {
  const catalog = useGame((s) => s.catalog);
  const story = useGame((s) => s.story ?? s.catalog?.story ?? null);
  const language = useGame((s) => s.language ?? s.catalog?.language ?? null);
  const languages = useGame((s) => s.catalog?.languages ?? []);
  const chosen = useGame((s) => s.chosenLanguage ?? s.language?.locale ?? s.catalog?.language?.locale ?? null);
  const chooseLanguage = useGame((s) => s.chooseLanguage);
  const starting = useGame((s) => s.starting);
  const error = useGame((s) => s.startError);
  const begin = useGame((s) => s.begin);
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
        <p data-testid="language-line" className="over-art m-0 mt-4 text-[13px] text-ink-2">
          Learn a language by needing it.
          {/* Without the catalog's list there is no picker, so name the one language here. */}
          {languages.length === 0 && language && (
            <>
              {" "}
              {language.name} ·{" "}
              <span lang={language.locale} className="target font-normal">
                {language.native_name}
              </span>
            </>
          )}
        </p>

        {languages.length > 0 && (
          <div className="mt-7 max-w-[560px] sm:mt-9">
            <p className="over-art m-0 text-[13px] text-ink-2">Which language do you want to need?</p>
            <div role="radiogroup" aria-label="Language" data-testid="language-choice" className="mt-2.5 flex flex-wrap gap-2">
              {languages.map((l) => {
                const on = l.locale === chosen;
                return (
                  <button
                    key={l.locale}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    aria-label={l.name}
                    data-testid={`start-language-${l.locale}`}
                    data-locale={l.locale}
                    data-active={on ? "1" : "0"}
                    onClick={() => chooseLanguage(l.locale)}
                    className={`rounded-[10px] border bg-glass px-4 py-2.5 text-left backdrop-blur-md transition-colors duration-150 ${on ? "border-ink/70" : "border-hair hover:border-hair-2"}`}
                  >
                    <span lang={l.locale} className={`target block text-[18px] leading-tight ${on ? "text-ink" : "text-ink-2"}`}>
                      {l.native_name}
                    </span>
                    <span className="mt-0.5 block text-[12px] leading-snug text-ink-3">{l.name}</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

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
