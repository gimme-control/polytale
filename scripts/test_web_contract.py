#!/usr/bin/env python3
"""Offline check of the v3 web client's contract (SPEC.md "v3: the game layer" + "Web", PRD §3, §4.3, §9.4).

Reads the source (and the built bundle when web/dist exists) and executes the WAV
encoder and the scene-fit maths under Node (via Vite's bundled esbuild). No server,
no browser. Exits non-zero on any failure.

Run: PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/test_web_contract.py
"""

from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
SRC = WEB / "src"
FAILURES: list[str] = []

# Scripts a target language may be written in. None of these may appear in the client
# outside the mock (SPEC invariant 7): CJK, kana, hangul, Cyrillic, Arabic, Devanagari, Thai.
TARGET_SCRIPT = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in ((0x3040, 0x30FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xAC00, 0xD7AF), (0x0400, 0x04FF), (0x0600, 0x06FF), (0x0900, 0x097F), (0x0E00, 0x0E7F), (0xFF01, 0xFF5E), (0x3001, 0x3003))) + "]")
MOCK_FILES = {"mockApi.ts"}


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'ok' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


def read(rel: str) -> str:
    p = SRC / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def sources(include_mock: bool) -> dict[str, str]:
    out = {}
    for p in sorted(SRC.rglob("*")):
        if p.suffix in (".ts", ".tsx", ".css") and (include_mock or p.name not in MOCK_FILES):
            out[str(p.relative_to(SRC))] = p.read_text(encoding="utf-8")
    return out


def run_node(entry: str, script: str) -> dict | None:
    node = shutil.which("node")
    esbuild = WEB / "node_modules" / ".bin" / "esbuild"
    if not node or not esbuild.exists():
        print("  [skip] node/esbuild not available")
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "mod.mjs"
        subprocess.run([str(esbuild), str(SRC / entry), "--bundle", "--format=esm", f"--outfile={out}", "--log-level=error"], check=True)
        runner = Path(tmp) / "run.mjs"
        runner.write_text(script)
        res = subprocess.run([node, str(runner)], capture_output=True, text=True, cwd=tmp)
        if res.returncode != 0:
            check(f"{entry} runs under node", False, res.stderr[:300])
            return None
        return json.loads(res.stdout)


def main() -> int:
    print("web contract (source)")
    client = sources(include_mock=False)
    everything = sources(include_mock=True)
    all_client = "\n".join(client.values())
    components = "\n".join(v for k, v in client.items() if k.startswith("components/"))
    play = "\n".join(read(f"components/{n}.tsx") for n in ("PlayView", "Scene", "Subtitles", "InputBar", "TopBar", "Hud", "Notebook", "HistoryDrawer", "RubyLine"))
    notebook, phrasebook, start = read("components/Notebook.tsx"), read("components/Phrasebook.tsx"), read("components/StartScreen.tsx")
    store, api, types = read("store.ts"), read("lib/api.ts"), read("lib/types.ts")
    ruby, subs, bar, top = read("components/RubyLine.tsx"), read("components/Subtitles.tsx"), read("components/InputBar.tsx"), read("components/TopBar.tsx")
    scene, summary, css = read("components/Scene.tsx"), read("components/Summary.tsx"), read("index.css")
    html = (WEB / "index.html").read_text(encoding="utf-8")

    # Name.
    hits = [k for k, v in everything.items() if re.search(r"relay", v, re.I)]
    check("no 'Relay' in the client", not hits and "relay" not in html.lower(), str(hits))
    check("product name is Polytale", "<title>Polytale</title>" in html and "Polytale" in start)
    check("tagline", "Learn a language by needing it." in start)

    # Title: the story is the hero; difficulty is the only choice; persona is not on it.
    check("story title is the hero, Polytale the small wordmark", 'data-testid="story-title"' in start and "story?.title" in start and 'data-testid="wordmark"' in start)
    check("premise from the API", "story?.premise" in start)
    check("title art with the bar cover as fallback", "story?.art_url || catalog?.scenes[0]?.cover_url" in start)

    # Language-agnostic client.
    leaks = {k: TARGET_SCRIPT.findall(v)[:5] for k, v in client.items() if TARGET_SCRIPT.search(v)}
    check("no target-language literals outside the mock", not leaks, str(leaks))
    check("no target-language literals in index.html", not TARGET_SCRIPT.search(html))
    check("the mock does carry its script", bool(TARGET_SCRIPT.search(read("lib/mockApi.ts"))))
    check("language line comes from the API", "language.name" in start and "language.native_name" in start)

    # No translation during play; the gloss exists only on the summary.
    check("gloss is never touched by a play component", "gloss" not in play)
    check("item gloss rendered only by the summary", [k for k, v in client.items() if k.startswith("components/") and ".gloss" in v] == ["components/Summary.tsx"])
    check("per-word gloss exists only for the learner's OWN phrase", [k for k, v in client.items() if "phrase-gloss" in v] == ["components/Phrasebook.tsx"] and ".g" not in read("components/RubyLine.tsx"))
    check("the phrasebook never sees a character line", all(x not in phrasebook for x in ("transcript", "e.line", "speakingLineId", "lineAudio")) and "phrase: (jid, token, text)" in api)
    check("no translation field on a line", "translation" not in types and "translation" not in all_client.replace("no translation", "").replace("No translation", "").replace("never a translation", "").replace("still no translation", "").replace("Still no translation", ""))

    # No word list during play: a count only.
    check("word counter is a count, and lives in the notebook (story first)", "{progress.encountered} / {progress.target_count} words met" in notebook and "words met" not in top)
    check("word list only on the summary", 'data-testid="word-list"' in summary and "word-list" not in play)
    check("summary items only read by the summary", "summary.items" in summary and ".items" not in play)

    # Ruby / segments.
    check("real <ruby> with <rt> per word segment", "<ruby" in ruby and "<rt" in ruby and "segments.map" in ruby)
    check("punctuation carries no romanization", "PUNCT" in ruby and r"\p{P}" in ruby)
    check("romanization_label null -> no ruby row", "romanization_label != null" in ruby and "!showRoman" in ruby)
    check("word_spacing honoured", "language.word_spacing" in ruby)
    check("target text is lang-tagged", "lang={language.locale}" in ruby)
    check("ruby sits above the word (column layout)", "column-reverse" in css and ".ruby-line rt" in css)
    check("subtitles render segments, not flat text", "segments={l.segments}" in subs and "l.text" not in subs)
    check("lines appear as they play", "hidden[l.line_id]" in subs and "hidden" in store and "playSequence" in store)
    check("current line bright, earlier dim", 'data-current={current ? "1" : "0"}' in subs and "text-ink-3" in subs)
    check("narration + learner echo + thinking", all(s in subs for s in ('data-testid={exchange.prose.narrator ? "narration"', 'data-testid="learner-line"', 'data-testid="thinking"')))
    check("narration is prose in the story face, above the lines", "story " in subs and subs.index("exchange.prose.text") < subs.index("visible.map") and "--font-story" in css and "Newsreader" in html)
    check("the narrator is read first, then the character speaks", "readingMs(r.narration)" in store and "narrating" in store)
    check("acting early cuts to the lines", "cutToLines()" in store)

    # One input bar: text field + mic, hold-to-talk, Space, waveform, preview window.
    check("text field and mic share one bar", 'data-testid="input-bar"' in bar and 'data-testid="text-input"' in bar and 'data-testid="mic-button"' in bar)
    check("no keyboard-toggle / mode switch", "keyboard-toggle" not in all_client)
    check("Enter sends (form submit)", "onSubmit={submit}" in bar and 'enterKeyHint="send"' in bar)
    check("hold mic: pointer + touch", all(s in bar for s in ("onPointerDown", "onPointerUp", "onPointerCancel", "setPointerCapture", "touch-none")))
    check("hold Space when the field is not focused", 'e.code !== "Space"' in bar and "typing(e.target)" in bar)
    check("live waveform while listening", "getByteTimeDomainData" in bar and 'data-testid="waveform"' in bar)
    check("preview: Heard + cancel + send", all(s in bar for s in ('data-testid="preview"', "Heard", 'testid="preview-cancel"', 'testid="preview-send"')))
    check("Esc cancels / Enter sends the preview", '"Escape"' in bar and "cancelPreview()" in bar and "confirmPreview()" in bar)
    check("cancel window is 1200 ms", "AUTO_SUBMIT_MS = 1200" in store and "AUTO_SUBMIT_MS" in bar)
    check("requires_confirmation blocks auto-submit", "requires_confirmation ? null" in store)
    check("recordings < 250 ms ignored", "MIN_RECORDING_MS = 250" in store and "MIN_RECORDING_MS" in store.split("async releaseMic")[-1])
    check("input states", all(f'"{s}"' in store for s in ("idle", "listening", "transcribing", "preview", "waiting", "error")) and '"speaking"' in bar)
    check("barge-in stops playback", "linePlayer.stop(); // barge-in" in store)

    # Help is two-step and server-driven.
    check("help label comes from progress.next_help", "next.label" in top and "next_help" in top)
    check("help 2: intent hint as a caption", 'help?.kind === "hint"' in subs and 'data-testid="help-hint"' in subs)

    # HUD: clock pressure, cash, notebook, inventory.
    check("notebook: badge, toast card, drawer of clues (title + text)", all(x in top + notebook for x in ('data-testid="notebook-badge"', 'data-testid="clue-toast"', "c.title", "c.text", "cluesSeen")))
    check("trust has no meter, only a sentence", "<meter" not in all_client and "<progress" not in all_client and "is warming to you" in notebook)

    # Verbs.

    # Prices and haggling.

    # Phrasebook.
    check("phrasebook: field, result with ruby + per-word gloss, hear, use", all(x in phrasebook for x in ("How do I say", 'data-testid="phrase-input"', 'data-role="phrase-gloss"', "s.r", 'data-testid="phrase-play"', 'data-testid="phrase-use"')))
    check("'Use it' fills the input and never sends", "draft: { text: p.text" in store and "setText(draft.text)" in bar and "sendText" not in phrasebook)
    check("phrasebook states: loading, 422, your phrases", all(x in phrasebook + store for x in ('data-testid="phrase-loading"', "I can only help with what YOU want to say", "Your phrases", 'data-testid="phrase-saved"')))
    check("phrasebook says it costs nothing", "costs no time" in phrasebook)

    # Ending.
    check("ending: art, title, text, stats, then the words and phrases", all(x in summary for x in ('data-testid="ending"', "ending.art_url", "ending.title", "ending.text", "st.clues", 'data-testid="summary-phrases"')))
    check("play again", "Play again" in summary)
    check("act takes exactly one of attempt_id / text", all(s in types for s in ("{ attempt_id: string }", "{ text: string }")))
    check("payloads typed", all(s in types for s in ("interface GameView", "interface Ending", "interface Phrase", "interface Clue", 'kind: "narration"', 'kind: "clue"', "narration?: string | null")))
    check("history includes narration and clues", 'data-kind="narration"' in read("components/HistoryDrawer.tsx") and 'data-kind="clue"' in read("components/HistoryDrawer.tsx"))
    check("402 out of credits is shown as the reason", "err.status === 402 ? err.detail" in store)
    check("help is POSTed, never automatic", "/help" in api and "requestHelp" in top and "setInterval" not in top)
    check("help disabled when exhausted", "!next ||" in top)

    # Persona switcher.

    # Scene: one transform, clickable cutouts, highlight, prices, wallet, moods.
    check("art failure never blanks the screen", "onError" in scene and "onError" in read("components/Picture.tsx"))

    # Chrome.
    check("goal checklist", "scene.goals.map" in top and "line-through" in top)
    check("history drawer with replay + slow", all(s in read("components/HistoryDrawer.tsx") for s in ('testid="replay"', 'testid="replay-slow"', "SLOW_RATE")))
    check("menu: volume, finish, restart, new journey", all(s in top for s in ('data-testid="volume"', "finish-scene", "restart-scene", "new-journey")))

    # Start, intro, summary.
    check("catalog exposes the language list", "languages" in types or "languages" in api)
    check("Begin asks for the mic, declining is fine", "mic.ensure()" in store.split("async begin")[1].split("async enterScene")[0] and "decline and type instead" in read("components/StartScreen.tsx"))
    check("intro card while POST /scene runs", "scene.intro || scene.tagline" in read("components/IntroCard.tsx") and 'screen: "intro"' in store)
    check("summary: states, how it went, recall, tap to hear", all(s in summary for s in ("STATE_LABEL", "first try", "needed a repeat", "needed a hint", 'data-testid="recall-callout"', "Came back from", "api.itemAudio")))

    # API client mirrors SPEC.
    for path in ("/api/health", "/api/catalog", "/api/journeys", "/scene", "/transcribe", "/act", "/help", "/phrase", "/phrases/", "/finish", "/reset", "/lines/", "/items/"):
        check(f"api: {path}", path in api)
    check("X-Journey-Token header", '"X-Journey-Token"' in api and "X-Session-Token" not in api)
    check("audio gets ?token=", "token=${encodeURIComponent(token)}" in api)
    check("502 keeps the attempt and offers resend", "failedAct: body" in store and "Send again" in bar)
    check("409 resyncs from the server", "err.status === 409" in store)
    check("journey persisted with try/catch", "localStorage" in read("lib/session.ts") and read("lib/session.ts").count("catch") >= 3)
    check("restore from GET state on boot", "loadJourney" in store and "api.getState(saved.journey_id, saved.token)" in store)
    check("mock mode", "createMockApi" in api and 'q.get("mock")' in api)

    # Design guardrails (what made v1 sloppy).
    gradients = [k for k, v in client.items() if k.startswith("components/") and "bg-gradient" in v]
    check("gradients only as scrims over art (scene / title / ending)", set(gradients) <= {"components/Scene.tsx", "components/StartScreen.tsx", "components/Summary.tsx"}, str(gradients))
    check("no uppercase letter-spaced micro-labels", "uppercase" not in components and "tracking-wide" not in components)
    check("no glow / box-shadow chrome", "shadow-" not in components.replace("drop-shadow", "").replace("text-shadow", ""))
    accents = set(re.findall(r"--color-(?!night|sheet|ink|hair|glass)([a-z]+)", css))
    check("one accent colour", accents <= {"jade", "ember"} and "jade" in accents, str(accents))
    check("reduced motion respected", "prefers-reduced-motion" in css)
    check("fonts: Inter + one serif (Newsreader) + Noto Sans SC/JP", all(f in html for f in ("Inter", "Newsreader", "Noto+Sans+SC", "Noto+Sans+JP")) and html.count("family=") == 4)

    # 16 kHz WAV capture.
    wav, recorder, player = read("lib/wav.ts"), read("audio/recorder.ts"), read("audio/linePlayer.ts")
    check("16 kHz target rate", "TARGET_SAMPLE_RATE = 16000" in wav)
    check("raw PCM capture via Web Audio", "AudioWorkletNode" in recorder and "createScriptProcessor" in recorder)
    check("uploads WAV to /transcribe", ".wav" in api and 'form.append("audio"' in api)
    check("slow replay preserves pitch", "preservesPitch = true" in player)
    check("audio failure still shows the line", "fallbackMs" in player and "fallbackMs" in store)

    print("web contract (WAV encoder under node)")
    info = run_node(
        "lib/wav.ts",
        "import { encodeWav, downsample } from './mod.mjs';\n"
        "const n = 48000; const x = new Float32Array(n); for (let i = 0; i < n; i++) x[i] = Math.sin(i / 10) * 0.5;\n"
        "const y = downsample(x, 48000, 16000);\n"
        "const b = encodeWav(y, 16000); const buf = Buffer.from(await b.arrayBuffer());\n"
        "process.stdout.write(JSON.stringify({len: y.length, type: b.type, hex: buf.subarray(0, 44).toString('hex'), size: buf.length}));\n",
    )
    if info:
        head = bytes.fromhex(info["hex"])
        riff, _, wave, fmt, _, fmt_code, ch, rate, byte_rate, align, bits, data = struct.unpack("<4sI4s4sIHHIIHH4s", head[:40])
        check("downsample 48k -> 16k (1 s)", info["len"] == 16000, str(info["len"]))
        check("WAV header RIFF/WAVE/fmt/data", (riff, wave, fmt, data) == (b"RIFF", b"WAVE", b"fmt ", b"data"))
        check("PCM mono 16 kHz 16-bit", (fmt_code, ch, rate, bits, align, byte_rate) == (1, 1, 16000, 16, 2, 32000), f"{fmt_code},{ch},{rate},{bits}")
        check("blob type audio/wav", info["type"] == "audio/wav")
        check("byte size matches samples", info["size"] == 44 + 2 * 16000)

    print("web contract (scene fit under node)")
    fit = run_node(
        "lib/cover.ts",
        "import { fitScene, safeBox } from './mod.mjs';\n"
        "const scene = { npc: { anchor: { x: 0.5, y: 0.3 } }, objects: [\n"
        "  { positions: { display: { x: 0.18, y: 0.55, h: 0.16 }, counter: { x: 0.4, y: 0.88, h: 0.3 } } },\n"
        "  { positions: { display: { x: 0.8, y: 0.55, h: 0.14 } } } ] };\n"
        "const safe = safeBox(scene, 16 / 9); const out = { safe };\n"
        "for (const [w, h] of [[1440, 900], [1920, 1080], [1024, 768], [390, 844], [2560, 1080], [844, 390]])\n"
        "  out[`${w}x${h}`] = fitScene(w, h, 2400, 1350, safe, { top: w < 640 ? 104 : 0, bottom: w < 640 ? 300 : 0 });\n"
        "process.stdout.write(JSON.stringify(out));\n",
    )
    if fit:
        safe = fit.pop("safe")
        for label, f in fit.items():
            w, h = (int(v) for v in label.split("x"))
            aspect_ok = abs(f["width"] / f["height"] - 16 / 9) < 1e-6
            x0, x1 = f["left"] + safe["x0"] * f["width"], f["left"] + safe["x1"] * f["width"]
            y0, y1 = f["top"] + safe["y0"] * f["height"], f["top"] + safe["y1"] * f["height"]
            inside = x0 >= -0.5 and x1 <= w + 0.5 and y0 >= -0.5 and y1 <= h + 0.5
            check(f"fit {label}: aspect kept, safe box in frame", aspect_ok and inside, f"frame {[round(f[k]) for k in ('left', 'top', 'width', 'height')]}")
        f = fit["1920x1080"]
        check("16:9 window is plain cover", (round(f["left"]), round(f["top"]), round(f["width"]), round(f["height"])) == (0, 0, 1920, 1080))
        check("phone portrait letterboxes instead of cropping the shelves", fit["390x844"]["letterboxed"] and fit["390x844"]["top"] > 0)

    dist = WEB / "dist" / "assets"
    if dist.exists():
        print("web contract (built bundle)")
        bundle = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in dist.glob("*.js"))
        for needle in ("X-Journey-Token", "preview-cancel", "words met", "Say something", "preservesPitch", "RIFF", "Came back from", "How do I say", "Play again"):
            check(f"bundle contains {needle!r}", needle in bundle)
        check("bundle has no 'Relay'", "Relay" not in bundle)
    else:
        print("  [skip] web/dist not built (npm run build)")

    print(f"\n{len(FAILURES)} failure(s)" + (": " + ", ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
