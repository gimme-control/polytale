# Polytale (working title: Relay)

**Learn a language by needing it.** A voice-first adventure where an absolute beginner learns to
speak Japanese by making themselves understood to an airship engineer who barely speaks English.

The demo episode, *The Broken Airship*, runs 3–5 minutes:

1. **Recognition.** Hana holds up a key: 「鍵。」 *kagi*. You say it back, or tap it.
2. **Supported production.** She holds the key out of reach and models 「鍵をください」
   *kagi o kudasai*. You ask for it (broken, mixed, "key… kudasai" all count), she recasts
   it naturally and hands it over. The engine panel opens.
3. **Transfer.** She holds up a map: 「地図」 *chizu*. Nobody shows you the sentence this time.
   You reuse the pattern, she hands you the map, and the airship launches.

The end card reports only what the ledger observed ("You reused the request for the map without
the full phrase"). It never shows a fluency score.

## How it works

- **The LLM runs the scene, code owns the ledgers.** A Gemini DM reads a scene snapshot and
  commits every change through typed tools (`show_object`, `give`, `set_fixture`,
  `record_language_evidence`, `set_language_help`, `advance_beat`, `deliver_narration`).
  Executors validate ids and apply deterministic rules. The learning stages are
  `unseen → context_recognized → speech_recognized → produced_with_cue →
  produced_independently → transferred`.
- **Honest evidence.** Support level comes from the server's help ledger, not the model. If the
  full phrase was modeled or the frame was shown, production counts as *with cue*. Tapping never
  counts as speech, and recognition confidence never counts as learning.
- **Help ladder (0–5).** Context → hear it slowly → the word → a phrase frame → a meaning hint →
  the full answer plus a tap fallback. Each press goes up exactly one level. A reused pattern
  starts lower than it did last time.
- **Voice.** Push-to-talk records 16 kHz WAV. The server transcribes it, and the client shows
  "Heard: …" with Cancel / Retry before anything touches the world. NPC lines arrive as text
  first; audio follows (ElevenLabs when `ELEVENLABS_API_KEY` is set, otherwise Gemini), with
  replay and slow replay. Romanization always sits under the native text. Translations stay
  hidden until you ask.

`SPEC.md` is the full build contract. `AGENTS.md` has the conventions.

## Run

```bash
python3 -m venv ~/.venvs/polytale && ~/.venvs/polytale/bin/pip install -r requirements.txt
cp .env.example .env            # set GEMINI_API_KEY (and optionally ELEVENLABS_API_KEY)
bash run.sh                     # http://localhost:5180  (API on :8100)
```

Before a demo, run `PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/warm_cache.py` to
pre-synthesize the authored audio. Art is pre-generated (`scripts/generate_art.py`) and never
generated at runtime. `?mock=1` runs the client against an in-browser mock of the API.

## Tests

Offline: `verify_imports`, `test_cartridge_schema`, `test_ledger`, `test_dm_tools`,
`test_dm_loop_offline`, `test_recap`, `test_speech_providers`, `test_server_api`, `test_matte`,
`test_run_sh` (dev runner: stale servers, reruns, Ctrl-C, foreign port owners),
`test_web_contract`.
Live (needs keys and a running server): `test_dm_live`, `test_speech_live`,
`playtest_voice_live` (recorded learner audio → STT → DM → TTS over HTTP),
`playtest_edges_live` (English-only, early map request, gibberish, tap fallback),
`playtest_browser_live` (headless Chrome with injected mic audio), `playtest_web_mock`.

```bash
PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/<name>.py
```
