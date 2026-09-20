"""End-of-scene summary: the first time the learner sees the word list.

Built only from the vocabulary record. Every sentence reports observed behaviour; nothing
here is a score, a percentage or a fluency claim.
"""

from __future__ import annotations

from core.content import Content
from core.state import (
    Journey,
    SceneRef,
    Summary,
    SummaryCounts,
    SummaryItem,
    item_audio_url,
)


def _listed(words: list[str]) -> str:
    return ", ".join(words[:-1]) + (" and " if len(words) > 1 else "") + words[-1]


def _lines(journey: Journey, content: Content, items: list[SummaryItem]) -> list[str]:
    run = journey.scene
    assert run is not None
    scene = content.scene(run.scene_id)
    total = len(items)
    lines: list[str] = []
    done = [g.label for g in scene.goals if g.id in run.goals_done]
    if done:
        lines.append(f"Done here: {_listed(done)}.")
    met = [i for i in items if i.item_id in journey.vocab and journey.vocab[i.item_id].met]
    lines.append(f"{len(met)} of {total} words came up in {scene.name}.")
    unaided = [i for i in items if "first_try" in i.outcomes]
    if unaided:
        lines.append(f"You understood {len(unaided)} of {total} words with no help.")
    produced = [i.text for i in items if i.produced]
    if produced:
        lines.append(f"You said {_listed(produced)} yourself.")
    for item in items:
        if item.recall:
            first = journey.vocab[item.item_id].first_scene
            origin = content.scenes[first].name if first in content.scenes else first
            lines.append(f"{item.text} came back from {origin} and you got it with no hints.")
    shaky = [i.text for i in items if i.state == "shaky"]
    if shaky:
        verb = "needs" if len(shaky) == 1 else "need"
        lines.append(f"{_listed(shaky)} still {verb} a second look.")
    return lines


def build_summary(journey: Journey, content: Content) -> Summary:
    """Summary of the scene being played (complete or not)."""
    run = journey.scene
    if run is None:
        raise ValueError("no scene to summarize")
    scene, language = content.scene(run.scene_id), content.language(journey.language)
    items: list[SummaryItem] = []
    for item_id in scene.targets:
        item, record = language.items[item_id], journey.vocab.get(item_id)
        here = [r for r in record.results if r.scene_id == scene.id] if record else []
        items.append(
            SummaryItem(
                item_id=item_id, text=item.text, roman=item.roman, gloss=item.gloss,
                state=record.state if record else "not_encountered",
                outcomes=[r.outcome for r in here],
                produced=any(r.produced for r in here),
                recall=any(r.recall for r in here),
                heard=bool(record and record.appearances),
                audio_url=item_audio_url(journey.journey_id, item_id),
            )
        )
    untested = [i for i in items if i.state == "not_encountered"]
    counts = SummaryCounts(
        mastered=sum(1 for i in items if i.state == "mastered"),
        shaky=sum(1 for i in items if i.state == "shaky"),
        heard=sum(1 for i in untested if i.heard),
        not_encountered=sum(1 for i in untested if not i.heard),
    )
    order = content.journey.scenes
    following = order[journey.scene_index + 1:journey.scene_index + 2]
    over = journey.game.ending_id is not None
    next_scene = content.scene(following[0]) if following and not over else None
    return Summary(
        scene_id=scene.id, scene_name=scene.name, items=items, counts=counts,
        recalled=[i.item_id for i in items if i.recall],
        lines=_lines(journey, content, items),
        next_scene=SceneRef(id=next_scene.id, name=next_scene.name, tagline=next_scene.tagline)
        if next_scene else None,
        phrasebook=list(journey.game.phrasebook),
    )
