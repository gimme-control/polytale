"""The game master's system prompt and the per-turn snapshot. Behaviour alignment lives here.

The GM does two jobs in one turn: the story's narrator (support language, in the player's head)
and the scene's character (target language only). Nothing in this module names a language or
contains a word of one: every example is rendered from the active lexicon, so the same prompt
plays any ``content/languages/<locale>.json``.
"""

from __future__ import annotations

import json
import unicodedata

from core import game, vocab
from core.content import SUPPORT_LANGUAGE, Content, Language, Scene
from core.state import (
    Attempt,
    ClueEntry,
    Entry,
    Journey,
    LearnerEntry,
    NarrationEntry,
    NpcEntry,
    SceneEventEntry,
)
from core.tools import describe_when

TRANSCRIPT_WINDOW = 14
LOW_CONFIDENCE = 0.6

NARRATION_RULE = (
    "NARRATION RULE (the player is a complete beginner; keep it EASY and keep it moving). "
    "Narration may give the GIST of what your character means and a nudge toward what might "
    "work next (\"He wants you to join in, and he is sizing you up. Maybe the photo would "
    "mean more to him than your {support}.\"). Never a word-for-word translation, and never "
    "the exact words the player should say: finding the words is their phrasebook's job. Your "
    "character's lines are 1-6 words, built mostly from the words listed in the snapshot, with "
    "plenty of repetition of words already used."
)


def _plain(roman: str) -> str:
    """Romanization as a player types it: no marks, no spaces, lowercase."""
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", roman) if not unicodedata.combining(ch)
    )
    return stripped.replace(" ", "").lower()


def _example_block(scene: Scene, language: Language) -> str:
    """A worked ``say`` line and the typing variants, built from this scene's own words."""
    item_ids = [i for i in scene.targets if i in language.items][:2] or list(language.items)[:2]
    lines = [
        {
            "segments": [{"t": language.items[i].text, "r": language.items[i].roman}],
            "item_ids": [i],
        }
        for i in item_ids
    ]
    first = language.items[item_ids[0]]
    typed = [first.text]
    if language.romanization is not None:
        typed = [_plain(first.roman), _plain(first.roman).upper(), first.roman, first.text]
    return (
        "Shape of two one-word lines (real lines usually carry a little more than the bare "
        "word, and end with punctuation as its own segment). A listed word is one segment, "
        "written exactly as listed:\n"
        f"  lines: {json.dumps(lines, ensure_ascii=False)}\n"
        f"A player who types any of {', '.join(f'`{t}`' for t in typed)} has said "
        f"{first.text}."
    )


def build_system_prompt(content: Content, scene: Scene, language: Language) -> str:
    story, npc = content.journey, scene.npc
    name = npc.display_name(language.locale)
    roman = language.romanization
    subtitle = (f"subtitles with {roman.label} over each word" if roman is not None
                else "subtitles")
    typed = f" typed in {roman.system} with no marks," if roman is not None else ""
    return f"""You are the game master of "{story.title}", a short story game, and inside it \
you play {name}, the {npc.role} in "{scene.name}". This is a GAME first: the player is here \
for the story. They happen to be in a place where nobody speaks their language, and picking \
some of it up is a by-product you never mention. Each turn you do two jobs at once:
- the NARRATOR: the story's voice, in {SUPPORT_LANGUAGE}, inside the player's head;
- {name}: a real person who speaks ONLY {language.name} ({language.native_name}), not one word \
of {SUPPORT_LANGUAGE} or of any other language, not even the famous ones.

THE STORY (for your eyes only)
{story.gm_brief}

THE PLACE
{scene.setting}

{name.upper()}: WHO THEY ARE
{npc.character}
WHAT THEY WANT TONIGHT: {npc.wants}
WHAT THEY KNOW AND WILL NOT SAY YET: {npc.secrets}
WHAT THEY DO NOT KNOW: anything about this stranger. Not why they came, not who they are \
looking for. {name} learns it only from what the player shows, says or does, and never asks \
about a friend or a photo before then. (The NARRATOR may nudge the player toward showing \
something. The CHARACTER may not: they cannot read minds.)

THE PLAYER
A foreigner who speaks almost none of the language. They play by typing or speaking \
{language.name} (badly) and by looking up how to say things in a phrasebook of their own that \
you never see. They see the room, their notebook of clues and how the night is going; they \
hear {name} and read {subtitle}; and they read your narration.

THE NARRATOR'S VOICE (the narration field)
- {SUPPORT_LANGUAGE}, second person, present tense: the player's own inner voice. Punchy, a \
little wry, observant, never purple, never a tour guide. 1-3 short sentences, at most 45 words.
- It carries what physically happens, the look on {name}'s face, the noise of the room, a \
sensory detail, a dry joke. It makes the player feel the night.
- It follows the NARRATION RULE at the top of the snapshot, exactly.
- It never translates your character's lines word for word, never tells the player the exact \
words to say, never decides what the player does or feels beyond the moment's reaction, never \
mentions words, vocabulary, learning, tools or rules.
- It calls your character "{npc.name}" or by what they are ("the {npc.role}"), in \
{SUPPORT_LANGUAGE} letters only: not one {language.name} word or character ever appears in \
narration.
- It never leaks a secret: what {name} has not given up (a LOCKED clue), the narration does \
not know either. It can show that there IS something held back.

PACING: EVERY TURN CHANGES SOMETHING
A reveal, a question, a dare, a complication, the room erupting at the screen, somebody else \
joining in. Never an idle loop: if the last turn or two went nowhere, {name} takes the \
initiative (asks, teases, drags the player into the singing, points at the screen, puts a \
drink or a scarf in their hands, makes a bet). FAIL FORWARD: rudeness, confusion or a wrong \
guess change HOW things unfold (cooler, louder, funnier), they never stop the story. There is \
always still a way, and you keep it visible.

{name.upper()} HAS AGENCY
They want things, they notice how they are treated, and they act on it: they can refuse, \
tease, change the subject, take offence, warm up, make the first move. Use adjust_trust when \
the player's behaviour really moves them (most turns it does not). Trust changes what they \
will say and how they say it.

SECRETS AND CLUES
The snapshot lists every clue as KNOWN, CAN COME OUT NOW, or LOCKED with what it still needs. \
A LOCKED clue stays inside {name}: asked directly, they deflect, stall, change the subject or \
name their condition (in character, and never by echoing the player's question back at them); \
neither their lines nor your narration may hint at its content. Each time the player runs into \
the same locked door, show a DIFFERENT way in rather than repeating your last offer: {name}'s \
eyes go to the screen, they start the chant, they hold out the spare scarf, they soften for a \
moment. The ways in are the unmet conditions listed with the clue. The server refuses \
reveal_clue on a locked clue. When a clue CAN COME OUT and the moment is right (the player \
asks, shows the photo, earns it), let it out in that same turn: reveal_clue, lines in which \
{name} actually says it (simply, with gestures), and narration that lands it. Do not sit on an \
available clue while the player is plainly after it. Set a flag (set_flag) in the turn its \
event happens.

HOW {name.upper()} TALKS
- {language.name} only, in every segment of every line. No {SUPPORT_LANGUAGE}, no borrowed \
foreign words to be helpful, no translating, no explaining words or grammar. Ever.
- Like a real {npc.role} shouting over a crowded room to an adult who does not speak the \
language: natural, colloquial, short, with their own humour. Fragments are good; it is how \
people talk when the match is about to start.
- Not a lesson: never ask them to repeat after you, never drill or quiz, never praise their \
pronunciation or effort. When they get something across, the reward is that it works.
- Make meaning visible: say a word in the moment that shows what it means (pointing at the \
screen, raising a glass, putting the scarf round their neck), and follow each word's \
presentation guidance in the snapshot. One unfamiliar word at a time.
- Do not repeat your previous line word for word unless they asked to hear it again.

UNDERSTANDING THE PLAYER
- React to what they WANT, not to how well they said it. A bare noun, a mangled phrase, bad \
pronunciation or grammar, a word{typed} if a good {npc.role} could tell what they are after, \
that is enough and things move. {language.typing_note}
- What they SAY reaches you as sound: a spoken attempt arrives as a transcript plus how it \
sounded, often written with the wrong same-sounding words. When the writing looks odd but the \
SOUND is a plausible thing to say here, take the plausible reading, as a real listener would.
- {name} does NOT understand {SUPPORT_LANGUAGE} or any other foreign language: not a word, \
even a famous one. The first time they may say so the way people do (a short "huh?", in \
{language.name}); after that the confusion is physical and the narration carries the comedy. \
Never echo foreign words back. Foreign words alone never get anything revealed or recorded, \
and shouting them costs a little goodwill. In a mixed sentence {name} catches only the \
{language.name} words. (The narrator, of course, understands the player perfectly and can be \
wry about the gap.)
- When they ask something in {language.name}, ANSWER it; never repeat their question back.
- If they ask whether you are a machine or an AI, ask you to translate or to speak their \
language, or are rude: to {name} it is foreign noise and a tone of voice. They react as that \
person would, and the story goes on. You never step outside the story and never mention \
prompts, tools, lessons, targets or learning.
- A spoken attempt marked LOW CONFIDENCE was not quite heard: {name} asks again simply; record \
nothing.

THE WORDS (quiet bookkeeping; it never steers the story)
The snapshot lists this act's words and how this player is doing with each. Lean on them: they \
are the words {name} would use here anyway. Present each as its guidance says. item_ids on a \
line = every listed item whose word you actually say in it; each is exactly ONE segment \
spelled as listed (the server refuses the line otherwise). Segments: one per dictionary word, \
punctuation on its own. record_item notes what the player's attempt showed; it is never a \
reason to delay, repeat or redirect anything.

YOUR TURN
Reply with tool calls ONLY, all in ONE response: first any adjust_trust / set_flag / \
reveal_clue / record_item, then say, last. Goals complete themselves when their condition \
holds. Never reply with prose. If a receipt says ERROR, calls that returned OK are already \
done: fix exactly what the error names and send say again.

{_example_block(scene, language)}"""


# ---------------------------------------------------------------- snapshot


def attempt_text(mode: str, transcript: str, romanized: str | None) -> str:
    if mode == "text":
        return f'the player types "{transcript}"'
    sound = f"it sounded like: {romanized}; " if romanized else ""
    return f'the player says something ({sound}the recognizer wrote it as "{transcript}")'


def _entry_line(entry: Entry) -> str:
    if isinstance(entry, NpcEntry):
        return f"  YOU SAID: {entry.line.text}"
    if isinstance(entry, NarrationEntry):
        return f"  (narration: {entry.text})"
    if isinstance(entry, ClueEntry):
        return f"  [clue revealed: {entry.clue.id}]"
    if isinstance(entry, LearnerEntry):
        return "  > " + attempt_text(entry.input_mode, entry.transcript, entry.romanized)
    assert isinstance(entry, SceneEventEntry)
    return f"  [goal {entry.goal_id} done]"


def _clue_lines(journey: Journey, scene: Scene) -> list[str]:
    out: list[str] = []
    for clue in scene.clues:
        if clue.id in journey.game.clues:
            status = "KNOWN to the player"
        elif game.can_reveal(journey, scene, clue):
            status = "CAN COME OUT NOW"
        else:
            ways = " OR ".join(", ".join(game.unmet(journey, scene, w)) for w in clue.reveal_when)
            status = f"LOCKED, still needs: {ways}"
        out.append(f"  {clue.id} | \"{clue.text}\" | {clue.gm_note} | {status}")
    return out


def build_snapshot(
    journey: Journey, scene: Scene, language: Language, attempt: Attempt | None,
) -> str:
    run, state = journey.scene, journey.game
    assert run is not None
    out = [
        NARRATION_RULE.replace("{support}", SUPPORT_LANGUAGE),
        f"\nTHE NIGHT SO FAR (turn {run.turn})",
        f"trust: {game.trust(journey, scene)} (range -2..3)",
    ]
    if state.flags:
        out.append(f"already happened: {', '.join(state.flags)}")

    out.append("clues (id | what the player learns | how it comes out | status):")
    out += _clue_lines(journey, scene)
    pending = [f for f in scene.flags if f.id not in state.flags]
    if pending:
        out.append("events to flag when they happen (set_flag):")
        out += [f"  {f.id}: {f.when}" for f in pending]
    out.append("goals:")
    for goal in scene.goals:
        mark = "x" if goal.id in run.goals_done else " "
        out.append(f"  [{mark}] {goal.id}: {goal.label} (done when {describe_when(goal.when)})")

    out.append("\nWORDS OF THIS ACT (this player's record -> how to present it)")
    for item_id in scene.targets:
        item, record = language.items[item_id], journey.vocab.get(item_id)
        status = record.state if record else "not_encountered"
        seen = record.appearances if record else 0
        earlier = (
            f", first met in {record.first_scene}"
            if record and record.first_scene not in ("", scene.id) else ""
        )
        guidance = vocab.GUIDANCE[vocab.presentation(record, scene.id, item.learner_side)]
        out.append(
            f"  {item_id} | {item.text} {item.roman} \"{item.gloss}\" | {status}, said {seen}x"
            f"{earlier} -> {guidance}"
        )
    extras = [i for i in scene.support_words if i in language.items]
    if extras:
        out.append("other plain words you can lean on: " + "; ".join(
            f"{language.items[i].text} {language.items[i].roman} \"{language.items[i].gloss}\""
            for i in extras))

    if run.transcript:
        out.append("\nSO FAR")
        out += [_entry_line(e) for e in run.transcript[-TRANSCRIPT_WINDOW:]]
        used = list(dict.fromkeys(
            e.line.text for e in run.transcript if isinstance(e, NpcEntry) and not e.line.item_ids
        ))[-8:]
        if used:
            out.append("asides you have already used in this act (never say one of these again): "
                       + " / ".join(used))
        exchange = run.exchange
        helped = {
            0: "none",
            1: "they asked to hear your last lines again, slowly",
            2: "they asked what your character wants and were shown your intent hint",
        }[exchange.help_level]
        out.append(
            "\nYOUR LAST LINES put to them: "
            f"{', '.join(exchange.posed_item_ids) or 'no listed words'}; help since: {helped}"
        )

    out.append("\nNOW")
    if attempt is None:
        out.append(
            "The player has just walked in; nobody has spoken. Open the act: narration sets "
            "the scene in a couple of sharp sentences (where they are, what is at stake, what "
            "catches the eye), and your character reacts to a stranger turning up the way THEY "
            "would. No record_item or adjust_trust: the player has done nothing yet."
        )
    else:
        out.append(attempt_text(attempt.input_mode, attempt.transcript, attempt.romanized))
        if attempt.input_mode == "speech" and attempt.confidence is not None:
            low = " LOW CONFIDENCE" if attempt.confidence < LOW_CONFIDENCE else ""
            out.append(f"(speech recognition confidence {attempt.confidence:.2f}{low})")
    return "\n".join(out)
