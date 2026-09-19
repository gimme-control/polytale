// "How do I say...?" The learner writes what THEY want to say, in English, and gets
// the simplest way to say it: ruby above each word, a gloss beneath it (it is their own
// sentence, so glossing it is fair), audio, and "Use it". It never translates what a
// character said. Collapsed it is a slim tab; open it is a card floating over the
// right of the scene, or a bottom sheet on a narrow screen.

import { useEffect, useRef, useState } from "react";
import { useGame } from "../store";
import type { Language, Phrase } from "../lib/types";

const PUNCT = /^[\p{P}\p{S}\s]+$/u;

/** A looked-up phrase: romanization over each word, its gloss under it. */
export function PhraseLine({ phrase, language, size = "lg" }: { phrase: Phrase; language: Language; size?: "lg" | "sm" }) {
  const roman = language.romanization_label != null;
  return (
    <span lang={language.locale} data-role="phrase" className={`target flex flex-wrap items-end gap-y-2 ${size === "lg" ? "text-[28px]" : "text-[20px]"} leading-none text-ink`}>
      {phrase.segments.map((s, i) => {
        const word = !PUNCT.test(s.t);
        return (
          <span key={i} className={`inline-flex flex-col items-center ${word ? "mx-[0.12em]" : ""} ${language.word_spacing && word && i > 0 ? "ml-[0.3em]" : ""}`}>
            {roman && <span className="font-ui pb-1 text-[12px] font-normal leading-none text-ink-2">{word && s.r ? s.r : " "}</span>}
            <span>{s.t}</span>
            {size === "lg" && (
              <span data-role="phrase-gloss" className="font-ui max-w-[7.5em] pt-1.5 text-center text-[11px] font-normal leading-tight text-ink-3">
                {word && s.g ? s.g : " "}
              </span>
            )}
          </span>
        );
      })}
    </span>
  );
}

export function PhrasebookTab() {
  const open = useGame((s) => s.phraseOpen);
  const setOpen = useGame((s) => s.setPhraseOpen);
  if (open) return null;
  return (
    <button
      type="button"
      data-testid="phrasebook-tab"
      onClick={() => setOpen(true)}
      className="pointer-events-auto absolute right-0 top-[42%] z-20 hidden -translate-y-1/2 rounded-l-[10px] border border-r-0 border-hair bg-glass px-1.5 py-4 text-[13px] font-medium text-ink-2 backdrop-blur-md transition-colors duration-150 [writing-mode:vertical-rl] hover:border-hair-2 hover:text-ink min-[1100px]:block"
    >
      How do I say…?
    </button>
  );
}

export function Phrasebook() {
  const open = useGame((s) => s.phraseOpen);
  const setOpen = useGame((s) => s.setPhraseOpen);
  const language = useGame((s) => s.language);
  const busy = useGame((s) => s.phraseBusy);
  const error = useGame((s) => s.phraseError);
  const result = useGame((s) => s.phraseResult);
  const phrases = useGame((s) => s.phrasebook);
  const askPhrase = useGame((s) => s.askPhrase);
  const showPhrase = useGame((s) => s.showPhrase);
  const playPhrase = useGame((s) => s.playPhrase);
  const usePhraseText = useGame((s) => s.usePhrase);
  const [text, setText] = useState("");
  const field = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) return;
    field.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open, setOpen]);

  if (!open || !language) return null;
  const others = phrases.filter((p) => p.phrase_id !== result?.phrase_id);

  return (
    <div className="absolute inset-0 z-30 min-[1100px]:pointer-events-none" data-testid="phrasebook">
      <button type="button" aria-label="Close phrasebook" onClick={() => setOpen(false)} className="fade-in absolute inset-0 h-full w-full cursor-default border-0 bg-black/50 min-[1100px]:hidden" />
      <aside
        aria-label="Phrasebook"
        className="sheet-in pointer-events-auto absolute inset-x-0 bottom-0 flex max-h-[82%] flex-col rounded-t-[14px] border border-b-0 border-hair bg-[#0e0f0f]/96 backdrop-blur-xl min-[1100px]:inset-x-auto min-[1100px]:bottom-auto min-[1100px]:right-4 min-[1100px]:top-[76px] min-[1100px]:max-h-[calc(100%-92px)] min-[1100px]:w-[340px] min-[1100px]:rounded-[12px] min-[1100px]:border-b"
      >
        <header className="flex items-center justify-between px-5 pb-1 pt-4">
          <h2 className="m-0 text-[15px] font-semibold tracking-[-0.01em]">How do I say…?</h2>
          <button type="button" data-testid="phrasebook-close" onClick={() => setOpen(false)} className="border-0 bg-transparent p-0 text-[13px] text-ink-2 hover:text-ink">
            Close
          </button>
        </header>
        <p className="m-0 px-5 text-[12px] leading-relaxed text-ink-3">For what you want to say. Looking something up costs no time in the story.</p>

        <form
          className="px-5 pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            void askPhrase(text);
          }}
        >
          <div className="flex h-11 items-center rounded-[9px] border border-hair bg-black/30 focus-within:border-hair-2">
            <input
              ref={field}
              data-testid="phrase-input"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Have you seen her?"
              aria-label="What do you want to say, in English"
              autoComplete="off"
              className="h-full min-w-0 flex-1 border-0 bg-transparent pl-3.5 text-[15px] text-ink outline-none placeholder:text-ink-3"
            />
            <button type="submit" data-testid="phrase-ask" disabled={busy || !text.trim()} className="mr-1 h-8 rounded-[7px] border-0 bg-ink px-3 text-[13px] font-medium text-night transition-opacity duration-150 disabled:opacity-35">
              Ask
            </button>
          </div>
        </form>

        <div className="scroll-quiet min-h-0 flex-1 overflow-y-auto px-5 pb-5 pt-4">
          {busy && (
            <div data-testid="phrase-loading" className="thinking py-3" aria-label="Looking it up">
              <span />
              <span />
              <span />
            </div>
          )}
          {error && !busy && (
            <p data-testid="phrase-error" role="alert" className="fade-in m-0 text-[13px] leading-relaxed text-ink-2">
              {error}
            </p>
          )}
          {result && !busy && !error && (
            <section data-testid="phrase-result" className="rise-in">
              <p className="story m-0 text-[15px] italic text-ink-3">“{result.source}”</p>
              <div className="mt-3">
                <PhraseLine phrase={result} language={language} />
              </div>
              <div className="mt-4 flex items-center gap-2">
                <button type="button" data-testid="phrase-use" onClick={() => usePhraseText(result)} className="h-9 rounded-[8px] border-0 bg-ink px-4 text-[13px] font-medium text-night hover:opacity-90">
                  Use it
                </button>
                <button type="button" data-testid="phrase-play" onClick={() => playPhrase(result)} className="h-9 rounded-[8px] border border-hair bg-transparent px-4 text-[13px] font-medium text-ink hover:border-hair-2">
                  Hear it
                </button>
              </div>
              <p className="m-0 mt-2.5 text-[12px] text-ink-3">It goes into the box. Send it, or hold the mic and say it yourself.</p>
            </section>
          )}

          {others.length > 0 && (
            <section className={result || error ? "mt-6 border-t border-hair pt-4" : ""}>
              <h3 className="m-0 text-[12px] font-normal text-ink-3">Your phrases</h3>
              <ul data-testid="phrase-list" className="m-0 mt-1 list-none p-0">
                {others.map((p) => (
                  <li key={p.phrase_id}>
                    <button type="button" data-testid="phrase-saved" onClick={() => showPhrase(p)} className="flex w-full items-baseline justify-between gap-3 border-0 border-b border-hair bg-transparent px-0 py-2.5 text-left hover:bg-white/[0.03]">
                      <span lang={language.locale} className="target text-[17px] text-ink">
                        {p.text}
                      </span>
                      <span className="truncate text-[12px] text-ink-3">{p.source}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </aside>
    </div>
  );
}
