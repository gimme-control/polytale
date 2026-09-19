"""Deterministic learning ledger: pure functions over GameState.

Every function tolerates a cartridge without ``language_learning`` (plain story mode)
by returning empty/None results or raising `LedgerError` where a ledger write is asked for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.cartridge import Cartridge, LanguageLearning, LearningBeat
from core.state import (
    STAGES,
    Attempt,
    EvidenceRecord,
    EvidenceType,
    GameState,
    LastConstruction,
    LearningState,
    Outcome,
    SpokenLine,
    Stage,
)

MAX_HELP_LEVEL = 5
FAILURES_TO_ESCALATE = 2
CUE_HELP_LEVEL = 3  # help at or above this level means the learner saw a phrase frame
_RANK = {stage: i for i, stage in enumerate(STAGES)}


class LedgerError(ValueError):
    """Invalid ledger request; the message is returned to the model as an ERROR receipt."""


def stage_at_least(stage: Stage | None, floor: Stage) -> bool:
    return stage is not None and _RANK[stage] >= _RANK[floor]


def raise_stage(current: Stage, new: Stage) -> Stage:
    """Stages only move up."""
    return new if _RANK[new] > _RANK[current] else current


# ---------------------------------------------------------------- beats


def _ledger(state: GameState, cartridge: Cartridge) -> tuple[LearningState, LanguageLearning]:
    if state.learning is None or cartridge.language_learning is None:
        raise LedgerError("this cartridge has no language-learning ledger")
    return state.learning, cartridge.language_learning


def active_beat(state: GameState, cartridge: Cartridge) -> LearningBeat | None:
    ll = cartridge.language_learning
    if state.learning is None or ll is None:
        return None
    index = state.learning.active_beat_index
    return ll.learning_beats[index] if 0 <= index < len(ll.learning_beats) else None


def enter_beat(state: GameState, cartridge: Cartridge, index: int) -> None:
    """Activate beat ``index``; reuse of a pattern starts at least one help level lower."""
    ls, ll = _ledger(state, cartridge)
    ls.active_beat_index = index
    if index >= len(ll.learning_beats):
        return
    beat = ll.learning_beats[index]
    prior = ls.last_successful_construction
    if prior is not None and beat.pattern is not None and prior.pattern_id == beat.pattern:
        level = min(beat.initial_help_level, max(0, prior.support_level - 1))
    else:
        level = beat.initial_help_level
    ls.help_level[beat.id] = level
    ls.help_max_used[beat.id] = max(ls.help_max_used.get(beat.id, 0), level)
    ls.failures[beat.id] = 0
    ls.phrase_modeled.setdefault(beat.id, False)


def _set_level(ls: LearningState, beat: LearningBeat, level: int) -> None:
    ls.help_level[beat.id] = level
    ls.help_max_used[beat.id] = max(ls.help_max_used.get(beat.id, 0), level)
    ls.failures[beat.id] = 0


def completion_gaps(state: GameState, cartridge: Cartridge, beat: LearningBeat) -> list[str]:
    """What is still missing before ``beat`` counts as complete (empty = complete)."""
    ls, _ = _ledger(state, cartridge)
    gaps: list[str] = []
    for oid, holder in beat.complete_when.holders.items():
        now = state.world.holders.get(oid)
        if now != holder:
            gaps.append(f"{oid} must be held by {holder} (now {now})")
    for fid, fx_state in beat.complete_when.fixtures.items():
        now = state.world.fixtures.get(fid)
        if now != fx_state:
            gaps.append(f"{fid} must be {fx_state} (now {now})")

    records = [r for r in ls.evidence if r.beat_id == beat.id]
    tap_rescue = any(r.tap_fallback and r.support_level >= MAX_HELP_LEVEL for r in records)
    slot = beat.slot_concept()
    slot_stage = ls.concept_stage.get(slot) if slot else None
    if beat.success_evidence == "recognition":
        if not any(stage_at_least(ls.concept_stage.get(c), "context_recognized")
                   for c in beat.concept_ids):
            gaps.append(
                "no recognition evidence yet: record_language_evidence(recognized) "
                "after the player shows they connected the word to the object"
            )
    elif beat.success_evidence == "production":
        if not (stage_at_least(slot_stage, "produced_with_cue") or tap_rescue):
            gaps.append(
                f"no production evidence yet: the player must ask for {slot} "
                "(record_language_evidence produced), or tap it at help level 5"
            )
    else:
        transfer_attempt = any(
            r.evidence_type == "transferred" and r.concept_id == slot and not r.tap_fallback
            and r.outcome != "not_understood"
            for r in records
        )
        if not ((transfer_attempt and stage_at_least(slot_stage, "produced_with_cue"))
                or tap_rescue):
            gaps.append(
                f"no transfer evidence yet: the player must reuse the pattern for {slot} "
                "(record_language_evidence transferred), or tap it at help level 5"
            )
    return gaps


def advance_beat(state: GameState, cartridge: Cartridge, beat_id: str) -> LearningBeat | None:
    """Complete the active beat and enter the next; returns the new active beat (None = done)."""
    ls, ll = _ledger(state, cartridge)
    beat = active_beat(state, cartridge)
    if beat is None:
        raise LedgerError("all learning beats are already complete")
    if beat_id != beat.id:
        raise LedgerError(f"learning_beat_id must be the active beat '{beat.id}', not '{beat_id}'")
    gaps = completion_gaps(state, cartridge, beat)
    if gaps:
        raise LedgerError(f"beat '{beat.id}' is not complete: " + "; ".join(gaps))
    next_index = ls.active_beat_index + 1
    enter_beat(state, cartridge, next_index)
    if next_index >= len(ll.learning_beats):
        state.episode_complete = True
        return None
    return ll.learning_beats[next_index]


# ---------------------------------------------------------------- help


def _concept_chip(ll: LanguageLearning, concept_id: str) -> dict[str, str]:
    concept = ll.concept(concept_id)
    if concept is None:
        return {"id": concept_id, "native": concept_id, "romanization": ""}
    return {"id": concept.id, "native": concept.native, "romanization": concept.romanization}


def help_line_id(beat_id: str, level: int) -> str:
    return f"help-{beat_id}-{level}"


def help_cue(
    state: GameState, cartridge: Cartridge, beat: LearningBeat, level: int
) -> dict[str, Any] | None:
    """The authored HelpCue payload for ``beat`` at ``level`` (None for level 0 / unauthored)."""
    ll = cartridge.language_learning
    entry = beat.help_entry(level) if ll is not None else None
    if entry is None or ll is None:
        return None
    cue: dict[str, Any] = {"level": entry.level, "label": entry.label, "kind": entry.kind}
    if entry.text:
        cue["text"] = entry.text
    for key in ("native", "romanization", "translation"):
        value = getattr(entry, key)
        if value:
            cue[key] = value
    if entry.line is not None:
        line_id = help_line_id(beat.id, entry.level)
        cue["line"] = SpokenLine.build(cartridge, state.session_id, line_id, entry.line).model_dump()
    concept_ids = list(entry.concept_ids)
    if entry.kind == "frame" and entry.pattern_id is not None:
        pattern = ll.pattern(entry.pattern_id)
        if pattern is not None:
            cue["frame"] = {
                "native": _blank_template(pattern.native_template),
                "romanization": _blank_template(pattern.romanization_template),
            }
        slot = beat.slot_concept()
        if slot and slot not in concept_ids:
            concept_ids.append(slot)
    if concept_ids:
        cue["concepts"] = [_concept_chip(ll, cid) for cid in concept_ids]
    return cue


def _blank_template(template: str) -> str:
    """``{object}をください`` -> ``___をください``."""
    out, depth = [], 0
    for ch in template:
        if ch == "{":
            depth += 1
            if depth == 1:
                out.append("___")
        elif ch == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def current_help_cue(state: GameState, cartridge: Cartridge) -> dict[str, Any] | None:
    beat = active_beat(state, cartridge)
    if beat is None or state.learning is None:
        return None
    return help_cue(state, cartridge, beat, state.learning.help_level.get(beat.id, 0))


def request_help(state: GameState, cartridge: Cartridge) -> dict[str, Any] | None:
    """Learner pressed Help: raise the active beat's level by exactly one (max 5).

    Mutates ``state``. Returns the HelpCue for the new level, or None when there is no
    active learning beat (plain story mode or finished episode).
    """
    beat = active_beat(state, cartridge)
    if beat is None or state.learning is None:
        return None
    ls = state.learning
    level = min(MAX_HELP_LEVEL, ls.help_level.get(beat.id, 0) + 1)
    if level != ls.help_level.get(beat.id, 0):
        _set_level(ls, beat, level)
    return help_cue(state, cartridge, beat, level)


def set_help_level(
    state: GameState, cartridge: Cartridge, beat_id: str, level: int
) -> dict[str, Any] | None:
    """DM-requested level: never below current, never more than current+1, max 5."""
    ls, _ = _ledger(state, cartridge)
    beat = active_beat(state, cartridge)
    if beat is None:
        raise LedgerError("all learning beats are already complete")
    if beat_id != beat.id:
        raise LedgerError(f"learning_beat_id must be the active beat '{beat.id}', not '{beat_id}'")
    current = ls.help_level.get(beat.id, 0)
    if level < current:
        raise LedgerError(f"help never goes down: current level is {current}")
    if level > min(MAX_HELP_LEVEL, current + 1):
        raise LedgerError(
            f"help rises one level at a time: current {current}, allowed "
            f"{current}..{min(MAX_HELP_LEVEL, current + 1)}"
        )
    if level != current:
        _set_level(ls, beat, level)
    return help_cue(state, cartridge, beat, level)


def tap_allowed(state: GameState, cartridge: Cartridge) -> bool:
    """Tapping an object is a valid input: always in a recognition beat, else at a tap rescue."""
    beat = active_beat(state, cartridge)
    if beat is None or state.learning is None:
        return False
    if beat.success_evidence == "recognition":
        return True
    entry = beat.help_entry(state.learning.help_level.get(beat.id, 0))
    return bool(entry and entry.tap_fallback)


def learning_view(state: GameState, cartridge: Cartridge) -> dict[str, Any]:
    """LearningView payload (empty view in plain story mode)."""
    ls = state.learning
    ll = cartridge.language_learning
    if ls is None or ll is None:
        return {
            "active_beat": None, "concept_stage": {}, "pattern_stage": {},
            "help_level": 0, "next_help": None, "tap_fallback": False,
        }
    beat = active_beat(state, cartridge)
    level = ls.help_level.get(beat.id, 0) if beat else 0
    next_entry = beat.help_entry(level + 1) if beat and level < MAX_HELP_LEVEL else None
    return {
        "active_beat": (
            {"id": beat.id, "objective": beat.objective, "index": ls.active_beat_index,
             "total": len(ll.learning_beats)}
            if beat else None
        ),
        "concept_stage": dict(ls.concept_stage),
        "pattern_stage": dict(ls.pattern_stage),
        "help_level": level,
        "next_help": {"level": next_entry.level, "label": next_entry.label} if next_entry else None,
        "tap_fallback": tap_allowed(state, cartridge),
    }


# ---------------------------------------------------------------- exposures


def note_spoken_lines(
    state: GameState, cartridge: Cartridge, lines: list[SpokenLine]
) -> None:
    """Delivered NPC lines raise exposures; a line modeling the beat's full pattern+slot
    marks ``phrase_modeled`` for the active beat."""
    ls = state.learning
    if ls is None or cartridge.language_learning is None:
        return
    beat = active_beat(state, cartridge)
    slot = beat.slot_concept() if beat else None
    for line in lines:
        if cartridge.npc(line.speaker) is None:
            continue
        for cid in line.concept_ids:
            if cid in ls.exposures:
                ls.exposures[cid] += 1
        if (
            beat is not None and beat.pattern is not None and line.pattern_id == beat.pattern
            and slot is not None and slot in line.concept_ids
        ):
            ls.phrase_modeled[beat.id] = True


# ---------------------------------------------------------------- evidence


@dataclass
class EvidenceResult:
    records: list[EvidenceRecord] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _prior_production(ls: LearningState, pattern_id: str, other_than: str) -> bool:
    return any(
        r.pattern_id == pattern_id and r.concept_id != other_than and not r.tap_fallback
        and r.evidence_type in ("produced", "transferred")
        and stage_at_least(r.stage_after, "produced_with_cue")
        for r in ls.evidence
    )


def record_evidence(
    state: GameState,
    cartridge: Cartridge,
    *,
    attempt: Attempt,
    turn: int,
    beat_id: str,
    concept_ids: list[str],
    pattern_id: str | None,
    evidence_type: EvidenceType,
    outcome: Outcome,
    mixed_language: bool,
) -> EvidenceResult:
    """Apply the ledger rules for one player attempt. Validates everything before mutating."""
    ls, ll = _ledger(state, cartridge)
    beat = active_beat(state, cartridge)
    if beat is None:
        raise LedgerError("all learning beats are already complete")
    if beat_id != beat.id:
        raise LedgerError(f"learning_beat_id must be the active beat '{beat.id}', not '{beat_id}'")
    if not concept_ids:
        raise LedgerError("concept_ids must name at least one concept")
    for cid in concept_ids:
        if ll.concept(cid) is None:
            raise LedgerError(f"unknown concept_id '{cid}'")
    productive = evidence_type in ("produced", "transferred")
    if pattern_id is not None and ll.pattern(pattern_id) is None:
        raise LedgerError(f"unknown pattern_id '{pattern_id}'")
    if productive:
        if beat.success_evidence == "recognition":
            raise LedgerError(
                f"beat '{beat.id}' is a recognition beat: record evidence_type='recognized'"
            )
        if pattern_id is None:
            pattern_id = beat.pattern
        if pattern_id != beat.pattern:
            raise LedgerError(f"pattern_id must be this beat's pattern '{beat.pattern}'")
        pattern = ll.pattern(pattern_id) if pattern_id else None
        allowed = {v for vals in pattern.slots.values() for v in vals} if pattern else set()
        for cid in concept_ids:
            if cid not in allowed:
                raise LedgerError(
                    f"concept '{cid}' is not a slot of pattern '{pattern_id}': list only the "
                    f"object the player asked for ({', '.join(sorted(allowed))})"
                )
    if (
        evidence_type == "transferred" and outcome != "not_understood"
        and attempt.input_mode != "tap" and pattern_id is not None
    ):
        for cid in concept_ids:
            if not _prior_production(ls, pattern_id, cid):
                raise LedgerError(
                    f"transferred needs '{pattern_id}' already produced with a different "
                    f"object; record evidence_type='produced' instead"
                )

    support = ls.help_max_used.get(beat.id, 0)
    cued = support >= CUE_HELP_LEVEL or ls.phrase_modeled.get(beat.id, False)
    result = EvidenceResult()
    seen = {(r.attempt_id, r.concept_id, r.evidence_type) for r in ls.evidence}
    fresh = [cid for cid in concept_ids if (attempt.attempt_id, cid, evidence_type) not in seen]
    for cid in concept_ids:
        if cid not in fresh:
            result.notes.append(f"{cid}: already recorded for this attempt (no change)")
    if not fresh:
        return result

    def make(cid: str, **extra: Any) -> EvidenceRecord:
        record = EvidenceRecord(
            attempt_id=attempt.attempt_id, turn=turn, beat_id=beat.id, concept_id=cid,
            pattern_id=pattern_id if productive else None, evidence_type=evidence_type,
            outcome=outcome, input_mode=attempt.input_mode, mixed_language=mixed_language,
            support_level=support, transcript=attempt.transcript, **extra,
        )
        ls.evidence.append(record)
        result.records.append(record)
        return record

    if outcome == "not_understood":
        for cid in fresh:
            make(cid)
        ls.failures[beat.id] = ls.failures.get(beat.id, 0) + 1
        result.notes.append(
            f"not understood: no stage change (failures {ls.failures[beat.id]}"
            f"/{FAILURES_TO_ESCALATE})"
        )
        if ls.failures[beat.id] >= FAILURES_TO_ESCALATE:
            level = min(MAX_HELP_LEVEL, ls.help_level.get(beat.id, 0) + 1)
            _set_level(ls, beat, level)
            entry = beat.help_entry(level)
            result.notes.append(
                f"help raised to level {level}" + (f" ({entry.label})" if entry else "")
            )
        return result

    if productive and attempt.input_mode == "tap":
        for cid in fresh:
            make(cid, tap_fallback=True)
        result.notes.append(
            f"tap fallback recorded at help level {support}; no production stage "
            "(a tap is not spoken production)"
        )
        return result

    for cid in fresh:
        before = ls.concept_stage.get(cid, "unseen")
        pattern_after: Stage | None = None
        downgraded = False
        if evidence_type == "recognized":
            target: Stage = "context_recognized" if attempt.input_mode == "tap" else "speech_recognized"
        elif evidence_type == "produced":
            target = "produced_with_cue" if cued else "produced_independently"
        elif cued:
            target, downgraded = "produced_with_cue", True
        else:
            target = "transferred"
        stage = raise_stage(before, target)
        ls.concept_stage[cid] = stage
        if productive and pattern_id is not None and not downgraded:
            pattern_after = raise_stage(ls.pattern_stage.get(pattern_id, "unseen"), target)
            ls.pattern_stage[pattern_id] = pattern_after
        elif productive and pattern_id is not None:
            pattern_after = ls.pattern_stage.get(pattern_id, "unseen")
        make(cid, stage_after=stage, pattern_stage_after=pattern_after, downgraded=downgraded)
        note = f"{cid} -> {stage}"
        if productive and pattern_id is not None:
            note += f"; {pattern_id} -> {pattern_after}"
            ls.last_successful_construction = LastConstruction(
                pattern_id=pattern_id, concept_id=cid, beat_id=beat.id, support_level=support
            )
        if downgraded:
            note += (
                f" (honest downgrade: support was used in this beat, help level {support}"
                + (", phrase modeled" if ls.phrase_modeled.get(beat.id) else "")
                + "; recorded as produced_with_cue, not transferred)"
            )
        elif productive and cued:
            note += f" (with cue: help level {support}" + (
                ", phrase modeled this beat)" if ls.phrase_modeled.get(beat.id) else ")"
            )
        result.notes.append(note)
    return result
