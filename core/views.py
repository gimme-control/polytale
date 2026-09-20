"""Client-facing payloads. Nothing here may leak item text or glosses during play.

The lexicon reaches the client only through lines the character has actually spoken and,
once a scene is complete, through the summary.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from core import game, vocab
from core.content import Anchor, Content, Language, Scene
from core.frames import FrameView
from core.state import ClueView, Entry, Journey, Line, NpcEntry, Summary
from core.summary import build_summary

SceneStatus = Literal["done", "current", "next", "locked"]


class NpcView(BaseModel):
    name: str
    role: str
    anchor: Anchor


class GoalView(BaseModel):
    id: str
    label: str


class SceneView(BaseModel):
    id: str
    name: str
    tagline: str
    intro: str
    background_url: str
    cover_url: str
    npc: NpcView
    goals: list[GoalView]
    target_count: int


class Progress(BaseModel):
    goals_done: list[str] = Field(default_factory=list)
    encountered: int = 0
    target_count: int = 0
    help_level: int = 0
    next_help: vocab.NextHelp | None = None


class LanguageView(BaseModel):
    locale: str
    name: str
    native_name: str
    romanization_label: str | None
    word_spacing: bool


class SceneCard(BaseModel):
    id: str
    name: str
    tagline: str
    intro: str
    cover_url: str
    status: SceneStatus


class GameView(BaseModel):
    trust: int  # the current scene's character; 0 when no scene is entered
    clues: list[ClueView]


class EndingStats(BaseModel):
    clues: int
    words_mastered: int
    words_shaky: int


class Ending(BaseModel):
    id: str
    title: str
    text: str
    art_url: str | None
    stats: EndingStats


class StoryView(BaseModel):
    title: str
    tagline: str
    premise: str
    art_url: str | None = None  # title art


class HeardWord(BaseModel):
    """A word the character actually said, as he said it.

    Not the same thing as the scene's vocabulary: he speaks like a person, so he says words
    that are not on any list. Those still belong here — "words you have heard" has to mean
    exactly that — with an empty gloss when the lexicon does not know them.
    """

    text: str
    roman: str
    gloss: str


def heard_words(journey: Journey, content: Content) -> list[HeardWord]:
    """Every word he has spoken this scene, in order, first time only.

    A listed phrase he said whole ("esta noche") is ONE entry with that phrase's meaning, not
    two words wearing the wrong glosses. A word the lexicon does not know still appears, with
    no meaning: he speaks freely, and the player heard it either way.
    """
    run = journey.scene
    if run is None:
        return []
    language = content.language(journey.language)
    joiner = " " if language.word_spacing else ""
    out: list[HeardWord] = []
    seen: set[str] = set()
    for entry in run.transcript:
        if not isinstance(entry, NpcEntry):
            continue
        words = [s for s in entry.line.segments if any(ch.isalpha() for ch in s.t)]
        i = 0
        for said, item_id in vocab.scan_items([s.t for s in words], language):
            span = len(said.split()) if language.word_spacing else 1
            if item_id is not None and not language.word_spacing:
                # An unspaced script writes a phrase as one segment anyway.
                span = 1
            group = words[i:i + span] or words[i:i + 1]
            i += max(span, 1)
            text = joiner.join(g.t for g in group) or said
            if text in seen:
                continue
            seen.add(text)
            item = language.items.get(item_id) if item_id else None
            out.append(HeardWord(text=text,
                                 roman=" ".join(g.r for g in group if g.r)
                                 or (item.roman if item else ""),
                                 gloss=item.gloss if item else ""))
    return out


class WordEntry(BaseModel):
    """One word of this scene's vocabulary, with what THAT WORD means.

    A per-word meaning is a dictionary, not a translation: nothing here says what a whole
    SENTENCE meant, so working out what he is asking for, and which words to put together,
    is still the player's job. ``heard`` marks the ones he has already said out loud.
    """

    item_id: str
    text: str
    roman: str
    gloss: str
    heard: bool = False


def dictionary(journey: Journey, content: Content) -> list[WordEntry]:
    """Every word of the scene: the ones he has said first, in the order he said them."""
    run = journey.scene
    if run is None:
        return []
    language = content.language(journey.language)
    scene = content.scene(run.scene_id)
    spoken: list[str] = []
    for entry in run.transcript:
        if isinstance(entry, NpcEntry):
            spoken += [i for i in entry.line.item_ids if i not in spoken]
    order = [i for i in spoken if i in scene.item_ids]
    order += [i for i in scene.item_ids if i not in order]
    out: list[WordEntry] = []
    for item_id in order:
        item = language.items.get(item_id)
        if item is not None:
            out.append(WordEntry(item_id=item_id, text=item.text, roman=item.roman,
                                 gloss=item.gloss, heard=item_id in spoken))
    return out


class PublicState(BaseModel):
    journey_id: str
    language: LanguageView
    scene: SceneView | None
    started: bool
    turn: int
    transcript: list[Entry]
    progress: Progress
    scene_complete: bool
    summary: Summary | None
    scenes: list[SceneCard]
    story: StoryView
    game: GameView
    ending: Ending | None
    #: the scene's vocabulary, word meanings only, heard-first
    dictionary: list[WordEntry] = []
    #: the words he has actually said, as he said them
    heard: list[HeardWord] = []
    #: the scene as it stands (see TurnResult.frame); the server fills it in
    frame: FrameView | None = None


def story_view(content: Content) -> StoryView:
    story = content.journey
    return StoryView(title=story.title, tagline=story.tagline, premise=story.premise,
                     art_url="/api/story/art" if story.art else None)


def game_view(journey: Journey, content: Content) -> GameView:
    state = journey.game
    scene = content.scene(journey.scene.scene_id) if journey.scene is not None else None
    known = {c.id: c for s in content.scenes.values() for c in s.clues}
    return GameView(
        trust=game.trust(journey, scene) if scene is not None else 0,
        clues=[ClueView(id=c, title=known[c].title, text=known[c].text)
               for c in state.clues if c in known],
    )


def ending_view(journey: Journey, content: Content) -> Ending | None:
    """The resolved ending with its stats, or None while the story is still running."""
    spec = next((e for e in content.journey.endings if e.id == journey.game.ending_id), None)
    if spec is None:
        return None
    targets = {t for sid in content.journey.scenes for t in content.scene(sid).targets}
    states = [journey.vocab[t].state for t in targets if t in journey.vocab]
    return Ending(
        id=spec.id, title=spec.title, text=spec.text,
        art_url=art_url(content.journey.scenes[-1], spec.art) if spec.art else None,
        stats=EndingStats(
            clues=len(journey.game.clues), words_mastered=states.count("mastered"),
            words_shaky=states.count("shaky"),
        ),
    )


def language_view(language: Language) -> LanguageView:
    return LanguageView(
        locale=language.locale, name=language.name, native_name=language.native_name,
        romanization_label=language.romanization.label if language.romanization else None,
        word_spacing=language.word_spacing,
    )


def art_url(scene_id: str, rel: str) -> str:
    return f"/api/scenes/{scene_id}/art/{rel}"


def scene_view(scene: Scene, locale: str) -> SceneView:
    return SceneView(
        id=scene.id, name=scene.name, tagline=scene.tagline, intro=scene.intro,
        background_url=art_url(scene.id, scene.art.background),
        cover_url=art_url(scene.id, scene.art.cover),
        npc=NpcView(name=scene.npc.display_name(locale), role=scene.npc.role,
                    anchor=scene.npc.anchor),
        goals=[GoalView(id=g.id, label=g.label) for g in scene.goals],
        target_count=len(scene.targets),
    )


def progress_view(journey: Journey, content: Content) -> Progress:
    run = journey.scene
    if run is None:
        return Progress()
    targets = content.scene(run.scene_id).targets
    playing = run.started and not run.complete
    return Progress(
        goals_done=list(run.goals_done),
        encountered=sum(
            1 for t in targets if t in journey.vocab and journey.vocab[t].met
        ),
        target_count=len(targets),
        help_level=run.exchange.help_level,
        next_help=vocab.next_help(run.exchange) if playing else None,
    )


def scene_cards(journey: Journey, content: Content) -> list[SceneCard]:
    run = journey.scene
    done = {s.scene_id for s in journey.history}
    if run is not None and run.complete:
        done.add(run.scene_id)
    current = run.scene_id if run is not None and not run.complete else None
    cards: list[SceneCard] = []
    upcoming_taken = current is not None
    for scene_id in content.journey.scenes:
        scene = content.scene(scene_id)
        status: SceneStatus = "locked"
        if scene_id == current:
            status = "current"
        elif scene_id in done:
            status = "done"
        elif not upcoming_taken:
            status, upcoming_taken = "next", True
        cards.append(SceneCard(id=scene.id, name=scene.name, tagline=scene.tagline,
                               intro=scene.intro,
                               cover_url=art_url(scene.id, scene.art.cover), status=status))
    return cards


def public_state(journey: Journey, content: Content) -> PublicState:
    language = content.language(journey.language)
    run = journey.scene
    return PublicState(
        journey_id=journey.journey_id,
        language=language_view(language),
        scene=scene_view(content.scene(run.scene_id), language.locale) if run else None,
        started=bool(run and run.started),
        turn=run.turn if run else 0,
        transcript=list(run.transcript) if run else [],
        progress=progress_view(journey, content),
        scene_complete=bool(run and run.complete),
        summary=build_summary(journey, content) if run and run.complete else None,
        scenes=scene_cards(journey, content),
        story=story_view(content),
        game=game_view(journey, content),
        ending=ending_view(journey, content),
        dictionary=dictionary(journey, content),
        heard=heard_words(journey, content),
    )


def find_line(journey: Journey, line_id: str) -> Line | None:
    """A spoken line of the scene being played, by id (for the audio route)."""
    if journey.scene is None:
        return None
    for entry in journey.scene.transcript:
        if isinstance(entry, NpcEntry) and entry.line.line_id == line_id:
            return entry.line
    return None
