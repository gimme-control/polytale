"""Best-effort romanization of a learner's own utterance, from the language's own lexicon.

The learner sees romanization over everything the character says (``Line.segments`` carry it)
and over every word in the dictionary and the summary. Their OWN line was the gap: speech
recognition returns a romanization, but typing does not, so a typed greeting echoed back as
bare characters with nothing to read.

This is a pure lookup against ``content/languages/<locale>.json`` — no model call, no network,
no guessing. It romanizes what the lexicon knows and leaves everything else exactly as typed,
so it can only ever add information. Languages written in Latin script (``romanization: None``)
get nothing, which is correct: there is nothing to romanize.
"""

from __future__ import annotations

from core.content import Language

__all__ = ["romanize_utterance"]


def _surface_forms(language: Language) -> list[tuple[str, str]]:
    """``(surface, roman)`` for every spoken part of every item, longest surface first.

    An item's ``text`` may be a frame with a placeholder around a slot, so each spoken part is
    indexed separately. Matching the longest surface first keeps a compound word from being
    split into its own characters.
    """
    forms: dict[str, str] = {}
    for item in language.items.values():
        parts, romans = item.parts, item.roman.split()
        if not item.roman:
            continue
        # A single-part item keeps its whole romanization; a frame lines parts up with the
        # romanized words it has, and anything that does not line up is skipped rather than
        # guessed at.
        if len(parts) == 1:
            forms.setdefault(parts[0], item.roman)
        elif len(parts) == len(romans):
            for part, roman in zip(parts, romans):
                forms.setdefault(part, roman)
    return sorted(forms.items(), key=lambda kv: len(kv[0]), reverse=True)


def romanize_utterance(text: str, language: Language) -> str | None:
    """Romanize what the lexicon recognises in ``text``; ``None`` when nothing was added.

    Returns ``None`` for a Latin-script language, for an empty utterance, and for text that
    is already romanization (typing "nihao" adds nothing), so a caller can simply keep the
    value it already had.
    """
    if language.romanization is None or not text.strip():
        return None
    forms = _surface_forms(language)
    if not forms:
        return None

    out: list[str] = []
    i, n, matched = 0, len(text), False
    while i < n:
        for surface, roman in forms:
            if surface and text.startswith(surface, i):
                # Space romanized words apart even when the script itself is unspaced.
                if out and not out[-1].endswith(" "):
                    out.append(" ")
                out.append(roman + " ")
                i += len(surface)
                matched = True
                break
        else:
            out.append(text[i])
            i += 1

    if not matched:
        return None
    result = "".join(out).strip()
    while "  " in result:
        result = result.replace("  ", " ")
    return result or None
