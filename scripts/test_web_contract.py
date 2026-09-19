#!/usr/bin/env python3
"""Offline check of the web client's mic-first UI contract (SPEC.md / PRD §§12, 13, 20).

Greps the source (and the built bundle when web/dist exists) for the contract, and
executes the WAV encoder under Node (via Vite's bundled esbuild) to verify it really
emits 16 kHz mono 16-bit PCM. Exits non-zero on any failure.

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


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'ok' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


def read(rel: str) -> str:
    p = SRC / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def all_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(SRC.rglob("*.ts*")))


def main() -> int:
    print("web contract (source)")
    src = all_source()
    dialogue = read("components/Dialogue.tsx")
    help_ui = read("components/Help.tsx")
    dock = read("components/MicDock.tsx")
    store = read("store.ts")
    api = read("lib/api.ts")
    wav = read("lib/wav.ts")
    recorder = read("audio/recorder.ts")
    player = read("audio/linePlayer.ts")
    hud = read("components/Hud.tsx")

    # Mic-first: no suggested dialogue choices anywhere in the UI.
    check("no suggested-action chips", not re.search(r"suggested_actions|SuggestedAction|suggestion-chip", src))

    # Romanization directly under native text (same component, native first), never a tooltip.
    i_native = dialogue.find('data-role="native"')
    i_roma = dialogue.find('data-role="romanization"')
    check("romanization rendered under native text", 0 <= i_native < i_roma, f"native@{i_native} roma@{i_roma}")
    check("romanization is not a tooltip", "title={line.romanization}" not in dialogue)

    # Translation hidden by default, revealed per line.
    check("translation hidden by default", "useState(false)" in dialogue and re.search(r"revealed\s*&&\s*line\.translation", dialogue) is not None)
    check("per-line reveal control", "Reveal meaning" in dialogue)
    check("replay + slow replay per line", "replay(line, 1)" in dialogue and "replay(line, SLOW_RATE)" in dialogue)
    check("slow replay is 0.7 with pitch preserved", "SLOW_RATE = 0.7" in store and "preservesPitch = true" in player)

    # Help ladder: button label comes from learning.next_help, every cue kind renders.
    check("help button label from next_help", "next_help" in help_ui and "next?.label" in help_ui)
    for kind in ("replay_slow", "word", "frame", "meaning", "full"):
        check(f"help cue kind '{kind}' rendered", f'cue.kind === "{kind}"' in help_ui)
    check("help is POSTed, never auto-applied", "/help" in api and "IDLE_OFFER_MS = 10_000" in help_ui)
    check("tap fallback hint at full rescue", "tap_fallback" in help_ui)

    # Transcript preview with cancel/retry and an auto-submit cancel window.
    check("preview shows what was heard", 'data-testid="preview"' in dock and "Heard" in dock)
    check("preview cancel + retry", 'testid="preview-cancel"' in dock and 'testid="preview-retry"' in dock)
    check("auto-submit after a short cancel window", "AUTO_SUBMIT_MS = 1200" in store)
    check("requires_confirmation blocks auto-submit", "requires_confirmation ? null" in store)
    check("empty transcript -> neutral retry", "Didn't catch that" in dock)
    check("recordings < 250 ms ignored", "MIN_RECORDING_MS = 250" in store and "MIN_RECORDING_MS" in store.split("async releaseMic")[-1])

    # Push-to-talk: pointer + touch + Space.
    check("push-to-talk pointer events", "onPointerDown" in dock and "onPointerUp" in dock and "setPointerCapture" in dock)
    check("push-to-talk Space bar", 'e.code !== "Space"' in dock)
    check("live waveform", "getByteTimeDomainData" in dock)

    # Keyboard fallback exists but is secondary.
    check("keyboard fallback present", 'data-testid="text-input"' in dock and 'data-testid="keyboard-toggle"' in dock)
    check("keyboard fallback off by default", "keyboard: false" in store)

    # Objective chip never renders a target sentence (only the beat objective).
    check("objective chip shows only objective", "beat!.objective" in hud and "native" not in hud.split("export function ObjectiveChip")[1].split("export function")[0])

    # 16 kHz WAV encoder.
    check("16 kHz target rate", "TARGET_SAMPLE_RATE = 16000" in wav)
    check("RIFF/WAVE PCM header", all(s in wav for s in ('"RIFF"', '"WAVE"', '"fmt "', '"data"')))
    check("mono 16-bit", "setUint16(22, 1, true)" in wav and "setUint16(34, 16, true)" in wav)
    check("raw PCM capture via Web Audio", "AudioWorkletNode" in recorder and "createScriptProcessor" in recorder)
    check("uploads WAV to /transcribe", "/transcribe" in api and ".wav" in api and "client_recording_id" in api)

    # Auth + persistence.
    check("X-Session-Token header", '"X-Session-Token"' in api)
    check("audio gets ?token=", "token=" in api)
    check("session persisted with try/catch", "localStorage" in read("lib/session.ts") and "catch" in read("lib/session.ts"))
    check("reduced-motion support", "prefers-reduced-motion" in read("index.css"))

    print("web contract (WAV encoder under node)")
    node = shutil.which("node")
    esbuild = WEB / "node_modules" / ".bin" / "esbuild"
    if node and esbuild.exists():
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "wav.mjs"
            subprocess.run([str(esbuild), str(SRC / "lib" / "wav.ts"), "--format=esm", f"--outfile={out}", "--log-level=error"], check=True)
            script = Path(tmp) / "run.mjs"
            script.write_text(
                "import { encodeWav, downsample } from './wav.mjs';\n"
                "const n = 48000; const x = new Float32Array(n); for (let i = 0; i < n; i++) x[i] = Math.sin(i / 10) * 0.5;\n"
                "const y = downsample(x, 48000, 16000);\n"
                "const b = encodeWav(y, 16000); const buf = Buffer.from(await b.arrayBuffer());\n"
                "process.stdout.write(JSON.stringify({len: y.length, type: b.type, hex: buf.subarray(0, 44).toString('hex'), size: buf.length}));\n"
            )
            res = subprocess.run([node, str(script)], capture_output=True, text=True, cwd=tmp)
            if res.returncode != 0:
                check("wav encoder runs", False, res.stderr[:300])
            else:
                info = json.loads(res.stdout)
                head = bytes.fromhex(info["hex"])
                riff, _, wave, fmt, fmt_len, fmt_code, ch, rate, byte_rate, align, bits, data = struct.unpack("<4sI4s4sIHHIIHH4s", head[:40])
                check("downsample 48k -> 16k (1 s)", info["len"] == 16000, str(info["len"]))
                check("WAV header RIFF/WAVE/fmt/data", (riff, wave, fmt, data) == (b"RIFF", b"WAVE", b"fmt ", b"data"))
                check("PCM mono 16 kHz 16-bit", (fmt_code, ch, rate, bits, align, byte_rate) == (1, 1, 16000, 16, 2, 32000), f"{fmt_code},{ch},{rate},{bits}")
                check("blob type audio/wav", info["type"] == "audio/wav")
                check("byte size matches samples", info["size"] == 44 + 2 * 16000)
    else:
        print("  [skip] node/esbuild not available")

    dist = WEB / "dist" / "assets"
    if dist.exists():
        print("web contract (built bundle)")
        bundle = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in dist.glob("*.js"))
        for needle in ("X-Session-Token", "preview-cancel", "preview-retry", "Hold to speak", "preservesPitch", "RIFF", "text-input", "help-button"):
            check(f"bundle contains {needle!r}", needle in bundle)
        check("bundle has no suggested actions", "suggested_actions" not in bundle)
    else:
        print("  [skip] web/dist not built (npm run build)")

    print(f"\n{len(FAILURES)} failure(s)" + (": " + ", ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
