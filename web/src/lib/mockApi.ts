// In-browser mock of the Polytale REST contract (SPEC.md), enabled with `?mock=1`.
//
// It scripts the golden path so the client can be built and demoed while the real
// backend is built in parallel: opening 鍵。 -> the learner names the key -> asks for
// it -> key given + panel opens -> map grounded -> map requested -> launch -> recap.
// The help ladder (levels 1..5) and failures-raise-help follow the ledger rules.
// Transcription returns canned transcripts; line audio is silent WAV of a plausible
// length. Test hook: `window.__polytaleMock.queue.push({transcript, romanized})`.
//
// This is a stand-in for the server, not product logic: the real DM is the model.

import type { Api } from "./api";
import { ApiError } from "./api";
import type {
  CartridgeView,
  EvidenceEntry,
  HelpCue,
  LearningView,
  PublicState,
  Recap,
  SpokenLine,
  Stage,
  TranscriptEntry,
  Transcription,
  TurnResult,
  World,
} from "./types";
import { encodeWav } from "./wav";

const CID = "broken-airship-ja";
const ART = "/mock-art/";
const KEY = "polytale.mock.state.v1";

const STAGES: Stage[] = [
  "unseen",
  "context_recognized",
  "speech_recognized",
  "produced_with_cue",
  "produced_independently",
  "transferred",
];
const rank = (s: string | undefined) => Math.max(0, STAGES.indexOf((s || "unseen") as Stage));
const maxStage = (a: string | undefined, b: Stage): Stage => (rank(a) >= rank(b) ? (a as Stage) : b);

const CONCEPTS: Record<string, { native: string; romanization: string; gloss: string }> = {
  "object.key": { native: "鍵", romanization: "kagi", gloss: "key" },
  "object.map": { native: "地図", romanization: "chizu", gloss: "map" },
  "word.douzo": { native: "どうぞ", romanization: "douzo", gloss: "here you go" },
  "word.hai": { native: "はい", romanization: "hai", gloss: "yes / okay" },
};

const CARTRIDGE: CartridgeView = {
  id: CID,
  name: "The Broken Airship",
  tagline: "A storm is coming. The engineer needs you — but she only speaks Japanese.",
  target_locale: "ja-JP",
  support_locale: "en-US",
  romanization_system: "hepburn",
  location: { name: "Windward Airfield", plate_url: `${ART}plate_base.png` },
  npcs: [
    {
      id: "npc.engineer",
      name: "Hana",
      role: "airship engineer",
      sprite_url: `${ART}engineer.png`,
      portrait_url: `${ART}engineer_portrait.png`,
      stage: { x: 0.7, y: 0.92, height: 0.62 },
    },
  ],
  objects: [
    { id: "obj.engine_key", concept_id: "object.key", icon_url: `${ART}icon_key.png`, native: "鍵", romanization: "kagi" },
    { id: "obj.route_map", concept_id: "object.map", icon_url: `${ART}icon_map.png`, native: "地図", romanization: "chizu" },
  ],
  fixtures: [
    { id: "fx.engine_panel", name: "engine panel", states: ["locked", "open"], hotspot: { x: 0.32, y: 0.55, r: 0.06 } },
    { id: "fx.airship", name: "airship", states: ["grounded", "launched"], hotspot: { x: 0.4, y: 0.45, r: 0.18 } },
  ],
};

type LineSeed = Omit<SpokenLine, "line_id" | "speaker" | "speaker_name" | "language" | "audio_url">;
const L = (text: string, romanization: string, translation: string, concept_ids: string[], pattern_id: string | null = null): LineSeed => ({
  text,
  romanization,
  translation,
  concept_ids,
  pattern_id,
});

interface HelpSeed {
  level: number;
  label: string;
  kind: string;
  line?: LineSeed;
  concept_ids?: string[];
  pattern_id?: string;
  text?: string;
  native?: string;
  romanization?: string;
  translation?: string;
  tap_fallback?: boolean;
}

interface BeatSeed {
  id: string;
  objective: string;
  initial_help_level: number;
  pattern: string | null;
  slot: string;
  help: HelpSeed[];
}

const FRAME = { native: "___をください", romanization: "___ o kudasai" };

const BEATS: BeatSeed[] = [
  {
    id: "ground_key",
    objective: "Figure out what the engineer is showing you.",
    initial_help_level: 0,
    pattern: null,
    slot: "object.key",
    help: [
      { level: 1, label: "Hear it slowly", kind: "replay_slow", line: L("鍵。", "Kagi.", "Key.", ["object.key"]) },
      { level: 2, label: "Show the word", kind: "word", concept_ids: ["object.key"] },
      { level: 3, label: "Hint at what to do", kind: "meaning", text: "She's naming the thing in her hand. Try saying it back to her." },
      { level: 4, label: "Hint at the meaning", kind: "meaning", text: "kagi ≈ the small brass thing she's holding up" },
      { level: 5, label: "Show the full answer", kind: "full", native: "鍵", romanization: "kagi", translation: "Key.", tap_fallback: true },
    ],
  },
  {
    id: "request_key",
    objective: "Ask the engineer for the key.",
    initial_help_level: 1,
    pattern: "request.give_object",
    slot: "object.key",
    help: [
      { level: 1, label: "Hear it slowly", kind: "replay_slow", line: L("鍵をください。", "Kagi o kudasai.", "Please give me the key.", ["object.key"], "request.give_object") },
      { level: 2, label: "Show the word", kind: "word", concept_ids: ["object.key"] },
      { level: 3, label: "Show a phrase frame", kind: "frame", pattern_id: "request.give_object" },
      { level: 4, label: "Hint at the meaning", kind: "meaning", text: "kudasai ≈ \"please give me\"" },
      { level: 5, label: "Show the full answer", kind: "full", native: "鍵をください", romanization: "Kagi o kudasai", translation: "Please give me the key.", tap_fallback: true },
    ],
  },
  {
    id: "transfer_map",
    objective: "Ask for the map.",
    initial_help_level: 0,
    pattern: "request.give_object",
    slot: "object.map",
    help: [
      { level: 1, label: "Hear it slowly", kind: "replay_slow", line: L("地図。", "Chizu.", "Map.", ["object.map"]) },
      { level: 2, label: "Show the word", kind: "word", concept_ids: ["object.map"] },
      { level: 3, label: "Show a phrase frame", kind: "frame", pattern_id: "request.give_object" },
      { level: 4, label: "Hint at the meaning", kind: "meaning", text: "Same request as before — just a new thing to ask for." },
      { level: 5, label: "Show the full answer", kind: "full", native: "地図をください", romanization: "Chizu o kudasai", translation: "Please give me the map.", tap_fallback: true },
    ],
  },
];

let OPENING = {
  narration: "Wind drags at the moorings. The engineer looks up from the dead engine, lifts a small brass key, and says one word.",
  line: L("鍵。", "Kagi.", "Key.", ["object.key"]),
};

/* eslint-disable @typescript-eslint/no-explicit-any */
let synced: Promise<void> | null = null;
/**
 * Mirror the authored cartridge (served by the Vite dev server at /mock-cartridge.json)
 * so the mock's objectives, help ladders, stage placement and hotspots match what the
 * real server will send. Scripted NPC turn lines stay the mock's own.
 */
function syncCartridge(): Promise<void> {
  if (synced) return synced;
  synced = (async () => {
    try {
      const res = await fetch("/mock-cartridge.json", { cache: "no-store" });
      if (!res.ok) return;
      const c: any = await res.json();
      if (c?.identity?.name) CARTRIDGE.name = c.identity.name;
      if (c?.identity?.tagline) CARTRIDGE.tagline = c.identity.tagline;
      if (c?.setting?.location?.name) CARTRIDGE.location.name = c.setting.location.name;
      for (const n of c?.npcs ?? []) {
        const v = CARTRIDGE.npcs.find((x) => x.id === n.id);
        if (v && n.stage) v.stage = { x: n.stage.x, y: n.stage.y, height: n.stage.height };
        if (v && n.name) v.name = n.name;
      }
      for (const f of c?.fixtures ?? []) {
        const v = CARTRIDGE.fixtures.find((x) => x.id === f.id);
        if (v && f.hotspot) v.hotspot = f.hotspot;
      }
      const ll = c?.language_learning;
      for (const b of ll?.learning_beats ?? []) {
        const v = BEATS.find((x) => x.id === b.id);
        if (!v) continue;
        if (b.objective) v.objective = b.objective;
        if (typeof b.initial_help_level === "number") v.initial_help_level = b.initial_help_level;
        if (Array.isArray(b.help) && b.help.length) {
          v.help = b.help.map((h: any) => ({
            ...h,
            line: h.line
              ? L(h.line.text, h.line.romanization, h.line.translation, h.line.concept_ids ?? [], h.line.pattern_id ?? null)
              : undefined,
          }));
        }
      }
      const op = c?.opening;
      const ol = op?.spoken_lines?.[0];
      if (op?.narration && ol) {
        OPENING = { narration: op.narration, line: L(ol.text, ol.romanization, ol.translation, ol.concept_ids ?? [], ol.pattern_id ?? null) };
      }
    } catch {
      /* no authored cartridge yet: built-in mock data */
    }
  })();
  return synced;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

interface MockState {
  session_id: string;
  token: string;
  started: boolean;
  turn: number;
  transcript: TranscriptEntry[];
  holders: Record<string, string>;
  fixtures: Record<string, string>;
  focus: World["focus"];
  beat: number;
  help_level: Record<string, number>;
  help_max: Record<string, number>;
  failures: Record<string, number>;
  phrase_modeled: Record<string, boolean>;
  concept_stage: Record<string, string>;
  pattern_stage: Record<string, string>;
  last_support: number | null;
  episode_complete: boolean;
  attempts: Record<string, { transcript: string; romanized: string | null; consumed: boolean }>;
  help_cue: HelpCue | null;
  lines: Record<string, SpokenLine>;
  seq: number;
}

function fresh(session_id: string, token: string): MockState {
  return {
    session_id,
    token,
    started: false,
    turn: 0,
    transcript: [],
    holders: { "obj.engine_key": "npc.engineer", "obj.route_map": "npc.engineer" },
    fixtures: { "fx.engine_panel": "locked", "fx.airship": "grounded" },
    focus: null,
    beat: 0,
    help_level: {},
    help_max: {},
    failures: {},
    phrase_modeled: {},
    concept_stage: {},
    pattern_stage: {},
    last_support: null,
    episode_complete: false,
    attempts: {},
    help_cue: null,
    lines: {},
    seq: 0,
  };
}

let mem: MockState | null = null;
function load(): MockState | null {
  if (mem) return mem;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) mem = JSON.parse(raw) as MockState;
  } catch {
    /* storage unavailable */
  }
  return mem;
}
function save(st: MockState) {
  mem = st;
  try {
    localStorage.setItem(KEY, JSON.stringify(st));
  } catch {
    /* storage unavailable */
  }
}
function need(sid: string, token: string): MockState {
  const st = load();
  if (!st || st.session_id !== sid) throw new ApiError(404, "unknown session");
  if (st.token !== token) throw new ApiError(403, "bad token");
  return st;
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const uid = (p: string) => `${p}_${Math.random().toString(36).slice(2, 10)}`;

function plateUrl(st: MockState): string {
  if (st.fixtures["fx.airship"] === "launched") return `${ART}plate_launched.png`;
  if (st.fixtures["fx.engine_panel"] === "open") return `${ART}plate_panel_open.png`;
  return `${ART}plate_base.png`;
}

function world(st: MockState): World {
  return { holders: { ...st.holders }, fixtures: { ...st.fixtures }, focus: st.focus, plate_url: plateUrl(st) };
}

function learning(st: MockState): LearningView {
  const beat = BEATS[st.beat];
  const level = beat ? st.help_level[beat.id] ?? beat.initial_help_level : 0;
  const next = beat?.help.find((h) => h.level === level + 1);
  return {
    active_beat: beat ? { id: beat.id, objective: beat.objective, index: st.beat, total: BEATS.length } : null,
    concept_stage: { ...st.concept_stage },
    pattern_stage: { ...st.pattern_stage },
    help_level: level,
    next_help: next ? { level: next.level, label: next.label } : null,
    tap_fallback: level >= 5,
  };
}

function line(st: MockState, seed: LineSeed): SpokenLine {
  st.seq += 1;
  const l: SpokenLine = {
    line_id: `ln_${st.turn}_${st.seq}`,
    speaker: "npc.engineer",
    speaker_name: "Hana",
    language: "ja-JP",
    audio_url: "",
    ...seed,
  };
  l.audio_url = `/api/sessions/${st.session_id}/lines/${l.line_id}/audio`;
  st.lines[l.line_id] = l;
  const beat = BEATS[st.beat];
  if (beat && beat.pattern && l.pattern_id === beat.pattern && l.concept_ids.includes(beat.slot)) {
    st.phrase_modeled[beat.id] = true;
  }
  return l;
}

function enterBeat(st: MockState, index: number) {
  st.beat = index;
  const beat = BEATS[index];
  if (!beat) {
    st.episode_complete = true;
    return;
  }
  const prior = st.last_support;
  st.help_level[beat.id] = prior == null ? beat.initial_help_level : Math.min(beat.initial_help_level, Math.max(0, prior - 1));
  st.help_max[beat.id] = st.help_level[beat.id];
  st.failures[beat.id] = 0;
}

function cueFor(st: MockState, beat: BeatSeed, level: number): HelpCue {
  const h = beat.help.find((x) => x.level === level)!;
  const cue: HelpCue = { level: h.level, label: h.label, kind: h.kind };
  if (h.line) cue.line = line(st, h.line);
  if (h.concept_ids) cue.concepts = h.concept_ids.map((id) => ({ id, native: CONCEPTS[id].native, romanization: CONCEPTS[id].romanization }));
  if (h.kind === "frame") {
    cue.frame = FRAME;
    cue.concepts = [{ id: beat.slot, native: CONCEPTS[beat.slot].native, romanization: CONCEPTS[beat.slot].romanization }];
  }
  if (h.text) cue.text = h.text;
  if (h.native) cue.native = h.native;
  if (h.romanization) cue.romanization = h.romanization;
  if (h.translation) cue.translation = h.translation;
  return cue;
}

function raiseHelp(st: MockState, beat: BeatSeed) {
  const cur = st.help_level[beat.id] ?? 0;
  const next = Math.min(5, cur + 1);
  st.help_level[beat.id] = next;
  st.help_max[beat.id] = Math.max(st.help_max[beat.id] ?? 0, next);
  return next;
}

function evidence(
  st: MockState,
  beat: BeatSeed,
  concept: string,
  type: EvidenceEntry["evidence_type"],
  outcome: EvidenceEntry["outcome"],
  mode: EvidenceEntry["input_mode"],
): EvidenceEntry {
  const support = st.help_max[beat.id] ?? 0;
  let stage: Stage = (st.concept_stage[concept] as Stage) || "unseen";
  if (outcome === "not_understood") {
    st.failures[beat.id] = (st.failures[beat.id] ?? 0) + 1;
    if (st.failures[beat.id] >= 2) {
      raiseHelp(st, beat);
      st.failures[beat.id] = 0;
    }
  } else if (type === "recognized") {
    stage = maxStage(st.concept_stage[concept], mode === "tap" ? "context_recognized" : "speech_recognized");
    st.concept_stage[concept] = stage;
  } else {
    const cued = support >= 3 || !!st.phrase_modeled[beat.id];
    const target: Stage = type === "transferred" ? (cued ? "produced_with_cue" : "transferred") : cued ? "produced_with_cue" : "produced_independently";
    stage = maxStage(st.concept_stage[concept], target);
    st.concept_stage[concept] = stage;
    if (beat.pattern && !(type === "transferred" && cued)) st.pattern_stage[beat.pattern] = maxStage(st.pattern_stage[beat.pattern], target);
    st.last_support = support;
  }
  const changed = outcome !== "not_understood";
  return { kind: "evidence", turn: st.turn, beat_id: beat.id, concept_ids: [concept], evidence_type: type, outcome, stage_after: { [concept]: changed ? stage : null }, support_level: support, input_mode: mode };
}

const has = (t: string, words: string[]) => words.some((w) => t.includes(w));
const KEYW = ["kagi", "鍵", "かぎ", "カギ", "key"];
const MAPW = ["chizu", "地図", "ちず", "map"];
const ASKW = ["kudasai", "ください", "下さい", "please", "kudasi", "give"];

const SUPPORT_PHRASE = [
  "on your own",
  "after hearing it slowly",
  "with the word shown",
  "with a phrase frame",
  "with a meaning hint",
  "with the full answer shown",
];

function buildRecap(st: MockState): Recap {
  const ev = st.transcript.filter((e): e is EvidenceEntry => e.kind === "evidence" && e.outcome !== "not_understood");
  const recognized = ["object.key", "object.map"]
    .filter((c) => rank(st.concept_stage[c]) >= 1)
    .map((c) => ({ concept_id: c, native: CONCEPTS[c].native, romanization: CONCEPTS[c].romanization }));
  const players = st.transcript.filter((e) => e.kind === "player");
  const productions = ev
    .filter((e) => e.evidence_type !== "recognized")
    .map((e) => {
      const c = e.concept_ids[0];
      const p = [...players].reverse().find((x) => x.turn === e.turn);
      return {
        beat_id: e.beat_id,
        concept_id: c,
        native: CONCEPTS[c].native,
        romanization: CONCEPTS[c].romanization,
        stage: e.stage_after[c] ?? null,
        support_level: e.support_level,
        input_mode: e.input_mode,
        transcript: p && p.kind === "player" ? p.transcript : "",
      };
    });
  const key = productions.find((p) => p.beat_id === "request_key");
  const map = productions.find((p) => p.beat_id === "transfer_map");
  const lines: string[] = [];
  if (recognized.length) lines.push(`You recognized ${recognized.map((r) => `${r.native} (${r.romanization})`).join(" and ")} from the scene.`);
  if (key) lines.push(`You asked for the key ${SUPPORT_PHRASE[key.support_level] ?? "with help"}.`);
  if (map)
    lines.push(
      map.stage === "transferred"
        ? "You reused the request for the map without the full phrase."
        : `You asked for the map ${SUPPORT_PHRASE[map.support_level] ?? "with help"}.`,
    );
  return {
    recognized,
    productions,
    transfer: {
      achieved: map?.stage === "transferred",
      summary: map?.stage === "transferred" ? "You carried “___ o kudasai” to a new object on your own." : "You asked for the map with some support.",
    },
    lines,
    next_episode: "Next: ask where something is.",
  };
}

// Payloads are deep copies, like JSON off the wire: the client must never alias mock state.
const wire = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

function publicState(st: MockState): PublicState {
  return wire({
    session_id: st.session_id,
    cartridge: CARTRIDGE,
    started: st.started,
    turn: st.turn,
    transcript: st.transcript,
    world: world(st),
    learning: learning(st),
    episode_complete: st.episode_complete,
    recap: st.episode_complete ? buildRecap(st) : null,
    help_cue: st.help_cue,
  });
}

function result(st: MockState, narration: string, lines: SpokenLine[], ev: EvidenceEntry[], t0: number): TurnResult {
  return wire({
    turn: st.turn,
    narration,
    spoken_lines: lines,
    world: world(st),
    learning: learning(st),
    evidence: ev,
    episode_complete: st.episode_complete,
    recap: st.episode_complete ? buildRecap(st) : null,
    latency_ms: Math.round(performance.now() - t0),
  });
}

function commit(st: MockState, narration: string, lines: SpokenLine[], ev: EvidenceEntry[]) {
  for (const e of ev) st.transcript.push(e);
  if (narration) st.transcript.push({ kind: "narration", turn: st.turn, text: narration });
  for (const l of lines) st.transcript.push({ kind: "npc", turn: st.turn, line: l });
  st.help_cue = null;
  save(st);
}

type Script = { transcript: string; romanized: string | null; requires_confirmation?: boolean; confidence?: number };
const hook = { queue: [] as Script[], transcribeMs: 700, actMs: 1500 };
declare global {
  interface Window {
    __polytaleMock?: typeof hook;
  }
}

const CANNED: Record<string, Script> = {
  ground_key: { transcript: "かぎ？", romanized: "kagi?" },
  request_key: { transcript: "鍵… ください", romanized: "kagi… kudasai" },
  transfer_map: { transcript: "地図をください", romanized: "chizu o kudasai" },
};

const silentCache = new Map<string, string>();

export function createMockApi(): Api {
  if (typeof window !== "undefined") window.__polytaleMock = hook;

  async function turn(st: MockState, input: { mode: "speech" | "text" | "tap"; text: string; romanized: string | null; tap: string | null; attempt_id: string }): Promise<TurnResult> {
    const t0 = performance.now();
    await wait(hook.actMs);
    st.turn += 1;
    st.transcript.push({ kind: "player", turn: st.turn, attempt_id: input.attempt_id, input_mode: input.mode, transcript: input.text, romanized: input.romanized, tapped_object_id: input.tap });
    const beat = BEATS[st.beat];
    const t = `${input.text} ${input.romanized ?? ""}`.toLowerCase();
    const lines: SpokenLine[] = [];
    const ev: EvidenceEntry[] = [];
    let narration = "";
    if (!beat) {
      narration = "The airship hums above the clouds. There is nothing left to ask for today.";
      commit(st, narration, lines, ev);
      return result(st, narration, lines, ev, t0);
    }
    const level = st.help_level[beat.id] ?? 0;
    const saysKey = input.tap === "obj.engine_key" || has(t, KEYW);
    const saysMap = input.tap === "obj.route_map" || has(t, MAPW);
    const asks = has(t, ASKW);

    if (beat.id === "ground_key") {
      if (saysKey) {
        ev.push(evidence(st, beat, "object.key", "recognized", "understood", input.mode));
        enterBeat(st, 1);
        lines.push(line(st, L("はい！鍵。", "Hai! Kagi.", "Yes! Key.", ["word.hai", "object.key"])));
        st.focus = { object_id: "obj.engine_key", gesture: "withhold" };
        lines.push(line(st, L("鍵をください。", "Kagi o kudasai.", "Please give me the key.", ["object.key"], "request.give_object")));
        narration = "Hana grins and pulls the key back against her chest. She holds out an open palm toward herself, waiting.";
      } else {
        ev.push(evidence(st, beat, "object.key", "recognized", "not_understood", input.mode));
        st.focus = { object_id: "obj.engine_key", gesture: "point" };
        lines.push(line(st, L("これ。鍵。", "Kore. Kagi.", "This. Key.", ["object.key"])));
        narration = "Hana taps the brass key and says it again, slower.";
      }
    } else if (beat.id === "request_key") {
      if ((saysKey && asks) || (input.tap === "obj.engine_key" && level >= 5)) {
        ev.push(evidence(st, beat, "object.key", "produced", "understood", input.mode));
        st.holders["obj.engine_key"] = "player";
        st.fixtures["fx.engine_panel"] = "open";
        lines.push(line(st, L("はい、鍵をください、ですね。どうぞ。", "Hai, kagi o kudasai, desu ne. Douzo.", "Yes — “please give me the key,” right? Here you go.", ["word.hai", "object.key", "word.douzo"], "request.give_object")));
        enterBeat(st, 2);
        st.focus = { object_id: "obj.route_map", gesture: "hold_up" };
        lines.push(line(st, L("地図。", "Chizu.", "Map.", ["object.map"])));
        narration = "She presses the key into your hand. The engine panel clanks open — an empty route slot glows inside. Hana unrolls a map.";
      } else {
        ev.push(evidence(st, beat, "object.key", "produced", "not_understood", input.mode));
        lines.push(line(st, L("鍵を…？", "Kagi o…?", "The key…?", ["object.key"])));
        narration = saysKey ? "Hana nods at the word and waits, eyebrows raised, for the rest." : "Hana tilts her head and lifts the key a little, encouraging.";
        st.focus = { object_id: "obj.engine_key", gesture: "withhold" };
      }
    } else if (beat.id === "transfer_map") {
      if ((saysMap && asks) || (input.tap === "obj.route_map" && level >= 5)) {
        ev.push(evidence(st, beat, "object.map", "transferred", "understood", input.mode));
        st.holders["obj.route_map"] = "player";
        st.fixtures["fx.airship"] = "launched";
        st.focus = null;
        lines.push(line(st, L("はい、地図。どうぞ！", "Hai, chizu. Douzo!", "Yes, the map. Here you go!", ["word.hai", "object.map", "word.douzo"])));
        narration = "The route clicks into its slot. Moorings slip, the envelope fills — and the airship rises into a clearing sky.";
        enterBeat(st, 3);
      } else {
        ev.push(evidence(st, beat, "object.map", "transferred", "not_understood", input.mode));
        st.focus = { object_id: "obj.route_map", gesture: "hold_up" };
        lines.push(line(st, L("地図…？", "Chizu…?", "The map…?", ["object.map"])));
        narration = "Hana rattles the map gently and waits for you to ask.";
      }
    }
    commit(st, narration, lines, ev);
    return result(st, narration, lines, ev, t0);
  }

  return {
    mock: true,
    health: async () => ({ ok: true, speech_provider: "mock", tts_provider: "mock" }),
    cartridges: async () => (await syncCartridge(), [{ id: CID, name: CARTRIDGE.name, tagline: CARTRIDGE.tagline, target_locale: "ja-JP" }]),
    artUrl: (_id, path) => `${ART}${path.replace(/^art\//, "")}`,
    createSession: async (cartridge_id) => {
      if (cartridge_id !== CID) throw new ApiError(404, "unknown cartridge");
      await syncCartridge();
      await wait(150);
      const st = fresh(uid("ses"), uid("tok"));
      save(st);
      return { session_id: st.session_id, token: st.token, state: publicState(st) };
    },
    getState: async (sid, token) => {
      await syncCartridge();
      return publicState(need(sid, token));
    },
    start: async (sid, token) => {
      const st = need(sid, token);
      if (st.started) throw new ApiError(409, "already started");
      const t0 = performance.now();
      await wait(400);
      st.started = true;
      enterBeat(st, 0);
      st.focus = { object_id: "obj.engine_key", gesture: "hold_up" };
      const narration = OPENING.narration;
      const lines = [line(st, OPENING.line)];
      commit(st, narration, lines, []);
      return result(st, narration, lines, [], t0);
    },
    transcribe: async (sid, token, _audio, _rec) => {
      const st = need(sid, token);
      await wait(hook.transcribeMs);
      const beat = BEATS[st.beat];
      const s = hook.queue.shift() ?? CANNED[beat?.id ?? "transfer_map"] ?? { transcript: "", romanized: null };
      const attempt_id = uid("att");
      if (s.transcript) st.attempts[attempt_id] = { transcript: s.transcript, romanized: s.romanized, consumed: false };
      save(st);
      const tr: Transcription = {
        attempt_id,
        transcript: s.transcript,
        romanized: s.romanized,
        detected_languages: s.transcript ? ["ja"] : [],
        confidence: s.confidence ?? (s.transcript ? 0.86 : null),
        requires_confirmation: !!s.requires_confirmation,
        provider: "mock",
      };
      return tr;
    },
    act: async (sid, token, body) => {
      const st = need(sid, token);
      if (!st.started) throw new ApiError(409, "not started");
      if ("attempt_id" in body) {
        const a = st.attempts[body.attempt_id];
        if (!a) throw new ApiError(404, "unknown attempt");
        if (a.consumed) throw new ApiError(409, "attempt already consumed");
        a.consumed = true;
        return turn(st, { mode: "speech", text: a.transcript, romanized: a.romanized, tap: null, attempt_id: body.attempt_id });
      }
      if ("text" in body) return turn(st, { mode: "text", text: body.text, romanized: null, tap: null, attempt_id: uid("att") });
      return turn(st, { mode: "tap", text: "", romanized: null, tap: body.tap_object_id, attempt_id: uid("att") });
    },
    help: async (sid, token) => {
      const st = need(sid, token);
      await wait(250);
      const beat = BEATS[st.beat];
      if (!beat) throw new ApiError(409, "episode complete");
      const level = raiseHelp(st, beat);
      const cue = cueFor(st, beat, level);
      st.help_cue = cue;
      save(st);
      return wire({ cue, learning: learning(st) });
    },
    recap: async (sid, token) => {
      const st = need(sid, token);
      if (!st.episode_complete) throw new ApiError(409, "episode not complete");
      return buildRecap(st);
    },
    reset: async (sid, token) => {
      need(sid, token);
      const st = fresh(sid, token);
      save(st);
      return publicState(st);
    },
    audioSrc: async (sid, token, _url, lineId) => {
      const st = need(sid, token);
      const cached = silentCache.get(lineId);
      if (cached) return cached;
      const text = st.lines[lineId]?.text ?? "";
      const secs = Math.min(3.2, 0.6 + text.length * 0.16);
      const url = URL.createObjectURL(encodeWav(new Float32Array(Math.round(16000 * secs)), 16000));
      silentCache.set(lineId, url);
      return url;
    },
    withToken: (url, token) => (url ? `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}` : url),
  };
}
