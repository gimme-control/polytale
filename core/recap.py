"""Evidence-based recap: observed behaviour from the ledger, never a fluency score."""

from __future__ import annotations

from typing import Any

from core.cartridge import Cartridge, LanguageLearning
from core.ledger import CUE_HELP_LEVEL, stage_at_least
from core.state import STAGES, EvidenceRecord, GameState

_RANK = {stage: i for i, stage in enumerate(STAGES)}


def _best_production(records: list[EvidenceRecord]) -> EvidenceRecord | None:
    """The strongest successful production for one (beat, concept); earliest on ties.

    Spoken productions outrank a tap fallback.
    """
    best: EvidenceRecord | None = None
    for r in records:
        if best is None:
            best = r
            continue
        r_rank = -1 if r.stage_after is None else _RANK[r.stage_after]
        b_rank = -1 if best.stage_after is None else _RANK[best.stage_after]
        if r_rank > b_rank:
            best = r
    return best


def _production_sentence(
    record: EvidenceRecord, ll: LanguageLearning, npc_name: str, modeled: bool
) -> str:
    concept = ll.concept(record.concept_id)
    gloss = concept.gloss if concept else record.concept_id
    if record.tap_fallback:
        return f"You used the tap fallback for the {gloss}."
    reuse = record.evidence_type == "transferred"
    verb = "reused the request for" if reuse else "asked for"
    if record.stage_after == "transferred":
        how = "without the full phrase"
    elif record.stage_after == "produced_independently":
        how = "without seeing the full phrase"
    elif record.support_level >= CUE_HELP_LEVEL:
        how = f"with a phrase frame (help level {record.support_level})"
    elif modeled:
        how = f"after hearing {npc_name} say the full phrase"
    else:
        how = "with support"
    sentence = f"You {verb} the {gloss} {how}."
    if record.mixed_language:
        sentence = sentence[:-1] + ", mixing in English, and were understood."
    return sentence


def build_recap(state: GameState, cartridge: Cartridge) -> dict[str, Any]:
    """Recap payload. Tolerates plain story mode (no learning ledger)."""
    ll = cartridge.language_learning
    ls = state.learning
    next_episode = ll.next_episode if ll else ""
    if ll is None or ls is None:
        return {
            "recognized": [], "productions": [],
            "transfer": {"achieved": False, "summary": "No language goals in this story."},
            "lines": [], "next_episode": next_episode,
        }
    npc_name = cartridge.npcs[0].name if cartridge.npcs else "the character"

    recognized = [
        {"concept_id": c.id, "native": c.native, "romanization": c.romanization}
        for c in ll.concepts
        if stage_at_least(ls.concept_stage.get(c.id), "context_recognized")
    ]

    productions: list[dict[str, Any]] = []
    lines: list[str] = []
    for beat in ll.learning_beats:
        if beat.success_evidence == "recognition":
            continue
        for cid in beat.concept_ids:
            records = [
                r for r in ls.evidence
                if r.beat_id == beat.id and r.concept_id == cid
                and r.evidence_type in ("produced", "transferred")
                and r.outcome != "not_understood"
            ]
            best = _best_production(records)
            if best is None:
                continue
            concept = ll.concept(cid)
            productions.append(
                {
                    "beat_id": beat.id,
                    "concept_id": cid,
                    "native": concept.native if concept else cid,
                    "romanization": concept.romanization if concept else "",
                    "stage": best.stage_after,
                    "support_level": best.support_level,
                    "input_mode": best.input_mode,
                    "transcript": best.transcript,
                }
            )
            lines.append(
                _production_sentence(best, ll, npc_name, ls.phrase_modeled.get(beat.id, False))
            )

    for c in recognized:
        concept = ll.concept(c["concept_id"])
        if concept is not None and concept.referents and not any(
            p["concept_id"] == concept.id and p["stage"] is not None for p in productions
        ):
            lines.insert(0, f"You recognized {concept.native} ({concept.romanization}) from what "
                            f"{npc_name} showed you.")

    transferred_patterns = [p for p in ll.patterns if ls.pattern_stage.get(p.id) == "transferred"]
    transfer_beats = [b for b in ll.learning_beats if b.success_evidence == "transfer"]
    downgraded = any(r.downgraded for r in ls.evidence)
    if transferred_patterns:
        p = transferred_patterns[0]
        summary = (f"You reused {p.romanization_template.replace('{object}', '___')} with a new "
                   "object without the full phrase in front of you.")
    elif downgraded:
        summary = ("You reused the request with a new object, with help on screen or after "
                   "hearing it modeled, so it is recorded as supported.")
    elif transfer_beats:
        summary = "Transfer not observed yet: the request has not been reused on its own."
    else:
        summary = "This episode has no transfer goal."

    helps = [ls.help_max_used.get(b.id, 0) for b in ll.learning_beats if b.pattern]
    if len(helps) >= 2 and helps[-1] < helps[0]:
        lines.append(f"You needed less help the second time (help level {helps[0]} then "
                     f"{helps[-1]}).")

    return {
        "recognized": recognized,
        "productions": productions,
        "transfer": {"achieved": bool(transferred_patterns), "summary": summary},
        "lines": lines,
        "next_episode": next_episode,
    }
