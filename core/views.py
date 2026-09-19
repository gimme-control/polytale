"""Client-facing payloads. Nothing here may leak item text or glosses during play.

The lexicon reaches the client only through lines the character has actually spoken and,
once a scene is complete, through the summary.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from core import game, vocab
from core.content import ACTIONS, NEUTRAL_MOOD, Anchor, Content, Language, Position, Scene
from core.state import ClueView, Entry, Journey, Line, NpcEntry, Phrase, Summary
from core.summary import build_summary

SceneStatus = Literal["done", "current", "next", "locked"]


class ActionView(BaseModel):
    id: str
    label: str


class ObjectView(BaseModel):
    id: str
    art_url: str
    price: int | None = None
    positions: dict[str, Position]
    actions: list[ActionView] = Field(default_factory=list)


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
    mood_urls: dict[str, str]
    cover_url: str
    npc: NpcView
    objects: list[ObjectView]
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
    currency_symbol: str


class PersonaView(BaseModel):
    id: str
    label: str
    blurb: str


class SceneCard(BaseModel):
    id: str
    name: str
    tagline: str
    intro: str
    cover_url: str
    status: SceneStatus


class ClockView(BaseModel):
    label: str
    time: str  # "23:12"
    minutes_left: int
    minutes_total: int


class GameView(BaseModel):
    wallet: int
    clock: ClockView
    trust: int  # the current scene's character; 0 when no scene is entered
    clues: list[ClueView]
    difficulty: Literal["story", "immersion"]
    prices: dict[str, int]  # current scene: object_id -> what it costs right now


class EndingStats(BaseModel):
    minutes_left: int
    wallet: int
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


class PublicState(BaseModel):
    journey_id: str
    language: LanguageView
    persona_id: str
    personas: list[PersonaView]
    scene: SceneView | None
    started: bool
    turn: int
    transcript: list[Entry]
    zones: dict[str, str]
    mood: str
    progress: Progress
    scene_complete: bool
    summary: Summary | None
    scenes: list[SceneCard]
    story: StoryView
    game: GameView
    ending: Ending | None
    phrasebook: list[Phrase]


def story_view(content: Content) -> StoryView:
    story = content.journey
    return StoryView(title=story.title, tagline=story.tagline, premise=story.premise,
                     art_url="/api/story/art" if story.art else None)


def game_view(journey: Journey, content: Content) -> GameView:
    state, clock = journey.game, content.journey.clock
    scene = content.scene(journey.scene.scene_id) if journey.scene is not None else None
    known = {c.id: c for s in content.scenes.values() for c in s.clues}
    return GameView(
        wallet=state.wallet,
        clock=ClockView(label=clock.label, time=game.clock_time(journey, content),
                        minutes_left=game.minutes_left(journey, content),
                        minutes_total=clock.total_minutes),
        trust=game.trust(journey, scene) if scene is not None else 0,
        clues=[ClueView(id=c, title=known[c].title, text=known[c].text)
               for c in state.clues if c in known],
        difficulty=state.difficulty,
        prices={} if scene is None else {
            o.id: price for o in scene.objects
            if (price := game.price_of(journey, scene, o.id)) is not None},
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
            minutes_left=game.minutes_left(journey, content), wallet=journey.game.wallet,
            clues=len(journey.game.clues), words_mastered=states.count("mastered"),
            words_shaky=states.count("shaky"),
        ),
    )


def language_view(language: Language) -> LanguageView:
    return LanguageView(
        locale=language.locale, name=language.name, native_name=language.native_name,
        romanization_label=language.romanization.label if language.romanization else None,
        word_spacing=language.word_spacing, currency_symbol=language.currency_symbol,
    )


def art_url(scene_id: str, rel: str) -> str:
    return f"/api/scenes/{scene_id}/art/{rel}"


def scene_view(scene: Scene, locale: str) -> SceneView:
    return SceneView(
        id=scene.id, name=scene.name, tagline=scene.tagline, intro=scene.intro,
        background_url=art_url(scene.id, scene.art.background),
        mood_urls={mood: art_url(scene.id, rel) for mood, rel in scene.art.moods.items()},
        cover_url=art_url(scene.id, scene.art.cover),
        npc=NpcView(name=scene.npc.display_name(locale), role=scene.npc.role,
                    anchor=scene.npc.anchor),
        objects=[
            ObjectView(id=o.id, art_url=art_url(scene.id, o.art), price=o.price,
                       positions=o.positions,
                       actions=[ActionView(id=a, label=ACTIONS[a]) for a in o.actions])
            for o in scene.objects
        ],
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
        persona_id=journey.persona_id,
        personas=[PersonaView(id=p.id, label=p.label, blurb=p.blurb) for p in content.personas],
        scene=scene_view(content.scene(run.scene_id), language.locale) if run else None,
        started=bool(run and run.started),
        turn=run.turn if run else 0,
        transcript=list(run.transcript) if run else [],
        zones=dict(run.zones) if run else {},
        mood=run.mood if run else NEUTRAL_MOOD,
        progress=progress_view(journey, content),
        scene_complete=bool(run and run.complete),
        summary=build_summary(journey, content) if run and run.complete else None,
        scenes=scene_cards(journey, content),
        story=story_view(content),
        game=game_view(journey, content),
        ending=ending_view(journey, content),
        phrasebook=list(journey.game.phrasebook),
    )


def find_line(journey: Journey, line_id: str) -> Line | None:
    """A spoken line of the scene being played, by id (for the audio route)."""
    if journey.scene is None:
        return None
    for entry in journey.scene.transcript:
        if isinstance(entry, NpcEntry) and entry.line.line_id == line_id:
            return entry.line
    return None
