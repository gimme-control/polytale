// In-browser mock of the Polytale REST contract (SPEC.md), enabled with `?mock=1`.
//
// A scripted playthrough of the one-scene demo: you are looking for Mei among football
// fans on final night. Show them her photo, win them over, and they tell you where she
// is. Trust, clues, flags, goals and the learning ledger underneath are
// all real; the character and the narrator are scripted stand-ins for the model.
// State persists, so a refresh restores. Real `content/` JSON and art are used for what
// they define when the Vite dev server can serve them (`/mock-content/...`).
//
// This is the ONLY file in web/src allowed to contain target-language text. It is a
// test double, not product logic.
//
// Test hooks: `window.__polytaleMock` = { queue, actMs, transcribeMs, sceneMs, failNextAct }.
// Query flags: `lang=<locale>`, `noroman=1`, `spaced=1`.

import type { Api } from "./api";
import { ApiError } from "./api";
import type {
  Clue,
  Ending,
  Entry,
  Frame,
  GameView,
  Help,
  ItemState,
  JourneyScene,
  Language,
  LanguageOption,
  Line,
  Outcome,
  Progress,
  PublicState,
  SceneView,
  Segment,
  Story,
  Summary,
  Transcription,
  TurnResult,
  HeardWord,
  WordEntry,
} from "./types";
import { encodeWav } from "./wav";

// ---------------------------------------------------------------------------
// Content shapes

interface LexItem {
  text: string;
  roman: string;
  gloss: string;
  kind: string;
}
interface LanguageFile {
  locale: string;
  name: string;
  native_name: string;
  romanization: { system: string; label: string } | null;
  word_spacing: boolean;
  items: Record<string, LexItem>;
}
interface When {
  clue?: string;
  flag?: string;
}
interface GoalDef {
  id: string;
  label: string;
  when: When;
}
interface Reveal {
  trust_at_least?: number;
  flags?: string[];
}
interface ClueDef extends Clue {
  /** one condition, or a list of alternatives (any one is enough) */
  reveal_when?: Reveal | Reveal[];
}
interface SceneFile {
  id: string;
  name: string;
  tagline: string;
  intro: string;
  art: { background: string; cover: string };
  npc: { id: string; name: string; names?: Record<string, string>; names_roman?: Record<string, string>; role: string; anchor?: { x: number; y: number }; trust?: number };
  targets?: string[];
  support_words?: string[];
  goals: GoalDef[];
  clues?: ClueDef[];
  flags?: { id: string }[];
}
interface ArtLayout {
  npc_anchor?: { x: number; y: number };
}
interface EndingDef {
  id: string;
  title: string;
  text: string;
  art: string;
  when?: { clues?: string[]; flags?: string[] };
}
interface StoryFile {
  title?: string;
  tagline?: string;
  premise?: string;
  scenes: string[];
  endings?: EndingDef[];
}

// ---------------------------------------------------------------------------
// Fallback content (only used when `content/` cannot be served)

const LOCALES = ["zh-CN", "ja-JP", "es-ES", "ko-KR"];

const FALLBACK_LANGUAGE: LanguageFile = {
  locale: "zh-CN",
  name: "Mandarin Chinese",
  native_name: "中文",
  romanization: { system: "pinyin", label: "Pinyin" },
  word_spacing: false,
  items: {
    hello: { text: "你好", roman: "nǐ hǎo", gloss: "hello", kind: "phrase" },
    thanks: { text: "谢谢", roman: "xièxie", gloss: "thanks", kind: "phrase" },
    friend: { text: "朋友", roman: "péngyou", gloss: "friend", kind: "noun" },
    where: { text: "在哪儿", roman: "zài nǎr", gloss: "where is …?", kind: "phrase" },
    seen: { text: "见过", roman: "jiànguo", gloss: "have seen", kind: "verb" },
    cheers: { text: "干杯", roman: "gānbēi", gloss: "cheers", kind: "phrase" },
    goal: { text: "进球", roman: "jìnqiú", gloss: "goal", kind: "noun" },
    go_team: { text: "加油", roman: "jiāyóu", gloss: "come on!", kind: "phrase" },
    fan_zone: { text: "球迷广场", roman: "qiúmí guǎngchǎng", gloss: "fan zone", kind: "noun" },
    awesome: { text: "太棒了", roman: "tài bàng le", gloss: "brilliant", kind: "phrase" },
    gate: { text: "二号门", roman: "èr hào mén", gloss: "gate 2", kind: "noun" },
    she: { text: "她", roman: "tā", gloss: "she", kind: "pronoun" },
    match: { text: "比赛", roman: "bǐsài", gloss: "the match", kind: "noun" },
    tonight: { text: "今晚", roman: "jīnwǎn", gloss: "tonight", kind: "noun" },
    scarf: { text: "围巾", roman: "wéijīn", gloss: "scarf", kind: "noun" },
    good: { text: "好", roman: "hǎo", gloss: "good", kind: "adjective" },
    sorry: { text: "对不起", roman: "duìbuqǐ", gloss: "sorry", kind: "phrase" },
    photo: { text: "照片", roman: "zhàopiàn", gloss: "photo", kind: "noun" },
  },
};

const FALLBACK_SCENE: SceneFile = {
  id: "bar",
  name: "The Corner Bar",
  tagline: "Match night. Everyone here knows Mei.",
  intro: "Final night, and the corner bar is packed shoulder to shoulder. One of the fans turns around, sees a stranger, and grins. You have Mei's photo and no words at all.",
  art: { background: "art/bg.webp", cover: "art/cover.webp" },
  npc: { id: "fan", name: "Tavo", role: "football fan", anchor: { x: 0.5, y: 0.262 }, trust: 0 },
  targets: ["hello", "thanks", "friend", "where", "seen", "cheers", "goal", "go_team", "fan_zone", "awesome"],
  goals: [
    { id: "ask", label: "Show someone Mei's photo", when: { flag: "photo_shown" } },
    { id: "trail", label: "Find out where Mei is", when: { clue: "gate" } },
  ],
  flags: [{ id: "photo_shown" }, { id: "cheered" }, { id: "chanted" }, { id: "scarf_worn" }],
  clues: [
    { id: "regular", title: "They know her", text: "The fans recognised Mei's photo instantly. She watches every big match in this bar.", reveal_when: [{ flags: ["photo_shown"] }] },
    { id: "waited", title: "She waited for you", text: "Mei sat with them from six, watching the door. When the crowd left for the fan zone she went too.", reveal_when: [{ flags: ["photo_shown"], trust_at_least: 1 }] },
    { id: "gate", title: "Gate 2", text: "Mei is at the fan zone, gate 2, under the big screen, holding your spot.", reveal_when: [{ flags: ["photo_shown"], trust_at_least: 2 }] },
  ],
};

const FALLBACK_STORY: Required<Pick<StoryFile, "title" | "tagline" | "premise" | "endings">> = {
  title: "Kickoff",
  tagline: "Find Mei before the whistle.",
  premise:
    "It is World Cup final night. You flew in to watch it with Mei on the big screen in the fan zone, and she has your ticket. Your phone is dead and all you have is a photo of her. Nobody here speaks English.",
  endings: [
    { id: "found", title: "Kickoff", text: "Gate 2, a sea of red, the big screen bright as daylight. She is standing on a plastic chair so you cannot miss her. The whistle goes. You made it.", art: "art/ending_kickoff.webp", when: { clues: ["gate"] } },
    { id: "outside", title: "Outside the Fence", text: "The whistle goes without you. You watch the final through a gap in the fence with a hundred other unlucky souls. Next time, you will know to ask.", art: "art/ending_late.webp", when: {} },
  ],
};

// ---------------------------------------------------------------------------
// Mock server state

interface VocabResult {
  scene_id: string;
  outcome: Outcome;
  produced: boolean;
  recall: boolean;
}
interface VocabRecord {
  appearances: number;
  first_scene: string | null;
  last_scene: string | null;
  results: VocabResult[];
  state: ItemState;
}
interface Attempt {
  transcript: string;
  romanized: string | null;
  consumed: boolean;
}
interface SceneRun {
  scene_id: string;
  turn: number;
  complete: boolean;
  goals_done: string[];
  transcript: Entry[];
  help_uses: number;
  exchange: { posed_item_ids: string[]; help_level: 0 | 1 | 2; line_ids: string[]; intent_hint: string };
  expression: string;
  patches: { region: string; change: string }[];
}
interface Game {
  trust: Record<string, number>;
  clues: string[];
  flags: string[];
  ending_id: string | null;
}
interface Journey {
  journey_id: string;
  token: string;
  locale: string;
  vocab: Record<string, VocabRecord>;
  scene: SceneRun | null;
  done: string[];
  summary: Summary | null;
  attempts: Record<string, Attempt>;
  lines: Record<string, string>;
  seq: number;
  game: Game;
}

interface Hook {
  queue: { transcript: string; romanized?: string | null; requires_confirmation?: boolean; confidence?: number }[];
  actMs: number;
  transcribeMs: number;
  sceneMs: number;
  failNextAct: boolean | number;
}

const KEY = "polytale.mock.journey.v4";
const CONTENT = "/mock-content/";
/** What crosses a real wire is a copy; never hand the client live references to mock state. */
const wire = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const wait = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));
const uid = (p: string) => `${p}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;

function flag(name: string): string | null {
  try {
    return new URLSearchParams(window.location.search).get(name);
  } catch {
    return null;
  }
}

export function createMockApi(): Api {
  let lang: LanguageFile = FALLBACK_LANGUAGE;
  const known = new Map<string, LanguageFile>();
  let order: string[] = ["bar"];
  let story = FALLBACK_STORY;
  const scenes: Record<string, SceneFile> = { bar: FALLBACK_SCENE };
  const art = new Map<string, string | null>();
  const audio = new Map<string, string>();
  let titleArt: string | null = null;
  let synced: Promise<void> | null = null;

  const hook: Hook = { queue: [], actMs: 1300, transcribeMs: 700, sceneMs: 2200, failNextAct: false };
  (window as unknown as { __polytaleMock: Hook }).__polytaleMock = hook;

  async function fetchJson<T>(path: string): Promise<T | null> {
    try {
      const res = await fetch(CONTENT + path, { cache: "no-cache" });
      if (!res.ok || !(res.headers.get("content-type") || "").includes("json")) return null;
      return (await res.json()) as T;
    } catch {
      return null;
    }
  }

  async function probeUrl(url: string): Promise<string | null> {
    if (art.has(url)) return art.get(url) ?? null;
    let ok: string | null = null;
    try {
      const res = await fetch(url, { method: "HEAD", cache: "no-cache" });
      ok = res.ok && (res.headers.get("content-type") || "").startsWith("image/") ? url : null;
    } catch {
      ok = null;
    }
    art.set(url, ok);
    return ok;
  }
  const sceneUrl = (sceneId: string, rel: string) => `${CONTENT}scenes/${sceneId}/${rel}`;

  /** Every language file `content/languages/` actually carries, in a fixed order. */
  async function loadLanguages(): Promise<void> {
    const files = await Promise.all(LOCALES.map((l) => fetchJson<LanguageFile>(`languages/${l}.json`)));
    for (const f of files) if (f?.items && f.locale) known.set(f.locale, f);
    if (!known.size) known.set(FALLBACK_LANGUAGE.locale, FALLBACK_LANGUAGE);
  }

  function useLocale(locale: string | null | undefined): void {
    const f = locale ? known.get(locale) : null;
    lang = f ?? known.get(FALLBACK_LANGUAGE.locale) ?? [...known.values()][0] ?? FALLBACK_LANGUAGE;
  }

  function sync(): Promise<void> {
    synced ??= (async () => {
      await loadLanguages();
      useLocale(flag("lang") ?? memory?.locale ?? FALLBACK_LANGUAGE.locale);
      const j = await fetchJson<StoryFile>("journey.json");
      if (j?.scenes?.length) order = j.scenes;
      if (j?.title && j.premise) story = { ...FALLBACK_STORY, ...j, endings: j.endings?.length ? j.endings : FALLBACK_STORY.endings } as typeof story;
      await Promise.all(
        order.map(async (id) => {
          const s = await fetchJson<SceneFile>(`scenes/${id}/scene.json`);
          if (s?.id) scenes[id] = s;
          const sc = scenes[id];
          if (!sc) return;
          // The art pipeline measures where the character really sits in the painting.
          const layout = await fetchJson<ArtLayout>(`scenes/${id}/art/LAYOUT.json`);
          if (layout?.npc_anchor) sc.npc.anchor = layout.npc_anchor;
        }),
      );
      order = order.filter((id) => scenes[id]);
      if (!order.length) {
        scenes[FALLBACK_SCENE.id] = FALLBACK_SCENE;
        order = [FALLBACK_SCENE.id];
      }
      const probes: Promise<unknown>[] = [probeUrl(`${CONTENT}title.webp`).then((u) => (titleArt = u))];
      for (const id of order) {
        const s = scenes[id];
        probes.push(probeUrl(sceneUrl(id, s.art.background)), probeUrl(sceneUrl(id, s.art.cover)));
      }
      for (const e of story.endings) for (const id of order) probes.push(probeUrl(sceneUrl(id, e.art)));
      await Promise.all(probes);
    })();
    return synced;
  }

  const artUrl = (sceneId: string, rel: string) => art.get(sceneUrl(sceneId, rel)) ?? null;
  // A missing background stays a (404ing) URL on purpose: the client owns that fallback.
  const bgUrl = (sceneId: string, rel: string) => artUrl(sceneId, rel) ?? sceneUrl(sceneId, rel);

  // -- language helpers -----------------------------------------------------

  const noRoman = () => flag("noroman") === "1" || !lang.romanization;
  const cjk = () => /^(zh|ja)/.test(lang.locale);
  const gitem = (id: string): Segment[] => {
    const it = lang.items[id];
    return it ? [{ t: it.text, r: noRoman() ? "" : it.roman }] : [];
  };
  const bare = (segs: Segment[]): Segment[] => segs.map(({ t, r }) => ({ t, r }));
  const item = (id: string) => bare(gitem(id));
  const punct = (p: "." | "?" | "!" | ","): Segment[] => {
    const wide = { ".": "。", "?": "？", "!": "！", ",": "，" } as const;
    return [{ t: cjk() ? wide[p] : p, r: "" }];
  };

  const fold = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().replace(/[\s'’.,!?。？！，]/g, "");
  const targetScript = (s: string) => /[぀-ヿ㐀-鿿가-힯]/.test(s);
  const targetsOf = (sc: SceneFile) => sc.targets?.length ? sc.targets : Object.keys(lang.items);

  /** Lexicon items the learner named, longest first so a word inside a phrase is not double-counted. */
  function mentioned(text: string): string[] {
    let f = fold(text);
    const hits: string[] = [];
    const forms = Object.entries(lang.items)
      .flatMap(([id, it]) => [{ id, form: fold(it.text) }, { id, form: fold(it.roman || "") }])
      .filter((x) => x.form)
      .sort((a, b) => b.form.length - a.form.length);
    for (const { id, form } of forms) {
      if (!f.includes(form)) continue;
      f = f.split(form).join(" ");
      if (!hits.includes(id)) hits.push(id);
    }
    return hits;
  }

  // -- state ----------------------------------------------------------------

  function load(): Journey | null {
    try {
      const raw = localStorage.getItem(KEY);
      return raw ? (JSON.parse(raw) as Journey) : null;
    } catch {
      return null;
    }
  }
  let memory: Journey | null = load();
  function save(j: Journey) {
    memory = j;
    try {
      localStorage.setItem(KEY, JSON.stringify(j));
    } catch {
      /* memory only */
    }
  }
  function need(jid: string, token: string): Journey {
    const j = memory;
    if (!j || j.journey_id !== jid) throw new ApiError(404, "unknown journey");
    if (j.token !== token) throw new ApiError(403, "bad token");
    useLocale(flag("lang") ?? j.locale);
    return j;
  }
  const fresh = (jid: string, token: string, locale: string): Journey => ({
    journey_id: jid, token, locale, vocab: {}, scene: null, done: [], summary: null, attempts: {}, lines: {}, seq: 0,
    game: { trust: {}, clues: [], flags: [], ending_id: null },
  });

  const rec = (j: Journey, id: string): VocabRecord =>
    (j.vocab[id] ??= { appearances: 0, first_scene: null, last_scene: null, results: [], state: "not_encountered" });

  function language(): Language {
    return {
      locale: lang.locale,
      name: lang.name,
      native_name: lang.native_name,
      romanization_label: noRoman() ? null : (lang.romanization?.label ?? null),
      word_spacing: flag("spaced") === "1" ? true : lang.word_spacing,
    };
  }

  const languageOptions = (): LanguageOption[] =>
    LOCALES.filter((l) => known.has(l)).map((l) => {
      const f = known.get(l)!;
      return { locale: f.locale, name: f.name, native_name: f.native_name };
    });

  const storyView = (): Story => ({ title: story.title, tagline: story.tagline, premise: story.premise, art_url: titleArt });
  const allClues = () => order.flatMap((id) => scenes[id].clues ?? []);

  function gameView(j: Journey): GameView {
    const sc = j.scene ? scenes[j.scene.scene_id] : null;
    return {
      trust: sc ? (j.game.trust[sc.id] ?? sc.npc.trust ?? 0) : 0,
      clues: j.game.clues.map((id) => allClues().find((c) => c.id === id)).filter((c): c is ClueDef => !!c).map(({ id, title, text }) => ({ id, title, text })),
    };
  }

  // -- the living scene ------------------------------------------------------
  // Stand-in cutouts: flat SVG data URIs, so the crossfade, the layer geometry and the
  // "text never waits for the picture" path are all exercised without a model call.
  // The real server paints these rectangles with the image-edit model.

  const FACES = ["neutral", "delighted", "laughing", "puzzled", "moved", "roaring", "conspiratorial"];
  const REGION_BOX: Record<string, [number, number, number, number]> = {
    counter: [0.06, 0.64, 0.88, 0.36],
    hands: [0.22, 0.392, 0.56, 0.39],
    room_left: [0, 0, 0.345, 0.72],
    room_right: [0.655, 0, 0.345, 0.72],
  };

  function faceBox(sc: SceneFile): [number, number, number, number] {
    const a = sc.npc.anchor ?? { x: 0.5, y: 0.3 };
    return [a.x - 0.135, a.y - 0.165, 0.27, 0.34];
  }

  function cutout(label: string, tint: string): string {
    const svg =
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" preserveAspectRatio="none">` +
      `<rect width="200" height="200" rx="10" fill="${tint}"/>` +
      `<text x="100" y="188" font-family="sans-serif" font-size="13" fill="#f1eee8" opacity="0.8" text-anchor="middle">${label}</text>` +
      `</svg>`;
    return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
  }

  function frameOf(j: Journey, run: SceneRun): Frame | null {
    const sc = scenes[run.scene_id];
    const layers = run.patches.map((p, i) => {
      const [left, top, width, height] = REGION_BOX[p.region] ?? REGION_BOX.counter;
      return { id: `beat${i}`, url: cutout(p.change, "rgb(159 195 177 / 0.22)"), left, top, width, height };
    });
    if (run.expression !== "neutral") {
      const [left, top, width, height] = faceBox(sc);
      layers.push({ id: `face-${run.expression}`, url: cutout(run.expression, "rgb(241 238 232 / 0.16)"), left, top, width, height });
    }
    if (!layers.length) return null;
    return { key: `${j.journey_id}-${run.turn}-${run.expression}-${run.patches.length}`, expression: run.expression, layers };
  }

  function sceneView(sc: SceneFile): SceneView {
    return {
      id: sc.id,
      name: sc.name,
      tagline: sc.tagline,
      intro: sc.intro,
      background_url: bgUrl(sc.id, sc.art.background),
      cover_url: bgUrl(sc.id, sc.art.cover),
      npc: { name: sc.npc.names?.[lang.locale] ?? sc.npc.name, role: sc.npc.role, anchor: sc.npc.anchor ?? { x: 0.5, y: 0.3 } },
      goals: sc.goals.map(({ id, label }) => ({ id, label })),
      target_count: targetsOf(sc).length,
    };
  }

  function progress(j: Journey): Progress {
    const run = j.scene;
    const sc = run ? scenes[run.scene_id] : null;
    const level = run?.exchange.help_level ?? 0;
    const labels = ["Say it again, slowly", "What do they want?"];
    return {
      goals_done: run?.goals_done ?? [],
      encountered: sc ? targetsOf(sc).filter((t) => (j.vocab[t]?.appearances ?? 0) > 0 || (j.vocab[t]?.results.length ?? 0) > 0).length : 0,
      target_count: sc ? targetsOf(sc).length : 0,
      help_level: level,
      next_help: run && !run.complete && level < 2 ? { level: level + 1, label: labels[level] } : null,
    };
  }

  function sceneList(j: Journey): JourneyScene[] {
    const nextId = order.find((id) => !j.done.includes(id) && j.scene?.scene_id !== id);
    return order.map((id) => {
      const s = scenes[id];
      const status = j.done.includes(id) ? "done" : j.scene?.scene_id === id ? "current" : id === nextId ? "next" : "locked";
      return { id, name: s.name, tagline: s.tagline, cover_url: bgUrl(id, s.art.cover), intro: s.intro, status };
    });
  }

  function endingView(j: Journey): Ending | null {
    const e = story.endings.find((x) => x.id === j.game.ending_id);
    if (!e) return null;
    const states = Object.values(j.vocab).map((v) => v.state);
    return {
      id: e.id, title: e.title, text: e.text,
      art_url: order.map((id) => art.get(sceneUrl(id, e.art))).find((u) => !!u) ?? sceneUrl(order[order.length - 1], e.art),
      stats: { clues: j.game.clues.length, words_mastered: states.filter((s) => s === "mastered").length, words_shaky: states.filter((s) => s === "shaky").length },
    };
  }

  /** Every word of the scene, the ones he has said first, each with that one word's meaning. */
  function silence(key: string, text: string): string {
    const cached = audio.get(key);
    if (cached) return cached;
    const secs = Math.min(3.4, 0.7 + text.length * 0.17);
    const url = URL.createObjectURL(encodeWav(new Float32Array(Math.round(16000 * secs)), 16000));
    audio.set(key, url);
    return url;
  }

  function dictionaryOf(j: Journey): WordEntry[] {
    const run = j.scene;
    if (!run) return [];
    const sc = scenes[run.scene_id];
    const ids = [...(sc.targets ?? []), ...(sc.support_words ?? [])].filter((v, i, a) => a.indexOf(v) === i);
    const spoken: string[] = [];
    for (const e of run.transcript) {
      if (e.kind === "npc") for (const id of e.line.item_ids) if (!spoken.includes(id)) spoken.push(id);
    }
    const order = [...spoken.filter((i) => ids.includes(i)), ...ids.filter((i) => !spoken.includes(i))];
    const roman = !noRoman();
    return order.flatMap((id) => {
      const it = lang.items[id];
      if (!it) return [];
      return [{ item_id: id, text: it.text, roman: roman ? it.roman : "", gloss: it.gloss, heard: spoken.includes(id) }];
    });
  }

  /** The words he has actually said, as he said them (free speech, so some are unlisted). */
  function heardOf(j: Journey): HeardWord[] {
    const run = j.scene;
    if (!run) return [];
    const roman = !noRoman();
    const out: HeardWord[] = [];
    const seen = new Set<string>();
    for (const e of run.transcript) {
      if (e.kind !== "npc") continue;
      for (const seg of e.line.segments) {
        if (!/\p{L}/u.test(seg.t) || seen.has(seg.t)) continue;
        seen.add(seg.t);
        const entry = Object.values(lang.items).find((i) => i.text === seg.t);
        out.push({ text: seg.t, roman: roman ? seg.r || entry?.roman || "" : "", gloss: entry?.gloss ?? "" });
      }
    }
    return out;
  }

  function publicState(j: Journey): PublicState {
    const run = j.scene;
    return {
      journey_id: j.journey_id,
      language: language(),
      scene: run ? sceneView(scenes[run.scene_id]) : null,
      started: !!run,
      turn: run?.turn ?? 0,
      transcript: run?.transcript ?? [],
      progress: progress(j),
      scene_complete: !!run?.complete,
      summary: j.summary,
      scenes: sceneList(j),
      story: storyView(),
      game: gameView(j),
      ending: endingView(j),
      dictionary: dictionaryOf(j),
      heard: heardOf(j),
      frame: run ? frameOf(j, run) : null,
    };
  }

  // -- the scripted character and narrator -----------------------------------

  interface Draft {
    segs: Segment[];
    items: string[];
  }
  interface Reply {
    narration: string;
    lines: Draft[];
    hint: string;
  }
  interface Input {
    mode: "speech" | "text";
    text: string;
  }

  const say = (segs: Segment[], items: string[] = []): Draft => ({ segs, items });
  /** A line built from lexicon items; ids the language file does not carry drop out. */
  const line = (ids: string[], end: "." | "?" | "!" = "."): Draft => {
    const have = ids.filter((id) => lang.items[id]);
    if (!have.length) return say([]);
    return say([...have.flatMap((id) => item(id)), ...bare(punct(end))], have);
  };

  function opening(sc: SceneFile): Reply {
    // Narration is prose the player reads, so it uses the readable name, exactly as
    // the real narrator is instructed to. Spoken bylines keep the native script.
    const name = sc.npc.names_roman?.[lang.locale] ?? sc.npc.name;
    return {
      narration: `The room is three deep at the counter and everyone is shouting at the screen. ${name} spots you, a stranger with no idea what is going on, and grins like you have made his night.`,
      lines: [line(["hello"], "!"), line(["match", "tonight"], "!")],
      hint: "He is welcoming you in and talking about the match.",
    };
  }

  function respond(j: Journey, sc: SceneFile, input: Input): { reply: Reply; understood: string[] } {
    const g = j.game;
    const said = mentioned(input.text);
    const has = (...ids: string[]) => ids.some((id) => said.includes(id));
    // Narration is prose the player reads, so it uses the readable name, exactly as
    // the real narrator is instructed to. Spoken bylines keep the native script.
    const name = sc.npc.names_roman?.[lang.locale] ?? sc.npc.name;
    const understood = new Set<string>(said);
    const trust = () => g.trust[sc.id] ?? sc.npc.trust ?? 0;
    const bump = (d: number) => (g.trust[sc.id] = Math.max(-2, Math.min(3, trust() + d)));
    const authored = (f: string) => (sc.flags ? sc.flags.some((x) => x.id === f) : true);
    const flagOn = (f: string) => g.flags.includes(`${sc.id}:${f}`);
    const setFlag = (f: string) => authored(f) && !flagOn(f) && g.flags.push(`${sc.id}:${f}`);
    const ok = (reply: Reply, ids: string[] = [...understood]) => ({ reply, understood: ids });

    // English (or noise) never lands: the character has none.
    const english = !said.length && !targetScript(input.text);

    // Asking after Mei: the story's main move.
    if (has("friend", "where", "seen", "photo", "she")) {
      if (!flagOn("photo_shown")) {
        setFlag("photo_shown");
        return ok({
          narration: `You hold up the photo. Three of them lean in at once and the shouting changes key: they know her, they all know her, and they want to know who you are.`,
          lines: [line(["she"], "!"), line(["friend"], "?")],
          hint: "They recognise her. They would like to know what you are to her.",
        });
      }
      if (trust() >= 2 || g.clues.includes("gate")) {
        return ok({
          narration: `${name} points at the door with his whole arm, then holds up two fingers and mimes a gate. The fan zone. She is already there, holding your spot.`,
          lines: [line(["she", "fan_zone"], "!"), line(["gate"], "!")],
          hint: "He is telling you where she is: the fan zone, gate two.",
        });
      }
      return ok({
        narration: `${name} taps the photo, then taps his own scarf. They will tell you, but not to somebody standing there like a tourist. Be one of them first.`,
        lines: [line(["go_team"], "!"), line(["scarf"], "?")],
        hint: "He wants you to join in before he tells you anything else.",
      });
    }

    // Joining in: the way to earn the answer.
    if (has("go_team")) {
      setFlag("chanted");
      bump(1);
      return ok({
        narration: `You try the chant. You get maybe half of it right, and the whole end of the bar joins in anyway, delighted.`,
        lines: [line(["go_team"], "!"), line(["awesome"], "!")],
        hint: "They are chanting it back at you.",
      });
    }
    if (has("cheers", "goal", "awesome")) {
      setFlag("cheered");
      bump(1);
      return ok({
        narration: `The screen replays the goal for the tenth time and you roar with them. ${name} bangs the counter and puts an arm round your shoulder.`,
        lines: [line(["cheers"], "!"), line(["goal"], "!")],
        hint: "You cheered with them, and it landed.",
      });
    }
    if (has("scarf")) {
      setFlag("scarf_worn");
      bump(1);
      return ok({
        narration: `Somebody drops a spare scarf over your head. It smells of nine years of finals. You are, as of now, one of them.`,
        lines: [line(["scarf"], "!"), line(["awesome"], "!")],
        hint: "You are wearing the colours now.",
      });
    }
    if (has("thanks")) return ok({ narration: `Manners travel. ${name} waves it off and goes back to the screen.`, lines: [line(["good"], "!")], hint: "Just being polite back." });
    if (has("hello")) return ok({ narration: `${name} answers the greeting and immediately asks you something about the match, as if you had been here all evening.`, lines: [line(["hello"], "!"), line(["match"], "?")], hint: "He greeted you back and is talking about the match." });

    return ok(
      {
        narration: english
          ? `That was English. ${name} has none of it. He shrugs happily, points at the screen, and waits for you to try again in words he knows.`
          : `${name} tips his head. That did not quite land. He points at the screen and waits.`,
        lines: [line(["sorry"], "?"), line(["match"], "?")],
        hint: "He did not follow. Try a word you have heard here, or look one up.",
      },
      [],
    );
  }

  // -- ledgers ---------------------------------------------------------------

  function record(j: Journey, run: SceneRun, itemId: string, produced: boolean) {
    const sc = scenes[run.scene_id];
    if (!targetsOf(sc).includes(itemId)) return;
    const r = rec(j, itemId);
    const ex = run.exchange;
    const helped = ex.help_level === 1;
    const outcome: Outcome = ex.help_level === 2 ? "with_hint" : helped ? "with_help" : "first_try";
    const recall = outcome === "first_try" && !!r.first_scene && r.first_scene !== run.scene_id;
    r.first_scene ??= run.scene_id;
    r.last_scene = run.scene_id;
    r.results.push({ scene_id: run.scene_id, outcome, produced, recall });
    r.state = outcome === "first_try" ? "mastered" : "shaky";
  }

  function holds(j: Journey, run: SceneRun, w: When): boolean {
    if (w.clue && !j.game.clues.includes(w.clue)) return false;
    if (w.flag && !j.game.flags.includes(`${run.scene_id}:${w.flag}`)) return false;
    return true;
  }

  function toLine(j: Journey, run: SceneRun, speaker: string, d: Draft, spaced: boolean): Line {
    const line_id = `ln_${run.scene_id}_${++j.seq}`;
    let text = "";
    for (const s of d.segs) text += spaced && s.r && text ? ` ${s.t}` : s.t;
    j.lines[line_id] = text;
    return {
      line_id, speaker_name: speaker, segments: d.segs, text,
      romanization: d.segs.map((s) => s.r).filter(Boolean).join(" "),
      item_ids: d.items, audio_url: `/api/journeys/${j.journey_id}/lines/${line_id}/audio`,
    };
  }

  function commit(j: Journey, run: SceneRun, reply: Reply, learner: Entry | null): TurnResult {
    const t0 = performance.now();
    const sc = scenes[run.scene_id];
    const npcName = sc.npc.names?.[lang.locale] ?? sc.npc.name;
    const spaced = language().word_spacing;
    const lines: Line[] = reply.lines.filter((d) => d.segs.length).slice(0, 3).map((d) => toLine(j, run, npcName, d, spaced));
    for (const l of lines) {
      for (const id of l.item_ids) {
        const r = rec(j, id);
        r.appearances += 1;
        r.first_scene ??= run.scene_id;
        r.last_scene = run.scene_id;
      }
    }

    const events: Entry[] = [];
    // Clues reveal only when an authored condition holds (the GM cannot leak early).
    const trust = j.game.trust[sc.id] ?? sc.npc.trust ?? 0;
    const met = (w: Reveal) => (w.trust_at_least ?? -9) <= trust && (w.flags ?? []).every((f) => j.game.flags.includes(`${sc.id}:${f}`));
    for (const c of sc.clues ?? []) {
      if (j.game.clues.includes(c.id)) continue;
      const ways = c.reveal_when == null ? [{}] : Array.isArray(c.reveal_when) ? c.reveal_when : [c.reveal_when];
      if (!ways.some(met)) continue;
      j.game.clues.push(c.id);
      events.push({ kind: "clue", turn: run.turn, clue: { id: c.id, title: c.title, text: c.text } });
      break; // one clue a turn reads better
    }
    for (const goal of sc.goals) {
      if (run.goals_done.includes(goal.id) || !holds(j, run, goal.when)) continue;
      run.goals_done.push(goal.id);
      events.push({ kind: "scene", turn: run.turn, event: "goal_done", goal_id: goal.id });
    }

    run.exchange = {
      posed_item_ids: [...new Set(lines.flatMap((l) => l.item_ids))],
      help_level: 0,
      line_ids: lines.map((l) => l.line_id),
      intent_hint: reply.hint,
    };
    if (learner) run.transcript.push(learner);
    run.transcript.push(...events);
    run.transcript.push({ kind: "narration", turn: run.turn, text: reply.narration });
    for (const l of lines) run.transcript.push({ kind: "npc", turn: run.turn, line: l });

    // The scripted stand-in for the model's own choice: a face every turn, a beat now and then.
    run.expression = FACES[(run.turn + events.length) % FACES.length];
    if (events.some((e) => e.kind === "clue") && run.patches.length < 8) {
      run.patches.push({ region: run.patches.length % 2 ? "room_right" : "counter", change: "something changes" });
    }

    if (run.goals_done.length === sc.goals.length && sc.goals.length > 0 && !run.complete) finishRun(j, run);
    save(j);
    return {
      turn: run.turn, lines, narration: reply.narration, events, progress: progress(j),
      dictionary: dictionaryOf(j),
      scene_complete: run.complete, summary: run.complete ? j.summary : null, game: gameView(j), ending: endingView(j),
      frame: frameOf(j, run),
      latency_ms: Math.round(performance.now() - t0),
    };
  }

  function finishRun(j: Journey, run: SceneRun) {
    run.complete = true;
    if (!j.done.includes(run.scene_id)) j.done.push(run.scene_id);
    if (order.indexOf(run.scene_id) === order.length - 1) {
      const fits = (w: NonNullable<EndingDef["when"]>) =>
        (w.clues ?? []).every((c) => j.game.clues.includes(c)) && (w.flags ?? []).every((f) => j.game.flags.some((x) => x.endsWith(`:${f}`)));
      const e = story.endings.find((x) => fits(x.when ?? {})) ?? story.endings[story.endings.length - 1];
      j.game.ending_id = e.id;
    }
    j.summary = buildSummary(j, run);
  }

  function buildSummary(j: Journey, run: SceneRun): Summary {
    const sc = scenes[run.scene_id];
    const items = targetsOf(sc)
      .filter((id) => lang.items[id])
      .map((id) => {
        const r = j.vocab[id];
        const here = (r?.results ?? []).filter((x) => x.scene_id === run.scene_id);
        return {
          item_id: id, text: lang.items[id].text, roman: noRoman() ? "" : lang.items[id].roman, gloss: lang.items[id].gloss,
          state: r?.state ?? ("not_encountered" as ItemState), outcomes: here.map((x) => x.outcome as string),
          produced: here.some((x) => x.produced), recall: here.some((x) => x.recall), heard: (r?.appearances ?? 0) > 0,
          audio_url: `/api/journeys/${j.journey_id}/items/${id}/audio`,
        };
      });
    const counts = { mastered: 0, shaky: 0, heard: 0, not_encountered: 0 };
    for (const it of items) {
      if (it.state === "not_encountered" && it.heard) counts.heard += 1;
      else counts[it.state] += 1;
    }
    const spoken = items.filter((i) => i.produced);
    const lines: string[] = [];
    if (spoken.length) lines.push(`You said ${spoken.length} of these yourself, by voice or keyboard.`);
    lines.push(run.help_uses ? `You asked for help ${run.help_uses} ${run.help_uses === 1 ? "time" : "times"}.` : "You never asked for help.");
    const nextId = j.game.ending_id ? undefined : order[order.indexOf(run.scene_id) + 1];
    const next = nextId ? scenes[nextId] : null;
    return { scene_id: sc.id, scene_name: sc.name, items, counts, recalled: items.filter((i) => i.recall).map((i) => i.item_id), lines, next_scene: next ? { id: next.id, name: next.name, tagline: next.tagline } : null };
  }

  async function turn(j: Journey, input: Input & { romanized: string | null; attempt_id: string }): Promise<TurnResult> {
    const run = j.scene;
    if (!run) throw new ApiError(409, "no scene in progress");
    if (run.complete) throw new ApiError(409, "scene complete");
    await wait(hook.actMs);
    if (hook.failNextAct) {
      const status = hook.failNextAct === true ? 502 : hook.failNextAct;
      hook.failNextAct = false;
      throw new ApiError(status, status === 402 ? "The AI account behind this demo is out of credits. Nothing was lost; try again later." : "model failure");
    }
    const sc = scenes[run.scene_id];
    run.turn += 1;
    const { reply, understood } = respond(j, sc, input);
    for (const id of understood) record(j, run, id, true);
    const learner: Entry = { kind: "learner", turn: run.turn, attempt_id: input.attempt_id, input_mode: input.mode, transcript: input.text, romanized: input.romanized };
    return wire(commit(j, run, reply, learner));
  }


  // -- the contract ----------------------------------------------------------

  return {
    mock: true,
    health: async () => ({ ok: true, speech_provider: "mock", tts_provider: "mock", language: lang.locale }),
    catalog: async () => {
      await sync();
      return wire({
        language: language(),
        languages: languageOptions(),
        scenes: order.map((id) => ({ id, name: scenes[id].name, tagline: scenes[id].tagline, cover_url: bgUrl(id, scenes[id].art.cover), intro: scenes[id].intro })),
        story: storyView(),
      });
    },
    createJourney: async (body) => {
      await sync();
      await wait(120);
      const locale = body.language ?? lang.locale;
      if (!known.has(locale)) throw new ApiError(400, "unknown language");
      useLocale(locale);
      const j = fresh(uid("jrn"), uid("tok"), locale);
      save(j);
      return wire({ journey_id: j.journey_id, token: j.token, state: publicState(j) });
    },
    getState: async (jid, token) => {
      await sync();
      return wire(publicState(need(jid, token)));
    },
    enterScene: async (jid, token, body) => {
      await sync();
      const j = need(jid, token);
      if (j.scene && !j.scene.complete && !body.restart) throw new ApiError(409, "scene in progress");
      const id = body.scene_id ?? order.find((s) => !j.done.includes(s)) ?? order[0];
      const sc = scenes[id];
      if (!sc) throw new ApiError(404, "unknown scene");
      await wait(hook.sceneMs);
      const run: SceneRun = {
        scene_id: id, turn: 0, complete: false, goals_done: [], transcript: [], help_uses: 0,
        exchange: { posed_item_ids: [], help_level: 0, line_ids: [], intent_hint: "" },
        expression: "neutral", patches: [],
      };
      if (body.restart) {
        j.game.flags = j.game.flags.filter((f) => !f.startsWith(`${id}:`));
        j.game.clues = j.game.clues.filter((c) => !(sc.clues ?? []).some((x) => x.id === c));
        delete j.game.trust[id];
      }
      j.scene = run;
      j.summary = null;
      return wire(commit(j, run, opening(sc), null));
    },
    transcribe: async (jid, token) => {
      const j = need(jid, token);
      await wait(hook.transcribeMs);
      const canned = lang.items.hello;
      const s = hook.queue.shift() ?? { transcript: canned?.text ?? "", romanized: canned?.roman ?? null };
      const attempt_id = uid("att");
      const romanized = noRoman() ? null : (s.romanized ?? null);
      if (s.transcript) j.attempts[attempt_id] = { transcript: s.transcript, romanized, consumed: false };
      save(j);
      const tr: Transcription = {
        attempt_id, transcript: s.transcript, romanized,
        detected_languages: s.transcript ? [lang.locale] : [],
        confidence: s.transcript ? (s.confidence ?? 0.88) : null,
        requires_confirmation: !!s.requires_confirmation, provider: "mock",
      };
      return tr;
    },
    act: async (jid, token, body) => {
      const j = need(jid, token);
      if ("attempt_id" in body) {
        const a = j.attempts[body.attempt_id];
        if (!a) throw new ApiError(404, "unknown attempt");
        if (a.consumed) throw new ApiError(409, "attempt already consumed");
        const r = await turn(j, { mode: "speech", text: a.transcript, romanized: a.romanized, attempt_id: body.attempt_id });
        a.consumed = true;
        save(j);
        return r;
      }
      return turn(j, { mode: "text", text: body.text, romanized: null, attempt_id: uid("att") });
    },
    help: async (jid, token) => {
      const j = need(jid, token);
      const run = j.scene;
      if (!run || run.complete) throw new ApiError(409, "no scene in progress");
      await wait(200);
      const level = Math.min(2, run.exchange.help_level + 1) as 1 | 2;
      run.exchange.help_level = level;
      run.help_uses += 1;
      save(j);
      const help: Help =
        level === 1
          ? { level, kind: "again", line_ids: run.exchange.line_ids, hint: null }
          : { level, kind: "hint", line_ids: [], hint: run.exchange.intent_hint };
      return wire({ help, progress: progress(j) });
    },
    finish: async (jid, token) => {
      const j = need(jid, token);
      if (!j.scene) throw new ApiError(409, "no scene in progress");
      await wait(250);
      if (!j.scene.complete) finishRun(j, j.scene);
      save(j);
      return wire(j.summary!);
    },
    reset: async (jid, token) => {
      const old = need(jid, token);
      const j = fresh(jid, token, old.locale);
      save(j);
      return wire(publicState(j));
    },
    frameSrc: (_jid, _token, _layerId, url) => url ?? "",
    lineAudio: async (jid, token, lineId) => silence(lineId, need(jid, token).lines[lineId] ?? ""),
    itemAudio: async (jid, token, itemId) => {
      const j = need(jid, token);
      if (j.scene && !j.scene.complete) throw new ApiError(409, "only on the summary");
      return silence(`item:${itemId}`, lang.items[itemId]?.text ?? "");
    },
  };
}
