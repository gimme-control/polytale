// Runtime payloads — mirrors polytale/SPEC.md "Runtime payloads" exactly (snake_case).

export type Gesture = "hold_up" | "point" | "offer" | "withhold" | "put_away";
export type InputMode = "speech" | "text" | "tap";
export type EvidenceType = "recognized" | "produced" | "transferred";
export type Outcome = "understood" | "clarified" | "not_understood";
export type Stage =
  | "unseen"
  | "context_recognized"
  | "speech_recognized"
  | "produced_with_cue"
  | "produced_independently"
  | "transferred";

export interface SpokenLine {
  line_id: string;
  speaker: string;
  speaker_name: string;
  text: string;
  language: string;
  romanization: string;
  translation: string;
  concept_ids: string[];
  pattern_id: string | null;
  audio_url: string;
}

export interface NarrationEntry {
  kind: "narration";
  turn: number;
  text: string;
}
export interface NpcEntry {
  kind: "npc";
  turn: number;
  line: SpokenLine;
}
export interface PlayerEntry {
  kind: "player";
  turn: number;
  attempt_id: string;
  input_mode: InputMode;
  transcript: string;
  romanized: string | null;
  tapped_object_id: string | null;
}
export interface EvidenceEntry {
  kind: "evidence";
  turn: number;
  beat_id: string;
  concept_ids: string[];
  evidence_type: EvidenceType;
  outcome: Outcome;
  /** concept_id -> resulting stage; null = no stage change (tap fallback / not_understood). */
  stage_after: Record<string, Stage | string | null>;
  support_level: number;
  input_mode: InputMode;
}
export type TranscriptEntry = NarrationEntry | NpcEntry | PlayerEntry | EvidenceEntry;

export interface Focus {
  object_id: string;
  gesture: Gesture;
}

export interface World {
  holders: Record<string, string>;
  fixtures: Record<string, string>;
  focus: Focus | null;
  plate_url: string;
}

export interface LearningView {
  active_beat: { id: string; objective: string; index: number; total: number } | null;
  concept_stage: Record<string, Stage | string>;
  pattern_stage: Record<string, Stage | string>;
  help_level: number;
  next_help: { level: number; label: string } | null;
  tap_fallback: boolean;
}

export type HelpKind = "replay_slow" | "word" | "frame" | "meaning" | "full";

export interface HelpCue {
  level: number;
  label: string;
  kind: HelpKind | string;
  text?: string;
  native?: string;
  romanization?: string;
  translation?: string;
  line?: SpokenLine;
  concepts?: { id: string; native: string; romanization: string }[];
  frame?: { native: string; romanization: string };
}

export interface RecapProduction {
  beat_id: string;
  concept_id: string;
  native: string;
  romanization: string;
  /** null = tap fallback (no spoken stage). */
  stage: Stage | string | null;
  support_level: number;
  input_mode: InputMode;
  transcript: string;
}

export interface Recap {
  recognized: { concept_id: string; native: string; romanization: string }[];
  productions: RecapProduction[];
  transfer: { achieved: boolean; summary: string };
  lines: string[];
  next_episode: string;
}

export interface TurnResult {
  turn: number;
  narration: string;
  spoken_lines: SpokenLine[];
  world: World;
  learning: LearningView;
  evidence: EvidenceEntry[];
  episode_complete: boolean;
  recap: Recap | null;
  latency_ms: number;
}

export interface StagePlacement {
  x: number;
  y: number;
  height: number;
  /** Held-object anchor as fractions of the sprite box. */
  hand?: { x: number; y: number } | null;
}

export interface CartridgeView {
  id: string;
  name: string;
  tagline: string;
  target_locale: string;
  support_locale: string;
  romanization_system: string;
  location: { name: string; plate_url: string };
  npcs: {
    id: string;
    name: string;
    role: string;
    sprite_url: string;
    portrait_url: string;
    stage: StagePlacement;
  }[];
  objects: { id: string; concept_id: string; icon_url: string; native: string; romanization: string }[];
  fixtures: { id: string; name: string; states: string[]; hotspot: { x: number; y: number; r: number } }[];
}

export interface PublicState {
  session_id: string;
  cartridge: CartridgeView;
  started: boolean;
  turn: number;
  transcript: TranscriptEntry[];
  world: World;
  learning: LearningView | null;
  episode_complete: boolean;
  recap: Recap | null;
  help_cue: HelpCue | null;
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

export interface CartridgeSummary {
  id: string;
  name: string;
  tagline: string;
  target_locale: string;
}

export interface CreateSessionResponse {
  session_id: string;
  token: string;
  state: PublicState;
}

export interface HelpResponse {
  cue: HelpCue;
  learning: LearningView;
}

export type ActBody = { attempt_id: string } | { text: string } | { tap_object_id: string };
