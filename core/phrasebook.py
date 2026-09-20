"""The player's phrasebook: "How do I say…?" for THEIR OWN words, never the character's.

One fast structured model call. The player types what they want to say in the support language
and gets the simplest natural way to say it, segmented, romanized and glossed word by word (it
is their own sentence, so glossing it is fine). Lexicon words in the phrase count as assisted
for the current exchange; that stamp is code's, not the model's.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from core import gemini
from core.content import SUPPORT_LANGUAGE, Content, Language, Scene, is_latin
from core.state import Journey, Phrase, PhraseSegment, phrase_audio_url
from core.tools import is_clean_word, is_word, spoken

log = logging.getLogger("polytale.phrasebook")

MAX_SOURCE_CHARS = 200
MAX_WORDS = 12
MAX_KEPT = 40
DEFAULT_MODELS = "gemini-3.5-flash,gemini-3.5-flash-lite"  # measured: ~0.9 s, most natural

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "refused": {"type": "boolean"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"t": {"type": "string"}, "r": {"type": "string"},
                               "g": {"type": "string"}},
                "required": ["t", "r", "g"],
            },
        },
    },
    "required": ["refused", "segments"],
}


class PhraseRefused(ValueError):
    """The text is not something the phrasebook answers. ``code``: empty | target_language |
    not_a_phrase."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PhraseError(RuntimeError):
    """The lookup failed on every model; nothing was stored."""


def phrase_models() -> list[str]:
    raw = os.environ.get("GEMINI_PHRASE_MODELS", DEFAULT_MODELS)
    return [m.strip() for m in raw.split(",") if m.strip()]


def build_prompt(language: Language, scene: Scene | None, content: Content) -> str:
    roman = language.romanization
    r_rule = (f"r = its {roman.system} with the proper marks" if roman is not None
              else 'r = ""')
    words = scene.item_ids if scene is not None else list(language.items)
    lexicon = "; ".join(
        f"{language.items[i].text} ({language.items[i].roman}) = {language.items[i].gloss}"
        for i in words if i in language.items
    )
    where = f'They are in "{scene.name}": {scene.setting}' if scene is not None else ""
    return f"""You are the pocket phrasebook of a traveller who speaks {SUPPORT_LANGUAGE} and \
almost no {language.name}. {where}
They type what THEY want to say, in {SUPPORT_LANGUAGE}. Answer with the simplest natural way to \
say it in {language.name}: what a local would actually say out loud in that spot, as SHORT as \
possible (usually 1-6 words, never more than {MAX_WORDS}), easy for a beginner to pronounce. \
Drop politeness padding and anything a local would leave out. Prefer these words wherever they \
fit, written exactly like this: {lexicon}.
segments = the phrase split into dictionary words and punctuation marks, in order: t = the word \
in {language.name} script, {r_rule} ("" for punctuation), g = a 1-3 word {SUPPORT_LANGUAGE} \
gloss of THAT word ("" for punctuation).
Set refused=true with no segments when the text is not something of their own to say: it is \
already in {language.name} (in any script or romanization), it asks what someone else said or \
what a word means, it asks you to translate the other person, or it is empty, a question \
about this game, or gibberish."""


def _validated(language: Language, raw: Any) -> list[PhraseSegment] | None:
    """Model output -> clean segments, or None when it does not hold up."""
    if not isinstance(raw, list) or not raw:
        return None
    lexicon = {item.text: item.roman for item in language.items.values()}
    out: list[PhraseSegment] = []
    for seg in raw:
        text = str(seg.get("t") or "").strip() if isinstance(seg, dict) else ""
        if not text:
            return None
        word = is_word(text)
        if word and not is_clean_word(text):
            return None
        if not language.latin_script and any(is_latin(ch) for ch in text):
            return None
        roman = lexicon.get(text, str(seg.get("r") or "").strip())
        if language.romanization is None or not word:
            roman = ""
        elif not roman:
            return None
        out.append(PhraseSegment(t=text, r=roman, g=str(seg.get("g") or "").strip() if word else ""))
    words = sum(1 for s in out if is_word(s.t))
    return out if 0 < words <= MAX_WORDS else None


def translate(
    journey: Journey, content: Content, text: str, *, client: Any = None,
    models: list[str] | None = None,
) -> Phrase:
    """The model half of a lookup: reads the journey, changes nothing.

    Raises PhraseRefused (the text is not the player's own support-language phrase) or
    PhraseError (every model failed).
    """
    source = " ".join(text.split())[:MAX_SOURCE_CHARS]
    language = content.language(journey.language)
    if not source:
        raise PhraseRefused("empty", "type what you want to say")
    if not language.latin_script and any(ch.isalpha() and not is_latin(ch) for ch in source):
        raise PhraseRefused("target_language",
                            f"type it in {SUPPORT_LANGUAGE}: this looks up YOUR words")
    run = journey.scene
    scene = content.scene(run.scene_id) if run is not None else None

    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=build_prompt(language, scene, content),
        response_mime_type="application/json", response_json_schema=SCHEMA,
        temperature=0.2, thinking_config=gemini.thinking_config(types, "minimal"),
    )
    client = client if client is not None else gemini.get_client()
    segments: list[PhraseSegment] | None = None
    for model in models or phrase_models():
        try:
            response = client.models.generate_content(model=model, contents=source, config=config)
            data = json.loads(response.text or "")
        except Exception as exc:  # provider or JSON failure: try the next model
            log.warning("phrasebook: model %s failed: %s", model, exc)
            continue
        if isinstance(data, dict) and data.get("refused"):
            raise PhraseRefused("not_a_phrase", "the phrasebook only looks up things YOU want "
                                                "to say")
        segments = _validated(language, data.get("segments") if isinstance(data, dict) else None)
        if segments is not None:
            break
        log.warning("phrasebook: model %s returned an unusable phrase", model)
    if segments is None:
        raise PhraseError("the phrasebook could not answer; try again")

    known = scene.item_ids if scene is not None else list(language.items)
    item_ids = [i for i in known if i in language.items and all(
        spoken(segments, part, language.word_spacing) for part in language.items[i].parts)]
    phrase_id = f"p-{uuid.uuid4().hex[:10]}"
    phrase = Phrase(
        phrase_id=phrase_id, source=source, segments=segments,
        text=(" " if language.word_spacing else "").join(s.t for s in segments),
        romanization=" ".join(s.r for s in segments if s.r),
        audio_url=phrase_audio_url(journey.journey_id, phrase_id), item_ids=item_ids,
    )
    return phrase


def remember(journey: Journey, phrase: Phrase) -> None:
    """The ledger half (in place): keep the phrase, and mark its lexicon words as assisted for
    the exchange in play so a result recorded next stamps ``with_help``."""
    journey.game.phrasebook = [*journey.game.phrasebook, phrase][-MAX_KEPT:]
    run = journey.scene
    if run is not None and run.started and not run.complete:
        run.exchange.phrasebook_item_ids = list(
            dict.fromkeys(run.exchange.phrasebook_item_ids + phrase.item_ids))


def lookup(
    journey: Journey, content: Content, text: str, *, client: Any = None,
    models: list[str] | None = None,
) -> tuple[Journey, Phrase]:
    """Look up how to say ``text``. Returns ``(new_journey, Phrase)``; the input is untouched.
    Costs no turn. Raises like ``translate``."""
    phrase = translate(journey, content, text, client=client, models=models)
    working = journey.model_copy(deep=True)
    remember(working, phrase)
    return working, phrase


def find_phrase(journey: Journey, phrase_id: str) -> Phrase | None:
    return next((p for p in journey.game.phrasebook if p.phrase_id == phrase_id), None)
