// The words he has already said, with what each ONE means, tappable, above the input.
//
// This answers "I don't know this language, what can I possibly type?". With zero knowledge
// the only reasonable move is to hand back something you have just heard, and on a US
// keyboard you often cannot type the script even if you knew it. So every word the character
// has spoken stays here — his script, its romanization, and that single word's meaning — and
// a tap drops it into the box. Two taps make a sentence, which is the whole game.
//
// A per-word meaning is a DICTIONARY, never a translation. It never says what a whole sentence
// meant, and it only ever holds words he has already said out loud in front of you. Working
// out what he is actually asking for, and which words to put together, is still yours to do.

import { useGame } from "../store";

const MAX_WORDS = 8;

export function Heard() {
  const heard = useGame((s) => s.heard);
  const language = useGame((s) => s.language);
  const sayWord = useGame((s) => s.sayWord);
  const phase = useGame((s) => s.phase);

  // What he actually said, most recent nearest the input box.
  if (!language || heard.length === 0) return null;
  const words = heard.slice(-MAX_WORDS);
  const showRoman = language.romanization_label != null;
  const busy = phase === "waiting" || phase === "transcribing";

  return (
    <div
      data-testid="heard-strip"
      className="mx-auto flex w-full max-w-[760px] shrink-0 flex-col items-center gap-3 pt-7 sm:gap-3.5 sm:pt-9 lg:hidden"
    >
      <span className="over-art text-[11px] text-ink-3">Words you have heard — tap to use</span>
      <div className="pointer-events-auto flex flex-wrap items-stretch justify-center gap-2 sm:gap-2.5">
        {words.map((w) => (
          <button
            key={w.text}
            type="button"
            data-testid="heard-word"
            data-word={w.text}
            disabled={busy}
            onClick={() => sayWord(w.text)}
            className="over-art flex min-w-[76px] flex-col items-center gap-1 rounded-[10px] border border-hair-2 bg-[#0e0f0f]/75 px-3.5 py-2 leading-none backdrop-blur-sm transition-colors hover:border-ink-3 disabled:opacity-40"
          >
            {showRoman && w.roman && <span className="font-ui text-[11px] text-ink-3">{w.roman}</span>}
            <span lang={language.locale} className="target text-[17px] text-ink">
              {w.text}
            </span>
            <span data-role="word-gloss" className="font-ui text-[11px] leading-tight text-ink-2">
              {w.gloss}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
