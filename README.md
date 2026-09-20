# Polytale

**Learn a language by needing it.** Polytale drops you into a concrete situation — a bar packed
with football fans on World Cup final night — where nobody speaks your language. You get what you
need by talking. Nothing is translated. You work out what words mean from what is happening, and
the night moves when you are understood.

The engine is language-agnostic: a language is one JSON file
(`content/languages/<locale>.json`) and the scene is language-neutral. Four ship today —
Mandarin, Japanese, Spanish and Korean — and you pick one before you start.

## What playing it is like

- You push into a bar full of supporters. One of them turns round, sees a stranger, and grins.
  He says something, generated live, and points at the TV.
- You show him a photo of your friend Mei. Half the room starts shouting at once: they all know
  her.
- They will not send a stranger after one of their own until they have decided you are all right,
  and tonight that means one thing: you are here for the football. Cheer the goal on the replay.
  Try the chant they are teaching you, badly. Take the spare scarf. Toast the team.
- Then they tell you exactly where she is — fan zone, gate 2 — and half the bar walks you there.
- Only at the end do you see the word list: what you met, what you got first try, what needed a
  repeat or a hint.

It is built to be played in about five minutes.

## How it works

- **The LLM plays the character; code owns the ledgers.** A Gemini model reads a scene snapshot
  and commits every change through typed tools (`record_item`, `adjust_trust`, `reveal_clue`,
  `set_flag`, `say`). Executors validate ids and apply deterministic rules. Model prose is never
  inspected or rewritten.
- **Mastery falls out of play.** The server tracks how much help each exchange needed. A correct
  response with no help marks the word mastered; one that needed a repeat or an intent hint marks
  it shaky, and so does a miss. Mastered words can no longer be highlighted; the tool layer
  refuses.
- **Help is two steps:** hear it again slowly, then a hint about what the character wants. There
  is never a translation.
- **Slang is the point.** Each language file carries what fans actually shout — 加油, がんばれ,
  ¡vamos!, 화이팅 — alongside the plain words, so what you learn is what you would really hear.
- **Speech:** character lines are text first and audio right after (ElevenLabs when
  `ELEVENLABS_API_KEY` is set, otherwise Gemini), with per-word romanization drawn over the text
  for the languages that need it. You can type, or hold the mic or Space to talk; "Heard: …" can
  be cancelled before it counts.
- **Art is pre-generated** (`scripts/generate_art.py`), never drawn at runtime.

`SPEC.md` is the build contract, `docs/PRD.md` the product doc, `AGENTS.md` the conventions.

## Run

```bash
python3 -m venv ~/.venvs/polytale && ~/.venvs/polytale/bin/pip install -r requirements.txt
cp .env.example .env            # set GEMINI_API_KEY (optionally ELEVENLABS_API_KEY)
bash run.sh                     # http://localhost:5180  (API on :8100)
bash run.sh --stop
```

`?mock=1` runs the client against an in-browser mock of the API, with no keys and no cost.

## Tests

Standalone scripts, no pytest: `PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/<name>.py`

Offline: `verify_imports`, `test_content`, `test_vocab`, `test_tools`, `test_dm_offline`,
`test_summary`, `test_language_agnostic`, `test_speech_providers`, `test_server_api`,
`test_web_contract`, `test_run_sh`, `test_matte`.
`test_dm_offline` plays the whole demo (photo → chant → trust → gate → the `found` ending), and
`test_language_agnostic` runs it in all four locales.

Live (needs keys): `test_speech_live`.

The live DM, live voice and browser playtests (`test_dm_live`, `playtest_voice_live`,
`playtest_browser_live`, `playtest_web_mock`) were built around items, cash, the clock,
difficulty modes and personas. They were removed with those features and still need
re-authoring against the streamlined shape.
