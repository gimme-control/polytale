// In-browser mock of the Polytale v3 REST contract (SPEC.md), enabled with `?mock=1`.
//
// A scripted playthrough of "The Last Train": bar -> night market -> ending, with the
// whole game layer (wallet, clock, trust, clues, verbs on objects, haggling, narration
// in two difficulties, the phrasebook) plus the v2 learning ledger underneath
// (help level / highlight / phrasebook -> outcome, first-try recall across scenes).
// State persists, so a refresh restores. Real `content/` JSON and art are used for
// what they define when the Vite dev server can serve them (`/mock-content/...`); the
// story layer below fills in whatever the content files do not carry yet.
//
// This is the ONLY file in web/src allowed to contain target-language text. It is a
// test double, not product logic: the real character and narrator are the model.
//
// Test hooks: `window.__polytaleMock` = { queue, actMs, transcribeMs, sceneMs, phraseMs,
// failNextAct, failNextPhrase, skipMinutes(n) }.
// Query flags: `lang=<locale>`, `noroman=1`, `spaced=1`.

import type { Api } from "./api";
import { ApiError } from "./api";
import type {
  Clue,
  Difficulty,
  Ending,
  Entry,
  GameView,
  Help,
  ItemState,
  JourneyScene,
  Language,
  Line,
  ObjectAction,
  Outcome,
  Persona,
  Phrase,
  PhraseSegment,
  Position,
  Progress,
  PublicState,
  SceneView,
  Segment,
  Story,
  Summary,
  Transcription,
  TurnResult,
} from "./types";
import { encodeWav } from "./wav";
import { placeholderCutout } from "./mockArt";

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
interface SceneObjectDef {
  id: string;
  item_id: string;
  art: string;
  zone: string;
  price?: number;
  price_floor?: number;
  actions?: string[];
  positions: Record<string, Position>;
}
interface When {
  in_zone?: Record<string, string>;
  any_in_zone?: { zone: string; objects: string[] };
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
  paid_at_least?: number;
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
  art: { background: string; cover: string; moods?: Record<string, string> };
  npc: { id: string; name: string; names?: Record<string, string>; role: string; anchor: { x: number; y: number }; trust?: number };
  objects: SceneObjectDef[];
  targets: string[];
  goals: GoalDef[];
  clues?: ClueDef[];
  flags?: { id: string }[];
}
interface ArtLayout {
  npc_anchor?: { x: number; y: number };
  objects?: Record<string, Record<string, Position | null>>;
}
interface EndingDef {
  id: string;
  title: string;
  text: string;
  art: string;
  when?: { clues?: string[]; flags?: string[]; clock_left?: boolean; minutes_left_at_least?: number };
}
interface StoryFile {
  title?: string;
  tagline?: string;
  premise?: string;
  wallet?: number;
  clock?: { label: string; start: string; end: string; minutes_per_turn: number };
  scenes: string[];
  endings?: EndingDef[];
}

// ---------------------------------------------------------------------------
// Fallback content

const FALLBACK_LANGUAGE: LanguageFile = {
  locale: "zh-CN",
  name: "Mandarin Chinese",
  native_name: "中文",
  romanization: { system: "pinyin", label: "Pinyin" },
  word_spacing: false,
  items: {
    hello: { text: "你好", roman: "nǐ hǎo", gloss: "hello", kind: "phrase" },
    thanks: { text: "谢谢", roman: "xièxie", gloss: "thanks", kind: "phrase" },
    want: { text: "我要", roman: "wǒ yào", gloss: "I want … / I'll have …", kind: "phrase" },
    this: { text: "这个", roman: "zhège", gloss: "this one", kind: "phrase" },
    how_much: { text: "多少钱", roman: "duōshao qián", gloss: "how much (is it)?", kind: "phrase" },
    money: { text: "钱", roman: "qián", gloss: "money", kind: "noun" },
    menu: { text: "菜单", roman: "càidān", gloss: "menu", kind: "noun" },
    beer: { text: "啤酒", roman: "píjiǔ", gloss: "beer", kind: "noun" },
    water: { text: "水", roman: "shuǐ", gloss: "water", kind: "noun" },
    tea: { text: "茶", roman: "chá", gloss: "tea", kind: "noun" },
    noodles: { text: "面条", roman: "miàntiáo", gloss: "noodles", kind: "noun" },
    dumplings: { text: "饺子", roman: "jiǎozi", gloss: "dumplings", kind: "noun" },
    spicy: { text: "辣", roman: "là", gloss: "spicy", kind: "adjective" },
  },
};

const FALLBACK_PERSONAS: Persona[] = [
  { id: "warm", label: "Warm", blurb: "Patient, repeats gladly" },
  { id: "brisk", label: "Brisk", blurb: "Busy, clipped, low patience" },
  { id: "unhinged", label: "Unhinged", blurb: "Theatrical, absurd, still kind" },
];

const FALLBACK_SCENES: Record<string, SceneFile> = {
  bar: {
    id: "bar",
    name: "The Corner Bar",
    tagline: "Someone here has seen her.",
    intro: "The name on the back of the photo matches the sign over the door. It's late, your phone is dead, and the man behind the counter is already watching you.",
    art: { background: "art/bg.webp", cover: "art/cover.webp", moods: { neutral: "art/bg.webp", pleased: "art/bg_pleased.webp", puzzled: "art/bg_puzzled.webp" } },
    npc: { id: "bartender", name: "Chen", names: { "zh-CN": "老陈" }, role: "bartender", anchor: { x: 0.5, y: 0.262 } },
    objects: [
      { id: "beer", item_id: "beer", art: "art/obj_beer.png", zone: "display", price: 20,
        positions: { display: { x: 0.175, y: 0.552, h: 0.16 }, counter: { x: 0.385, y: 0.885, h: 0.31 } } },
      { id: "water", item_id: "water", art: "art/obj_water.png", zone: "display", price: 5,
        positions: { display: { x: 0.235, y: 0.552, h: 0.106 }, counter: { x: 0.48, y: 0.895, h: 0.205 } } },
      { id: "tea", item_id: "tea", art: "art/obj_tea.png", zone: "display", price: 15,
        positions: { display: { x: 0.315, y: 0.555, h: 0.083 }, counter: { x: 0.59, y: 0.89, h: 0.161 } } },
      { id: "menu", item_id: "menu", art: "art/obj_menu.png", zone: "display",
        positions: { display: { x: 0.7, y: 0.555, h: 0.162 }, counter: { x: 0.15, y: 0.9, h: 0.324 } } },
      { id: "money", item_id: "money", art: "art/obj_money.png", zone: "inventory",
        positions: { counter: { x: 0.83, y: 0.9, h: 0.102 }, npc: { x: 0.56, y: 0.58, h: 0.09 } } },
    ],
    targets: ["hello", "beer", "water", "tea", "want", "this", "how_much", "money", "thanks", "menu"],
    goals: [],
  },
  market: {
    id: "market",
    name: "Night Market",
    tagline: "The stall with the red lanterns.",
    intro: "Smoke, steam, a hundred voices. One stall has a queue and a cook who misses nothing. If Mei came through here, this woman saw her.",
    art: { background: "art/bg.webp", cover: "art/cover.webp", moods: { neutral: "art/bg.webp", pleased: "art/bg_pleased.webp", puzzled: "art/bg_puzzled.webp" } },
    npc: { id: "vendor", name: "Lin", names: { "zh-CN": "林姐" }, role: "stall cook", anchor: { x: 0.617, y: 0.37 } },
    objects: [
      { id: "noodles", item_id: "noodles", art: "art/obj_noodles.png", zone: "display", price: 15,
        positions: { display: { x: 0.315, y: 0.603, h: 0.112 }, counter: { x: 0.36, y: 0.815, h: 0.216 } } },
      { id: "dumplings", item_id: "dumplings", art: "art/obj_dumplings.png", zone: "display", price: 12,
        positions: { display: { x: 0.415, y: 0.605, h: 0.087 }, counter: { x: 0.585, y: 0.93, h: 0.186 } } },
      { id: "beer", item_id: "beer", art: "art/obj_beer.png", zone: "display", price: 10,
        positions: { display: { x: 0.755, y: 0.662, h: 0.15 }, counter: { x: 0.8, y: 0.94, h: 0.33 } } },
      { id: "water", item_id: "water", art: "art/obj_water.png", zone: "display", price: 3,
        positions: { display: { x: 0.797, y: 0.664, h: 0.099 }, counter: { x: 0.885, y: 0.95, h: 0.224 } } },
      { id: "money", item_id: "money", art: "art/obj_money.png", zone: "inventory",
        positions: { npc: { x: 0.6, y: 0.62, h: 0.09 } } },
    ],
    targets: ["hello", "want", "this", "how_much", "money", "thanks", "beer", "water", "noodles", "dumplings", "spicy"],
    goals: [],
  },
};

// The story layer. Used for whatever journey.json / scene.json do not define yet.
const STORY: Required<Pick<StoryFile, "title" | "tagline" | "premise" | "wallet" | "clock" | "endings">> = {
  title: "The Last Train",
  tagline: "Find Mei before 23:55.",
  premise:
    "You land in a city you can't read, at night, with a dead phone. Your friend Mei was meant to meet you. All you have is a photo of her and the name of a bar. Nobody here speaks English.",
  wallet: 60,
  clock: { label: "Last train", start: "22:40", end: "23:55", minutes_per_turn: 3 },
  endings: [
    { id: "reunited", title: "Time to Spare", text: "Platform 2. She is on a bench under the departures board, shoes off, losing an argument with a vending machine. She looks up. \"You're late,\" says Mei. The train, for once, is not.", art: "art/ending_reunited.webp", when: { clues: ["platform"], minutes_left_at_least: 15 } },
    { id: "seconds", title: "By Seconds", text: "You take the station stairs three at a time. Platform 2, doors beeping, and there, red-eyed and furious and laughing, is Mei, holding them open with her whole body.", art: "art/ending_reunited.webp", when: { clues: ["platform"], clock_left: true } },
    { id: "late", title: "The Long Night", text: "The last train leaves without you, and you never quite worked out where she went. The night is long, the city is loud, and you now know how to order in it.", art: "art/ending_late.webp" },
  ],
};

interface StoryScene {
  trust: number;
  goals: GoalDef[];
  clues: ClueDef[];
  actions: Record<string, string[]>;
  floors: Record<string, number>;
}
const STORY_SCENES: Record<string, StoryScene> = {
  bar: {
    trust: 0,
    goals: [
      { id: "ask", label: "Show someone Mei's photo", when: { flag: "photo_shown" } },
      { id: "trail", label: "Find out where Mei went", when: { clue: "market" } },
    ],
    clues: [
      { id: "regular", title: "He knows her", text: "The bartender recognised Mei's photo at once. She is a regular here. He is still deciding about you.", reveal_when: [{ flags: ["photo_shown"] }] },
      { id: "waited", title: "She waited for you", text: "Mei sat at this counter for two hours tonight, watching the door. Then she left.", reveal_when: [{ flags: ["photo_shown"], trust_at_least: 1 }, { flags: ["tab_paid"] }] },
      { id: "market", title: "The night market", text: "Mei went to eat at Lin's stall in the night market. It is what she does when she is stood up.", reveal_when: [{ flags: ["photo_shown", "tab_paid"] }, { flags: ["photo_shown"], trust_at_least: 2 }] },
    ],
    actions: { beer: ["point", "drink"], water: ["point", "drink"], tea: ["point", "drink"], menu: ["point", "take"], money: ["pay"], photo: ["show", "give"] },
    floors: {},
  },
  market: {
    trust: 0,
    goals: [
      { id: "seen", label: "Find someone who has seen Mei", when: { clue: "scarf" } },
      { id: "find", label: "Find out where Mei is now", when: { clue: "platform" } },
    ],
    clues: [
      { id: "scarf", title: "She ate here", text: "Mei sat at this stall tonight. One bowl, extra chili, left in a hurry.", reveal_when: [{ flags: ["photo_shown_lin"] }] },
      { id: "platform", title: "Platform 2", text: "Mei is taking the last train home. The station, platform 2. Run.", reveal_when: [{ flags: ["photo_shown_lin"], trust_at_least: 2 }, { flags: ["photo_shown_lin"], paid_at_least: 10, trust_at_least: 1 }] },
    ],
    actions: { noodles: ["point", "eat"], dumplings: ["point", "eat"], chili: ["point", "take", "eat"], beer: ["point", "drink"], water: ["point", "drink"], money: ["pay"], photo: ["show", "give"] },
    floors: { noodles: 10, dumplings: 8 },
  },
};
const PHOTO: SceneObjectDef = { id: "photo", item_id: "", art: "art/obj_photo.png", zone: "inventory", positions: {} };
const ACTION_LABEL: Record<string, string> = { point: "Point", take: "Take", give: "Give", show: "Show", drink: "Drink", eat: "Eat", pay: "Pay" };

// Words the scripted character uses that are not lexicon items. Other locales simply
// get shorter lines built from lexicon items and punctuation.
const GLUE: Record<string, Record<string, PhraseSegment[]>> = {
  "zh-CN": {
    what: [{ t: "要", r: "yào", g: "want" }, { t: "什么", r: "shénme", g: "what" }],
    ok: [{ t: "好", r: "hǎo", g: "good" }],
    huh: [{ t: "听不懂", r: "tīng bu dǒng", g: "don't understand" }],
    bye: [{ t: "慢走", r: "màn zǒu", g: "take care" }],
    first: [{ t: "先", r: "xiān", g: "first" }, { t: "付钱", r: "fù qián", g: "pay" }],
    her: [{ t: "她", r: "tā", g: "she" }],
    know: [{ t: "认识", r: "rènshi", g: "know (a person)" }],
    owes: [{ t: "她", r: "tā", g: "she" }, { t: "欠", r: "qiàn", g: "owes" }],
    went: [{ t: "她", r: "tā", g: "she" }, { t: "去", r: "qù", g: "went to" }, { t: "夜市", r: "yèshì", g: "night market" }],
    stall: [{ t: "面摊", r: "miàntān", g: "noodle stall" }],
    came: [{ t: "她", r: "tā", g: "she" }, { t: "来过", r: "láiguo", g: "came by" }],
    station: [{ t: "火车站", r: "huǒchēzhàn", g: "train station" }],
    platform: [{ t: "二", r: "èr", g: "two" }, { t: "站台", r: "zhàntái", g: "platform" }],
    hurry: [{ t: "快", r: "kuài", g: "quick" }],
    too_much: [{ t: "太贵了", r: "tài guì le", g: "too expensive" }],
    fine: [{ t: "好吧", r: "hǎo ba", g: "fine, then" }],
    no: [{ t: "不行", r: "bù xíng", g: "no way" }],
    where: [{ t: "在哪儿", r: "zài nǎr", g: "is where" }],
    seen: [{ t: "见过", r: "jiànguo", g: "have seen" }],
    you: [{ t: "你", r: "nǐ", g: "you" }],
    q: [{ t: "吗", r: "ma", g: "(question)" }],
    cheaper: [{ t: "便宜", r: "piányi", g: "cheaper" }, { t: "一点", r: "yìdiǎn", g: "a little" }],
  },
};
const ZH_DIGITS: [string, string][] = [["零", "líng"], ["一", "yī"], ["二", "èr"], ["三", "sān"], ["四", "sì"], ["五", "wǔ"], ["六", "liù"], ["七", "qī"], ["八", "bā"], ["九", "jiǔ"]];

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
  zones: Record<string, string>;
  goals_done: string[];
  mood: string;
  transcript: Entry[];
  help_uses: number;
  paid: number;
  exchange: { posed_item_ids: string[]; highlighted_item_ids: string[]; phrasebook_item_ids: string[]; help_level: 0 | 1 | 2; line_ids: string[]; intent_hint: string };
}
interface Game {
  wallet: number;
  minutes_used: number;
  difficulty: Difficulty;
  trust: Record<string, number>;
  clues: string[];
  flags: string[];
  prices: Record<string, number>;
  spent: number;
  phrasebook: Phrase[];
  ending_id: string | null;
}
interface Journey {
  journey_id: string;
  token: string;
  persona_id: string;
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
  phraseMs: number;
  failNextAct: boolean | number;
  failNextPhrase: boolean;
  skipMinutes(n: number): void;
}

const KEY = "polytale.mock.journey.v3";
const CONTENT = "/mock-content/";
/** What crosses a real wire is a copy; never hand the client live references to mock state. */
const wire = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const wait = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));
const uid = (p: string) => `${p}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
const minutes = (hhmm: string) => parseInt(hhmm.slice(0, 2), 10) * 60 + parseInt(hhmm.slice(3), 10);
const clockText = (m: number) => `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

function flag(name: string): string | null {
  try {
    return new URLSearchParams(window.location.search).get(name);
  } catch {
    return null;
  }
}

export function createMockApi(): Api {
  let lang: LanguageFile = FALLBACK_LANGUAGE;
  let personas: Persona[] = FALLBACK_PERSONAS;
  let order: string[] = ["bar", "market"];
  let story = STORY;
  const scenes: Record<string, SceneFile> = { ...FALLBACK_SCENES };
  const art = new Map<string, string | null>();
  const audio = new Map<string, string>();
  let titleArt: string | null = null;
  let synced: Promise<void> | null = null;

  const hook: Hook = {
    queue: [], actMs: 1300, transcribeMs: 700, sceneMs: 2200, phraseMs: 900, failNextAct: false, failNextPhrase: false,
    skipMinutes(n) {
      if (memory) {
        memory.game.minutes_used += n;
        save(memory);
      }
    },
  };
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

  function sync(): Promise<void> {
    synced ??= (async () => {
      const locale = flag("lang") || FALLBACK_LANGUAGE.locale;
      const [l, p, j] = await Promise.all([
        fetchJson<LanguageFile>(`languages/${locale}.json`),
        fetchJson<Persona[]>("personas.json"),
        fetchJson<StoryFile>("journey.json"),
      ]);
      if (l?.items) lang = l;
      if (Array.isArray(p) && p.length) personas = p.map(({ id, label, blurb }) => ({ id, label, blurb }));
      if (j?.scenes?.length) order = j.scenes;
      if (j?.title && j.premise) story = { ...STORY, ...j, endings: j.endings?.length ? j.endings : STORY.endings } as typeof STORY;
      await Promise.all(
        order.map(async (id) => {
          const s = await fetchJson<SceneFile>(`scenes/${id}/scene.json`);
          const authored = !!s?.clues?.length; // a v3 scene file carries its own story
          if (s?.objects) scenes[id] = authored ? s : { ...s, tagline: FALLBACK_SCENES[id]?.tagline ?? s.tagline, intro: FALLBACK_SCENES[id]?.intro ?? s.intro };
          const sc = scenes[id];
          if (!sc) return;
          // The art pipeline measures where things really sit in the painting.
          const layout = await fetchJson<ArtLayout>(`scenes/${id}/art/LAYOUT.json`);
          if (layout) {
            if (layout.npc_anchor) sc.npc.anchor = layout.npc_anchor;
            for (const o of sc.objects) {
              const measured = layout.objects?.[o.id];
              if (!measured) continue;
              for (const zone of Object.keys(o.positions)) if (measured[zone]) o.positions[zone] = measured[zone]!;
            }
          }
          const layer = STORY_SCENES[id];
          if (!authored && layer) {
            sc.goals = layer.goals;
            sc.clues = layer.clues;
            sc.npc.trust = layer.trust;
            for (const o of sc.objects) {
              if (o.zone === "wallet") o.zone = "inventory";
              o.actions = layer.actions[o.id] ?? ["point"];
              if (layer.floors[o.id]) o.price_floor = layer.floors[o.id];
            }
          }
          if (!sc.objects.some((o) => o.id === "photo")) sc.objects.push({ ...PHOTO, actions: ["show", "give"] });
        }),
      );
      order = order.filter((id) => scenes[id]);
      const probes: Promise<unknown>[] = [probeUrl(`${CONTENT}title.webp`).then((u) => (titleArt = u))];
      for (const id of order) {
        const s = scenes[id];
        probes.push(probeUrl(sceneUrl(id, s.art.background)), probeUrl(sceneUrl(id, s.art.cover)));
        for (const rel of Object.values(s.art.moods ?? {})) probes.push(probeUrl(sceneUrl(id, rel)));
        for (const o of s.objects) probes.push(probeUrl(sceneUrl(id, o.art)));
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
  const gitem = (id: string): PhraseSegment[] => {
    const it = lang.items[id];
    return it ? [{ t: it.text, r: noRoman() ? "" : it.roman, g: it.gloss.replace(/\s*[…(/].*$/, "") }] : [];
  };
  const gglue = (k: string): PhraseSegment[] => (GLUE[lang.locale]?.[k] ?? []).map((s) => ({ ...s, r: noRoman() ? "" : s.r }));
  const bare = (segs: PhraseSegment[]): Segment[] => segs.map(({ t, r }) => ({ t, r }));
  const item = (id: string) => bare(gitem(id));
  const glue = (k: string) => bare(gglue(k));
  /** A lexicon word when the language file has it, otherwise the mock's own glue. */
  const word = (itemId: string, glueKey: string): Segment[] => (lang.items[itemId] ? item(itemId) : glue(glueKey));
  const punct = (p: "." | "?" | "!" | ","): PhraseSegment[] => {
    const wide = { ".": "。", "?": "？", "!": "！", ",": "，" } as const;
    return [{ t: cjk() ? wide[p] : p, r: "", g: "" }];
  };
  function price(n: number): Segment[] {
    if (lang.locale !== "zh-CN" || n < 1 || n > 99) return [{ t: String(n), r: "" }];
    const tens = Math.floor(n / 10);
    const ones = n % 10;
    let t = "";
    const r: string[] = [];
    if (tens > 1) (t += ZH_DIGITS[tens][0]), r.push(ZH_DIGITS[tens][1]);
    if (tens >= 1) (t += "十"), r.push("shí");
    if (ones) (t += ZH_DIGITS[ones][0]), r.push(ZH_DIGITS[ones][1]);
    return [{ t, r: noRoman() ? "" : r.join("") }, { t: "块", r: noRoman() ? "" : "kuài" }];
  }

  const fold = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().replace(/[\s'’.,!?。？！，]/g, "");
  const targetScript = (s: string) => /[぀-ヿ㐀-鿿가-힯]/.test(s);

  /** Scene targets the learner named, longest first so a word inside a phrase is not double-counted. */
  function mentioned(text: string, sc: SceneFile): string[] {
    let f = fold(text);
    const hits: string[] = [];
    const forms = sc.targets
      .flatMap((id) => {
        const it = lang.items[id];
        return it ? [{ id, form: fold(it.text) }, { id, form: fold(it.roman || "") }] : [];
      })
      .filter((x) => x.form)
      .sort((a, b) => b.form.length - a.form.length);
    for (const { id, form } of forms) {
      if (!f.includes(form)) continue;
      f = f.split(form).join(" ");
      if (!hits.includes(id)) hits.push(id);
    }
    return hits;
  }
  const saidGlue = (text: string, key: string) => (GLUE[lang.locale]?.[key] ?? []).some((s) => fold(text).includes(fold(s.t)) || fold(text).includes(fold(s.r)));

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
    return j;
  }
  const fresh = (jid: string, token: string, persona: string, difficulty: Difficulty): Journey => ({
    journey_id: jid, token, persona_id: persona, vocab: {}, scene: null, done: [], summary: null, attempts: {}, lines: {}, seq: 0,
    game: { wallet: story.wallet, minutes_used: 0, difficulty, trust: {}, clues: [], flags: [], prices: {}, spent: 0, phrasebook: [], ending_id: null },
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
      currency_symbol: lang.locale === "zh-CN" ? "¥" : null,
    };
  }

  const storyView = (): Story => ({ title: story.title, tagline: story.tagline, premise: story.premise, art_url: titleArt });
  const allClues = () => order.flatMap((id) => scenes[id].clues ?? []);

  function gameView(j: Journey): GameView {
    const total = minutes(story.clock.end) - minutes(story.clock.start);
    const left = Math.max(0, total - j.game.minutes_used);
    const sc = j.scene ? scenes[j.scene.scene_id] : null;
    const prices: Record<string, number> = {};
    for (const o of sc?.objects ?? []) if (o.price != null) prices[o.id] = j.game.prices[`${sc!.id}:${o.id}`] ?? o.price;
    return {
      wallet: j.game.wallet,
      clock: { label: story.clock.label, time: clockText(minutes(story.clock.start) + Math.min(total, j.game.minutes_used)), minutes_left: left, minutes_total: total },
      trust: sc ? (j.game.trust[sc.id] ?? sc.npc.trust ?? 0) : 0,
      clues: j.game.clues.map((id) => allClues().find((c) => c.id === id)).filter((c): c is ClueDef => !!c).map(({ id, title, text }) => ({ id, title, text })),
      difficulty: j.game.difficulty,
      prices,
    };
  }

  function sceneView(sc: SceneFile): SceneView {
    const moods: Record<string, string> = {};
    for (const [m, rel] of Object.entries(sc.art.moods ?? {})) {
      const u = artUrl(sc.id, rel);
      if (u) moods[m] = u;
    }
    return {
      id: sc.id,
      name: sc.name,
      tagline: sc.tagline,
      intro: sc.intro,
      background_url: bgUrl(sc.id, sc.art.background),
      mood_urls: moods,
      cover_url: bgUrl(sc.id, sc.art.cover),
      npc: { name: sc.npc.names?.[lang.locale] ?? sc.npc.name, role: sc.npc.role, anchor: sc.npc.anchor },
      objects: sc.objects.map((o) => ({
        id: o.id,
        art_url: artUrl(sc.id, o.art) ?? placeholderCutout(o.id),
        price: o.price ?? null,
        positions: o.positions,
        actions: (o.actions ?? ["point"]).map((id): ObjectAction => ({ id, label: ACTION_LABEL[id] ?? id })),
      })),
      goals: sc.goals.map(({ id, label }) => ({ id, label })),
      target_count: sc.targets.length,
    };
  }

  function progress(j: Journey): Progress {
    const run = j.scene;
    const sc = run ? scenes[run.scene_id] : null;
    const level = run?.exchange.help_level ?? 0;
    const labels = ["Say it again, slowly", "What do they want?"];
    return {
      goals_done: run?.goals_done ?? [],
      encountered: sc ? sc.targets.filter((t) => (j.vocab[t]?.appearances ?? 0) > 0 || (j.vocab[t]?.results.length ?? 0) > 0).length : 0,
      target_count: sc?.targets.length ?? 0,
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
      id: e.id, title: e.title, text: e.text, art_url: order.map((id) => art.get(sceneUrl(id, e.art))).find((u) => !!u) ?? sceneUrl(order[order.length - 1], e.art),
      stats: { minutes_left: gameView(j).clock.minutes_left, wallet: j.game.wallet, clues: j.game.clues.length, words_mastered: states.filter((s) => s === "mastered").length, words_shaky: states.filter((s) => s === "shaky").length },
    };
  }

  function publicState(j: Journey): PublicState {
    const run = j.scene;
    return {
      journey_id: j.journey_id,
      language: language(),
      persona_id: j.persona_id,
      personas,
      scene: run ? sceneView(scenes[run.scene_id]) : null,
      started: !!run,
      turn: run?.turn ?? 0,
      transcript: run?.transcript ?? [],
      zones: run?.zones ?? {},
      mood: run?.mood ?? "neutral",
      progress: progress(j),
      scene_complete: !!run?.complete,
      summary: j.summary,
      scenes: sceneList(j),
      story: storyView(),
      game: gameView(j),
      ending: endingView(j),
      phrasebook: j.game.phrasebook,
    };
  }

  // -- the scripted character and narrator -----------------------------------

  interface Draft {
    segs: Segment[];
    items: string[];
    highlight: string[];
  }
  interface Reply {
    /** [story mode, immersion mode]: the gist is only ever given in story mode */
    narration: [string, string];
    lines: Draft[];
    hint: string;
    mood: string;
  }
  interface Input {
    mode: "speech" | "text" | "tap";
    text: string;
    tap: string | null;
    action: string | null;
  }

  const say = (segs: Segment[], items: string[] = [], highlight: string[] = []): Draft => ({ segs, items, highlight });
  const sellable = (sc: SceneFile) => sc.objects.filter((o) => o.price != null);
  const priceOf = (j: Journey, sc: SceneFile, id: string) => j.game.prices[`${sc.id}:${id}`] ?? sc.objects.find((o) => o.id === id)?.price ?? 0;
  const owed = (j: Journey, sc: SceneFile, run: SceneRun) => sellable(sc).filter((o) => run.zones[o.id] === "counter" && !j.game.flags.includes(`paid:${sc.id}:${o.id}`));

  /** `[item]?` naming one object: highlighted the first time it is heard, then used bare; never once mastered. */
  function offer(j: Journey, sc: SceneFile, objectId: string, point = false): Draft {
    const o = sc.objects.find((x) => x.id === objectId)!;
    const r = j.vocab[o.item_id];
    const lit = r?.state !== "mastered" && (point || !r?.appearances || (r.state === "shaky" && r.last_scene !== sc.id));
    return say([...item(o.item_id), ...punct("?")], [o.item_id], lit ? [o.id] : []);
  }

  function opening(j: Journey, sc: SceneFile): Reply {
    const first = sellable(sc).slice(0, 2).map((o) => o.id);
    const name = sc.npc.name;
    return {
      narration:
        sc.id === "bar"
          ? ["The photo is warm from your pocket. The man behind the counter looks up: he wants to know what you're having. Order, or get to the point.", "Low light, old wood, one customer asleep in the corner. The man behind the counter looks up and says something short."]
          : [`${name} doesn't stop moving: ladle, bowl, change, next. She's asking what you want to eat. The photo can wait ten seconds. Maybe.`, "Steam rolls off the pots. The cook's hands never stop. She barks something at you over the noise."],
      lines: [say([...item("hello"), ...punct("!"), ...glue("what"), ...(glue("what").length ? punct("?") : [])], ["hello"]), ...first.map((id) => offer(j, sc, id))],
      hint: "They want to know what you would like.",
      mood: "neutral",
    };
  }

  function respond(j: Journey, sc: SceneFile, run: SceneRun, input: Input): { reply: Reply; understood: string[]; produced: boolean } {
    const g = j.game;
    const said = input.tap ? [] : mentioned(input.text, sc);
    const tapped = input.tap ? sc.objects.find((o) => o.id === input.tap) : undefined;
    const action = input.action ?? (tapped ? "point" : null);
    const produced = input.mode !== "tap";
    const understood = new Set<string>(said);
    const named = tapped ?? said.map((id) => sc.objects.find((o) => o.item_id === id && o.id !== "photo" && o.id !== "money")).find((o) => !!o);
    const name = sc.npc.name;
    const bar = sc.id === order[0];
    const they = bar ? "He" : "She";
    const their = bar ? "his" : "her";
    const trust = () => g.trust[sc.id] ?? sc.npc.trust ?? 0;
    const bump = (d: number) => (g.trust[sc.id] = Math.max(-2, Math.min(3, trust() + d)));
    const authored = (f: string) => (sc.flags ? sc.flags.some((x) => x.id === f) : true);
    const flagOn = (f: string) => g.flags.includes(`${sc.id}:${f}`);
    const setFlag = (f: string) => authored(f) && !flagOn(f) && g.flags.push(`${sc.id}:${f}`);
    const photoFlag = sc.flags?.find((f) => f.id.startsWith("photo_shown"))?.id ?? (bar ? "photo_shown" : "photo_shown_lin");
    const bills = owed(j, sc, run);
    const total = bills.reduce((n, o) => n + priceOf(j, sc, o.id), 0);
    const ok = (reply: Reply, ids: string[] = [...understood]) => ({ reply, understood: ids, produced });
    const asksAfterHer = !input.tap && (said.includes("friend") || said.includes("where") || saidGlue(input.text, "seen") || saidGlue(input.text, "where"));

    // Showing (or handing over) the photo, or asking after her: the story's main move.
    if (tapped?.id === "photo" || asksAfterHer) {
      if (!flagOn(photoFlag)) {
        setFlag(photoFlag);
        if (!bar) setFlag("scarf_noticed");
        return ok(
          bar
            ? { narration: [`You slide the photo across. ${name} looks a beat too long, then at you. He knows her. He also isn't giving that away for nothing.`, `You slide the photo across. ${name} looks a beat too long. His jaw works. He says two words and folds his arms.`], lines: [say([...word("friend", "know"), ...punct("?")], ["friend"]), say([...word("she", "her"), ...punct(".")])], hint: "He recognises her, and he is waiting to see what you do next.", mood: "neutral" }
            : { narration: [`${name} glances at the photo and laughs, not unkindly. Mei was here. She's telling you so, and pointing at the pot: customers get answers.`, `${name} glances at the photo mid-ladle and laughs. She says something fast, then jabs her ladle at the pot.`], lines: [say([...word("she", "her"), ...word("left", "came"), ...punct("!")]), offer(j, sc, sellable(sc)[0].id, true)], hint: "She has seen Mei. She would like you to buy something.", mood: "pleased" },
        );
      }
      const tab = sc.objects.find((o) => o.id === "tab");
      if (tab && !flagOn("tab_paid") && trust() < 2) {
        return ok({ narration: [`You tap the photo again. ${name} lifts a slip off the spike by the till and lays it next to her face. Mei left a tab. Funny how debts make people forgetful.`, `You tap the photo again. ${name} lifts a paper slip off the spike and lays it beside the photo, one finger on the number.`], lines: [say([...price(priceOf(j, sc, tab.id)), ...punct(".")], [], [tab.id])], hint: "He is showing you that Mei left a debt here.", mood: "neutral" });
      }
      return ok({ narration: [`You hold the photo up again. ${they}'s told you what ${they.toLowerCase()} is going to tell you for free. The clock hasn't stopped.`, `You hold the photo up again. ${name} nods at it, then goes back to work.`], lines: [say([...glue("hurry"), ...punct("!")])], hint: "There is nothing more to learn from the photo right now.", mood: "neutral" });
    }

    // Haggling.
    if (!input.tap && (said.includes("too_expensive") || said.includes("cheaper") || saidGlue(input.text, "too_much") || saidGlue(input.text, "cheaper"))) {
      const target = sellable(sc).find((o) => o.price_floor && priceOf(j, sc, o.id) > o.price_floor && !j.game.flags.includes(`paid:${sc.id}:${o.id}`));
      if (target) {
        g.prices[`${sc.id}:${target.id}`] = target.price_floor!;
        return ok({ narration: [`${name} clutches ${their} chest like you've insulted the ancestors. Then a shrug, and a lower number. You just haggled, in a language you don't speak.`, `${name} clutches ${their} chest, mutters at the sky, then holds up fingers: fewer than before.`], lines: [say([...glue("fine"), ...punct(","), ...price(target.price_floor!), ...punct(".")], [], [target.id])], hint: "The price just dropped.", mood: "pleased" });
      }
      return ok({ narration: [`${name} shakes ${their} head. That price is the price.`, `${name} shakes ${their} head once, flat.`], lines: [say([...glue("no"), ...punct(".")])], hint: "No discount here.", mood: "neutral" });
    }

    // Paying: the verb on the money, the verb on a bill (Mei's tab), or naming money.
    const tabObj = sc.objects.find((o) => o.id === "tab" && run.zones[o.id] !== "gone");
    const payingTab = !!tabObj && (tapped?.id === "tab" ? action === "pay" : false);
    const paying = tapped?.id === "money" || payingTab || (said.includes("money") && !said.includes("how_much"));
    if (paying) {
      understood.add("money");
      const tabDue = tabObj && !flagOn("tab_paid") && (payingTab || (!total && flagOn(photoFlag))) ? priceOf(j, sc, tabObj.id) : 0;
      const due = payingTab ? tabDue : total || tabDue;
      if (!due) return ok({ narration: [`You wave cash at ${name}. There's nothing to pay for. ${they} looks at the money, then at you, waiting for the rest of the sentence.`, `You hold out cash. ${name} looks at it, then at you, and doesn't take it.`], lines: [say([...glue("what"), ...punct("?")])], hint: "Nothing is owed yet. They are asking what you want.", mood: "puzzled" }, []);
      if (due > g.wallet) return ok({ narration: [`You count what's left: ¥${g.wallet}. It isn't enough, and ${name} can count too.`, `You count the notes twice. ${name} watches you do it.`], lines: [say([...price(due), ...punct(".")])], hint: "You cannot afford that.", mood: "puzzled" }, []);
      g.wallet -= due;
      g.spent += due;
      run.paid += due;
      bump(1);
      if (due === tabDue && (payingTab || !total)) {
        setFlag("tab_paid");
        if (tabObj) run.zones[tabObj.id] = "gone";
        return ok({ narration: ["You pay Mei's tab. Money you won't see again. He spikes the slip, and for the first time tonight he almost smiles.", "You put the notes on the slip. He spikes it, and the set of his face changes."], lines: [say([...item("thanks"), ...punct(".")], ["thanks"])], hint: "Her debt is settled. He is warmer now.", mood: "pleased" });
      }
      for (const o of bills) g.flags.push(`paid:${sc.id}:${o.id}`);
      return ok({ narration: [`The notes disappear under the counter. Something in ${name}'s shoulders comes down an inch. Paying customers get treated like people.`, `The notes disappear. ${name} nods, slower this time, and looks at you properly.`], lines: [say([...item("thanks"), ...punct(".")], ["thanks"])], hint: "You have paid. They are warmer now.", mood: "pleased" });
    }

    // Asking the price.
    if (said.includes("how_much")) {
      const lines = total
        ? [say([...price(total), ...punct(".")])]
        : sellable(sc).filter((o) => o.id !== "tab").slice(0, 3).map((o) => say([...item(o.item_id), ...punct(","), ...price(priceOf(j, sc, o.id)), ...punct(".")], [o.item_id], j.vocab[o.item_id]?.state === "mastered" ? [] : [o.id]));
      return ok({ narration: [`${name} runs through the prices like ${they.toLowerCase()}'s done it ten thousand times. Watch the tags: you have ¥${g.wallet}.`, `${name} points along the shelf, rattling off numbers.`], lines, hint: "They are telling you the prices.", mood: "neutral" });
    }

    // The scarf: notice it, then (once she trusts you) carry it to Mei.
    if (named?.id === "scarf") {
      understood.add(named.item_id);
      setFlag("scarf_noticed");
      if (action === "take" && j.game.clues.includes("scarf") && trust() >= 1) {
        run.zones.scarf = "inventory";
        setFlag("scarf_taken");
        return ok({ narration: [`${name} folds the scarf twice and presses it into your hands. Take it to her. That much needs no translation.`, `${name} folds the scarf twice and presses it into your hands, then points down the street.`], lines: [say([...item("scarf"), ...punct(".")], ["scarf"])], hint: "She wants you to take the scarf to Mei.", mood: "pleased" });
      }
      return ok({ narration: [`The red scarf. ${name} follows your eyes to it and puts a hand on it, not unfriendly, not letting go either. It isn't hers, and it isn't yours.`, `The red scarf. ${name} follows your eyes to it and lays a hand on it.`], lines: [say([...item("scarf"), ...punct("?")], ["scarf"], ["scarf"])], hint: "She noticed you looking at the scarf.", mood: "neutral" });
    }

    // Food and drink: the verb orders it from the shelf, and consumes it once it is yours.
    if (named && named.price != null && named.id !== "tab") {
      understood.add(named.item_id);
      const consume = action === "drink" || action === "eat";
      if (run.zones[named.id] === "counter" && consume) {
        if (named.id === "baijiu") setFlag("drank_baijiu");
        if (named.id === "baijiu" || named.id === "beer") setFlag("tipsy");
        bump(1);
        return ok({ narration: [`You ${action} it. ${name} watches you do it and approves. It's also three minutes you won't get back.`, `You ${action} it. ${name} watches, and nods. The clock over the door moves anyway.`], lines: [say([...word("good", "ok"), ...punct("?")])], hint: "They are asking if it's good.", mood: "pleased" });
      }
      if (run.zones[named.id] !== "counter" && (consume || action === "take" || !input.tap)) {
        run.zones[named.id] = "counter";
        const p = priceOf(j, sc, named.id);
        return ok({ narration: [`It lands in front of you. ${name} names the price: ¥${p}. You have ¥${g.wallet}, and a train to catch.`, `It lands in front of you. ${name} holds out a hand, palm up, and says a number.`], lines: [say([...item(named.item_id), ...punct(".")], [named.item_id]), say([...price(p), ...punct(".")]), say([...item("money"), ...punct("?")], ["money"], j.vocab.money?.state === "mastered" ? [] : ["money"])], hint: "They are telling you what it costs and waiting to be paid.", mood: "neutral" });
      }
      return ok({ narration: [`You point. ${name} follows your finger and says the word for it, slowly, like a dare.`, `You point. ${name} follows your finger and says one word.`], lines: [offer(j, sc, named.id, true)], hint: "They are naming what you pointed at, and asking if you want it.", mood: "neutral" }, []);
    }

    // The chili: the dare.
    if (named?.id === "chili") {
      understood.add(named.item_id);
      const food = sellable(sc).some((o) => run.zones[o.id] === "counter" && (o.actions ?? []).includes("eat"));
      if (food && action !== "point") {
        setFlag("dare_taken");
        bump(1);
        return ok({ narration: [`You spoon the chili on like a local. ${name} stops mid-ladle to watch. Your eyes water. You have never been more respected.`, `You spoon the chili on. ${name} stops mid-ladle to watch. Your eyes water.`], lines: [say([...item("spicy"), ...punct("!")], ["spicy"])], hint: "She is impressed that you took the spicy dare.", mood: "pleased" });
      }
      return ok({ narration: [`${name} taps the jar and grins. It is a dare, and it needs something to go on.`, `${name} taps the jar and grins.`], lines: [say([...item("spicy"), ...punct("?")], ["spicy"], ["chili"])], hint: "She is asking if you like it spicy.", mood: "neutral" });
    }

    // Other props (the menu, the tab when only pointed at): look.
    if (named && named.id !== "money") {
      understood.add(named.item_id);
      if (named.id !== "tab" && named.positions.counter && run.zones[named.id] !== "counter") run.zones[named.id] = "counter";
      const lines = named.id === "tab" ? [say([...price(priceOf(j, sc, named.id)), ...punct(".")], [], [named.id])] : [say([...item(named.item_id), ...punct(".")], lang.items[named.item_id] ? [named.item_id] : []), ...sellable(sc).slice(0, 2).map((o) => offer(j, sc, o.id))];
      return ok({ narration: named.id === "tab" ? [`A slip on a spike, a number on the slip. ${name} watches you read it. Somebody owes ${bar ? "him" : "her"} money.`, `A slip on a spike. ${name} watches you read it.`] : [`${name} slides it over. Prices, mostly. None of them are friendly to a wallet holding ¥${g.wallet}.`, `${name} slides it over and waits.`], lines, hint: "They are waiting for you to decide.", mood: "neutral" });
    }

    if (said.includes("thanks") || said.includes("cheers")) return ok({ narration: [`Manners travel. ${name} nods.`, `${name} nods.`], lines: [say([...word("good", "ok"), ...punct(".")])], hint: "Just being polite back.", mood: "pleased" });
    if (said.includes("hello")) return ok({ narration: [`${name} returns the greeting and waits. Pleasantries are over; what do you want?`, `${name} answers, and waits.`], lines: [say([...item("hello"), ...punct(".")], ["hello"]), ...sellable(sc).slice(0, 2).map((o) => offer(j, sc, o.id))], hint: "They greeted you back and want to know what you would like.", mood: "neutral" });

    // Not understood (support language, noise): puzzled, point, repeat simply.
    return ok({ narration: [`That was English. ${name} has none. ${they} shrugs, and points at what's on offer instead. Try a word you've heard, show something, or look one up.`, `${name} frowns, shrugs, and points along the shelf.`], lines: [say([...glue("huh"), ...punct(".")]), ...sellable(sc).filter((o) => o.id !== "tab").slice(0, 2).map((o) => offer(j, sc, o.id, true))], hint: "They didn't follow. Name something you can see, or show them something.", mood: "puzzled" }, []);
  }

  // -- ledgers ---------------------------------------------------------------

  function record(j: Journey, run: SceneRun, itemId: string, produced: boolean) {
    const sc = scenes[run.scene_id];
    if (!sc.targets.includes(itemId)) return;
    const r = rec(j, itemId);
    const ex = run.exchange;
    const helped = ex.help_level === 1 || ex.highlighted_item_ids.includes(itemId) || ex.phrasebook_item_ids.includes(itemId);
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
    if (!Object.entries(w.in_zone ?? {}).every(([o, z]) => run.zones[o] === z)) return false;
    if (w.any_in_zone && !w.any_in_zone.objects.some((o) => run.zones[o] === w.any_in_zone!.zone)) return false;
    return true;
  }

  function commit(j: Journey, run: SceneRun, reply: Reply, learner: Entry | null, before: Record<string, string>): TurnResult {
    const t0 = performance.now();
    const sc = scenes[run.scene_id];
    const npcName = sc.npc.names?.[lang.locale] ?? sc.npc.name;
    const spaced = language().word_spacing;
    const lines: Line[] = reply.lines.filter((d) => d.segs.length).slice(0, 3).map((d) => {
      const line_id = `ln_${run.scene_id}_${++j.seq}`;
      let text = "";
      for (const s of d.segs) text += spaced && s.r && text ? ` ${s.t}` : s.t;
      j.lines[line_id] = text;
      for (const id of d.items) {
        const r = rec(j, id);
        r.appearances += 1;
        r.first_scene ??= run.scene_id;
        r.last_scene = run.scene_id;
      }
      return { line_id, speaker_name: npcName, segments: d.segs, text, romanization: d.segs.map((s) => s.r).filter(Boolean).join(" "), item_ids: d.items, highlight_object_ids: d.highlight, audio_url: `/api/journeys/${j.journey_id}/lines/${line_id}/audio` };
    });

    const events: Entry[] = [];
    for (const [id, zone] of Object.entries(run.zones)) {
      if (before[id] !== zone) events.push({ kind: "scene", turn: run.turn, event: "object_moved", object_id: id, from: before[id], to: zone });
    }
    // Clues reveal only when an authored condition holds (the GM cannot leak early).
    const trust = j.game.trust[sc.id] ?? sc.npc.trust ?? 0;
    const met = (w: Reveal) => (w.trust_at_least ?? -9) <= trust && (w.paid_at_least ?? 0) <= run.paid && (w.flags ?? []).every((f) => j.game.flags.includes(`${sc.id}:${f}`));
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

    // The last clue of an act comes with the line that gives it away.
    const gave = events.find((e) => e.kind === "clue");
    let narration = reply.narration[j.game.difficulty === "story" ? 0 : 1];
    if (gave?.kind === "clue" && gave.clue.id === "market") {
      lines.splice(0, lines.length, ...[say(lang.items.night_market ? [...item("she"), ...item("left"), ...punct(","), ...item("night_market"), ...punct(".")] : [...glue("went"), ...punct(".")]), say([...glue("stall"), ...punct(".")])].map((d, i) => toLine(j, run, npcName, d, i)));
      narration = j.game.difficulty === "story" ? "He leans in and drops his voice. The night market. A noodle stall. It's the first straight answer you've had all night, and it cost you a drink." : "He leans in and drops his voice. Two short sentences, and a thumb jerked toward the door.";
    } else if (gave?.kind === "clue" && gave.clue.id === "platform") {
      lines.splice(0, lines.length, ...[say([...word("station", "station"), ...punct("!")]), say(lang.items.number_two ? [...item("number_two"), ...item("platform"), ...punct("."), ...glue("hurry"), ...punct("!")] : [...glue("platform"), ...punct("."), ...glue("hurry"), ...punct("!")])].map((d, i) => toLine(j, run, npcName, d, i)));
      narration = j.game.difficulty === "story" ? "She points down the street with the ladle, holds up two fingers, and shoos you like a chicken. The station. Platform two. Run." : "She points down the street with the ladle, holds up two fingers, and shoos you away from her stall.";
    }

    run.mood = reply.mood;
    run.exchange = {
      posed_item_ids: [...new Set(lines.flatMap((l) => l.item_ids))],
      highlighted_item_ids: [...new Set(lines.flatMap((l) => l.highlight_object_ids.map((o) => sc.objects.find((x) => x.id === o)?.item_id ?? "")))].filter(Boolean),
      phrasebook_item_ids: [],
      help_level: 0,
      line_ids: lines.map((l) => l.line_id),
      intent_hint: reply.hint,
    };
    if (learner) run.transcript.push(learner);
    run.transcript.push(...events);
    run.transcript.push({ kind: "narration", turn: run.turn, text: narration });
    for (const l of lines) run.transcript.push({ kind: "npc", turn: run.turn, line: l });

    const clockOut = gameView(j).clock.minutes_left <= 0;
    if ((run.goals_done.length === sc.goals.length || clockOut) && !run.complete) finishRun(j, run, clockOut);
    save(j);
    return {
      turn: run.turn, lines, narration, mood: run.mood, zones: { ...run.zones }, events, progress: progress(j),
      scene_complete: run.complete, summary: run.complete ? j.summary : null, game: gameView(j), ending: endingView(j),
      latency_ms: Math.round(performance.now() - t0),
    };
  }

  function toLine(j: Journey, run: SceneRun, speaker: string, d: Draft, _i: number): Line {
    const line_id = `ln_${run.scene_id}_${++j.seq}`;
    const text = d.segs.map((s) => s.t).join("");
    j.lines[line_id] = text;
    return { line_id, speaker_name: speaker, segments: d.segs, text, romanization: d.segs.map((s) => s.r).filter(Boolean).join(" "), item_ids: d.items, highlight_object_ids: d.highlight, audio_url: `/api/journeys/${j.journey_id}/lines/${line_id}/audio` };
  }

  function finishRun(j: Journey, run: SceneRun, clockOut: boolean) {
    run.complete = true;
    if (!j.done.includes(run.scene_id)) j.done.push(run.scene_id);
    const last = order.indexOf(run.scene_id) === order.length - 1;
    if (last || clockOut) {
      const minutesLeft = gameView(j).clock.minutes_left;
      const fits = (w: NonNullable<EndingDef["when"]>) =>
        (w.clues ?? []).every((c) => j.game.clues.includes(c)) &&
        (w.flags ?? []).every((f) => j.game.flags.some((x) => x.endsWith(`:${f}`))) &&
        (!w.clock_left || minutesLeft > 0) &&
        (w.minutes_left_at_least ?? 0) <= minutesLeft;
      const e = story.endings.find((x) => fits(x.when ?? {})) ?? story.endings[story.endings.length - 1];
      j.game.ending_id = e.id;
    }
    j.summary = buildSummary(j, run);
  }

  function buildSummary(j: Journey, run: SceneRun): Summary {
    const sc = scenes[run.scene_id];
    const items = sc.targets
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
    if (j.game.phrasebook.length) lines.push(`You looked up ${j.game.phrasebook.length} ${j.game.phrasebook.length === 1 ? "phrase" : "phrases"} of your own.`);
    lines.push(run.help_uses ? `You asked for help ${run.help_uses} ${run.help_uses === 1 ? "time" : "times"}.` : "You never asked for help.");
    const nextId = j.game.ending_id ? undefined : order[order.indexOf(run.scene_id) + 1];
    const next = nextId ? scenes[nextId] : null;
    return { scene_id: sc.id, scene_name: sc.name, items, counts, recalled: items.filter((i) => i.recall).map((i) => i.item_id), lines, next_scene: next ? { id: next.id, name: next.name, tagline: next.tagline } : null, phrasebook: j.game.phrasebook };
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
    const before = { ...run.zones };
    run.turn += 1;
    j.game.minutes_used += story.clock.minutes_per_turn;
    const { reply, understood, produced } = respond(j, sc, run, input);
    for (const id of understood) record(j, run, id, produced);
    const learner: Entry = { kind: "learner", turn: run.turn, attempt_id: input.attempt_id, input_mode: input.mode, transcript: input.text, romanized: input.romanized, tapped_object_id: input.tap, action_id: input.action };
    return wire(commit(j, run, reply, learner, before));
  }

  // -- phrasebook ------------------------------------------------------------

  function composePhrase(source: string): PhraseSegment[] {
    const s = source.toLowerCase();
    const has = (...w: string[]) => w.some((x) => s.includes(x));
    const gword = (itemId: string, glueKey: string) => (lang.items[itemId] ? gitem(itemId) : gglue(glueKey));
    const thing = Object.keys(lang.items).find((id) => lang.items[id].kind === "noun" && s.includes(lang.items[id].gloss.toLowerCase().replace(/s$/, "")));
    if (has("how much", "price", "cost")) return [...gitem("how_much"), ...punct("?")];
    if (has("expensive", "too much", "pricey")) return [...gword("too_expensive", "too_much"), ...punct("!")];
    if (has("cheaper", "discount", "lower")) return [...gword("cheaper", "cheaper"), ...punct("?")];
    if (has("where")) return [...gword("she", "her"), ...gword("where", "where"), ...punct("?")];
    if (has("seen", "know her", "friend", "looking for")) return [...gglue("you"), ...gword("seen", "seen"), ...gword("she", "her"), ...gglue("q"), ...punct("?")];
    if (has("thank")) return [...gitem("thanks"), ...punct("!")];
    if (has("hello", "hi ", "good evening")) return [...gitem("hello"), ...punct("!")];
    if (thing) return [...gitem("want"), ...gitem(thing), ...punct(".")];
    return [...gitem("want"), ...gitem("this"), ...punct(".")];
  }

  function silence(key: string, text: string): string {
    const cached = audio.get(key);
    if (cached) return cached;
    const secs = Math.min(3.4, 0.7 + text.length * 0.17);
    const url = URL.createObjectURL(encodeWav(new Float32Array(Math.round(16000 * secs)), 16000));
    audio.set(key, url);
    return url;
  }

  // -- the contract ----------------------------------------------------------

  return {
    mock: true,
    health: async () => ({ ok: true, speech_provider: "mock", tts_provider: "mock", language: lang.locale }),
    catalog: async () => {
      await sync();
      return wire({
        language: language(),
        scenes: order.map((id) => ({ id, name: scenes[id].name, tagline: scenes[id].tagline, cover_url: bgUrl(id, scenes[id].art.cover), intro: scenes[id].intro })),
        personas,
        story: storyView(),
      });
    },
    createJourney: async (body) => {
      await sync();
      await wait(120);
      const persona = personas.find((p) => p.id === body.persona_id)?.id ?? personas[0].id;
      const j = fresh(uid("jrn"), uid("tok"), persona, "story");
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
      const zones: Record<string, string> = {};
      for (const o of sc.objects) zones[o.id] = o.zone;
      const run: SceneRun = {
        scene_id: id, turn: 0, complete: false, zones, goals_done: [], mood: "neutral", transcript: [], help_uses: 0, paid: 0,
        exchange: { posed_item_ids: [], highlighted_item_ids: [], phrasebook_item_ids: [], help_level: 0, line_ids: [], intent_hint: "" },
      };
      if (body.restart) {
        j.game.flags = j.game.flags.filter((f) => !f.includes(`${id}:`));
        j.game.clues = j.game.clues.filter((c) => !(sc.clues ?? []).some((x) => x.id === c));
        delete j.game.trust[id];
      }
      j.scene = run;
      j.summary = null;
      return wire(commit(j, run, opening(j, sc), null, { ...zones }));
    },
    transcribe: async (jid, token) => {
      const j = need(jid, token);
      await wait(hook.transcribeMs);
      const canned = lang.items.how_much;
      const s = hook.queue.shift() ?? { transcript: canned?.text ?? "", romanized: canned?.roman ?? null };
      const attempt_id = uid("att");
      const romanized = noRoman() ? null : (s.romanized ?? null);
      if (s.transcript) j.attempts[attempt_id] = { transcript: s.transcript, romanized, consumed: false };
      save(j);
      const tr: Transcription = { attempt_id, transcript: s.transcript, romanized, detected_languages: s.transcript ? [lang.locale] : [], confidence: s.transcript ? (s.confidence ?? 0.88) : null, requires_confirmation: !!s.requires_confirmation, provider: "mock" };
      return tr;
    },
    act: async (jid, token, body) => {
      const j = need(jid, token);
      if ("attempt_id" in body) {
        const a = j.attempts[body.attempt_id];
        if (!a) throw new ApiError(404, "unknown attempt");
        if (a.consumed) throw new ApiError(409, "attempt already consumed");
        const r = await turn(j, { mode: "speech", text: a.transcript, romanized: a.romanized, tap: null, action: null, attempt_id: body.attempt_id });
        a.consumed = true;
        save(j);
        return r;
      }
      if ("text" in body) return turn(j, { mode: "text", text: body.text, romanized: null, tap: null, action: null, attempt_id: uid("att") });
      return turn(j, { mode: "tap", text: "", romanized: null, tap: body.tap_object_id, action: body.action_id ?? null, attempt_id: uid("att") });
    },
    help: async (jid, token) => {
      const j = need(jid, token);
      const run = j.scene;
      if (!run || run.complete) throw new ApiError(409, "no scene in progress");
      await wait(200);
      const sc = scenes[run.scene_id];
      const level = Math.min(2, run.exchange.help_level + 1) as 1 | 2;
      run.exchange.help_level = level;
      run.help_uses += 1;
      save(j);
      const help: Help =
        level === 1
          ? { level, kind: "again", line_ids: run.exchange.line_ids, highlight_object_ids: sc.objects.filter((o) => o.item_id && run.exchange.posed_item_ids.includes(o.item_id)).map((o) => o.id), hint: null }
          : { level, kind: "hint", line_ids: [], highlight_object_ids: [], hint: run.exchange.intent_hint };
      return wire({ help, progress: progress(j) });
    },
    persona: async (jid, token, personaId) => {
      const j = need(jid, token);
      if (!personas.some((p) => p.id === personaId)) throw new ApiError(422, "unknown persona");
      await wait(120);
      j.persona_id = personaId;
      save(j);
      return wire(publicState(j));
    },
    difficulty: async (jid, token, difficulty) => {
      const j = need(jid, token);
      if (difficulty !== "story" && difficulty !== "immersion") throw new ApiError(422, "unknown difficulty");
      await wait(100);
      j.game.difficulty = difficulty;
      save(j);
      return wire(publicState(j));
    },
    phrase: async (jid, token, text) => {
      const j = need(jid, token);
      await wait(hook.phraseMs);
      if (hook.failNextPhrase) {
        hook.failNextPhrase = false;
        throw new ApiError(502, "model failure");
      }
      const source = text.trim();
      if (!source || targetScript(source)) throw new ApiError(422, "support-language text only");
      const segments = composePhrase(source).map((s) => (noRoman() ? { ...s, r: "" } : s));
      const textOut = segments.map((s) => s.t).join(language().word_spacing ? " " : "");
      const item_ids = Object.entries(lang.items).filter(([, it]) => segments.some((s) => s.t === it.text)).map(([id]) => id);
      const p: Phrase = { phrase_id: uid("phr"), source, segments, text: textOut, romanization: segments.map((s) => s.r).filter(Boolean).join(" "), audio_url: "", item_ids };
      p.audio_url = `/api/journeys/${j.journey_id}/phrases/${p.phrase_id}/audio`;
      j.game.phrasebook = [p, ...j.game.phrasebook.filter((x) => x.text !== p.text)];
      if (j.scene) j.scene.exchange.phrasebook_item_ids = [...new Set([...j.scene.exchange.phrasebook_item_ids, ...item_ids])];
      save(j);
      return wire(p);
    },
    phraseAudio: async (jid, token, phraseId) => {
      const j = need(jid, token);
      return silence(`phrase:${phraseId}`, j.game.phrasebook.find((p) => p.phrase_id === phraseId)?.text ?? "");
    },
    finish: async (jid, token) => {
      const j = need(jid, token);
      if (!j.scene) throw new ApiError(409, "no scene in progress");
      await wait(250);
      if (!j.scene.complete) finishRun(j, j.scene, false);
      save(j);
      return wire(j.summary!);
    },
    reset: async (jid, token) => {
      const old = need(jid, token);
      const j = fresh(jid, token, old.persona_id, old.game.difficulty);
      save(j);
      return wire(publicState(j));
    },
    lineAudio: async (jid, token, lineId) => silence(lineId, need(jid, token).lines[lineId] ?? ""),
    itemAudio: async (jid, token, itemId) => {
      const j = need(jid, token);
      if (j.scene && !j.scene.complete) throw new ApiError(409, "only on the summary");
      return silence(`item:${itemId}`, lang.items[itemId]?.text ?? "");
    },
  };
}
