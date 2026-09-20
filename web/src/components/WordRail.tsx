// The word rail: always open down the left, on a screen wide enough to hold it.
//
// It answers "what can I even say?" without ever answering "what did he just say?". By
// default it holds ONLY the words he has actually said, in the order he said them, so it
// starts empty and fills as you listen — the list is earned, and listening stays the way you
// get one. The full scene vocabulary sits behind the search box, for when you are stuck and
// need a word you have not met.
//
// That boundary is the point. A permanently visible list of every word with its meaning
// would let someone finish the scene by scanning the English column, which is the same
// failure as a translator, only slower. One word at a time, on purpose: there is nowhere
// here that takes a sentence.

import { useMemo, useState } from "react";
import { useGame } from "../store";

/** Compare the way a learner types: no tone marks, no case. */
function fold(s: string): string {
  return s
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .trim()
    .toLowerCase();
}

export function WordRail() {
  const heard = useGame((s) => s.heard);
  const dictionary = useGame((s) => s.dictionary);
  const language = useGame((s) => s.language);
  const sayWord = useGame((s) => s.sayWord);
  const phase = useGame((s) => s.phase);
  const [q, setQ] = useState("");

  const found = useMemo(() => {
    const needle = fold(q);
    if (!needle) return null;
    return dictionary.filter((w) =>
      [w.gloss, w.text, w.roman].some((f) => {
        const hay = fold(f);
        return hay.includes(needle) || hay.replace(/\s+/g, "").includes(needle.replace(/\s+/g, ""));
      })
    );
  }, [dictionary, q]);

  if (!language) return null;
  const showRoman = language.romanization_label != null;
  const busy = phase === "waiting" || phase === "transcribing";
  // In the order he said them: reversing it splits a phrase across the list and reads
  // backwards. New words arrive at the bottom, where the eye already is.
  const mine = heard;

  const row = (key: string, text: string, roman: string, gloss: string, testid: string) => (
    <li key={key}>
      <button
        type="button"
        data-testid={testid}
        data-word={text}
        disabled={busy}
        onClick={() => sayWord(text)}
        title="Put it in the box"
        className="flex w-full flex-col items-start gap-0.5 rounded-[8px] border-0 bg-transparent px-2 py-1.5 text-left transition-colors hover:bg-white/[0.05] disabled:opacity-40"
      >
        <span className="flex items-baseline gap-2">
          <span lang={language.locale} className="target text-[16px] text-ink">{text}</span>
          {showRoman && roman && <span className="text-[11px] text-ink-3">{roman}</span>}
        </span>
        {gloss && <span data-role="word-gloss" className="text-[12px] leading-tight text-ink-2">{gloss}</span>}
      </button>
    </li>
  );

  return (
    <aside
      data-testid="word-rail"
      className="pointer-events-auto absolute left-0 top-0 z-30 hidden h-full w-[232px] flex-col border-r border-hair bg-[#0b0c0c]/80 backdrop-blur-md lg:flex"
    >
      <div className="shrink-0 px-3 pb-2 pt-4">
        <input
          data-testid="rail-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Look up a word…"
          aria-label="Look up a word"
          autoComplete="off"
          className="h-9 w-full rounded-[8px] border border-hair bg-transparent px-2.5 text-[13px] text-ink outline-none placeholder:text-ink-3 focus:border-hair-2"
        />
        <p className="m-0 px-1 pt-2 text-[11px] text-ink-3">
          {found ? `${found.length} in the dictionary` : "Words you have heard"}
        </p>
      </div>

      <ul className="m-0 min-h-0 flex-1 list-none overflow-y-auto px-1.5 pb-4">
        {found === null && mine.length === 0 && (
          <li data-testid="rail-empty" className="px-2 py-3 text-[12px] leading-snug text-ink-3">
            Nothing yet. Words land here as he says them.
          </li>
        )}
        {found === null &&
          mine.map((w, i) => row(`${w.text}-${i}`, w.text, w.roman, w.gloss, "heard-word"))}
        {found !== null && found.length === 0 && (
          <li data-testid="rail-none" className="px-2 py-3 text-[12px] leading-snug text-ink-3">
            Nothing for that. Try a single word.
          </li>
        )}
        {found?.map((w) => row(w.item_id, w.text, w.roman, w.gloss, "dictionary-word"))}
      </ul>
    </aside>
  );
}
