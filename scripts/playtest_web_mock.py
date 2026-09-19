#!/usr/bin/env python3
"""Headless-Chrome playtest of the web client against the in-browser mock API.

Walks the full mock golden path at 1440x900 and again at phone width (390x844):
start -> mic hold (mouse / Space / touch) -> "Heard" preview -> auto-submit ->
cancel + empty-transcript recovery -> help ladder -> key request (flight into the
pack, panel opens) -> meaning reveal -> map request -> launch -> recap -> play again.
Screenshots land in logs/playtests/web_mock_<timestamp>/.

Needs the Vite dev server (cd web && npx vite, port 5180). Chrome is launched
headless on CDP port 9335 unless one is already listening there.

Run: PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/playtest_web_mock.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

import websockets

ROOT = Path(__file__).resolve().parents[1]
WEB = os.environ.get("POLYTALE_WEB", "http://localhost:5180")
PORT = int(os.environ.get("CDP_PORT", "9335"))
CDP = f"http://127.0.0.1:{PORT}"
CHROME = os.environ.get("CHROME", "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe")
PROFILE = os.environ.get("CHROME_PROFILE", r"C:\Users\haris\AppData\Local\Temp\polytale-chrome-web")
FIXTURES = ROOT / "scripts" / "fixtures" / "learner_audio"

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'ok' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


def win_path(p: Path) -> str:
    try:
        return subprocess.check_output(["wslpath", "-w", str(p)], text=True).strip()
    except Exception:
        return str(p)


def cdp_up() -> bool:
    try:
        urlopen(CDP + "/json/version", timeout=2).read()
        return True
    except Exception:
        return False


def launch_chrome() -> subprocess.Popen | None:
    if cdp_up():
        print(f"using Chrome already on :{PORT}")
        return None
    args = [
        CHROME,
        "--headless=new",
        f"--remote-debugging-port={PORT}",
        f"--user-data-dir={PROFILE}",
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        "--autoplay-policy=no-user-gesture-required",
        "--window-size=1440,900",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    wav = next(iter(sorted(FIXTURES.glob("*.wav"))), None) if FIXTURES.exists() else None
    if wav:
        args.append(f"--use-file-for-fake-audio-capture={win_path(wav)}")
        print(f"fake mic input: {wav.name}")
    args.append("about:blank")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        if cdp_up():
            return proc
        time.sleep(0.25)
    raise SystemExit("Chrome did not open the CDP port")


class Page:
    def __init__(self, ws) -> None:
        self.ws = ws
        self.seq = 0
        self.errors: list[str] = []

    async def call(self, method: str, **params):
        self.seq += 1
        my = self.seq
        await self.ws.send(json.dumps({"id": my, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("method") == "Runtime.exceptionThrown":
                d = msg["params"]["exceptionDetails"]
                self.errors.append(str(d.get("exception", {}).get("description") or d.get("text"))[:300])
            if msg.get("method") == "Runtime.consoleAPICalled" and msg["params"].get("type") == "error":
                args = msg["params"].get("args", [])
                self.errors.append("console.error: " + " ".join(str(a.get("value", a.get("description", ""))) for a in args)[:300])
            if msg.get("id") == my:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def eval(self, expr: str):
        res = await self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in res:
            raise RuntimeError(f"eval failed: {expr[:80]} -> {res['exceptionDetails'].get('text')}")
        return res.get("result", {}).get("value")

    async def wait_for(self, expr: str, timeout: float = 10.0, step: float = 0.1) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            try:
                if await self.eval(f"!!({expr})"):
                    return True
            except RuntimeError:
                pass
            await asyncio.sleep(step)
        return False

    async def shot(self, out: Path, name: str) -> Path:
        res = await self.call("Page.captureScreenshot", format="png")
        path = out / f"{name}.png"
        path.write_bytes(base64.b64decode(res["data"]))
        print(f"    shot: {path.name}")
        return path

    async def viewport(self, w: int, h: int, mobile: bool) -> None:
        await self.call(
            "Emulation.setDeviceMetricsOverride",
            width=w, height=h, deviceScaleFactor=1 if not mobile else 2, mobile=mobile,
        )
        await self.call("Emulation.setTouchEmulationEnabled", enabled=mobile, maxTouchPoints=5)

    async def center(self, selector: str):
        return await self.eval(
            f"""(() => {{ const r = document.querySelector({json.dumps(selector)})?.getBoundingClientRect();
                return r ? [r.left + r.width/2, r.top + r.height/2] : null; }})()"""
        )

    async def click(self, selector: str) -> bool:
        return bool(await self.eval(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return false; e.click(); return true; }})()"))

    async def hold_mouse(self, selector: str, seconds: float) -> None:
        x, y = await self.center(selector)
        await self.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        await self.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
        await asyncio.sleep(seconds)
        await self.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)

    async def hold_touch(self, selector: str, seconds: float) -> None:
        x, y = await self.center(selector)
        await self.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
        await asyncio.sleep(seconds)
        await self.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])

    async def space_down(self) -> None:
        await self.call("Input.dispatchKeyEvent", type="keyDown", key=" ", code="Space", windowsVirtualKeyCode=32, text=" ")

    async def space_up(self) -> None:
        await self.call("Input.dispatchKeyEvent", type="keyUp", key=" ", code="Space", windowsVirtualKeyCode=32)

    async def mic_phase(self) -> str:
        return await self.eval("document.querySelector('[data-testid=mic-button]')?.dataset.phase || '-'")


async def open_page() -> Page:
    targets = json.loads(urlopen(CDP + "/json", timeout=10).read().decode())
    page = next((t for t in targets if t.get("type") == "page"), None)
    if page is None:
        raise SystemExit("No page target on the CDP port")
    ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024)
    p = Page(ws)
    await p.call("Page.enable")
    await p.call("Runtime.enable")
    return p


async def fresh_load(p: Page, fast: bool = False) -> None:
    p.errors.clear()  # only count errors from this load onward (not stale HMR noise)
    await p.call("Page.navigate", url=f"{WEB}/?mock=1")
    await p.wait_for("document.readyState === 'complete'", 15)
    await p.eval("localStorage.clear(); true")
    await p.call("Page.reload", ignoreCache=True)
    await p.wait_for("document.querySelector('[data-testid=start-button]')", 15)
    await p.eval("document.fonts ? document.fonts.ready.then(() => true) : true")
    if fast:
        await p.eval("window.__polytaleMock.actMs = 700; window.__polytaleMock.transcribeMs = 400; true")
    await asyncio.sleep(1.2)


async def wait_idle(p: Page, timeout: float = 20) -> bool:
    """Idle and done speaking (mock audio is silent but has a duration)."""
    return await p.wait_for(
        "document.querySelector('[data-testid=mic-button]')?.dataset.phase === 'idle' && "
        "document.querySelector('[data-testid=mic-button]')?.dataset.speaking === '0'",
        timeout,
    )


async def desktop_run(p: Page, out: Path) -> None:
    print("desktop 1440x900")
    await p.viewport(1440, 900, mobile=False)
    await fresh_load(p)
    await p.shot(out, "d01_start")

    await p.click("[data-testid=start-button]")
    check("play view mounts", await p.wait_for("document.querySelector('[data-testid=play-view]')", 10))
    check("opening line 鍵 shown", await p.wait_for("[...document.querySelectorAll('[data-role=native]')].some(e => e.textContent.includes('鍵'))", 5))
    check("romanization under native", await p.eval(
        "(() => { const n = document.querySelector('[data-role=native]'); const r = n?.nextElementSibling; return !!r && r.dataset.role === 'romanization' && r.textContent.trim().length > 0; })()"))
    check("translation hidden by default", await p.eval("!document.querySelector('[data-role=translation]')"))
    check("focus object held up", await p.wait_for("document.querySelector('[data-focus][data-gesture=hold_up]')", 5))
    check("objective chip", await p.eval("!!document.querySelector('[data-testid=objective]')?.textContent.includes('Figure out')"))
    check("no suggested-action chips", await p.eval("!document.querySelector('[data-testid*=suggest]')"))
    await asyncio.sleep(1.4)
    await p.shot(out, "d02_opening_speaking")
    await wait_idle(p)
    await asyncio.sleep(0.4)
    await p.shot(out, "d03_opening_idle")

    # Beat 1: hold the mic with the mouse.
    x, y = await p.center("[data-testid=mic-button]")
    await p.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
    await p.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
    check("listening state", await p.wait_for("document.querySelector('[data-testid=mic-button]').dataset.phase === 'listening'", 4))
    await asyncio.sleep(0.9)
    check("live waveform", await p.eval("!!document.querySelector('[data-testid=waveform]')"))
    await p.shot(out, "d04_listening")
    await p.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)
    check("transcribing state", await p.wait_for("document.querySelector('[data-state=transcribing]')", 2))
    await p.shot(out, "d05_transcribing")
    check("preview shows Heard", await p.wait_for("document.querySelector('[data-testid=preview]')", 5))
    check("preview has cancel+retry", await p.eval("!!document.querySelector('[data-testid=preview-cancel]') && !!document.querySelector('[data-testid=preview-retry]')"))
    await asyncio.sleep(0.5)
    await p.shot(out, "d06_preview_countdown")
    check("auto-submits after cancel window", await p.wait_for("document.querySelector('[data-testid=mic-button]').dataset.phase === 'waiting'", 3))
    await asyncio.sleep(0.3)
    await p.shot(out, "d07_waiting")
    check("beat 1 recognized chip", await p.wait_for("document.querySelector('[data-kind=evidence][data-outcome=understood]')", 8))
    check("key withheld", await p.wait_for("document.querySelector('[data-focus][data-gesture=withhold]')", 3))
    await asyncio.sleep(1.2)
    await p.shot(out, "d08_after_recognition")
    await wait_idle(p)

    # Cancel path: hold Space, then cancel the preview — nothing is spent.
    turns_before = await p.eval("document.querySelectorAll('[data-kind=player]').length")
    await p.space_down()
    await asyncio.sleep(0.6)
    await p.space_up()
    await p.wait_for("document.querySelector('[data-testid=preview]')", 5)
    await p.click("[data-testid=preview-cancel]")
    await asyncio.sleep(2.3)
    check("cancel spends no turn", await p.eval("document.querySelectorAll('[data-kind=player]').length") == turns_before)

    # Empty transcript -> neutral retry message.
    await p.eval("window.__polytaleMock.queue.push({transcript: '', romanized: null}); true")
    await p.space_down()
    await asyncio.sleep(0.5)
    await p.space_up()
    check("empty transcript neutral message", await p.wait_for("document.querySelector('[data-state=empty]')?.textContent.includes('try again')", 5))
    await p.shot(out, "d09_empty_transcript")

    # Too-short press is ignored.
    await p.space_down()
    await asyncio.sleep(0.08)
    await p.space_up()
    await asyncio.sleep(0.4)
    check("<250ms press ignored", await p.mic_phase() == "idle")

    # Help ladder in the request beat (starts at level 1).
    for n in range(2, 6):
        await p.click("[data-testid=help-button]")
        ok = await p.wait_for(f"document.querySelector('[data-testid=help-card]')?.dataset.level === '{n}'", 5)
        kind = await p.eval("document.querySelector('[data-testid=help-card]')?.dataset.kind")
        check(f"help level {n} card ({kind})", ok)
        await asyncio.sleep(0.5)
        await p.shot(out, f"d10_help_L{n}_{kind}")
    check("full answer offers tap fallback", await p.eval("document.querySelector('[data-testid=help-card]')?.textContent.includes('tap')"))
    await p.eval("document.querySelector('[data-testid=help-card] button[aria-label=\"Hide help\"]')?.click(); true")

    # Beat 2: ask for the key (Space).
    await p.space_down()
    await asyncio.sleep(1.0)
    await p.space_up()
    await p.wait_for("document.querySelector('[data-testid=preview]')", 5)
    await p.shot(out, "d11_preview_key_request")
    check("key flies into pack", await p.wait_for("document.querySelector('[data-flight]')", 8, 0.05))
    await asyncio.sleep(0.45)
    await p.shot(out, "d12_key_flight")
    check("key in inventory", await p.wait_for("document.querySelector('[data-inv-slot=\"obj.engine_key\"]')", 5))
    check("panel flash", await p.eval("!!document.querySelector('[data-flash=\"fx.engine_panel\"]')"))
    await asyncio.sleep(1.2)
    check("plate crossfaded to panel_open", await p.eval("[...document.querySelectorAll('[data-plate-url]')].some(e => e.dataset.plateUrl.includes('panel_open'))"))
    await p.shot(out, "d13_key_given_panel_open")
    await wait_idle(p)

    # Reveal meaning on the latest line.
    await p.eval("[...document.querySelectorAll('button[aria-label=\"Reveal meaning\"]')].pop()?.click(); true")
    check("meaning revealed on demand", await p.wait_for("document.querySelector('[data-role=translation]')", 2))
    await asyncio.sleep(0.4)
    await p.shot(out, "d14_meaning_revealed")

    # Idle offer: wait > 10 s without input.
    await p.eval("document.querySelector('[data-testid=help-card] button[aria-label=\"Hide help\"]')?.click(); true")
    check("help offered after 10s idle", await p.wait_for("document.querySelector('[data-testid=help-button]').dataset.offering === '1'", 14, 0.5))
    await p.shot(out, "d15_idle_help_offer")

    # Beat 3: typed fallback for variety? No — speak it (mouse hold) to keep it voice-first.
    await p.hold_mouse("[data-testid=mic-button]", 1.0)
    check("map request preview", await p.wait_for("document.querySelector('[data-testid=preview]')?.textContent.includes('地図')", 5))
    check("launch moment", await p.wait_for("document.querySelector('[data-testid=launch-light]')", 8))
    await asyncio.sleep(1.8)
    await p.shot(out, "d16_launch")
    check("end card", await p.wait_for("document.querySelector('[data-testid=end-card]')", 15))
    await asyncio.sleep(1.0)
    await p.shot(out, "d17_recap")
    check("recap recognized words", await p.eval("document.querySelector('[data-testid=recap-recognized]')?.textContent.includes('kagi')"))
    check("recap side-by-side", await p.eval("!!document.querySelector('[data-testid=moment-key]') && !!document.querySelector('[data-testid=moment-map]')"))
    check("recap next episode", await p.eval("document.querySelector('[data-testid=recap-next]')?.textContent.includes('Next')"))

    # Refresh persistence: the end state is rebuilt from PublicState.
    await p.call("Page.reload")
    check("refresh restores session", await p.wait_for("document.querySelector('[data-testid=end-card]')", 10))

    await p.click("[data-testid=play-again]")
    check("play again restarts", await p.wait_for("document.querySelector('[data-focus][data-gesture=hold_up]') && !document.querySelector('[data-testid=end-card]')", 8))
    await asyncio.sleep(1.0)

    # Keyboard fallback visible when toggled.
    await p.click("[data-testid=keyboard-toggle]")
    check("keyboard fallback", await p.wait_for("document.querySelector('[data-testid=text-input] input')", 2))
    await p.shot(out, "d18_keyboard_fallback")

    # Menu + reset back to title.
    await p.click("[data-testid=menu-button]")
    await asyncio.sleep(0.3)
    await p.shot(out, "d19_menu")
    await p.click("[data-testid=reset-button]")
    check("reset returns to title", await p.wait_for("document.querySelector('[data-testid=start-screen]')", 5))


async def mobile_run(p: Page, out: Path) -> None:
    print("mobile 390x844")
    await p.viewport(390, 844, mobile=True)
    await fresh_load(p, fast=True)
    await p.shot(out, "m01_start")
    await p.click("[data-testid=start-button]")
    await p.wait_for("document.querySelector('[data-testid=play-view]')", 10)
    await asyncio.sleep(1.5)
    await p.shot(out, "m02_opening")
    overflow = await p.eval("document.documentElement.scrollWidth > window.innerWidth || document.body.scrollWidth > window.innerWidth")
    check("no horizontal overflow (mobile)", not overflow)
    await wait_idle(p)

    x, y = await p.center("[data-testid=mic-button]")
    await p.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
    check("touch hold listens", await p.wait_for("document.querySelector('[data-testid=mic-button]').dataset.phase === 'listening'", 4))
    await asyncio.sleep(0.8)
    await p.shot(out, "m03_listening")
    await p.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
    await p.wait_for("document.querySelector('[data-testid=preview]')", 5)
    await asyncio.sleep(0.2)
    await p.shot(out, "m04_preview")
    await p.wait_for("document.querySelector('[data-focus][data-gesture=withhold]')", 8)
    await asyncio.sleep(1.0)
    await p.shot(out, "m05_after_recognition")
    await wait_idle(p)

    for n in range(2, 4):
        await p.click("[data-testid=help-button]")
        await p.wait_for(f"document.querySelector('[data-testid=help-card]')?.dataset.level === '{n}'", 5)
    await asyncio.sleep(0.5)
    await p.shot(out, "m06_help_frame")
    await p.eval("document.querySelector('[data-testid=help-card] button[aria-label=\"Hide help\"]')?.click(); true")

    await p.hold_touch("[data-testid=mic-button]", 0.9)
    await p.wait_for("document.querySelector('[data-flight]')", 8, 0.05)
    await asyncio.sleep(0.5)
    await p.shot(out, "m07_key_flight")
    await wait_idle(p)
    await asyncio.sleep(0.3)
    await p.shot(out, "m08_map_grounded")

    await p.click("[data-testid=keyboard-toggle]")
    await asyncio.sleep(0.3)
    await p.eval("""(() => { const i = document.querySelector('[data-testid=text-input] input');
        const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        set.call(i, 'chizu o kudasai'); i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()""")
    await p.shot(out, "m09_keyboard")
    await p.eval("document.querySelector('[data-testid=text-input]').requestSubmit(); true")
    check("launch (mobile, typed)", await p.wait_for("document.querySelector('[data-testid=launch-light]')", 8))
    await asyncio.sleep(1.6)
    await p.shot(out, "m10_launch")
    check("end card (mobile)", await p.wait_for("document.querySelector('[data-testid=end-card]')", 15))
    await asyncio.sleep(1.0)
    await p.shot(out, "m11_recap")
    await p.eval("document.querySelector('[data-testid=end-card]').scrollTo(0, 99999); true")
    await asyncio.sleep(0.4)
    await p.shot(out, "m12_recap_scrolled")
    overflow = await p.eval("document.documentElement.scrollWidth > window.innerWidth")
    check("no horizontal overflow on recap (mobile)", not overflow)


async def main() -> int:
    out = ROOT / "logs" / "playtests" / f"web_mock_{datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    print(f"web mock playtest -> {out}")
    try:
        urlopen(WEB, timeout=5).read(64)
    except Exception:
        raise SystemExit(f"Vite dev server not reachable at {WEB} (cd web && npx vite)")
    proc = launch_chrome()
    try:
        p = await open_page()
        which = sys.argv[1] if len(sys.argv) > 1 else "all"
        if which in ("all", "desktop"):
            await desktop_run(p, out)
        if which in ("all", "mobile"):
            await mobile_run(p, out)
        errs = [e for e in p.errors if "favicon" not in e and "[vite]" not in e]
        check("no page exceptions", not errs, "; ".join(errs[:3]))
    finally:
        if proc is not None:
            proc.terminate()
    print(f"\n{len(FAILURES)} failure(s)" + (": " + ", ".join(FAILURES) if FAILURES else ""))
    print(f"screenshots: {out}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
