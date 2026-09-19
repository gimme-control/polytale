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
  highlight_object_ids: string[];
  audio_url: string;
}

export type InputMode = "speech" | "text" | "tap";

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
  tapped_object_id: string | null;
  /** v3: the verb used on the object ("show", "take", ...); absent means point */
  action_id?: string | null;
}
export interface SceneEventEntry {
  kind: "scene";
  turn: number;
  event: "object_moved" | "goal_done";
  object_id?: string;
  from?: string;
  to?: string;
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

export interface Position {
  x: number;
  y: number;
  h: number;
}

export interface ObjectAction {
  id: string;
  /** support-language verb, e.g. "Show", "Drink" */
  label: string;
}

export interface SceneObject {
  id: string;
  art_url: string;
  price: number | null;
  positions: Record<string, Position>;
  /** v3 verbs; absent or empty means the object can only be pointed at */
  actions?: ObjectAction[];
}

export interface SceneView {
  id: string;
  name: string;
  tagline: string;
  intro: string;
  background_url: string;
  mood_urls: Record<string, string>;
  cover_url: string;
  npc: { name: string; role: string; anchor: { x: number; y: number } };
  objects: SceneObject[];
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

export type Difficulty = "story" | "immersion";

export interface GameView {
  wallet: number;
  clock: { label: string; time: string; minutes_left: number; minutes_total: number };
  trust: number;
  clues: Clue[];
  difficulty: Difficulty;
  prices: Record<string, number>;
}

export interface Ending {
  id: string;
  title: string;
  text: string;
  art_url: string;
  stats: { minutes_left: number; wallet: number; clues: number; words_mastered: number; words_shaky: number };
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
  mood: string;
  zones: Record<string, string>;
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
  /** extension: prefix for price tags; digits only when absent */
  currency_symbol?: string | null;
}

export interface Persona {
  id: string;
  label: string;
  blurb: string;
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
  persona_id: string;
  personas: Persona[];
  scene: SceneView | null;
  started: boolean;
  turn: number;
  transcript: Entry[];
  zones: Record<string, string>;
  mood: string;
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
  highlight_object_ids: string[];
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
  language: Language;
  scenes: SceneCard[];
  personas: Persona[];
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
export type ActBody = { attempt_id: string } | { text: string } | { tap_object_id: string; action_id?: string };

export interface SceneBody {
  scene_id?: string;
  restart?: boolean;
}
