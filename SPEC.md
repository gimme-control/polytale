# Polytale v3 — build contract

> **v3 direction (owner feedback on v2): "it feels like a learning game, not a real game that has
> learning in it."** v3 is a story game first. Learning is a by-product the ledger observes.
> Where this section conflicts with anything below it (or with docs/PRD.md), THIS SECTION WINS.

## v3: the game layer

**Pitch.** *The Last Train.* You land in a Chinese city at night with a dead phone. Your friend
Mei was meant to meet you; all you have is a photo of her and the name of a bar. Find her before
the last train. Nobody speaks English. Two acts reuse the existing scenes: the bar (the bartender
knows Mei but has reasons to be cagey) and the night market (the vendor has something of hers).

**Principles.**
1. **Story first.** Goals are story goals ("Find out where Mei went"), never lesson goals ("Get a
   drink"). Nothing about vocabulary may gate, delay or nudge the story: the v2 "owed pass" wrap-up
   nudge is removed; fading support is soft prompt guidance only.
2. **A narrator.** Every turn carries `narration`: English, second person, the player's inner
   voice, punchy and a little wry (1–3 sentences, ≤ 45 words). It carries plot, stakes, humour and
   sensory detail. It replaces `stage_direction`.
3. **Difficulty** (journey setting, switchable any time): `story` (default) — narration may give
   the GIST of what the character means and hint at what might work ("He's asking what you want —
   and sizing you up."), and the character keeps lines to 1–6 words built mostly from scene words;
   `immersion` — narration is physical/sensory only, never the gist. Neither mode ever prints a
   word-for-word translation of a character line.
4. **Phrasebook ("How do I say…?").** The learner types what THEY want to say in English and gets
   the simplest natural way to say it in the target language: segments with romanization AND a
   per-word gloss (it is their own sentence, so glossing it is fine), audio, and "Use it" (fills
   the input; they still send or say it). It never translates character lines: the endpoint takes
   only learner-authored support-language text, and the prompt refuses target-language input.
   Lexicon items that appear in a looked-up phrase count as assisted for that exchange
   (`with_help`), stamped by code. Looked-up phrases are kept per journey as the learner's own
   phrasebook and shown on the summary.
5. **Real choices, real resources.** A wallet (integer cash; things cost money; you cannot afford
   everything), a clock (each learner turn costs minutes; the last train leaves), character trust
   (what they will tell you depends on it), clues (a notebook of what you have learned), verbs on
   objects (not just pointing), haggling, more than one way through each act, and endings that
   depend on time, cash and how you treated people. Fail forward: no dead ends, no game-over
   before the ending.
6. Everything in v2's invariants still holds: typed tools, code-owned ledgers, no regex over
   prose, language-agnostic core (story content is language-neutral JSON; English is the support
   language), pre-made art, client-drawn highlights.

**Content.** `content/journey.json` becomes the story file:
```jsonc
{ "title": "The Last Train", "tagline": "...", "premise": "player-facing, 2–3 sentences",
  "gm_brief": "GM-facing truth: who Mei is, what each character knows and wants, how clues chain, tone",
  "wallet": 60, "clock": { "label": "Last train", "start": "22:40", "end": "23:55", "minutes_per_turn": 3 },
  "scenes": ["bar", "market"],
  "endings": [ { "id": "reunited", "title": "...", "text": "...", "art": "art/ending_reunited.webp",
                 "when": { "clues": ["platform"], "clock_left": true } }, ... ]   // first match wins; last is the fallback
}
```
Scene additions: `npc.wants`, `npc.secrets` (GM-facing), `npc.trust` (start, −2..3),
`clues: [{ id, title, text, reveal_when: { trust_at_least?, flags?: [], paid_at_least? } }]`,
`goals[].when` may use `clue`, `flag`, `in_zone`, `any_in_zone`; objects gain
`actions: ["point","take","give","show","drink","eat","pay"]` (subset), `price`, optional
`price_floor` (haggling), and the player-held zone is `inventory` (renamed from `wallet`).
Money is numeric (`game.wallet`); the money object stays in `inventory` as the thing you use to pay.

**State.** `Journey.game = { wallet, minutes_used, difficulty, trust: {scene_id: int},
clues: [clue_id], flags: [str], prices: {object_id: int}, spent: int, phrasebook: [Phrase],
ending_id }`. `Exchange.phrasebook_item_ids`.

**Tools** (one response per turn, `say` terminal):
`move_object(object_id, to_zone)` · `pay(amount, for_object_ids[])` (≤ wallet; amount must equal the
current prices' sum unless `tip`) · `set_price(object_id, amount)` (haggling: within
[`price_floor`, `price`]) · `adjust_trust(delta ∈ −1..1, reason)` (once per turn, clamped −2..3) ·
`reveal_clue(clue_id)` (ERROR unless `reveal_when` holds — the GM cannot leak a secret early) ·
`set_flag(flag)` (authored flags only) · `complete_goal(goal_id)` · `record_item(...)` (unchanged) ·
`say(narration, lines[], intent_hint, mood)`.
The clock ticks in code per learner turn; when it runs out the current act ends at the next turn
boundary and the ending resolves. After the last act's goals complete, the ending resolves.

**Learner input.** `act` accepts `{attempt_id}` | `{text}` | `{tap_object_id, action_id}`.
The GM sees verbs as "[the player shows the photo]". Characters only understand the target
language and actions; support-language speech still earns a puzzled look.

**Payload deltas.**
```ts
TurnResult += { narration: string|null, game: GameView, ending: Ending|null }   // stage_direction removed
Entry      += { kind: "narration", turn, text } | { kind: "clue", turn, clue: Clue }
GameView   { wallet, clock: { label, time: "23:12", minutes_left, minutes_total }, trust: number,
             clues: Clue[], difficulty: "story"|"immersion", prices: {object_id: number} }
Clue       { id, title, text }
SceneView.objects[] += { actions: [{ id, label }] }     // labels in English, e.g. "Show", "Drink"
Ending     { id, title, text, art_url, stats: { minutes_left, wallet, clues, words_mastered, words_shaky } }
Phrase     { phrase_id, source, segments: [{ t, r, g }], text, romanization, audio_url, item_ids }
PublicState += { story: { title, tagline, premise }, game: GameView, ending: Ending|null, phrasebook: Phrase[] }
Summary    += { phrasebook: Phrase[] }
```
**REST deltas.** `POST /api/journeys/{jid}/phrase {text}` → Phrase (fast model, ≤ 2 s; 422 when
the text is not support-language or is empty; never consumes a turn or clock time) ·
`GET /api/journeys/{jid}/phrases/{phrase_id}/audio` · `POST /api/journeys/{jid}/difficulty
{difficulty}` → PublicState · `act` body gains `action_id`.

**Web.** Same restrained cinematic language as v2, now a game: narration rendered as prose above
the subtitles (it is the story's voice — give it presence); HUD with clock (it should feel like
pressure as it runs down), cash, a notebook of clues, inventory tray; object verb menu on click;
right-side Phrasebook panel (collapsible; bottom sheet on phones): "How do I say…" field, result
with ruby + per-word gloss + play + "Use it", and the journey's looked-up phrases below; difficulty
toggle in the menu; ending screen (art, title, text, stats) before the word summary.

### v3 as built (engine + server; where this differs from the sketch above, THIS wins)

**Content.**
- `journey.json`: `endings[].when` = `{clues[], flags[], clock_left?, minutes_left_at_least?,
  wallet_at_least?}`; the LAST ending must have an empty `when` (fallback). `endings[].art` is
  relative to the LAST scene's directory (served by that scene's art route).
- Scene: `travel_minutes` (clock cost of arriving), `support_words[]` (non-target lexicon words the
  GM may lean on and tag), `flags: [{id, when, requires_paid[]}]` (`requires_paid`: ANY one of
  those objects must have been paid for before `set_flag` is accepted), `clues: [{id, title, text,
  gm_note, key_items[], reveal_when: [ {trust_at_least?, flags[], paid_at_least?}, ... ]}]` —
  `reveal_when` is a LIST of ways; ANY one way suffices, every field inside a way must hold;
  `paid_at_least` counts cash spent in THIS scene. `key_items` are the giveaway words: `say` is
  refused while a line carries one and the clue is not revealed (LOCKED → "deflect"; available →
  "call reveal_clue in this response"). Flags are journey-global (they carry across acts).
- Language: `phrasebook_voice {gemini_voice, elevenlabs_voice_id, style}`.
- New validator codes: `unknown_action`, `price_floor_invalid`, `unknown_clue`, `unknown_flag`,
  `ending_no_fallback`, `clock_empty`.

**State.** `Game.prices` and `Game.paid_for` are keyed by scene (`{scene_id: {...}}`);
`SceneRun.spent`; `Attempt.action_id` / learner entries carry `action_id`.
`GameView.prices` is the CURRENT scene's `{object_id: price now}`; `GameView.trust` is the current
scene's character.

**Tools.** `complete_goal` is gone: goals complete themselves the moment their `when` holds
(clue / flag / zones) and at every commit. `pay(amount, for_object_ids[], tip?)`; `set_price` is
declared only in scenes with a `price_floor`; `adjust_trust` a second time in one turn is an OK
no-op; `pay` / `adjust_trust` / `record_item` are refused in the opening. The clock ticks
`minutes_per_turn` per player turn at commit (the opening and phrasebook lookups are free).
The snapshot tells the GM when the clock runs out with the turn in play, lists each clue as KNOWN
/ CAN COME OUT NOW / LOCKED (with what each way still lacks), and lists what was served but not
paid for.

**Flow.** An act completes when all its goals are done OR the clock hits zero. The ending resolves
(first match) when the LAST act completes or the clock runs out in any act; `TurnResult.ending` is
set only on that turn, `PublicState.ending` from then on; `Summary.next_scene` is null once the
story has ended. `finish` on the last act also resolves the ending.

**REST.**
- `GET /api/catalog` += `story {title, tagline, premise}`.
- `POST …/act` `{tap_object_id, action_id?}`: `action_id` omitted = `point`; 422 when the object
  does not have that verb or `action_id` is sent without `tap_object_id`.
- `POST …/phrase {text}` → `Phrase`; 422 `{detail: {code: "empty"|"target_language"|
  "not_a_phrase", message}}`; 502 when every model failed; works before, during and after play;
  the model call runs outside the journey lock. `Phrase.item_ids` are found by code; they mark
  `exchange.phrasebook_item_ids` so the next result for those words stamps `with_help`.
- `GET …/phrases/{phrase_id}/audio` (language `phrasebook_voice`) · `POST …/difficulty
  {difficulty}` → PublicState (422 on an unknown value).
- `POST …/scene` → 409 once the story has ended.

---

# v2 contract (still in force where v3 is silent)

Polytale is a scenario-based language learning game for adults. You are dropped into a concrete
situation (a bar, a night-market stall), a character speaks ONLY the target language, and you get
things done by speaking, typing, or pointing. Meaning is inferred from what you can see; nothing
is ever translated. Every line of dialogue is generated live by an LLM playing the character.
Product doc: `docs/PRD.md` (read it first). The product name is **Polytale** (never "Relay").

Demo language: **Mandarin Chinese (zh-CN)**. The engine is language-agnostic: a language is one
JSON file; scenes are language-neutral.

Polytale is standalone. It may copy code from the parent Arbitale checkout (`..`) but never
imports from it and never modifies anything outside `polytale/`.

## Invariants

1. **The LLM plays the character; code owns the ledgers.** The model reads a snapshot and commits
   changes only through typed tools. Executors validate every id and mutate state
   deterministically. The vocabulary record is written only by code.
2. **No hardcoding model output.** No regex/keyword classifiers over model prose and no rewriting
   it. Misbehaviour is fixed in the prompt, tool declarations, or snapshot. Invalid tool args
   return `ERROR: ...` receipts and the model retries within the same loop.
3. **No native-language translation during play.** Character speech is target-language text plus
   romanization (when the language declares one). Glosses appear only on the end-of-scene summary.
4. **Everything must be showable.** Target items are concrete nouns and simple functional phrases
   tied to visible objects/actions. No abstract vocabulary, no grammar explanation.
5. **Highlighting is code-controlled.** The model names object ids; the client draws the highlight.
   Art is pre-generated; nothing is drawn at runtime.
6. **Scene-state change is the evidence.** No scores, no quizzes, no fluency percentages.
7. **Language-agnostic core.** `core/`, `server/`, `media/`, `web/` contain no language-specific
   words, scripts, or examples; those come from `content/languages/<locale>.json`. Prompt examples
   are built from the active lexicon.
8. Content is declarative JSON. `core/` never imports `fastapi`, `server`, or `media`.

## Layout

```
polytale/
  content/
    languages/zh-CN.json      language profile + lexicon (ja-JP.json also ships as a proof)
    scenes/<scene_id>/scene.json + art/
    personas.json
    journey.json              {"scenes": ["bar", "market"]}
  core/     gemini.py content.py state.py vocab.py tools.py prompt.py dm.py summary.py views.py
  media/    tts.py stt.py common.py          (speech providers; ElevenLabs primary, Gemini fallback)
  server/   app.py sessions.py spa.py        (FastAPI, REST, single process)
  scripts/  standalone tests + tools (no pytest)
  web/      Vite + React 19 + TS + Tailwind 4 + zustand
  docs/     PRD
  states/ cache/ logs/   runtime (gitignored)
```

The v1 `cartridges/` tree, `core/cartridge.py`, `core/ledger.py`, `core/recap.py` and the airship
content are removed. Venv `~/.venvs/polytale`; run scripts from `polytale/` with
`PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/<name>.py`. Ports: API 8100, web 5180.

## Content

### Language file `content/languages/<locale>.json`

```jsonc
{
  "locale": "zh-CN", "name": "Mandarin Chinese", "native_name": "中文",
  "romanization": { "system": "pinyin", "label": "Pinyin" },     // or null (e.g. Spanish)
  "word_spacing": false,            // false: segments join with no space (zh, ja); true: spaces
  "typing_note": "Learners may type pinyin without tones (\"pijiu\"); treat it as the word.",
  "items": {
    "beer":     { "text": "啤酒",   "roman": "píjiǔ",       "gloss": "beer",       "kind": "noun" },
    "want":     { "text": "我要",   "roman": "wǒ yào",      "gloss": "I want …",   "kind": "phrase" },
    "how_much": { "text": "多少钱", "roman": "duōshao qián", "gloss": "how much?", "kind": "phrase" }
  }
}
```

An item may set `"learner_side": true` for a customer's line ("how much?"): the character never
says it for the learner (snapshot guidance "THEIR line, never yours") and only answers it. A
placeholder in `text` ("…", "...", "~") splits a frame into its spoken parts.

Item ids are language-neutral concept ids shared by every scene and language. `gloss` is English
and is only ever sent on the summary. A language must define every item any scene targets.

### Scene file `content/scenes/<id>/scene.json` (language-neutral)

```jsonc
{
  "id": "bar", "name": "The Corner Bar", "tagline": "Get a drink. Pay for it.",
  "intro": "It's late. You duck into a small bar. You're thirsty, and nobody here speaks English.",
  "setting": "DM-facing description: place, mood, what is physically present, what is NOT.",
  "art": { "background": "art/bg.webp", "cover": "art/cover.webp",
           "moods": { "neutral": "art/bg.webp", "pleased": "art/bg_pleased.webp",
                      "puzzled": "art/bg_puzzled.webp" } },       // moods optional
  "npc": { "id": "bartender", "name": "Chen", "names": { "zh-CN": "老陈" }, "role": "bartender",
           "character": "DM-facing: who they are, independent of persona",
           "voice": { "gemini_voice": "Charon", "elevenlabs_voice_id": "", "style": "..." },
           "anchor": { "x": 0.5, "y": 0.35 } },                   // where speech emanates (UI)
  "zones": ["display", "counter", "npc", "wallet", "gone"],   // fixed zone vocabulary
  "objects": [
    { "id": "beer", "item_id": "beer", "art": "art/obj_beer.png", "zone": "display", "price": 20,
      "positions": { "display": { "x": 0.31, "y": 0.22, "h": 0.16 },
                     "counter": { "x": 0.42, "y": 0.78, "h": 0.30 } } },
    { "id": "money", "item_id": "money", "art": "art/obj_money.png", "zone": "wallet",
      "positions": { "counter": { "x": 0.6, "y": 0.82, "h": 0.12 }, "npc": { "x": 0.5, "y": 0.5, "h": 0.1 } } }
  ],
  "targets": ["hello", "beer", "water", "tea", "want", "this", "how_much", "money", "thanks", "menu"],
  "goals": [
    { "id": "order", "label": "Get something to drink",
      "when": { "any_in_zone": { "zone": "counter", "objects": ["beer", "water", "tea"] } } },
    { "id": "pay", "label": "Pay for it", "when": { "in_zone": { "money": "npc" } } }
  ]
}
```

- Coordinates are fractions of the background (origin top-left); `x,y` = object centre-bottom,
  `h` = height as a fraction of background height. `wallet` and `gone` have no position (wallet is
  a HUD tray). An object may only move to zones it has a position for, or `wallet`/`gone`.
- `price` (optional int) is showable: the client renders it as digits on a tag when the menu is
  open or the object is highlighted.
- Goal conditions: `in_zone {object: zone}`, `any_in_zone {zone, objects[]}`; all clauses must hold.
- 8–12 targets per scene. Scene 2 (`market`) must reuse at least 5 of scene 1's targets and objects
  (`beer`, `water`, `money` at minimum) so recall has something to attach to.

### `content/personas.json`

`[{ "id": "warm", "label": "Warm", "blurb": "Patient, repeats gladly", "prompt": "...",
    "voice_style": "..." }, ...]` — 3 presets: `warm`, `brisk` (busy, clipped, low patience),
`unhinged` (theatrical, absurd, still kind). Persona changes ONLY tone, patience, repetition —
never objects, targets, or rules.

Validation (`core/content.py`, error codes; loader raises on any): unknown item/object/zone/goal
refs, target missing from the language, object zone without a position, duplicate ids, art path
escaping the scene dir, targets outside 8–12, scene 2+ sharing < 5 targets with earlier scenes,
persona ids not unique, journey naming unknown scenes. `missing_art()` is a separate check.
Codes (`"<code>: <detail>"` strings): `unknown_item`, `target_missing_in_language`,
`unknown_object`, `unknown_zone`, `zone_without_position` (also a goal that needs an object in a
zone it has no position for), `duplicate_id`, `art_escapes_scene`, `target_count`,
`recall_overlap`, `journey_unknown_scene`, `personas_empty`, `languages_empty`, `goal_empty`,
`romanization_missing` / `romanization_unexpected`, plus loader-only `schema`, `id_mismatch`,
`unreadable`. Every language must define every scene target AND every object's `item_id`.
`resolve_art_path(scene, rel)` returns the absolute path or raises `ValueError` on escape.
The support language (glosses, intent hints, stage directions) is `content.SUPPORT_LANGUAGE`
(English).

## State (`core/state.py`)

```
Journey:
  journey_id, language, persona_id, created_at, schema_version: 2
  vocab: {item_id: VocabRecord}                 // persists across scenes
  scene_index: int                              // into journey.scenes
  scene: SceneRun | null                        // the scene being played
  history: [SceneSummary]                       // finished scenes
  attempts: {attempt_id: Attempt}

SceneRun:
  scene_id, turn, started, complete
  zones: {object_id: zone}
  goals_done: [goal_id]
  mood: str
  transcript: [Entry]
  exchange: { posed_item_ids: [], highlighted_item_ids: [], help_level: 0|1|2,
              line_ids: [], intent_hint: str }   // since the character last spoke

VocabRecord: { appearances: int, results: [Result], first_scene: str, last_scene: str, state,
               produced: bool }
Result:      { scene_id, turn, attempt_id, outcome: "first_try"|"with_help"|"with_hint"|"missed",
               produced: bool, recall: bool }
state:       "not_encountered" | "shaky" | "mastered"
```

`history` holds the full `Summary` of each finished scene. `exchange.highlighted_item_ids` = the
items of every highlighted object, plus, for a line that carries any highlight, that line's
items that have no object of their own in the scene ("this one", "how much").

Atomic save (`.tmp` + `os.replace`) under `states/journeys/` (`save_journey` / `load_journey`).

Scene flow: `enter_scene(journey, content, scene_id=None) -> Journey` returns a NEW journey at a
fresh unstarted SceneRun (input untouched, so a failed opening costs nothing). Default target:
the scene in play when it is incomplete (restart), else the next in journey order; a COMPLETE
previous scene's summary is archived into `history`, an abandoned one is dropped (its vocabulary
results persist). `finish_scene(journey, content) -> Summary` marks the scene complete in place.
`request_help` and `set_persona` also mutate in place.

## Vocabulary rules (`core/vocab.py`, pure + deterministic) — PRD §4

- A character line carrying `item_ids` counts one **appearance** per item and sets `last_scene`.
  Appearances alone never change `state`: an item stays `not_encountered` until a result is
  recorded. `Progress.encountered` counts scene targets with `appearances > 0`.
- `record(item, understood|missed, produced)` stamps the outcome from the SERVER's exchange ledger,
  never from the model:
  - missed → `missed`
  - understood, `help_level == 2` → `with_hint`
  - understood, `help_level == 1` OR the item was highlighted in the exchange → `with_help`
  - understood otherwise → `first_try`
- State after a result: `first_try` → `mastered`; anything else → `shaky` (a mastered item that is
  later missed drops to `shaky`).
- `recall = true` when outcome is `first_try` and the item's first appearance was in an EARLIER
  scene. This is the demo's proof moment.
- Help (`request_help`): level rises by exactly one per press (max 2) within the exchange and
  resets when the character next speaks. Level 1 = "again, slowly": returns the exchange's
  `line_ids` for slow replay plus the object ids of `posed_item_ids` to highlight. Level 2 =
  the exchange's `intent_hint` (support language; what the character WANTS, never a translation).
- **Highlight gate:** a line may not highlight an object whose item is `mastered` for this learner
  → `ERROR` receipt ("mastered: present it with no highlight"). `shaky`/`not_encountered` may.
  The gate judges the record as it stood when the turn began (what the snapshot told the model),
  so a result recorded earlier in the same response cannot trip it.
- A tap is never production (`produced` is forced false), and a tap only counts as understanding
  of a word the character's last lines carried; otherwise `record_item` records nothing (OK
  receipt, no ERROR).
- Duplicate `(attempt_id, item_id)` results are idempotent.
- **Fading support inside one scene (PRD §5.3).** An object word whose results in THIS scene
  include `with_help`/`with_hint` but no `first_try` is *owed an unsupported pass*
  (`vocab.owed_items`). The snapshot lists it ("STILL OWED AN UNSUPPORTED PASS: …") and the
  character brings it back once with no highlight before taking payment, so a correct response
  stamps `first_try`. Each turn in which an owed word (owed when the turn began) is said with no
  highlight counts in `SceneRun.unsupported_offers`; at 2 the debt lapses. `complete_goal` on the
  goal that would END the scene returns one ERROR receipt ("not yet: … still owed an unsupported
  pass") while a never-offered debt exists, sets `SceneRun.wrap_nudged`, and is allowed on the
  next attempt: a nudge, never a block. Learner-side and object-less items are never owed.
- Presentation guidance in the snapshot per target: `not_encountered` → "introduce: say it,
  highlight it, act it out"; `shaky` → "use it with a highlight"; `shaky` with a `with_help`
  success already this scene → "use it WITHOUT a highlight"; `mastered` → "use it with NO support".

## Tools (`core/tools.py`)

| tool | args | effect |
| --- | --- | --- |
| `move_object` | object_id, to_zone | validates object + zone position; updates `zones` |
| `record_item` | item_id, result ∈ understood/missed, produced: bool | vocab rules; requires a learner attempt this turn; item must be a scene target |
| ~~`complete_goal`~~ | — | removed in v3: goals complete themselves |
| `say` (TERMINAL) | lines[], stage_direction?, intent_hint, mood? | ends the turn |

`say.lines[]`: `{ segments: [{t, r}], item_ids: [], highlight_object_ids: [] }`.
- `segments` are words/punctuation in order: `t` target-language text, `r` its romanization (""
  for punctuation, and always "" when the language has no romanization). Code derives
  `text` = join of `t` (no separator unless `word_spacing`) and `romanization` = join of non-empty
  `r` with spaces. Validation: ≥1 segment, every word segment has `r` when the language declares
  romanization, (v3: a listed `item_id` whose word is not exactly one segment is dropped from the line's
  items by code, not refused) every counted `item_id`'s text is exactly ONE segment (each spoken part, for a
  frame), a highlighted object's own item must be among the line's items (a highlight means
  "this word is that thing"; a bare price line lights nothing), a word segment holds the word
  only (punctuation is its own segment), `t` holds
  no Latin letters when the language's own lexicon has none (romanization belongs in `r`),
  1–3 lines per turn, ≤ 14 word segments per line, item/object ids exist, highlight
  gate. Segments are what let the client draw romanization over each word (ruby) and show word
  boundaries.
  Code-owned bookkeeping on the structured segments: a segment whose `t` equals a lexicon item's
  text takes the lexicon's `r`, and a scene item whose text is a segment is added to the line's
  `item_ids` even when the model did not tag it.
- `stage_direction`: optional, support language, ≤ 12 words, physical action only ("sets it down
  in front of you"). It is shown on screen, so it must never name or describe an object or item
  (that is a translation), and never paraphrase speech.
- `intent_hint`: required, support language, ≤ 16 words: what the character wants from the
  learner right now; intent only, never a quoted word or a word/meaning pair. Stored server-side; revealed only by help level 2.
- `mood`: one of the scene's moods (`neutral` + the authored `art.moods` keys); required in the
  declaration, and an omitted mood commits as `neutral` so a puzzled face never sticks.
- A line's `item_ids` may name any scene target or any scene object's item.
- `say` returns ERROR if any other call in the same response errored.

Receipts end with a compact NOW line (zones, goals, mood).

## DM (`core/dm.py`, `core/prompt.py`)

- `run_opening(journey, content) -> (journey, TurnResult)` — a REAL model turn with no learner
  input ("the learner just arrived"); `run_turn(journey, content, attempt) -> (journey, TurnResult)`.
  Deep-copy in, new state out; on failure the caller keeps the old state. Client injectable for
  tests. Same loop shape as v1 (cascade, nudges, max 6 rounds, all tools + `say` in ONE response).
- When every goal is done after a committed turn, code sets `scene.complete = true` and attaches
  the summary.
- Prompt (language-agnostic; examples rendered from the lexicon) must enforce PRD §7.3:
  speak ONLY the target language; react to intent, not language; if the learner uses the support
  language the character does not understand — looks puzzled (`mood`), points, repeats simply;
  accept fragments, romanized typing, wrong tones/grammar when intent is recoverable; never
  translate, explain grammar, admit to being an AI, or break character (in-character deflection);
  stay within this scene's objects; short natural adult speech (not a classroom, not a children's
  show): a real bartender talking to a foreigner, 2–8 words a line; use targets per the snapshot's
  presentation guidance; prefer offering visible choices with per-line highlights; move objects when
  things physically happen; record an item result for each target the learner clearly responded to
  or produced this turn; tap input ("points at X") is a legitimate move; low recognition
  confidence → ask again, record nothing; keep the scene moving toward its goals but let the
  learner roam.
- System prompt (stable per scene + language): rules, scene setting, NPC character, a worked
  example rendered from the lexicon. Snapshot (per turn): persona prompt, object table (id, item,
  zone, price), goals + done, targets table (item id, text, roman, state, guidance,
  appearances, first-met scene), recent transcript (~12 entries), exchange ledger, learner
  attempt. A speech attempt shows BOTH `romanized` ("it sounded like") and the recognizer's
  `transcript`, plus confidence (< 0.6 = LOW CONFIDENCE): the character hears by sound, so a
  homophone-confused transcript still reads as the plausible request.
  Glosses ARE included for the model (it needs meaning); they are never sent to the client
  during play.

## Payloads (snake_case JSON)

```ts
Segment   { t, r }
Line      { line_id, speaker_name, segments: Segment[], text, romanization,
            item_ids: string[], highlight_object_ids: string[], audio_url }
Entry     = { kind: "npc", turn, line: Line }
          | { kind: "direction", turn, text }
          | { kind: "learner", turn, attempt_id, input_mode: "speech"|"text"|"tap",
              transcript, romanized: string|null, tapped_object_id: string|null }
          | { kind: "scene", turn, event: "object_moved"|"goal_done", object_id?, from?, to?, goal_id? }
            // absent fields are null; pydantic dumps `from`/`to` by alias on every dump
SceneView { id, name, tagline, intro, background_url, mood_urls: {mood: url}, cover_url,
            npc: { name, role, anchor }, 
            objects: [{ id, art_url, price: number|null, positions }],   // NO item text, NO gloss
            goals: [{ id, label }], target_count }
Progress  { goals_done: string[], encountered: number, target_count: number,
            help_level: 0|1|2, next_help: { level, label } | null }
TurnResult{ turn, lines: Line[], stage_direction: string|null, mood, zones,
            events: Entry[],                // EVERY transcript entry this turn added, in order:
                                            // learner, scene events, direction, npc lines
            progress: Progress, scene_complete, summary: Summary|null, latency_ms }
Summary   { scene_id, scene_name,
            items: [{ item_id, text, roman, gloss, state, outcomes: string[], produced, recall,
                      audio_url }],
            counts: { mastered, shaky, heard, not_encountered },   // heard = said by the character, never acted on
            recalled: [item_id],            // first_try on items first met in an earlier scene
            lines: string[],                // observed-behaviour sentences, no scores
            next_scene: { id, name, tagline } | null }
PublicState { journey_id, language: { locale, name, native_name, romanization_label: string|null,
              word_spacing }, persona_id, personas: [{id,label,blurb}], scene: SceneView|null,
              started, turn, transcript: Entry[], zones, mood, progress, scene_complete,
              summary: Summary|null,       // non-null exactly when scene_complete
              scenes: [{id,name,tagline,cover_url,status: "done"|"current"|"next"|"locked"}] }
Help      { level, kind: "again"|"hint", line_ids: string[], highlight_object_ids: string[],
            hint: string|null }
Transcription { attempt_id, transcript, romanized, detected_languages, confidence,
            requires_confirmation, provider }
```

## REST (`server/`)

Auth: `X-Journey-Token` header (audio GETs accept `?token=`). Bad token 403, unknown journey 404.

| method | path | notes |
| --- | --- | --- |
| GET | `/api/health` | `{ok, speech_provider, tts_provider, language}` |
| GET | `/api/catalog` | `{language, scenes:[{id,name,tagline,cover_url}], personas}` |
| GET | `/api/scenes/{id}/art/{path}` | path confined to the scene dir |
| POST | `/api/journeys` | `{persona_id?, language?}` → `{journey_id, token, state}`; language defaults to `POLYTALE_LANGUAGE` (zh-CN) |
| GET | `/api/journeys/{jid}` | PublicState |
| POST | `/api/journeys/{jid}/scene` | `{scene_id?}` enter the next (or named) scene and run the opening turn → TurnResult. 409 if a scene is in progress and incomplete (unless `restart: true`) |
| POST | `/api/journeys/{jid}/transcribe` | multipart audio ≤ 5 MB → Transcription; stores a pending attempt only |
| POST | `/api/journeys/{jid}/act` | exactly one of `{attempt_id}`, `{text}`, `{tap_object_id}` → TurnResult. 409 consumed/busy, 502 model failure (state unchanged, attempt reusable), 402 provider out of credits (same guarantees; the client shows the reason) |
| POST | `/api/journeys/{jid}/help` | → `{help: Help, progress}`; no story turn |
| POST | `/api/journeys/{jid}/persona` | `{persona_id}` → PublicState; applies from the next reply |
| POST | `/api/journeys/{jid}/finish` | end the scene now → Summary |
| GET | `/api/journeys/{jid}/lines/{line_id}/audio` | TTS, cached; slow replay is client playbackRate |
| GET | `/api/journeys/{jid}/items/{item_id}/audio` | the bare word (summary screen only; 409 during play) |
| POST | `/api/journeys/{jid}/reset` | fresh journey, same id/token |

TTS voice = scene NPC voice; style = NPC style + persona `voice_style`. Server pre-warms audio for
new lines as each turn commits.

## Speech (`media/`)

Unchanged provider design. Must be language-agnostic: no hardcoded Japanese/Hepburn; STT prompt
is built from the language profile (name, romanization system) and asks for `romanized` in that
system (null when none). CJK script detection maps by target locale, not a fixed language.

## Web (`web/`)

Adult, restrained, cinematic. The scene fills the viewport; dialogue is a subtitle over the scene
(target text large, romanization ruby above each word, never a translation); one quiet input bar
(text field + mic, equal weight; Enter sends; hold mic or Space to talk); objects are clickable;
highlights are a crisp outline/glow on the object's alpha; served objects slide between zones; a
wallet tray; a minimal goal checklist + "n / N words met" counter; persona switcher; two-step help;
history drawer; intro card on scene entry; summary screen (first time the word list is shown, with
glosses, states, recall callouts, tap-to-hear); "Continue to <next scene>".
`?mock=1` runs an in-browser mock of this contract.

## Tests (standalone scripts; exit non-zero on failure)

Offline: `verify_imports`, `test_content`, `test_vocab`, `test_tools`, `test_dm_offline`,
`test_summary`, `test_speech_providers`, `test_server_api`, `test_web_contract`, `test_run_sh`,
`test_language_agnostic` (greps core/server/media/web/src for target-language literals; runs the
offline loop with the ja-JP lexicon).
Live: `test_dm_live` (bar golden path, adversarial learner per PRD §9.4, persona shift, scene-2
recall without highlight), `test_speech_live`, `playtest_voice_live`, `playtest_browser_live`.
