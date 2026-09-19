#!/usr/bin/env python3
"""Live browser playtest: real backend (no mock), real learner audio, headless Chrome.

The web app is driven over CDP through the whole golden path with REAL microphone
audio. Per-utterance input: a test-only override of navigator.mediaDevices.getUserMedia
(installed with Page.addScriptToEvaluateOnNewDocument — never shipped in the bundle)
returns a MediaStream fed by an AudioBufferSourceNode -> MediaStreamDestination; for
each utterance the test holds the mic (Space on desktop, touch on mobile), plays the
chosen WAV fixture into that stream, and releases after the clip. The real
/transcribe -> "Heard" preview -> auto-submit -> /act -> audio pipeline runs.

Sequence: Start -> kagi.wav (retry once if the beat doesn't advance) -> key_kudasai.wav
(fallback kagi_o_kudasai.wav) -> Help in the transfer beat -> slow replay + meaning
reveal -> refresh mid-episode -> chizu_please.wav (fallback chizu_o_kudasai.wav) ->
launch -> recap -> Play again. Desktop 1440x900 and mobile 390x844.

Needs the API on :8100 (real Gemini) and Vite on :5180. Screenshots + timings.json go
to logs/playtests/browser_live_<ts>/.

Run: PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/playtest_browser_live.py [desktop|mobile|all]
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
import wave
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

from scripts.playtest_web_mock import Page, launch_chrome, open_page  # shared CDP driver

ROOT = Path(__file__).resolve().parents[1]
WEB = os.environ.get("POLYTALE_WEB", "http://localhost:5180")
API = os.environ.get("POLYTALE_API", "http://127.0.0.1:8100")
FIX = ROOT / "scripts" / "fixtures" / "learner_audio"
FAILURES: list[str] = []
TIMINGS: list[dict] = []

MIC_OVERRIDE = r"""
(() => {
  const hook = { ctx: null, dest: null, clips: {} };
  window.__ptMic = hook;
  const ensure = () => {
    if (!hook.ctx) {
      hook.ctx = new AudioContext();
      hook.dest = hook.ctx.createMediaStreamDestination();
    }
    return hook;
  };
  hook.load = async (name, b64) => {
    const h = ensure();
    const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    h.clips[name] = await h.ctx.decodeAudioData(bin.buffer);
    return h.clips[name].duration;
  };
  hook.play = async (name) => {
    const h = ensure();
    await h.ctx.resume();
    const src = h.ctx.createBufferSource();
    src.buffer = h.clips[name];
    src.connect(h.dest);
    src.start();
    return h.clips[name].duration;
  };
  if (navigator.mediaDevices) {
    navigator.mediaDevices.getUserMedia = async () => ensure().dest.stream;
  }
})();
"""


def check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"  [{'ok' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)
    return bool(cond)


class LivePage(Page):
    """Page that also records network responses (audio status codes, API calls)."""

    def __init__(self, ws) -> None:
        super().__init__(ws)
        self.responses: list[dict] = []

    async def call(self, method: str, **params):
        self.seq += 1
        my = self.seq
        await self.ws.send(json.dumps({"id": my, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            m = msg.get("method")
            if m == "Runtime.exceptionThrown":
                d = msg["params"]["exceptionDetails"]
                self.errors.append(str(d.get("exception", {}).get("description") or d.get("text"))[:300])
            elif m == "Runtime.consoleAPICalled" and msg["params"].get("type") == "error":
                args = msg["params"].get("args", [])
                self.errors.append("console.error: " + " ".join(str(a.get("value", a.get("description", ""))) for a in args)[:300])
            elif m == "Network.responseReceived":
                r = msg["params"]["response"]
                if "/api/" in r["url"]:
                    self.responses.append({"url": r["url"], "status": r["status"], "t": time.monotonic()})
            elif m == "Network.loadingFailed":
                p = msg["params"]
                if not p.get("canceled"):
                    self.errors.append(f"network failed: {p.get('errorText')} {p.get('requestId')}")
            if msg.get("id") == my:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})


async def live_page() -> LivePage:
    base = await open_page()
    p = LivePage(base.ws)
    await p.call("Network.enable")
    await p.call("Network.setCacheDisabled", cacheDisabled=False)
    await p.call("Page.addScriptToEvaluateOnNewDocument", source=MIC_OVERRIDE)
    return p


def clip_seconds(name: str) -> float:
    with wave.open(str(FIX / name)) as w:
        return w.getnframes() / w.getframerate()


async def load_clips(p: Page) -> None:
    for f in sorted(FIX.glob("*.wav")):
        b64 = base64.b64encode(f.read_bytes()).decode()
        await p.eval(f"window.__ptMic.load({json.dumps(f.name)}, {json.dumps(b64)})")


def q(sel: str) -> str:
    return f"document.querySelector({json.dumps(sel)})"


async def counts(p: Page) -> dict:
    return await p.eval(
        "({npc: document.querySelectorAll('[data-kind=npc]').length,"
        " player: document.querySelectorAll('[data-kind=player]').length,"
        " objective: document.querySelector('[data-role=objective-text]')?.textContent || '',"
        " phase: document.querySelector('[data-testid=mic-button]')?.dataset.phase,"
        " speaking: document.querySelector('[data-testid=mic-button]')?.dataset.speaking})"
    )


async def wait_settled(p: Page, timeout: float = 90) -> bool:
    """Turn done and NPC audio finished (or failed)."""
    return await p.wait_for(
        f"{q('[data-testid=mic-button]')}?.dataset.phase === 'idle' && {q('[data-testid=mic-button]')}?.dataset.speaking === '0'"
        f" || {q('[data-testid=end-card]')}",
        timeout, 0.2,
    )


async def speak(p: Page, clip: str, mobile: bool, out: Path, tag: str) -> dict:
    """Hold the mic, play the fixture into the fake stream, release; time the pipeline."""
    before = await counts(p)
    dur = clip_seconds(clip)
    mic_sel = "[data-testid=mic-button]"
    if mobile:
        x, y = await p.center(mic_sel)
        await p.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
    else:
        await p.space_down()
    ok = await p.wait_for(f"{q(mic_sel)}.dataset.phase === 'listening'", 5, 0.05)
    check(f"[{tag}] mic listening", ok)
    await asyncio.sleep(0.15)
    await p.eval(f"window.__ptMic.play({json.dumps(clip)})")
    await asyncio.sleep(dur * 0.6)
    await p.shot(out, f"{tag}_listening")
    await asyncio.sleep(dur * 0.4 + 0.35)
    if mobile:
        await p.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
    else:
        await p.space_up()
    t_release = time.monotonic()
    t = {"clip": clip, "tag": tag, "clip_s": round(dur, 2)}

    # Poll the pipeline at 50 ms.
    heard = None
    t_preview = t_text = t_audio = None
    deadline = t_release + 120
    shot_preview = False
    while time.monotonic() < deadline:
        s = await p.eval(
            "({phase: document.querySelector('[data-testid=mic-button]')?.dataset.phase,"
            " speaking: document.querySelector('[data-testid=mic-button]')?.dataset.speaking,"
            " heard: document.querySelector('[data-role=heard]')?.textContent || null,"
            " state: document.querySelector('[data-testid=mic-status] [data-state]')?.dataset.state || null,"
            " npc: document.querySelectorAll('[data-kind=npc]').length})"
        )
        now = time.monotonic()
        if t_preview is None and (s["heard"] or s["state"] in ("empty", "error")):
            t_preview = now
            heard = s["heard"]
            if s["state"] == "empty":
                break
        if s["heard"] and not shot_preview:
            shot_preview = True
            await p.shot(out, f"{tag}_preview")
        if s["phase"] == "preview" and t_preview and now - t_preview > 2.6:
            # requires_confirmation: no auto-submit — confirm explicitly like a learner would.
            t["confirmed_manually"] = True
            await p.click("[data-testid=preview-send]")
        if t_text is None and s["npc"] > before["npc"]:
            t_text = now
        if t_audio is None and s["speaking"] == "1" and t_text is not None:
            t_audio = now
        if s["state"] == "error":
            break
        if t_text is not None and (t_audio is not None or now - t_text > 25):
            break
        await asyncio.sleep(0.05)
    t["heard"] = heard
    t["release_to_preview_s"] = round(t_preview - t_release, 2) if t_preview else None
    t["preview_to_npc_text_s"] = round(t_text - t_preview, 2) if t_text and t_preview else None
    t["npc_text_to_first_audio_s"] = round(t_audio - t_text, 2) if t_audio and t_text else None
    t["release_to_first_audio_s"] = round(t_audio - t_release, 2) if t_audio else None
    TIMINGS.append(t)
    print(f"    {tag}: heard={heard!r} timings={ {k: v for k, v in t.items() if k.endswith('_s')} }")
    if t_text:
        await asyncio.sleep(0.6)
        await p.shot(out, f"{tag}_npc_reply")
    await wait_settled(p)
    return t


async def run(mobile: bool, out: Path) -> None:
    label = "mobile" if mobile else "desktop"
    print(f"{label} {'390x844' if mobile else '1440x900'}")
    p = await live_page()
    p.errors.clear()
    await p.viewport(390, 844, True) if mobile else await p.viewport(1440, 900, False)
    await p.call("Page.navigate", url=WEB + "/")
    await p.wait_for("document.readyState === 'complete'", 15)
    await p.eval("localStorage.clear(); true")
    await p.call("Page.reload", ignoreCache=True)
    check("start screen", await p.wait_for(q("[data-testid=start-button]"), 20))
    await p.eval("document.fonts.ready.then(() => true)")
    await load_clips(p)
    await asyncio.sleep(1.0)
    pre = "m" if mobile else "d"
    await p.shot(out, f"{pre}01_start")

    t0 = time.monotonic()
    await p.click("[data-testid=start-button]")
    check("play view (real /sessions + /start)", await p.wait_for(q("[data-testid=play-view]"), 30))
    check("opening line shown", await p.wait_for("document.querySelectorAll('[data-kind=npc]').length >= 1", 30))
    opening_text = time.monotonic() - t0
    got_audio = await p.wait_for(f"{q('[data-testid=mic-button]')}.dataset.speaking === '1'", 20, 0.05)
    TIMINGS.append({"tag": f"{pre}_opening", "start_to_text_s": round(opening_text, 2),
                    "start_to_first_audio_s": round(time.monotonic() - t0, 2) if got_audio else None})
    check("opening audio plays", got_audio)
    await asyncio.sleep(0.5)
    await p.shot(out, f"{pre}02_opening_speaking")
    await wait_settled(p)
    check("key held up", await p.eval(f"!!{q('[data-focus][data-gesture]')}"))
    check("plate base", await p.eval("[...document.querySelectorAll('[data-plate-url]')].pop()?.dataset.plateUrl.includes('plate_base')"))

    # Beat 1: name the key.
    for attempt in range(2):
        await speak(p, "kagi.wav", mobile, out, f"{pre}03_kagi_{attempt}")
        c = await counts(p)
        if "Figure out" not in c["objective"]:
            break
    check("beat 1 -> request beat", "Figure out" not in (await counts(p))["objective"], (await counts(p))["objective"])

    # Beat 2: ask for the key.
    for clip in ("key_kudasai.wav", "kagi_o_kudasai.wav", "kagi_o_kudasai.wav"):
        await speak(p, clip, mobile, out, f"{pre}04_{clip[:-4]}")
        if await p.eval(f"!!{q('[data-inv-slot=\"obj.engine_key\"]')}"):
            break
    check("key in the pack", await p.wait_for(q('[data-inv-slot="obj.engine_key"]'), 5))
    check("plate -> panel_open", await p.wait_for("[...document.querySelectorAll('[data-plate-url]')].pop()?.dataset.plateUrl.includes('panel_open')", 10))
    await p.shot(out, f"{pre}05_key_given")

    # Slow replay + meaning reveal on a real line.
    n_audio = len([r for r in p.responses if "/audio" in r["url"]])
    await p.eval("[...document.querySelectorAll('button[aria-label=\"Replay slowly\"]')].pop()?.click(); true")
    check("slow replay plays", await p.wait_for(f"{q('[data-testid=mic-button]')}.dataset.speaking === '1'", 15, 0.05))
    await p.eval("[...document.querySelectorAll('button[aria-label=\"Reveal meaning\"]')].pop()?.click(); true")
    check("meaning revealed", await p.wait_for(q("[data-role=translation]"), 3))
    await asyncio.sleep(0.4)
    await p.shot(out, f"{pre}06_slow_replay_meaning")
    await wait_settled(p)
    check("slow replay hit audio endpoint", len([r for r in p.responses if "/audio" in r["url"]]) >= n_audio)

    # Refresh mid-episode: rebuilt from GET /api/sessions/{sid}.
    before = await counts(p)
    await p.call("Page.reload")
    check("refresh restores play view", await p.wait_for(q("[data-testid=play-view]"), 20))
    await asyncio.sleep(1.0)
    after = await counts(p)
    check("refresh keeps transcript", after["npc"] == before["npc"] and after["player"] == before["player"], f"{before} -> {after}")
    check("refresh keeps key in pack", await p.eval(f"!!{q('[data-inv-slot=\"obj.engine_key\"]')}"))
    await load_clips(p)
    await p.shot(out, f"{pre}07_after_refresh")

    # Transfer beat: one real Help, then ask for the map.
    lvl0 = await p.eval(f"{q('[data-testid=help-button]')}?.dataset.level")
    await p.click("[data-testid=help-button]")
    check("real /help returns a cue", await p.wait_for(q("[data-testid=help-card]"), 15))
    kind = await p.eval(f"{q('[data-testid=help-card]')}?.dataset.kind")
    lvl1 = await p.eval(f"{q('[data-testid=help-button]')}?.dataset.level")
    check("help level rose by one", lvl1 is not None and lvl0 is not None and int(lvl1) == int(lvl0) + 1, f"{lvl0}->{lvl1} ({kind})")
    await asyncio.sleep(0.6)
    await p.shot(out, f"{pre}08_help_{kind}")
    await wait_settled(p, 30)

    for clip in ("chizu_please.wav", "chizu_o_kudasai.wav", "chizu_o_kudasai.wav"):
        await speak(p, clip, mobile, out, f"{pre}09_{clip[:-4]}")
        if await p.eval(f"!!{q('[data-testid=launch-light]')} || !!{q('[data-testid=end-card]')}"):
            break
    check("launch moment", await p.wait_for(q("[data-testid=launch-light]"), 10))
    check("plate -> launched", await p.eval("[...document.querySelectorAll('[data-plate-url]')].pop()?.dataset.plateUrl.includes('launched')"))
    check("map in the pack", await p.eval(f"!!{q('[data-inv-slot=\"obj.route_map\"]')}"))
    await asyncio.sleep(1.5)
    await p.shot(out, f"{pre}10_launch")
    check("recap end card", await p.wait_for(q("[data-testid=end-card]"), 40))
    check("recap has content", await p.wait_for(q("[data-testid=recap-lines]"), 10))
    await asyncio.sleep(1.0)
    await p.shot(out, f"{pre}11_recap")
    if mobile:
        await p.eval(f"{q('[data-testid=end-card]')}.scrollTo(0, 99999); true")
        await asyncio.sleep(0.4)
        await p.shot(out, f"{pre}12_recap_scrolled")
    recap_text = await p.eval(f"{q('[data-testid=end-card]')}.innerText")
    print("    recap:", " | ".join(recap_text.split("\n")[:24]))

    # Play again (POST reset + start).
    await p.click("[data-testid=play-again]")
    check("play again -> fresh opening", await p.wait_for(
        f"!{q('[data-testid=end-card]')} && document.querySelectorAll('[data-kind=npc]').length === 1 && {q('[data-role=objective-text]')}?.textContent.includes('Figure out')", 30))
    await asyncio.sleep(1.0)
    await p.shot(out, f"{pre}13_play_again")
    await wait_settled(p, 30)

    audio = [r for r in p.responses if "/audio" in r["url"]]
    bad = [r for r in audio if r["status"] not in (200, 206)]  # 206 = media range request
    check("every NPC audio request 200/206", bool(audio) and not bad, f"{len(audio)} requests, bad={[(r['status'], r['url'][-40:]) for r in bad]}")
    api_bad = [r for r in p.responses if r["status"] >= 400 and "/audio" not in r["url"]]
    check("no failed API calls", not api_bad, str([(r["status"], r["url"][-50:]) for r in api_bad]))
    overflow = await p.eval("document.documentElement.scrollWidth > window.innerWidth")
    check("no horizontal overflow", not overflow)
    errs = [e for e in p.errors if "[vite]" not in e]
    check("no console errors", not errs, "; ".join(errs[:3]))
    await p.ws.close()


async def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    out = ROOT / "logs" / "playtests" / f"browser_live_{datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    print(f"browser live playtest -> {out}")
    try:
        health = json.loads(urlopen(API + "/api/health", timeout=5).read())
        print(f"api: {health}")
        urlopen(WEB, timeout=5).read(64)
    except Exception as exc:
        raise SystemExit(f"API (:8100) and Vite (:5180) must be running: {exc}")
    proc = launch_chrome()
    try:
        if which in ("all", "desktop"):
            await run(False, out)
        if which in ("all", "mobile"):
            await run(True, out)
    finally:
        (out / "timings.json").write_text(json.dumps(TIMINGS, indent=2, ensure_ascii=False))
        if proc is not None:
            proc.terminate()
    print(f"\n{len(FAILURES)} failure(s)" + (": " + ", ".join(FAILURES) if FAILURES else ""))
    print(f"screenshots: {out}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
