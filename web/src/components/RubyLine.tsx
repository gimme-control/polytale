// One line of target-language text. Each word segment is a real <ruby> with its
// romanization above it; punctuation carries none. Languages without romanization
// (romanization_label: null) render the words alone, and word_spacing decides
// whether words are separated by a space or only by the ruby gap.

import type { Language, Segment } from "../lib/types";

const PUNCT = /^[\p{P}\p{S}\s]+$/u;

export function RubyLine({
  segments,
  language,
  dim = false,
  className = "",
}: {
  segments: Segment[];
  language: Language;
  dim?: boolean;
  className?: string;
}) {
  const showRoman = language.romanization_label != null;
  return (
    <span lang={language.locale} data-role="target" className={`target ruby-line ${dim ? "is-dim" : ""} ${className}`}>
      {segments.map((s, i) => {
        const word = !PUNCT.test(s.t);
        const space = language.word_spacing && word && i > 0 ? " " : "";
        if (!showRoman) {
          return (
            <span key={i} data-seg={word ? "word" : "punct"} className={word && !language.word_spacing ? "mx-[0.14em]" : ""}>
              {space}
              {s.t}
            </span>
          );
        }
        if (!word || !s.r) {
          // Same column shape as a word (with an empty romanization row) so every
          // segment shares one baseline.
          return (
            <span key={i}>
              {space}
              <span data-seg={word ? "word" : "punct"} className={`ruby-col ${word ? "" : "is-punct"}`}>
                {s.t}
                <span aria-hidden className="ruby-pad">
                  &nbsp;
                </span>
              </span>
            </span>
          );
        }
        return (
          <span key={i}>
            {space}
            <ruby data-seg="word">
              {s.t}
              <rt data-role="romanization">{s.r}</rt>
            </ruby>
          </span>
        );
      })}
    </span>
  );
}
