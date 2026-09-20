// Wire types. These mirror SPEC.md "Payloads" exactly (snake_case JSON).
// Optional fields marked "extension" are tolerated when the server sends them and
// never required.

export interface Segment {
  /** target-language text of one word or punctuation mark */
  t: string;
  /** its romanization; "" for punctuation and for languages without romanization */
  r: string;
}

export interface Line {
  line_id: string;
  speaker_name: string;
  segments: Segment[];
  text: string;
  romanization: string;
  item_ids: string[];
  audio_url: string;
}

export type InputMode = "speech" | "text";

export interface NpcEntry {
  kind: "npc";
  turn: number;
  line: Line;
}
export interface DirectionEntry {
  kind: "direction";
  turn: number;
  text: string;
}
export interface LearnerEntry {
  kind: "learner";
  turn: number;
  attempt_id: string;
  input_mode: InputMode;
  transcript: string;
  romanized: string | null;
}
export interface SceneEventEntry {
  kind: "scene";
  turn: number;
  event: "goal_done";
  goal_id?: string;
}
export interface NarrationEntry {
  kind: "narration";
  turn: number;
  text: string;
}
export interface Clue {
  id: string;
  title: string;
  text: string;
}
export interface ClueEntry {
  kind: "clue";
  turn: number;
  clue: Clue;
}
export type Entry = NpcEntry | DirectionEntry | LearnerEntry | SceneEventEntry | NarrationEntry | ClueEntry;

export interface SceneView {
  id: string;
  name: string;
  tagline: string;
  intro: string;
  background_url: string;
  cover_url: string;
  npc: { name: string; role: string; anchor: { x: number; y: number } };
  goals: { id: string; label: string }[];
  target_count: number;
}

export interface NextHelp {
  level: number;
  label: string;
}

export interface Progress {
  goals_done: string[];
  encountered: number;
  target_count: number;
  help_level: 0 | 1 | 2;
  next_help: NextHelp | null;
}

export type ItemState = "not_encountered" | "shaky" | "mastered";
export type Outcome = "first_try" | "with_help" | "with_hint" | "missed";

export interface SummaryItem {
  item_id: string;
  text: string;
  roman: string;
  gloss: string;
  state: ItemState;
  outcomes: string[];
  produced: boolean;
  recall: boolean;
  heard?: boolean;
  audio_url: string;
}

export interface SceneRef {
  id: string;
  name: string;
  tagline: string;
}

export interface Summary {
  scene_id: string;
  scene_name: string;
  items: SummaryItem[];
  counts: { mastered: number; shaky: number; heard?: number; not_encountered: number };
  recalled: string[];
  lines: string[];
  next_scene: SceneRef | null;
  phrasebook?: Phrase[];
}

export interface GameView {
  trust: number;
  clues: Clue[];
}

export interface Ending {
  id: string;
  title: string;
  text: string;
  art_url: string;
  stats: { clues: number; words_mastered: number; words_shaky: number };
}

export interface PhraseSegment extends Segment {
  /** per-word gloss of the learner's OWN sentence; "" for punctuation */
  g: string;
}

export interface Phrase {
  phrase_id: string;
  /** what the learner asked for, in the support language */
  source: string;
  segments: PhraseSegment[];
  text: string;
  romanization: string;
  audio_url: string;
  item_ids: string[];
}

export interface Story {
  title: string;
  tagline: string;
  premise: string;
  /** extension: title art for the start screen */
  art_url?: string | null;
}

export interface TurnResult {
  turn: number;
  lines: Line[];
  /** v3: the story's voice, shown before the character speaks */
  narration?: string | null;
  game?: GameView;
  ending?: Ending | null;
  /** v2 only; v3 sends narration instead */
  stage_direction?: string | null;
  events: Entry[];
  progress: Progress;
  scene_complete: boolean;
  summary: Summary | null;
  latency_ms: number;
}

export interface Language {
  locale: string;
  name: string;
  native_name: string;
  romanization_label: string | null;
  word_spacing: boolean;
}

/** One row of `GET /api/catalog`'s `languages`: what the start screen offers. */
export interface LanguageOption {
  locale: string;
  name: string;
  native_name: string;
}

export interface SceneCard extends SceneRef {
  cover_url: string;
  /** extension: lets the intro card show the scene's intro before POST /scene returns */
  intro?: string;
}

export interface JourneyScene extends SceneCard {
  status: string;
}

export interface PublicState {
  journey_id: string;
  language: Language;
  scene: SceneView | null;
  started: boolean;
  turn: number;
  transcript: Entry[];
  progress: Progress;
  scene_complete: boolean;
  summary: Summary | null;
  scenes: JourneyScene[];
  story?: Story;
  game?: GameView;
  ending?: Ending | null;
  phrasebook?: Phrase[];
}

export interface Help {
  level: number;
  kind: "again" | "hint";
  line_ids: string[];
  hint: string | null;
}

export interface HelpResponse {
  help: Help;
  progress: Progress;
}

export interface Transcription {
  attempt_id: string;
  transcript: string;
  romanized: string | null;
  detected_languages: string[];
  confidence: number | null;
  requires_confirmation: boolean;
  provider: string;
}

export interface Catalog {
  /** the journey's default/active language */
  language: Language;
  /** every language the story can be played in */
  languages: LanguageOption[];
  scenes: SceneCard[];
  /** extension: lets the title screen show the story before a journey exists */
  story?: Story;
}

export interface Health {
  ok: boolean;
  speech_provider: string;
  tts_provider: string;
  language: string;
}

export interface CreateJourneyResponse {
  journey_id: string;
  token: string;
  state: PublicState;
}

/** POST /act takes exactly one of these. */
export type ActBody = { attempt_id: string } | { text: string };

export interface SceneBody {
  scene_id?: string;
  restart?: boolean;
}
