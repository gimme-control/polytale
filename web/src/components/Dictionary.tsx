// The dictionary: every word of this scene, searchable, one word at a time.
//
// It replaces the old "How do I say…?" box, which took a whole English sentence and handed
// back the target-language sentence. That is a translator, and it plays the game for you.
// This is deliberately narrower: you can look up what a single WORD means, or find the word
// for a single thing, and that is all. There is no box that takes a sentence, so stringing
// words together into something he understands is still your job — which is the game.
//
// Words he has already said are marked, so you can tell what you have actually met from what
// you are reaching for. Tapping any word puts it in the input.

import { useEffect, useMemo, useRef, useState } from "react";
import { useGame } from "../store";

/** Compare the way a learner actually types: no tone marks, no case. The lexicon stores
 *  "péngyou"; somebody hunting for it types "pengyou", and both must find the word. */
function fold(s: string): string {
  return s
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .trim()
    .toLowerCase();
}

export function DictionaryDrawer({ onClose }: { onClose: () => void }) {
  const dictionary = useGame((s) => s.dictionary);
  const language = useGame((s) => s.language);
  const sayWord = useGame((s) => s.sayWord);
  const [q, setQ] = useState("");
  const field = useRef<HTMLInputElement>(null);

  useEffect(() => {
    field.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  const results = useMemo(() => {
    const needle = fold(q);
    if (!needle) return dictionary;
    // Search the meaning, the word itself and its romanization, so it works whichever end
    // the player starts from and whatever they can actually type.
    return dictionary.filter((w) =>
      [w.gloss, w.text, w.roman].some((f) => {
        const hay = fold(f);
        // Also match with spaces closed up: a learner types "nihao", the lexicon says "nǐ hǎo".
        return hay.includes(needle) || hay.replace(/\s+/g, "").includes(needle.replace(/\s+/g, ""));
      })
    );
  }, [dictionary, q]);

  if (!language) return null;
  const showRoman = language.romanization_label != null;

  return (
    <div data-testid="dictionary" className="fade-in absolute inset-0 z-40 flex justify-center bg-[#080909]/70 backdrop-blur-sm" onClick={onClose}>
      <div
        className="mt-[8vh] flex h-fit max-h-[78vh] w-full max-w-[520px] flex-col overflow-hidden rounded-[14px] border border-hair-2 bg-[#0e0f0f]/95"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-hair px-5 py-4">
          <div>
            <h2 className="m-0 text-[15px] font-semibold text-ink">Dictionary</h2>
            <p className="m-0 mt-0.5 text-[12px] text-ink-3">One word at a time. No sentences.</p>
          </div>
          <button type="button" data-testid="dictionary-close" onClick={onClose} className="border-0 bg-transparent p-1 text-[13px] text-ink-2 hover:text-ink">
            Close
          </button>
        </div>

        <div className="shrink-0 px-5 pt-4">
          <input
            ref={field}
            data-testid="dictionary-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search a word or a meaning…"
            aria-label="Search the dictionary"
            autoComplete="off"
            className="h-10 w-full rounded-[8px] border border-hair bg-transparent px-3 text-[15px] text-ink outline-none placeholder:text-ink-3 focus:border-hair-2"
          />
        </div>

        <ul className="m-0 min-h-0 flex-1 list-none overflow-y-auto px-5 py-3">
          {results.length === 0 && (
            <li data-testid="dictionary-empty" className="py-6 text-center text-[13px] text-ink-3">
              Nothing for that. Try a single word.
            </li>
          )}
          {results.map((w) => (
            <li key={w.item_id} className="border-b border-hair last:border-0">
              <button
                type="button"
                data-testid="dictionary-word"
                data-heard={w.heard ? "1" : "0"}
                onClick={() => {
                  sayWord(w.text);
                  onClose();
                }}
                title="Put it in the box"
                className="flex w-full items-baseline justify-between gap-4 border-0 bg-transparent px-0 py-3 text-left hover:bg-white/[0.03]"
              >
                <span className="flex min-w-0 items-baseline gap-2.5">
                  <span lang={language.locale} className="target shrink-0 text-[17px] text-ink">
                    {w.text}
                  </span>
                  {showRoman && w.roman && <span className="shrink-0 text-[12px] text-ink-3">{w.roman}</span>}
                </span>
                <span className="flex items-baseline gap-2.5">
                  <span data-role="word-gloss" className="text-right text-[13px] text-ink-2">{w.gloss}</span>
                  {w.heard && (
                    <span data-testid="dictionary-heard" title="He has said this" className="shrink-0 text-[10px] text-jade">
                      heard
                    </span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
