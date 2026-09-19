# AGENTS.md - Polytale

Polytale is a scenario-based language learning game for adults: a live LLM character who speaks
only the target language, a scene you can see, and tasks you complete by speaking, typing, or
pointing. `SPEC.md` is the build contract (content schema, vocabulary rules, tools, payloads,
REST). `docs/PRD.md` is the product doc. The name is Polytale.

Polytale lives inside the Arbitale checkout only so code can be copied from it. It is a separate
project with its own git repo: never import from the parent directory and never modify it.

## Invariants

- The LLM plays the character and commits every change through typed tools; executors in
  `core/tools.py` validate ids and mutate state deterministically. Code owns the world and the
  vocabulary record.
- No hardcoding model output: no regex or keyword guards over model prose, no rewriting it. Fix
  the prompt (`core/prompt.py`), the tool declarations, or the snapshot. Invalid tool args come
  back to the model as `ERROR:` receipts inside the same loop.
- No native-language translation during play. Glosses appear only on the end-of-scene summary.
- Everything taught must be showable on screen. Highlights are drawn by the client from object
  ids; art is generated offline (`scripts/generate_art.py`), never at runtime.
- Language-agnostic: no target-language literals in `core/`, `server/`, `media/`, `web/src`. They
  live in `content/languages/<locale>.json` (`scripts/test_language_agnostic.py` enforces this).
- Outcomes (first try / with help / with hint / missed) are stamped from the server's exchange
  ledger, never from a model claim. The summary reports observed behaviour. No scores.
- Content is declarative JSON. `core/` never imports `fastapi`, `server`, or `media`.

## Run

```bash
bash run.sh           # API :8100 + web :5180
bash run.sh --quiet   # detached
bash run.sh --stop    # also clears any leftover Polytale server holding :8100/:5180
bash run.sh --prod    # built SPA + API on :8100
```

Venv: `~/.venvs/polytale` (Linux filesystem). Env: `.env` (see `.env.example`).
`GEMINI_API_KEY` is required. `ELEVENLABS_API_KEY` switches speech to ElevenLabs; without it
Gemini handles TTS and STT.

## Testing

Test-driven. Standalone scripts under `scripts/` (no pytest), run from `polytale/`:

```bash
PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/<name>.py
```

Run the scripts covering a change, `scripts/verify_imports.py`, `ruff check .`, `mypy core media
server`, and `npx tsc --noEmit && npm run build` in `web/` before declaring done.
