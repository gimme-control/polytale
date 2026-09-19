"""DM system prompt and per-turn scene snapshot (behavior alignment lives here)."""

from __future__ import annotations

from typing import Any

from core import ledger
from core.cartridge import Cartridge, LanguageLearning, LearningBeat
from core.state import (
    EvidenceEntry,
    GameState,
    NarrationEntry,
    NpcEntry,
    PlayerEntry,
)

TRANSCRIPT_WINDOW = 12
LOW_CONFIDENCE = 0.6

LANGUAGE_NAMES = {
    "ja": "Japanese", "zh": "Mandarin Chinese", "ko": "Korean", "es": "Spanish",
    "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese", "en": "English",
}

# What the learner sees at each help level, and what that lets the NPC do.
HELP_LEVEL_MEANING = {
    0: "context only. The learner sees no help text; meaning must come from gestures and "
       "the world. Speak the target word with show_object.",
    1: "the learner can replay the beat's focus line slowly. You may repeat the key word "
       "slowly and on its own.",
    2: "the learner sees the word with its romanization.",
    3: "the learner sees the phrase frame (with a blank) and the word separately. You may "
       "say the frame and the word.",
    4: "the learner also sees a partial meaning hint.",
    5: "full rescue: the learner sees the full answer and translation, and may tap the "
       "object instead of speaking (tap fallback).",
}


def _language_name(locale: str) -> str:
    return LANGUAGE_NAMES.get(locale.split("-")[0], locale)


def _fill(template: str, value: str) -> str:
    return template.replace("{object}", value)


def build_system_prompt(cartridge: Cartridge) -> str:
    ll = cartridge.language_learning
    npc_names = ", ".join(f"{n.name} ({n.id})" for n in cartridge.npcs)
    base = f"""You are the game master (DM) of "{cartridge.identity.name}", a short voice-first \
adventure. You voice the NPCs ({npc_names}) and a brief narrator. You never step outside the \
fiction and you never act as a tutor.

HOW A TURN WORKS
- Each turn you receive a SCENE snapshot (committed world + ledger state) and the PLAYER \
ATTEMPT. Decide what the NPC understood and how the world reacts.
- The world and ledgers change ONLY through tool calls. Code validates every call and owns \
the state; your prose changes nothing.
- Emit ALL tool calls in ONE response, in this order: world tools (show_object, give, \
set_fixture), then ledger tools, then deliver_narration LAST. Do not wait for receipts; \
receipts only matter if one says ERROR.
- If any receipt says ERROR, the narration was rejected: fix or drop the failing call and \
send the remaining corrected calls plus deliver_narration again. Calls that returned OK are \
already committed; do not repeat them.
- Your narration and lines must describe exactly what your tool calls committed. Never \
describe an object changing hands or scenery changing without the matching tool call.
"""
    if ll is None:
        return base + """
STYLE
- Narration: at most 2 short sentences. NPC lines: short and in character.
"""
    target = _language_name(ll.target_locale)
    support = _language_name(ll.support_locale)
    concept_list = ", ".join(f"{c.native} ({c.romanization})" for c in ll.concepts)
    pattern = ll.patterns[0] if ll.patterns else None
    pattern_example = ""
    if pattern is not None:
        pattern_example = (
            f" The request pattern is {_fill(pattern.native_template, '___')} "
            f"({_fill(pattern.romanization_template, '___')})."
        )
    return base + f"""
THIS IS A LANGUAGE-LEARNING GAME
The player is an absolute beginner learning spoken {target}. They learn by communicating with \
the NPC to get practical things done. Success is the NPC understanding them and the world \
changing, never a grade.

LANGUAGE RULES (follow all of them every turn)
1. NPC speech is ALWAYS in {target} ({ll.target_locale}), even when the player speaks \
{support}. Never switch the scene to {support}. The NPC's English is only what her persona \
allows, and only to rescue total confusion.
2. NPC lines are SHORT: one to six words each, one or two lines per turn. Build them from the \
authored words ({concept_list}) plus tiny natural glue (ね, よ, です, ですね, いいえ).{pattern_example} \
Never introduce new essential vocabulary.
3. Every {ll.target_locale} line needs: romanization ({ll.romanization_system}, sentence-case, \
particle を as "o", e.g. "Hai, kagi o kudasai, desu ne. Douzo."), a natural {support} \
translation, concept_ids listing EVERY authored concept whose word appears in the line \
(はい -> word.hai, どうぞ -> word.douzo, 鍵 -> object.key, ...), and pattern_id ONLY when the \
line itself contains the request pattern (...をください).
4. Ground words in the world: whenever an NPC line names an object, call show_object for it \
in the same response (hold_up if she holds it, point otherwise). Meaning comes from what the \
player can see, not from explanations.
5. Meaning before form. Fragments ("kagi?"), code-switching ("kagi please", "key... \
kudasai"), and rough pronunciation are legitimate attempts. If the intent is clear, the NPC \
responds to the MEANING and the world reacts.
6. Recast, never correct. When an understood attempt is incomplete or mixed, the NPC \
naturally says the correct phrase back as a friendly confirmation and then acts, e.g. player \
"key... kudasai" -> "はい、鍵をください、ですね。どうぞ。" plus give. Never say "wrong", never \
explain grammar, never lecture, never ask the player to repeat a correct phrase.
7. A request made ONLY in {support} (no {target} word and no {target} request pattern, \
e.g. "can I have the key?") is understood in spirit but does NOT move the story and is NOT \
evidence: the NPC stays in {target}, points at the object or holds it just out of reach, and \
invites the {target} request (outside a transfer beat she may say the full request once as \
the thing to say; in a transfer beat only the word). Do not hand the object over, and do not \
call record_language_evidence for it.
8. Narration is {support} orientation only: at most 2 short sentences about what the player \
sees or does (gestures, objects moving, scenery). NEVER translate or explain the NPC's \
{target} in narration and never name the {target} words in it; the help ladder owns \
meaning. The narration never judges the player.
9. Follow the current help level (see the snapshot). Help rises only when the player asks \
for help or is clearly lost after repeated tries; never skip levels.
10. Speech recognition is imperfect. If the attempt has low recognition confidence, is \
empty, or is garbled, the recognizer probably misheard: the NPC gently asks again \
(もう一度？ mou ichido?) with a warm gesture. Never treat it as a mistake, never add any \
negative consequence, and record no evidence for it.
11. Record evidence honestly with record_language_evidence, at most once per attempt, for \
the ACTIVE beat, and only for what THIS attempt actually showed. An attempt counts only if it \
contains some {target} (the object word or the request pattern, in any spelling or \
romanization); {support} words may be mixed in (set mixed_language).
   - concept_ids = the object the player actually asked about or for. Never credit an object \
the player did not ask for: if they ask for something else (for example an object they \
already hold), the NPC responds to THAT request and you record nothing for the beat.
   - recognized: the player connected a word to its object (repeated or asked about the \
word, answered with its meaning, or tapped the object after hearing it).
   - produced: the player asked for the beat's object using {target} ("kagi o kudasai", \
"kagi... kudasai", "kagi please", "key... kudasai" all count when the intent is clear).
   - transferred: in a transfer beat, the player asked for the NEW object using {target} \
(its word and/or the request pattern).
   - outcome not_understood only when you heard the player clearly but truly cannot tell \
what they want. Otherwise understood (or clarified if it took a clarification exchange).
   - A tap (input_mode tap) means the player pointed at that object. At help level 5 a tap \
on the beat's object is the tap fallback: record produced (or transferred), have the NPC say \
the full request herself, and complete the world result.
12. Beats: never call advance_beat until the beat's world result is committed AND its \
evidence is recorded (same response is fine: world tools, record_language_evidence, then \
advance_beat). If the snapshot says the beat is already satisfied, advance it.
13. Starting a beat (right after you advance into it, in the same response):
   - production beat: the NPC keeps the object just out of reach (show_object withhold) and \
demonstrates the full request once, as the thing to say.
   - transfer beat: the NPC grounds the new word: show_object(<new object>, hold_up) and \
says just the word (e.g. 地図。). NEVER say the completed request sentence for the new \
object in a transfer beat before the player has attempted it; the player must build it.
14. Keep momentum and warmth: one short reaction, one visible action, then hand the turn \
back to the player.
"""


def _holder_label(cartridge: Cartridge, holder: str) -> str:
    npc = cartridge.npc(holder)
    return f"{npc.name} ({holder})" if npc else holder


def _world_block(state: GameState, cartridge: Cartridge, ll: LanguageLearning | None) -> list[str]:
    lines = ["WORLD (committed)"]
    focus = state.world.focus
    for obj in cartridge.objects:
        concept = ll.concept(obj.concept_id) if ll and obj.concept_id else None
        word = f" [{concept.native} {concept.romanization}]" if concept else ""
        held = _holder_label(cartridge, state.world.holders.get(obj.id, "?"))
        focus_note = (
            f", NPC gesture: {focus.gesture}" if focus and focus.object_id == obj.id else ""
        )
        lines.append(f"- {obj.id}{word}: held by {held}{focus_note}")
    for fx in cartridge.fixtures:
        lines.append(
            f"- {fx.id} ({fx.name}): {state.world.fixtures.get(fx.id)} "
            f"(states: {', '.join(fx.states)})"
        )
    return lines


def _beat_block(state: GameState, cartridge: Cartridge, ll: LanguageLearning) -> list[str]:
    ls = state.learning
    assert ls is not None
    total = len(ll.learning_beats)
    beat = ledger.active_beat(state, cartridge)
    if beat is None:
        return [
            "ACTIVE LEARNING BEAT: none, the episode is complete. React warmly in "
            f"{_language_name(ll.target_locale)}; do not call ledger tools."
        ]
    level = ls.help_level.get(beat.id, 0)
    entry = beat.help_entry(level)
    lines = [f"ACTIVE LEARNING BEAT {ls.active_beat_index + 1}/{total}: {beat.id}"]
    lines.append(f"- player's objective: {beat.objective}")
    lines.append(f"- success evidence: {beat.success_evidence}")
    lines += _beat_target_lines(ll, beat)
    lines.append(f"- world result when achieved: {beat.world_result}")
    gaps = ledger.completion_gaps(state, cartridge, beat)
    lines.append(
        "- still missing before advance_beat: " + ("; ".join(gaps) if gaps else "nothing "
        "(the beat is satisfied: call advance_beat)")
    )
    label = f" '{entry.label}'" if entry else ""
    lines.append(f"- help level {level}{label}: {HELP_LEVEL_MEANING.get(level, '')}")
    if beat.success_evidence == "transfer":
        lines.append(
            "- TRANSFER BEAT: never say the completed request for the new object before the "
            "player attempts it."
        )
    lines.append(
        f"- full request already modeled by the NPC in this beat: "
        f"{'yes' if ls.phrase_modeled.get(beat.id) else 'no'}"
    )
    lines.append(f"- misunderstood attempts since last help change: {ls.failures.get(beat.id, 0)}")
    upcoming = ll.learning_beats[ls.active_beat_index + 1:]
    if upcoming:
        nxt = upcoming[0]
        lines.append(
            f"NEXT BEAT (after advance_beat): {nxt.id}: {nxt.objective} "
            f"(success: {nxt.success_evidence})"
        )
        lines += ["  " + x for x in _beat_target_lines(ll, nxt)]
    else:
        lines.append("NEXT BEAT: none; advancing this beat completes the episode.")
    return lines


def _beat_target_lines(ll: LanguageLearning, beat: LearningBeat) -> list[str]:
    lines = []
    concepts = [ll.concept(c) for c in beat.concept_ids]
    words = ", ".join(f"{c.id} {c.native} ({c.romanization})" for c in concepts if c)
    if words:
        lines.append(f"- beat words: {words}")
    pattern = ll.pattern(beat.pattern) if beat.pattern else None
    slot = ll.concept(beat.slot_concept() or "")
    if pattern is not None and slot is not None:
        referents = ", ".join(slot.referents) or "-"
        lines.append(
            f"- target request: {_fill(pattern.native_template, slot.native)} / "
            f"{_fill(pattern.romanization_template, slot.romanization)} (pattern {pattern.id}, "
            f"slot {slot.id}, object {referents})"
        )
    return lines


def _stages_block(state: GameState, ll: LanguageLearning) -> list[str]:
    ls = state.learning
    assert ls is not None
    lines = ["SYLLABUS (the only target words the NPC teaches) with ledger stages"]
    for c in ll.concepts:
        refs = f", object {', '.join(c.referents)}" if c.referents else ""
        lines.append(
            f"- {c.id}: {c.native} ({c.romanization}) = {c.gloss}{refs}; stage "
            f"{ls.concept_stage.get(c.id, 'unseen')}; heard {ls.exposures.get(c.id, 0)}x"
        )
    for p in ll.patterns:
        lines.append(
            f"- {p.id}: {p.native_template} / {p.romanization_template} = {p.gloss_template}; "
            f"stage {ls.pattern_stage.get(p.id, 'unseen')}"
        )
    return lines


def _transcript_block(state: GameState, cartridge: Cartridge) -> list[str]:
    lines = [f"RECENT TRANSCRIPT (last {TRANSCRIPT_WINDOW} entries)"]
    window = state.transcript[-TRANSCRIPT_WINDOW:]
    if not window:
        lines.append("- (nothing yet)")
    for entry in window:
        if isinstance(entry, NarrationEntry):
            lines.append(f"- t{entry.turn} narration: {entry.text}")
        elif isinstance(entry, NpcEntry):
            ln = entry.line
            lines.append(
                f"- t{entry.turn} {ln.speaker_name}: {ln.text} ({ln.romanization} = "
                f"{ln.translation}) pattern={ln.pattern_id or '-'}"
            )
        elif isinstance(entry, PlayerEntry):
            tapped = f" tapped {entry.tapped_object_id}" if entry.tapped_object_id else ""
            lines.append(f"- t{entry.turn} PLAYER ({entry.input_mode}){tapped}: {entry.transcript!r}")
        elif isinstance(entry, EvidenceEntry):
            lines.append(
                f"- t{entry.turn} ledger: {entry.evidence_type}/{entry.outcome} "
                f"{', '.join(entry.concept_ids)} -> {entry.stage_after}"
            )
    return lines


def _attempt_block(attempt: dict[str, Any] | None, turn: int) -> list[str]:
    if attempt is None:
        return ["PLAYER ATTEMPT: none"]
    mode = attempt.get("input_mode", "text")
    lines = [f"PLAYER ATTEMPT (turn {turn})", f"- input_mode: {mode}"]
    if mode == "tap":
        lines.append(f"- tapped object: {attempt.get('tapped_object_id')}")
    else:
        lines.append(f"- transcript: {attempt.get('transcript', '')!r}")
        if attempt.get("romanized"):
            lines.append(f"- romanized: {attempt['romanized']!r}")
        detected = attempt.get("detected_languages") or []
        lines.append(f"- detected languages: {', '.join(detected) or 'unknown'}")
        confidence = attempt.get("confidence")
        if confidence is None:
            lines.append("- recognition confidence: n/a (typed or not reported)")
        else:
            note = (
                " (LOW: the recognizer may have misheard. Ask again gently, never judge, "
                "record nothing)"
                if float(confidence) < LOW_CONFIDENCE else ""
            )
            lines.append(f"- recognition confidence: {float(confidence):.2f}{note}")
    return lines


def build_snapshot(
    state: GameState, cartridge: Cartridge, attempt: dict[str, Any] | None
) -> str:
    """Fresh per-turn snapshot: premise, NPCs, world, beat, stages, transcript, attempt."""
    ll = cartridge.language_learning
    loc = cartridge.setting.location
    out = ["SCENE", f"Premise: {cartridge.setting.premise}", f"Location: {loc.name}. {loc.description}"]
    for npc in cartridge.npcs:
        english = f" English: {npc.english}" if npc.english else ""
        out.append(f"NPC {npc.id} {npc.name} ({npc.role}): {npc.persona}{english}")
    out.append("")
    out += _world_block(state, cartridge, ll)
    if ll is not None and state.learning is not None:
        out.append("")
        out += _stages_block(state, ll)
        out.append("")
        out += _beat_block(state, cartridge, ll)
    out.append("")
    out += _transcript_block(state, cartridge)
    out.append("")
    out += _attempt_block(attempt, state.turn)
    out.append("")
    out.append(
        "Respond now with ALL your tool calls in one response, ending with deliver_narration."
    )
    return "\n".join(out)
