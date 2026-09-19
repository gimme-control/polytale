# AGENTS.md - Polytale

Polytale (working title "Relay") is a voice-first adventure for learning practical spoken
language. `SPEC.md` is the build contract (layout, cartridge schema, ledger rules, tools,
payloads, REST API). The product doc is `../business/language-learning-prd.md`.

Polytale lives inside the Arbitale checkout only so code can be copied from it. It is a separate
project with its own git repo: never import from the parent directory and never modify it.

## Invariants

- The LLM is the DM. It commits every change through typed tools; executors in `core/tools.py`
  validate ids and mutate state deterministically. Code owns both the world and the learning
  ledger.
- No hardcoding model output: no regex or keyword guards over model prose, no rewriting what the
  model wrote. Fix the prompt (`core/prompt.py`), the tool declarations, or the snapshot instead.
  Invalid tool args come back to the model as `ERROR:` receipts inside the same loop.
- Recognition confidence is never learning evidence. A tap fallback never counts as speech.
- The recap reports observed behaviour from the ledger. No fluency scores.
- Cartridges are declarative JSON. Art is generated offline (`scripts/generate_art.py`).
- `core/` never imports `fastapi`, `server`, or `media` (`scripts/verify_imports.py`).

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
