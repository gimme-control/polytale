# Polytale MVP — build contract

Polytale (working title "Relay") is a voice-first adventure for learning practical spoken
language. The judged slice: an absolute beginner, Japanese, one NPC (an airship engineer),
one location, one phrase pattern (`___をください` / `___ o kudasai`), two object slots
(鍵 kagi = key, 地図 chizu = map). Product source of truth: `../business/language-learning-prd.md`
(read-only; it lives in the parent Arbitale repo).

Polytale is a standalone project. It may copy code from the parent Arbitale repo
(`..`) but NEVER imports from it and NEVER modifies anything outside `polytale/`.

## Invariants (non-negotiable)

1. **The LLM is the DM, code owns the ledgers.** The model reads a scene snapshot and commits
   changes only through typed tools. Tool executors mutate state deterministically and validate
   every id. The model never mutates world state or learning state directly.
2. **No hardcoding model output.** No regex/keyword classifiers over model prose, no rewriting
   model text. If the model misbehaves, fix the prompt, the tool declarations, or the snapshot.
   Validation failures in tool args are returned to the model as `ERROR: ...` receipts so it
   retries inside the same loop. Tests may assert on output shape.
3. **Cartridges are declarative JSON only.** No executable logic in cartridges.
4. **Speech recognition confidence is not learning evidence.** Low-confidence transcripts never
   produce negative consequences and never judge the learner.
5. **Honesty.** The recap reports observed behaviour from the ledger, never a fluency score.
6. `core/` must not import `fastapi`, `server`, or `media`. Nothing imports from the parent repo.

## Layout

```
polytale/
  core/            pure game + learning logic (no web, no network except core/gemini.py)
    gemini.py      Gemini client singleton, model cascade, thinking config
    cartridge.py   pydantic cartridge schema + load/validate
    state.py       GameState + atomic save/load
    ledger.py      learning ledger (pure functions over GameState)
    tools.py       tool declarations + executors
    prompt.py      DM system prompt + scene snapshot
    dm.py          run_turn / run_opening
    recap.py       evidence-based recap
  media/           speech providers (network)
    tts.py         synthesize(): ElevenLabs primary, Gemini fallback, disk cache
    stt.py         transcribe(): ElevenLabs Scribe primary, Gemini fallback
  server/          FastAPI app (REST only; single process)
  cartridges/<id>/cartridge.json + art/
  scripts/         standalone test + tool scripts (no pytest)
  web/             Vite + React 19 + TS + Tailwind 4 + zustand
  states/ cache/ logs/   runtime, gitignored
```

Python: venv at `~/.venvs/polytale` (Linux FS). Run scripts from `polytale/` with
`PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/<name>.py`. Load `.env` with python-dotenv
(`load_dotenv(Path(__file__).resolve().parents[N] / ".env")`) in entry points only.
Ports: API `8100`, Vite dev `5180` (proxy `/api` → 8100). Arbitale uses 8000/5173; never touch them.

## Cartridge schema (`cartridges/<id>/cartridge.json`)

```jsonc
{
  "schema_version": 1,
  "identity": { "id": "broken-airship-ja", "name": "The Broken Airship",
                "tagline": "...", "locale": "en-US" },
  "setting": {
    "premise": "support-language premise for the DM",
    "location": {
      "id": "loc.airfield", "name": "...", "description": "...",
      "art": {
        "base": "art/plate_base.png",
        // most-specific matching variant wins (count of matched keys); ties -> later entry
        "variants": [
          { "id": "panel_open", "when": { "fx.engine_panel": "open" }, "image": "art/plate_panel_open.png" },
          { "id": "launched",   "when": { "fx.airship": "launched" }, "image": "art/plate_launched.png" }
        ]
      }
    }
  },
  "npcs": [{
    "id": "npc.engineer", "name": "Hana", "role": "airship engineer",
    "persona": "...", "english": "Knows only: okay, good, no, yes.",
    "voice": { "elevenlabs_voice_id": "...", "gemini_voice": "Kore", "style": "warm, clear, unhurried" },
    "art": { "sprite": "art/engineer.png", "portrait": "art/engineer_portrait.png" },
    "stage": { "x": 0.75, "y": 0.92, "height": 0.5,     // feet x/y + height as fractions of plate
               "hand": { "x": 0.137, "y": 0.17 } }  // optional held-object anchor, fractions of the sprite box
  }],
  "objects": [   // things that can be held and handed over
    { "id": "obj.engine_key", "concept_id": "object.key", "icon": "art/icon_key.png",
      "holder": "npc.engineer" },            // "npc.<id>" | "player" | "world"
    { "id": "obj.route_map", "concept_id": "object.map", "icon": "art/icon_map.png",
      "holder": "npc.engineer" }
  ],
  "fixtures": [  // scenery with discrete states
    { "id": "fx.engine_panel", "name": "engine panel", "states": ["locked", "open"], "initial": "locked",
      "hotspot": { "x": 0.32, "y": 0.55, "r": 0.06 } },
    { "id": "fx.airship", "name": "airship", "states": ["grounded", "launched"], "initial": "grounded",
      "hotspot": { "x": 0.40, "y": 0.45, "r": 0.18 } }   // r = fraction of plate HEIGHT
  ],
  "opening": {   // authored first turn, applied through the SAME executors (no model call)
    "narration": "...",
    "actions": [ { "tool": "show_object", "args": { "object_id": "obj.engine_key", "gesture": "hold_up" } } ],
    "spoken_lines": [ { "speaker": "npc.engineer", "text": "鍵。", "language": "ja-JP",
                        "romanization": "Kagi.", "translation": "Key.",
                        "concept_ids": ["object.key"], "pattern_id": null } ]
  },
  "language_learning": {
    "target_locale": "ja-JP", "support_locale": "en-US",
    "romanization_system": "hepburn", "starting_level": "absolute_beginner",
    "input_mode": "voice_first", "narrator_language": "support",
    "concepts": [
      { "id": "object.key", "native": "鍵", "romanization": "kagi", "gloss": "key",
        "referents": ["obj.engine_key"] },
      { "id": "object.map", "native": "地図", "romanization": "chizu", "gloss": "map",
        "referents": ["obj.route_map"] },
      { "id": "word.douzo", "native": "どうぞ", "romanization": "douzo", "gloss": "here you go", "referents": [] },
      { "id": "word.hai", "native": "はい", "romanization": "hai", "gloss": "yes / okay", "referents": [] }
    ],
    "patterns": [
      { "id": "request.give_object", "function": "request an object",
        "native_template": "{object}をください", "romanization_template": "{object} o kudasai",
        "gloss_template": "Please give me the {object}.",
        "slots": { "object": ["object.key", "object.map"] } }
    ],
    "learning_beats": [
      { "id": "ground_key", "objective": "Figure out what the engineer is showing you.",
        "concept_ids": ["object.key"], "pattern": null, "slot_values": {},
        "initial_help_level": 0, "success_evidence": "recognition",
        "world_result": "none — the engineer keeps the key but reacts warmly",
        "complete_when": {},
        "help": [ /* levels 1..5, see below */ ] },
      { "id": "request_key", "objective": "Ask the engineer for the key.",
        "concept_ids": ["object.key"], "pattern": "request.give_object",
        "slot_values": { "object": "object.key" }, "initial_help_level": 1,
        "success_evidence": "production", "world_result": "engineer gives the key; the engine panel opens",
        "complete_when": { "holders": { "obj.engine_key": "player" } }, "help": [] },
      { "id": "transfer_map", "objective": "Ask for the map.",
        "concept_ids": ["object.map"], "pattern": "request.give_object",
        "slot_values": { "object": "object.map" }, "initial_help_level": 0,
        "success_evidence": "transfer", "world_result": "engineer gives the map; the airship launches",
        "complete_when": { "holders": { "obj.route_map": "player" }, "fixtures": { "fx.airship": "launched" } },
        "help": [] }
    ],
    "next_episode": "Next: ask where something is."
  }
}
```

Help entries (per beat, levels 1..5, each optional field by kind):

```jsonc
{ "level": 1, "label": "Hear it slowly", "kind": "replay_slow",
  "line": { "speaker": "npc.engineer", "text": "鍵。", "language": "ja-JP", "romanization": "Kagi.",
            "translation": "Key.", "concept_ids": ["object.key"], "pattern_id": null } }
{ "level": 2, "label": "Show the word",        "kind": "word",    "concept_ids": ["object.key"] }
{ "level": 3, "label": "Show a phrase frame",  "kind": "frame",   "pattern_id": "request.give_object" }
{ "level": 4, "label": "Hint at the meaning",  "kind": "meaning", "text": "kudasai ≈ \"please give me\"" }
{ "level": 5, "label": "Show the full answer", "kind": "full",
  "native": "鍵をください", "romanization": "Kagi o kudasai", "translation": "Please give me the key.",
  "tap_fallback": true }
```

Validation (`core/cartridge.py`, returns a list of `"<code>: <where>"` strings; loader raises
`CartridgeError` on any; art existence is NOT validated, see `missing_art(cartridge)`):
unknown npc/object/fixture/concept/pattern/beat references, concept referents not in objects,
pattern slot values not in concepts, fixture `initial` not in `states`, variant `when` keys not
fixtures or values not in that fixture's states, help levels outside 1..5 or duplicated,
`romanization_system` not in {"hepburn","pinyin","latin"}, locales not BCP-47-ish
(`^[a-z]{2,3}(-[A-Z]{2})?$`), art paths that escape the cartridge dir, target line in opening
missing romanization/translation. A cartridge without `language_learning` is still valid (plain
story mode); every learning-specific code path must tolerate that.

## Game state (`core/state.py`)

```
GameState (pydantic):
  session_id, cartridge_id, created_at, started: bool, turn: int
  world: { holders: {obj_id: holder}, fixtures: {fx_id: state},
           focus: {object_id, gesture} | null, flags: {str: bool|str|int} }
  learning: LearningState | null
  transcript: list[TranscriptEntry]   // full visible history, survives refresh
  attempts: dict[attempt_id, Attempt] // pending + consumed
  episode_complete: bool
  schema_version: 1
```

Atomic save: write `states/sessions/<session_id>.json.tmp` then `os.replace`.

```
LearningState:
  target_locale, support_locale
  active_beat_index: int            // index into learning_beats; == len(beats) when finished
  concept_stage: {concept_id: Stage}
  pattern_stage: {pattern_id: Stage}
  exposures: {concept_id: int}      // spoken NPC lines that carried this concept
  help_level: {beat_id: int}        // current level
  help_max_used: {beat_id: int}     // highest level the learner saw in that beat
  failures: {beat_id: int}          // not_understood count since last level change
  phrase_modeled: {beat_id: bool}   // an NPC line in this beat carried the beat's pattern AND slot concept
  evidence: list[EvidenceRecord]
  last_successful_construction: {pattern_id, concept_id, beat_id, support_level} | null

Stage (ordered): unseen < context_recognized < speech_recognized < produced_with_cue
                 < produced_independently < transferred
```

## Learning ledger rules (`core/ledger.py`, pure + deterministic)

- Stages only move up (`max`). Each executor call returns the resulting stages.
- `evidence_type="recognized"`: tap → `context_recognized`; speech/text → `speech_recognized`.
- `evidence_type="produced"`: tap → rejected (receipt says tap fallback recorded, no stage).
  Else if `help_max_used[beat] >= 3` or `phrase_modeled[beat]` → `produced_with_cue`;
  else → `produced_independently`.
- `evidence_type="transferred"`: needs the pattern previously produced (with_cue or better) with a
  DIFFERENT slot concept; otherwise ERROR. If `help_max_used[beat] >= 3` or `phrase_modeled[beat]`
  → the concept gets `produced_with_cue` and the pattern stage is unchanged (honest downgrade, say
  so in the receipt); else concept → `transferred` AND pattern → `transferred`.
  For produced/transferred with a pattern, the pattern stage is raised to the same stage.
- `outcome="not_understood"` never raises stages; it increments `failures[beat]`; at 2 failures the
  help level rises by one (max 5) and failures reset. `clarified`/`understood` raise stages.
- Support level recorded on evidence is the SERVER's `help_max_used[beat]`, never a model claim.
- Help: `request_help(beat)` raises level by exactly one (max 5), updates `help_max_used`,
  returns the authored cue for the new level. The DM tool `set_language_help` may set a level
  but never more than current+1 and never below current.
- Beat entry: when a beat becomes active, if `last_successful_construction` exists for the same
  pattern, `help_level = min(initial_help_level, max(0, prior_success_support - 1))` (reuse starts
  at least one level lower); otherwise `help_level = initial_help_level`. The entry level counts
  toward `help_max_used`.
- Evidence validation: `produced`/`transferred` are rejected in a `recognition` beat; their
  `pattern_id` defaults to (and must equal) the beat pattern; their concepts must be slot values
  of that pattern.
- Beat completion (checked by `advance_beat`): `complete_when` holders/fixtures all match the world
  AND the success evidence exists for this beat:
  recognition → some beat concept stage ≥ context_recognized;
  production → beat slot concept ≥ produced_with_cue, or a tap-fallback attempt at help level 5;
  transfer → beat slot concept ≥ produced_with_cue (with a recorded `transferred` evidence attempt),
  or tap fallback at level 5.
  Advancing past the last beat sets `episode_complete = true`.
- Duplicate `(attempt_id, concept_id, evidence_type)` is idempotent (no double count).
- Exposures: every delivered NPC spoken line increments `exposures` for its concept_ids.
  `phrase_modeled[beat]` becomes true when a delivered NPC line has `pattern_id == beat.pattern`
  and the beat's slot concept in its `concept_ids`.

## DM tools (`core/tools.py`)

All executors: `(state, cartridge, args, ctx) -> str receipt` (`ERROR: ...` on invalid).
`ctx` carries the current attempt (id, input_mode, transcript) and per-turn guards.

| tool | args | effect |
| --- | --- | --- |
| `show_object` | object_id, gesture ∈ hold_up/point/offer/withhold/put_away | sets `world.focus`. hold_up/offer/withhold require an NPC holder |
| `give` | object_id, to ("player" or npc id) | validates current holder is someone else; transfers; clears focus if that object |
| `set_fixture` | fixture_id, state | validates authored states |
| `record_language_evidence` | learning_beat_id (must equal active beat), concept_ids[], pattern_id?, evidence_type ∈ recognized/produced/transferred, outcome ∈ understood/clarified/not_understood, mixed_language: bool | ledger rules above; attempt_id and input_mode come from ctx, not args. Requires a player attempt this turn (ERROR on opening/help). |
| `set_language_help` | learning_beat_id, level | ledger rule; returns cue text |
| `advance_beat` | learning_beat_id (must equal active) | checks completion; ERROR explains what is missing; at most once per turn |
| `deliver_narration` | narration (support language, ≤ 2 short sentences), spoken_lines[] | TERMINAL. Validates each line: speaker is an npc id; `language` is a locale; if language == target_locale then `romanization` and `translation` are required and non-empty; concept_ids exist; pattern_id exists or null (`""` = null). Shape caps: narration ≤ 320 chars, ≤ 4 lines, line text ≤ 200 chars. Rejected (ERROR) if any other call in the same response returned ERROR, so narration never describes an uncommitted change. Invalid → ERROR receipt, loop continues. |

Receipts end with a compact NOW line (holders, fixtures, active beat, help level) so the model
always sees committed state.

## DM loop (`core/dm.py`)

- `run_turn(state, cartridge, attempt, *, client=None, models=None, trace=None)
  -> (new_state, TurnResult)` is synchronous (server wraps in a thread). Works on a deep copy;
  commits by returning the new state (caller persists). On exception (`ValueError` for a bad /
  consumed attempt or unstarted session, `core.dm.TurnError` for model failure) the caller keeps
  the old state (attempt stays unconsumed so it can be resubmitted). `attempt` is a dict
  `{attempt_id, input_mode, transcript, romanized?, detected_languages?, confidence?,
  tapped_object_id?}` (for voice, pass the stored pending `Attempt.model_dump()`).
- Function calling runs in mode `ANY` (every reply must be tool calls).
- One Gemini `generate_content` per round with all tool declarations; the prompt instructs the
  model to emit its world/ledger tool calls AND `deliver_narration` in the SAME response (one round
  on the golden path). Receipts go back as function responses; loop ends on a valid
  `deliver_narration`. Max 6 rounds, 2 nudges for prose-only replies. Model cascade on errors.
- `run_opening(state, cartridge) -> (new_state, TurnResult)` applies `cartridge.opening` through the
  same executors (no model); raises `ValueError` if already started.
- Line ids: `t{turn}-l{i}` for delivered lines; help-cue lines are `help-{beat_id}-{level}`.
  `core.views.find_line(state, cartridge, line_id)` resolves either (for the audio endpoint).
- Snapshot (built fresh each turn, in `core/prompt.py`): cartridge premise + NPC persona, world
  holders/fixtures/focus, the active learning beat (objective, pattern template native+romaji,
  slot concept, success_evidence, world_result, current help level and what that level permits),
  concept stages, the last ~12 transcript entries, and the player attempt (input_mode, transcript,
  detected languages, recognition confidence + a note that low confidence means "ask again
  gently, never judge").
- Prompt must cover every bullet in PRD §19, including: NPC speech stays in the target language
  even when the player uses English; code-switching and fragments are legitimate; resolve intent
  before form; recast understandable attempts naturally; no grammar lectures; short lines from
  authored concepts; never model the completed target sentence during a transfer beat; ground new
  words with `show_object`; never advance a beat without evidence; one round of tool calls.

### Core API used by the server

```python
from core.cartridge import load_cartridge, list_cartridges, missing_art, resolve_art_path, CartridgeError
from core.state import new_game, save_state, load_state, Attempt, GameState   # load_state -> GameState | None
from core.dm import run_turn, run_opening, TurnError
from core.ledger import request_help, learning_view      # request_help mutates state; -> HelpCue | None
from core.views import public_state, find_line            # public_state(state, cart) -> PublicState
from core.recap import build_recap                        # build_recap(state, cart) -> Recap
```

`request_help` returns None when there is no active beat (plain mode / finished); persist the
state after it. `PublicState.help_cue` is the cue for the active beat's current level (survives
refresh). `resolve_art_path(cart, rel)` returns an absolute path inside the cartridge dir or None.

## Runtime payloads (JSON, snake_case)

```ts
SpokenLine  { line_id, speaker, speaker_name, text, language, romanization, translation,
              concept_ids: string[], pattern_id: string|null, audio_url: string }
TranscriptEntry =
  | { kind: "narration", turn, text }
  | { kind: "npc", turn, line: SpokenLine }
  | { kind: "player", turn, attempt_id, input_mode: "speech"|"text"|"tap", transcript,
      romanized: string|null, tapped_object_id: string|null }
  | { kind: "evidence", turn, beat_id, concept_ids, evidence_type, outcome,
      stage_after: {concept_id: Stage|null},   // null = no stage change (tap fallback / not_understood)
      support_level, input_mode }
EvidenceEntry = the "evidence" TranscriptEntry above (TurnResult.evidence lists this turn's)
World       { holders, fixtures, focus: {object_id, gesture}|null, plate_url }
LearningView{ active_beat: { id, objective, index, total } | null,
              concept_stage: {id: stage}, pattern_stage: {id: stage},
              help_level: number, next_help: { level, label } | null,
              tap_fallback: boolean }   // true = tapping an object is a valid input right now
                                        // (recognition beat, or a level with tap_fallback)
HelpCue     { level, label, kind, text?, native?, romanization?, translation?,
              line?: SpokenLine, concepts?: [{id, native, romanization}], frame?: {native, romanization} }
TurnResult  { turn, narration, spoken_lines: SpokenLine[], world: World, learning: LearningView,
              evidence: EvidenceEntry[], episode_complete, recap: Recap|null, latency_ms }
PublicState { session_id, cartridge: CartridgeView, started, turn, transcript: TranscriptEntry[],
              world, learning, episode_complete, recap: Recap|null, help_cue: HelpCue|null }
CartridgeView { id, name, tagline, target_locale, support_locale, romanization_system,
              location: {name, plate_url},
              npcs: [{id, name, role, sprite_url, portrait_url, stage}],
              objects: [{id, concept_id, icon_url, native, romanization}],  // no English gloss
              fixtures: [{id, name, states, hotspot}] }
Transcription { attempt_id, transcript, romanized: string|null, detected_languages: string[],
              confidence: number|null, requires_confirmation: boolean, provider }
Recap       { recognized: [{concept_id, native, romanization}],
              productions: [{beat_id, concept_id, native, romanization,
                             stage,          // Stage | null (null = tap fallback, no stage)
                             support_level, input_mode, transcript}],
              transfer: { achieved: boolean, summary: string },
              lines: string[],   // observed-behaviour sentences built from the ledger
              next_episode: string }
```

English glosses (`translation`) are sent in payloads but the client hides them until the learner
reveals a line (or help level 5). Objects never expose their English gloss in CartridgeView.

## REST API (`server/`)

Auth: `session_id` + `token` from create. Send `X-Session-Token` header; audio/art GETs accept
`?token=`. Wrong/missing token → 403. Unknown session → 404.

| method | path | body / returns |
| --- | --- | --- |
| GET  | `/api/health` | `{ok, speech_provider, tts_provider}` |
| GET  | `/api/cartridges` | `[{id, name, tagline, target_locale}]` |
| GET  | `/api/cartridges/{id}/art/{path}` | image (path must stay inside cartridge dir) |
| POST | `/api/sessions` | `{cartridge_id}` → `{session_id, token, state: PublicState}` |
| GET  | `/api/sessions/{sid}` | PublicState |
| POST | `/api/sessions/{sid}/start` | TurnResult (authored opening; idempotent: second call returns 409) |
| POST | `/api/sessions/{sid}/transcribe` | multipart `audio` (≤ 5 MB, wav/webm/ogg/mp4/mpeg) + `client_recording_id` → Transcription. Does NOT touch game state except storing a pending attempt. |
| POST | `/api/sessions/{sid}/act` | `{attempt_id}` (from transcribe) OR `{text}` OR `{tap_object_id}` → TurnResult. Consumed attempt_id → 409. Turn failure → 502, attempt stays pending, state unchanged. One turn at a time per session (lock). |
| POST | `/api/sessions/{sid}/help` | `{}` → `{cue: HelpCue, learning: LearningView}`; no story turn |
| GET  | `/api/sessions/{sid}/lines/{line_id}/audio` | audio bytes; synthesized on demand, disk-cached. Slow replay is client `playbackRate` (0.7, pitch preserved). |
| GET  | `/api/sessions/{sid}/recap` | Recap (409 until episode_complete) |
| POST | `/api/sessions/{sid}/reset` | fresh state, same session id/token → PublicState |

## Speech providers (`media/`)

- Provider interface; `SPEECH_PROVIDER=auto` → ElevenLabs when `ELEVENLABS_API_KEY` is set,
  else Gemini. Both implementations exist and are tested with stubs; live tests skip cleanly
  without a key.
- TTS cache key = sha256 of (provider, model, voice, language, text, variant). Files under
  `cache/audio/`. Per-character stable voice from the cartridge NPC `voice` block.
- STT returns transcript + detected languages + confidence when available. Mixed English/Japanese
  must be preserved (no forced language). Gemini fallback asks for JSON
  `{transcript, romanized, languages, confidence}` and must not "correct" the learner.
- All provider calls have explicit timeouts (TTS 20 s, STT 15 s). A timeout raises a typed error
  the server maps to 504 (STT) or leaves text usable (TTS 503).

## Tests (standalone scripts in `scripts/`, exit non-zero on failure)

Offline: `verify_imports.py`, `test_cartridge_schema.py`, `test_ledger.py`, `test_dm_tools.py`,
`test_dm_loop_offline.py` (fake Gemini client), `test_recap.py`, `test_speech_providers.py`
(stubbed HTTP), `test_server_api.py` (FastAPI TestClient with fake DM + fake speech),
`test_web_contract.py` (greps built bundle/source for mic-first UI contract).
Live: `test_dm_live.py` (real Gemini turns on the golden path), `playtest_voice_live.py`
(synthesized learner audio → transcribe → act → world + ledger + recap),
`playtest_browser_live.py` (headless Chrome over CDP, screenshots under `logs/playtests/`).
