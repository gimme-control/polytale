# Polytale

**Learn a language by needing it.** Polytale drops you into a concrete situation, such as a
late-night bar or a night-market stall, where the only other person speaks the language you are
learning. You get things done by speaking, typing, or pointing. Nothing is translated. You work
out what words mean from what you can see, and the scene changes when you are understood.

The demo language is Mandarin Chinese. The engine is language-agnostic: a language is one JSON
file (`content/languages/<locale>.json`) and scenes are language-neutral.

## What playing it is like

- You sit down at the bar. The bartender says something, generated live, and glances at the
  shelf: 「啤酒？」 *píjiǔ?* The beer bottle lights up. 「水？」 *shuǐ?* The glass lights up.
- You say "píjiǔ", type `pijiu`, or click the bottle. He slides it across the counter.
- You want to pay. You try 「多少钱？」 or point at your wallet. He tells you the price, you hand
  over the notes, and the scene is done.
- Only then do you see the word list: what you met, what you got first try, what needed a repeat
  or a hint.
- The next scene is a night-market stall. The words you mastered at the bar come back with no
  highlight and no hint. Getting them anyway is the proof that you learned them.

You can change the character's personality at any time (warm, brisk, unhinged). That changes how
they talk to you and never what the scene teaches. Try English on them: they won't understand,
and they won't break character.

## How it works

- **The LLM plays the character; code owns the ledgers.** A Gemini model reads a scene snapshot
  and commits every change through typed tools (`move_object`, `record_item`, `complete_goal`,
  `say`). Executors validate ids and apply deterministic rules. Model prose is never inspected or
  rewritten.
- **Mastery falls out of play.** The server tracks how much help each exchange needed. A correct
  response with no help marks the word mastered. One that needed a repeat, a highlight, or an
  intent hint marks it shaky, and so does a miss. Mastered words can no longer be highlighted;
  the tool layer refuses.
- **Help is two steps:** hear it again slowly with the objects lit, then a hint about what the
  character wants. There is never a translation.
- **Speech:** character lines are text first and audio right after (ElevenLabs when
  `ELEVENLABS_API_KEY` is set, otherwise Gemini), with per-word romanization drawn over the text.
  You can type, or hold the mic or Space to talk; "Heard: …" can be cancelled before it counts.
- **Art is pre-generated** (`scripts/generate_art.py`). Highlights are drawn by the client, never
  by an image model.

`SPEC.md` is the build contract, `docs/PRD.md` the product doc, `AGENTS.md` the conventions.

## Run

```bash
python3 -m venv ~/.venvs/polytale && ~/.venvs/polytale/bin/pip install -r requirements.txt
cp .env.example .env            # set GEMINI_API_KEY (optionally ELEVENLABS_API_KEY)
bash run.sh                     # http://localhost:5180  (API on :8100)
bash run.sh --stop
```

`?mock=1` runs the client against an in-browser mock of the API.

## Tests

Standalone scripts, no pytest: `PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/<name>.py`

Offline: `verify_imports`, `test_content`, `test_vocab`, `test_tools`, `test_dm_offline`,
`test_summary`, `test_language_agnostic`, `test_speech_providers`, `test_server_api`,
`test_web_contract`, `test_run_sh`, `test_matte`.
Live (needs keys; a running server for the playtests): `test_dm_live`, `test_speech_live`,
`playtest_voice_live`, `playtest_browser_live`, `playtest_web_mock`.
