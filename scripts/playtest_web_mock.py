#!/usr/bin/env python3
"""Headless-Chrome playtest of the v3 web client against the in-browser mock API.

Plays the scripted "The Last Train" (bar -> night market -> ending) at 1440x900 and at
phone size (390x844): title (story hero, difficulty) -> intro -> narrator first, then the
character's lines (ruby, highlight, price tag) -> verb menus (keyboard, Esc, outside
click) -> show the photo (game-log echo, clock tick, clue toast, notebook badge) ->
typed English (puzzled) -> phrasebook (422, loading, result with glosses, "Use it",
saved phrases, costs no time) -> mic hold + preview window -> help 1 / help 2 -> menu
(difficulty, character mood) -> take a beer -> 502 and 402 recovery -> pay (cash counts
down) -> clue -> act summary -> refresh restore -> act two (clock pressure, haggling
price tag, mid-scene restore) -> ending (art, stats, words, phrases) -> restore -> try
the other difficulty. It also checks cutout registration at 1440x900, 1920x1080,
1024x768, 2560x1080, 390x844 and 844x390, the clock-out ending, a language without
romanization, ja-JP, and missing art. Screenshots land in logs/playtests/web_mock_<ts>/.

Needs the Vite dev server (cd web && npx vite, port 5180). Chrome is launched
headless on CDP port 9335 unless one is already listening there.

Run: PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/playtest_web_mock.py [all|desktop|mobile|aspects]
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

# What the fake microphone "says" (the mock transcriber returns whatever is queued).
HOW_MUCH = {"transcript": "多少钱", "romanized": "duōshao qián"}

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
        await self.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=2 if mobile else 1, mobile=mobile)
        await self.call("Emulation.setTouchEmulationEnabled", enabled=mobile, maxTouchPoints=5)

    async def center(self, selector: str):
        return await self.eval(
            f"""(() => {{ const r = document.querySelector({json.dumps(selector)})?.getBoundingClientRect();
                return r ? [r.left + r.width/2, r.top + r.height/2] : null; }})()"""
        )

    async def exists(self, selector: str) -> bool:
        return bool(await self.eval(f"!!document.querySelector({json.dumps(selector)})"))

    async def click(self, selector: str) -> bool:
        return bool(await self.eval(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return false; e.click(); return true; }})()"))

    async def mouse_click(self, selector: str) -> None:
        """A real pointer click, so hit-testing (z-order, pointer-events) is exercised."""
        x, y = await self.center(selector)
        await self.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        await self.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
        await self.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)

    async def tap(self, selector: str) -> None:
        x, y = await self.center(selector)
        await self.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
        await self.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])

    async def hover(self, selector: str) -> None:
        x, y = await self.center(selector)
        await self.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)

    async def type_and_send(self, text: str) -> None:
        await self.eval("document.querySelector('[data-testid=text-input]').focus(); true")
        await self.call("Input.insertText", text=text)
        await asyncio.sleep(0.15)
        await self.call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13, text="\r")
        await self.call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)

    async def key(self, key: str, code: str, vk: int) -> None:
        await self.call("Input.dispatchKeyEvent", type="keyDown", key=key, code=code, windowsVirtualKeyCode=vk)
        await self.call("Input.dispatchKeyEvent", type="keyUp", key=key, code=code, windowsVirtualKeyCode=vk)

    async def space_down(self) -> None:
        await self.eval("document.activeElement && document.activeElement.blur(); true")
        await self.call("Input.dispatchKeyEvent", type="keyDown", key=" ", code="Space", windowsVirtualKeyCode=32, text=" ")

    async def space_up(self) -> None:
        await self.call("Input.dispatchKeyEvent", type="keyUp", key=" ", code="Space", windowsVirtualKeyCode=32)

    async def state(self) -> str:
        return await self.eval("document.querySelector('[data-testid=input-bar]')?.dataset.state || '-'")

    async def queue(self, item: dict) -> None:
        await self.eval(f"window.__polytaleMock.queue.push({json.dumps(item, ensure_ascii=False)}); true")


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


async def fresh_load(p: Page, query: str = "") -> None:
    p.errors.clear()  # only count errors from this load onward (not stale HMR noise)
    await p.call("Page.navigate", url=f"{WEB}/?mock=1{query}")
    await p.wait_for("document.readyState === 'complete'", 15)
    await p.eval("localStorage.clear(); true")
    await p.call("Page.reload", ignoreCache=True)
    await p.wait_for("document.querySelector('[data-testid=begin-button]')", 15)
    await p.eval("document.fonts ? document.fonts.ready.then(() => true) : true")
    await asyncio.sleep(1.0)


async def reload(p: Page) -> None:
    """Reload and wait until the NEW document is up (the old one still matches selectors)."""
    await p.eval("window.__stale = true")
    await p.call("Page.reload")
    await p.wait_for("!window.__stale && document.readyState === 'complete' && document.querySelector('[data-screen]')?.dataset.screen !== 'boot'", 15)


async def wait_idle(p: Page, timeout: float = 25) -> bool:
    """Input idle and the character done speaking (mock audio is silent but timed)."""
    return await p.wait_for("document.querySelector('[data-testid=input-bar]')?.dataset.state === 'idle'", timeout)


async def turns(p: Page) -> int:
    return int(await p.eval("JSON.parse(localStorage.getItem('polytale.mock.journey.v3') || '{}').scene?.turn ?? -1"))


NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth && document.body.scrollWidth <= window.innerWidth"

# Every live cutout's bottom-centre must sit where its authored fraction says, measured
# against the painted background frame; everything the learner needs must be on screen;
# the subtitles must sit clear of the character's face.
REGISTRATION = """(() => {
  const frame = document.querySelector('[data-testid=scene-frame]').getBoundingClientRect();
  const out = { worst: 0, offscreen: [], n: 0, frame: [frame.left, frame.top, frame.width, frame.height].map(Math.round) };
  for (const b of document.querySelectorAll('[data-object]')) {
    if (!b.dataset.pos || b.dataset.carried === '1' || b.dataset.zone === 'npc') continue;
    const [x, y, h] = b.dataset.pos.split(',').map(Number);
    const r = b.getBoundingClientRect();
    const dx = Math.abs(r.left + r.width / 2 - (frame.left + x * frame.width));
    const dy = Math.abs(r.bottom - (frame.top + y * frame.height));
    const dh = Math.abs(r.height - h * frame.height);
    out.worst = Math.max(out.worst, dx, dy, dh);
    out.n += 1;
    if (r.left < -1 || r.right > innerWidth + 1 || r.top < -1 || r.bottom > innerHeight + 1) out.offscreen.push(b.dataset.object);
  }
  const [ax, ay] = document.querySelector('[data-testid=scene-frame]').dataset.anchor.split(',').map(Number);
  const face = { x: frame.left + ax * frame.width, y: frame.top + ay * frame.height, r: 0.1 * frame.height };
  out.faceOnScreen = face.x > 0 && face.x < innerWidth && face.y - face.r > 0 && face.y + face.r < innerHeight;
  // The anchor is the mouth: the face is the box above and around it.
  const box = { left: face.x - 0.07 * frame.height, right: face.x + 0.07 * frame.height, top: face.y - 0.17 * frame.height, bottom: face.y + 0.06 * frame.height };
  out.subtitlesClearOfFace = [...document.querySelectorAll('[data-testid=subtitles] p')].every(e => {
    const r = e.getBoundingClientRect();
    return !(r.left < box.right && r.right > box.left && r.top < box.bottom && r.bottom > box.top);
  });
  out.covered = [];
  for (const line of document.querySelectorAll('[data-testid=subtitle-line] [data-role=target]')) {
    const t = line.getBoundingClientRect();
    for (const b of document.querySelectorAll('[data-object]:not([disabled])')) {
      if (b.dataset.carried === '1') continue;
      const r = b.getBoundingClientRect();
      if (t.left < r.right && t.right > r.left && t.top < r.bottom && t.bottom > r.top) out.covered.push(b.dataset.object);
    }
  }
  const status = document.querySelector('[data-testid=scene-status]').getBoundingClientRect();
  out.chromeClearOfFace = !(status.right > face.x - face.r && status.bottom > face.y - face.r);
  return out;
})()"""


async def check_registration(p: Page, label: str) -> None:
    reg = await p.eval(REGISTRATION)
    check(f"objects registered to background ({label})", reg["n"] >= 3 and reg["worst"] <= 1.5, f"worst {reg['worst']:.2f}px over {reg['n']} objects, frame {reg['frame']}")
    check(f"every object on screen ({label})", not reg["offscreen"], str(reg["offscreen"]))
    check(f"character's face on screen ({label})", reg["faceOnScreen"])
    check(f"subtitles clear of the face ({label})", reg["subtitlesClearOfFace"])
    check(f"chrome clear of the face ({label})", reg["chromeClearOfFace"])
    check(f"subtitles do not cover an object ({label})", not reg["covered"], str(reg["covered"]))
    check(f"no horizontal overflow ({label})", await p.eval(NO_OVERFLOW))


async def begin(p: Page, out: Path, tag: str) -> None:
    check("story title is the hero", await p.eval("document.querySelector('[data-testid=story-title]')?.textContent") == "The Last Train")
    check("Polytale is the small wordmark", await p.eval("document.querySelector('[data-testid=wordmark]')?.textContent.trim()") == "Polytale")
    check("premise shown", await p.eval("(document.querySelector('[data-testid=premise]')?.textContent || '').length > 60"))
    check("no 'Relay' anywhere", not await p.eval("document.body.innerText.includes('Relay') || document.title.includes('Relay')"))
    check("language line from the API", await p.eval("(document.querySelector('[data-testid=language-line]')?.textContent || '').includes('·')"))
    check("difficulty choice, no persona on the start screen", await p.eval("document.querySelectorAll('[data-testid=difficulty-choice] [role=radio]').length") == 2 and not await p.exists("[data-testid=persona-switch]"))
    await p.click("[data-testid=start-difficulty-immersion]")
    await p.click("[data-testid=start-difficulty-story]")
    check("Story is the chosen difficulty", await p.eval("document.querySelector('[data-testid=start-difficulty-story]').dataset.active") == "1")
    await p.shot(out, f"{tag}01_start")
    await p.click("[data-testid=begin-button]")
    check("intro card while the opening turn is generated", await p.wait_for("document.querySelector('[data-testid=intro-text]')?.textContent.length > 20", 6))
    await asyncio.sleep(0.6)
    await p.shot(out, f"{tag}02_intro")
    check("play view mounts", await p.wait_for("document.querySelector('[data-testid=play-view]')", 12))


async def opening_checks(p: Page, out: Path, tag: str) -> None:
    check("the narrator speaks first", await p.wait_for(
        "document.querySelector('[data-testid=narration]')?.textContent.length > 30 && document.querySelectorAll('[data-testid=subtitle-line]').length === 0", 4, 0.03))
    await p.shot(out, f"{tag}03_narration_first")
    check("then the first line appears alone", await p.wait_for("document.querySelectorAll('[data-testid=subtitle-line]').length === 1", 8, 0.05))
    check("narration is prose in the story face", await p.eval("getComputedStyle(document.querySelector('[data-testid=narration]')).fontFamily.includes('Newsreader')"))
    check("ruby: romanization above each word", await p.eval(
        "(() => { const r = document.querySelector('[data-testid=subtitle-line] ruby'); const rt = r?.querySelector('rt');"
        " if (!r || !rt || !rt.textContent.trim()) return false;"
        " return rt.getBoundingClientRect().bottom <= r.getBoundingClientRect().bottom - 8; })()"))
    check("an object is highlighted while its line plays", await p.wait_for("document.querySelector('[data-lit=\"1\"]')", 10, 0.05))
    check("price tag shown on the highlighted object", await p.wait_for(
        "(() => { const t = document.querySelector('[data-lit=\"1\"] [data-testid^=price-]'); return !!t && getComputedStyle(t).opacity > 0.5 && /\\d/.test(t.textContent); })()", 2, 0.05))
    check("current line bright, earlier dim", await p.eval(
        "document.querySelectorAll('[data-testid=subtitle-line][data-current=\"1\"]').length === 1 && "
        "document.querySelectorAll('[data-testid=subtitle-line][data-current=\"0\"]').length >= 1"))
    await asyncio.sleep(0.5)
    await p.shot(out, f"{tag}04_opening_highlight")
    check("input idle after the lines", await wait_idle(p))
    await asyncio.sleep(0.3)
    await p.shot(out, f"{tag}05_opening_idle")
    text = await p.eval("document.body.innerText")
    check("no translation of character lines during play", not any(g in text.lower() for g in ("beer", "how much", "thanks")) and not await p.exists("[data-role=gloss]"))
    check("no word list or word counter on the play screen", not await p.exists("[data-testid=word-list]") and not await p.exists("[data-testid=word-count]"))
    check("HUD: clock and cash", await p.eval("/^\\d\\d:\\d\\d$/.test(document.querySelector('[data-testid=clock] .tick')?.textContent.trim() || '') && /\\d/.test(document.querySelector('[data-testid=cash]')?.textContent || '')"))
    check("story goals, not lesson goals", await p.eval("[...document.querySelectorAll('[data-testid=goals] li')].some(e => e.textContent.includes('Mei'))"))
    check("inventory tray holds the photo and the money", await p.eval("document.querySelector('[data-testid=object-photo]')?.dataset.carried === '1' && document.querySelector('[data-testid=object-money]')?.dataset.carried === '1'"))
    check("text field + mic in one bar", await p.eval("!!document.querySelector('[data-testid=input-bar] [data-testid=text-input]') && !!document.querySelector('[data-testid=input-bar] [data-testid=mic-button]')"))


async def verb(p: Page, object_id: str, action: str, touch: bool = False) -> None:
    sel = f"[data-testid=object-{object_id}]"
    await (p.tap(sel) if touch else p.mouse_click(sel))
    await p.wait_for(f"document.querySelector('[data-testid=verb-menu][data-for={object_id}]')", 3, 0.05)
    await asyncio.sleep(0.15)
    vsel = f"[data-testid=verb-menu] [data-testid=verb-{action}]"
    await (p.tap(vsel) if touch else p.mouse_click(vsel))


async def desktop_run(p: Page, out: Path) -> None:
    print("desktop 1440x900")
    await p.viewport(1440, 900, mobile=False)
    await fresh_load(p)
    await begin(p, out, "d")
    await opening_checks(p, out, "d")
    await check_registration(p, "1440x900")

    # Verbs: a click opens the object's verbs; keyboard works; Esc closes.
    await p.mouse_click("[data-testid=object-photo]")
    check("verb menu opens on the photo (Show, Give)", await p.wait_for("[...document.querySelectorAll('[data-testid=verb-menu][data-for=photo] button')].map(b => b.textContent.trim()).join(',') === 'Show,Give'", 3))
    check("verb menu takes focus", await p.eval("document.activeElement?.dataset.testid === 'verb-show'"))
    await p.key("ArrowRight", "ArrowRight", 39)
    check("arrow keys move between verbs", await p.eval("document.activeElement?.dataset.testid === 'verb-give'"))
    await asyncio.sleep(0.2)
    await p.shot(out, "d06_verb_menu_inventory")
    await p.key("Escape", "Escape", 27)
    check("Esc closes the verb menu and spends nothing", await p.wait_for("!document.querySelector('[data-testid=verb-menu]')", 2) and await turns(p) == 0)
    await p.mouse_click("[data-testid=object-beer]")
    await p.wait_for("document.querySelector('[data-testid=verb-menu][data-for=beer]')", 3)
    check("price shows while the menu is open", await p.wait_for("getComputedStyle(document.querySelector('[data-testid=price-beer]')).opacity > 0.5", 2, 0.05))
    await asyncio.sleep(0.25)
    await p.shot(out, "d07_verb_menu_object")
    await p.eval("document.body.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true})); true")
    check("outside click closes the verb menu", await p.wait_for("!document.querySelector('[data-testid=verb-menu]')", 2))

    # Show the photo: game-log echo, the clock ticks, a clue lands.
    await verb(p, "photo", "show")
    check("echo reads like a game log", await p.wait_for("(document.querySelector('[data-testid=learner-line]')?.textContent || '').replace(/\\s+/g, ' ').trim().startsWith('You show') || /^You\\s*show/.test(document.querySelector('[data-testid=learner-line]')?.textContent || '')", 3, 0.05))
    await p.shot(out, "d08_you_show_waiting")
    check("clue toast", await p.wait_for("(document.querySelector('[data-testid=clue-toast]')?.textContent || '').includes('Notebook')", 8, 0.05))
    check("the clock ticked and said what it cost", await p.eval("document.querySelector('[data-testid=clock] .tick').textContent.trim() === '22:43'") and await p.exists("[data-testid=clock-spent]"))
    check("notebook badge", await p.exists("[data-testid=notebook-badge]"))
    check("first story goal checked off", await p.eval("document.querySelector('[data-goal=ask]').dataset.done") == "1")
    await asyncio.sleep(0.5)
    await p.shot(out, "d09_clue_toast")
    await wait_idle(p)
    await p.click("[data-testid=notebook-button]")
    check("notebook lists the clue (title + text)", await p.wait_for("document.querySelector('[data-testid=notebook] [data-clue=regular]')?.textContent.length > 30", 3))
    check("trust is a sentence, not a meter", await p.eval("(document.querySelector('[data-testid=standing]')?.textContent || '').length > 10") and not await p.exists("[data-testid=notebook] progress, [data-testid=notebook] meter"))
    check("word count lives in the notebook", bool(await p.eval("/\\d+ \\/ \\d+ words met/.test(document.querySelector('[data-testid=notebook] [data-testid=word-count]')?.textContent || '')")))
    await asyncio.sleep(0.4)
    await p.shot(out, "d10_notebook")
    await p.click("[data-testid=notebook-close]")
    check("badge clears once read", not await p.exists("[data-testid=notebook-badge]"))

    # Typed English: the character does not understand; the narrator says so.
    await p.type_and_send("hello, have you seen my friend?")
    check("typed line echoed", await p.wait_for("(document.querySelector('[data-testid=learner-line]')?.textContent || '').includes('You say')", 3, 0.05))
    check("mood changes (puzzled)", await p.wait_for("document.querySelector('[data-testid=scene]').dataset.mood === 'puzzled'", 8))
    await asyncio.sleep(1.4)
    await p.shot(out, "d11_typed_english_puzzled")
    await wait_idle(p)

    # Phrasebook.
    check("collapsed phrasebook is a slim tab", await p.eval("(() => { const r = document.querySelector('[data-testid=phrasebook-tab]')?.getBoundingClientRect(); return !!r && r.width < 56 && r.right >= innerWidth - 1; })()"))
    before = await turns(p)
    clock_before = await p.eval("document.querySelector('[data-testid=clock]').dataset.minutesLeft")
    await p.click("[data-testid=phrasebook-tab]")
    await p.wait_for("document.querySelector('[data-testid=phrase-input]')", 3)
    await p.eval("document.querySelector('[data-testid=phrase-input]').focus(); true")
    await p.call("Input.insertText", text="多少钱")
    await p.click("[data-testid=phrase-ask]")
    check("422: it will not translate the target language", await p.wait_for("(document.querySelector('[data-testid=phrase-error]')?.textContent || '').includes('YOU want to say')", 5))
    await p.shot(out, "d12_phrasebook_422")
    await p.eval("(() => { const i = document.querySelector('[data-testid=phrase-input]'); i.focus(); i.select(); return true; })()")
    await p.call("Input.insertText", text="Have you seen her?")
    await p.click("[data-testid=phrase-ask]")
    check("phrasebook loading state", await p.wait_for("document.querySelector('[data-testid=phrase-loading]')", 2, 0.03))
    check("result: ruby above, gloss beneath each word", await p.wait_for(
        "(() => { const r = document.querySelector('[data-testid=phrase-result]'); if (!r) return false; const g = [...r.querySelectorAll('[data-role=phrase-gloss]')].filter(e => e.textContent.trim()); return g.length >= 3; })()", 5))
    await asyncio.sleep(0.3)
    await p.shot(out, "d13_phrasebook_result")
    check("the scene is not covered by the panel's column", await p.eval(
        "(() => { const a = document.querySelector('[data-testid=phrasebook] aside').getBoundingClientRect(); const b = document.querySelector('[data-testid=input-bar]').getBoundingClientRect(); return a.left >= b.right; })()"))
    await p.click("[data-testid=phrase-play]")
    await p.click("[data-testid=phrase-use]")
    check("'Use it' fills and focuses the input, and sends nothing", await p.wait_for(
        "document.querySelector('[data-testid=text-input]').value.length >= 3 && document.activeElement === document.querySelector('[data-testid=text-input]')", 3) and await turns(p) == before)
    check("the phrasebook costs no game time", await p.eval("document.querySelector('[data-testid=clock]').dataset.minutesLeft") == clock_before)
    await p.shot(out, "d14_phrase_in_input")
    await p.eval("(() => { const i = document.querySelector('[data-testid=phrase-input]'); i.focus(); i.select(); return true; })()")
    await p.call("Input.insertText", text="too expensive")
    await p.click("[data-testid=phrase-ask]")
    check("'Your phrases' keeps what was looked up", await p.wait_for("document.querySelectorAll('[data-testid=phrase-saved]').length >= 1", 5))
    await p.click("[data-testid=phrasebook-close]")
    await p.eval("document.querySelector('[data-testid=text-input]').focus(); true")
    await p.call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13, text="\r")
    await p.call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)
    check("the looked-up phrase is sent by the learner", await p.wait_for("document.querySelector('[data-testid=input-bar]').dataset.state === 'waiting'", 3, 0.05))
    check("asking again: he points at the unpaid tab", await p.wait_for("document.querySelector('[data-testid=object-tab]')?.dataset.lit === '1' || (document.querySelector('[data-testid=narration]')?.textContent || '').includes('photo')", 10, 0.05))
    await asyncio.sleep(0.5)
    await p.shot(out, "d14b_asked_again")
    await wait_idle(p)

    # Mic: hold with the mouse, fake audio, preview, auto-submit.
    await p.queue(HOW_MUCH)
    x, y = await p.center("[data-testid=mic-button]")
    await p.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
    await p.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
    check("listening", await p.wait_for("document.querySelector('[data-testid=input-bar]').dataset.state === 'listening'", 4))
    await asyncio.sleep(0.9)
    check("live waveform replaces the placeholder", await p.exists("[data-testid=waveform]") and not await p.exists("[data-testid=text-input]"))
    await p.shot(out, "d15_listening")
    await p.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)
    check("transcribing", await p.wait_for("document.querySelector('[data-testid=transcribing]')", 2, 0.05))
    check("preview: Heard …", await p.wait_for("(document.querySelector('[data-testid=preview]')?.textContent || '').includes('Heard')", 5, 0.05))
    check("cancel window runs", await p.exists("[data-testid=countdown]") and await p.exists("[data-testid=preview-cancel]"))
    await asyncio.sleep(0.35)
    await p.shot(out, "d16_preview")
    check("auto-submits after the cancel window", await p.wait_for("document.querySelector('[data-testid=input-bar]').dataset.state === 'waiting'", 3, 0.05))
    check("prices answered with highlights", await p.wait_for("document.querySelector('[data-lit=\"1\"]')", 12, 0.05))
    await asyncio.sleep(0.6)
    await p.shot(out, "d17_prices")
    await wait_idle(p)

    # Esc cancels a preview and spends nothing; requires_confirmation never auto-submits.
    before = await turns(p)
    await p.queue(HOW_MUCH)
    await p.space_down()
    check("hold Space listens", await p.wait_for("document.querySelector('[data-testid=input-bar]').dataset.state === 'listening'", 4))
    await asyncio.sleep(0.6)
    await p.space_up()
    await p.wait_for("document.querySelector('[data-testid=preview]')", 5, 0.05)
    await p.key("Escape", "Escape", 27)
    await asyncio.sleep(1.8)
    check("Esc cancels, no turn spent", await turns(p) == before and await p.state() == "idle")
    await p.queue({**HOW_MUCH, "requires_confirmation": True})
    await p.space_down()
    await asyncio.sleep(0.6)
    await p.space_up()
    await p.wait_for("document.querySelector('[data-testid=preview]')", 5, 0.05)
    await asyncio.sleep(1.8)
    check("requires_confirmation never auto-submits", await p.state() == "preview" and not await p.exists("[data-testid=countdown]"))
    await p.key("Escape", "Escape", 27)
    await p.space_down()
    await asyncio.sleep(0.06)
    await p.space_up()
    await asyncio.sleep(0.5)
    check("<250 ms press ignored", await p.state() == "idle")
    await p.queue({"transcript": ""})
    await p.space_down()
    await asyncio.sleep(0.5)
    await p.space_up()
    check("nothing heard -> quiet retry notice", await p.wait_for("(document.querySelector('[data-testid=notice]')?.textContent || '').includes(\"Didn't catch\")", 5))

    # Help is two steps.
    await p.click("[data-testid=help-button]")
    check("help 1 replays with highlights", await p.wait_for("document.querySelector('[data-lit=\"1\"]') && document.querySelector('[data-testid=mic-button]').dataset.speaking === '1'", 5, 0.05))
    check("help 1 shows no hint", not await p.exists("[data-testid=help-hint]"))
    await wait_idle(p)
    await p.click("[data-testid=help-button]")
    check("help 2 shows the intent hint", await p.wait_for("document.querySelector('[data-testid=help-hint]')?.textContent.length > 10", 5))
    check("no third help step", await p.wait_for("document.querySelector('[data-testid=help-button]').disabled", 3))
    await asyncio.sleep(0.4)
    await p.shot(out, "d18_help2_hint")

    # Menu: difficulty and character mood live here now.
    await p.click("[data-testid=menu-button]")
    check("menu: difficulty, character mood, volume, finish, restart, new journey", all([await p.exists(f"[data-testid=menu] [data-testid={t}]") for t in ("difficulty-switch", "persona-switch", "volume", "finish-scene", "restart-scene", "new-journey")]))
    await asyncio.sleep(0.3)
    await p.shot(out, "d19_menu")
    await p.click("[data-testid=difficulty-immersion]")
    check("difficulty toast", await p.wait_for("(document.querySelector('[data-testid=toast]')?.textContent || '').includes('Immersion')", 3))
    await p.click("[data-testid=difficulty-story]")
    await p.click("[data-testid=menu] [data-testid=persona-brisk]")
    check("character mood applies from the next reply", await p.wait_for("(document.querySelector('[data-testid=toast]')?.textContent || '').includes('next reply')", 3))
    await p.key("Escape", "Escape", 27)

    # Order a beer with a verb: it slides to the counter; nothing is paid yet.
    await verb(p, "beer", "drink")
    check("beer leaves the shelf", await p.wait_for("document.querySelector('[data-testid=object-beer]').dataset.zone === 'counter'", 8, 0.03))
    await asyncio.sleep(0.22)
    await p.shot(out, "d20_beer_sliding")
    await wait_idle(p)
    check("taking is not paying", await p.eval("document.querySelector('[data-testid=cash]').dataset.wallet") == "60")
    await check_registration(p, "1440x900 served")
    await p.shot(out, "d21_beer_served")

    # Pay: a model failure first (quiet, recoverable), then out of credits, then it goes through.
    await p.eval("window.__polytaleMock.failNextAct = true; true")
    await p.mouse_click("[data-testid=object-money]")  # one verb (Pay): acts at once, no menu
    check("502 -> inline 'send again'", await p.wait_for("document.querySelector('[data-testid=retry-send]')", 8))
    await p.eval("window.__polytaleMock.failNextAct = 402; true")
    await p.click("[data-testid=retry-send]")
    check("402 -> says the account is out of credits", await p.wait_for("(document.querySelector('[data-testid=notice]')?.textContent || '').includes('out of credits')", 8))
    await p.shot(out, "d22_out_of_credits")
    await p.click("[data-testid=retry-send]")
    check("cash counts down and says what it cost", await p.wait_for("document.querySelector('[data-testid=cash]').dataset.wallet === '40' && document.querySelector('[data-testid=cash-spent]')", 8, 0.03))
    await asyncio.sleep(0.25)
    mid = await p.eval("parseInt(document.querySelector('[data-testid=cash] span').textContent.replace(/\\D/g, ''), 10)")
    check("the number is animated, not snapped", 40 <= mid <= 60, str(mid))
    await p.shot(out, "d23_paid_cash_counting")
    check("paying earns trust, and trust earns a clue", await p.wait_for("(document.querySelector('[data-testid=clue-toast]')?.textContent || '').includes('waited')", 6, 0.05))
    await wait_idle(p)
    await verb(p, "beer", "drink")
    check("drinking with him earns the answer: the market clue", await p.wait_for("(document.querySelector('[data-testid=clue-toast]')?.textContent || '').includes('market')", 8, 0.05))
    await asyncio.sleep(0.4)
    await p.shot(out, "d24_clue_market")

    # History now includes the narrator and the clues.
    await p.click("[data-testid=history-button]")
    check("history: narration, clues, replay + slow, no translation", await p.wait_for(
        "document.querySelectorAll('[data-testid=history] [data-kind=narration]').length >= 3 && document.querySelectorAll('[data-testid=history] [data-kind=clue]').length >= 2"
        " && document.querySelector('[data-testid=history] [data-testid=replay-slow]') && !document.querySelector('[data-testid=history] [data-role=gloss]')", 3))
    await asyncio.sleep(0.4)
    await p.shot(out, "d25_history")
    await p.click("[data-testid=history-close]")

    check("act summary after the last line", await p.wait_for("document.querySelector('[data-testid=summary]')", 20))
    await asyncio.sleep(1.0)
    await p.shot(out, "d26_summary_bar")
    check("word list shown for the first time, with glosses", await p.eval("document.querySelectorAll('[data-testid=word-row]').length") >= 8 and await p.eval("[...document.querySelectorAll('[data-role=gloss]')].some(e => e.textContent.includes('beer'))"))
    check("summary lists your phrases", await p.eval("document.querySelectorAll('[data-testid=summary-phrase]').length") >= 2)
    check("no ending yet", not await p.exists("[data-testid=ending]"))
    await reload(p)
    check("refresh restores the summary", await p.wait_for("document.querySelector('[data-testid=summary]')", 10))

    # Act two.
    await p.click("[data-testid=continue-button]")
    check("intro card for act two", await p.wait_for("document.querySelector('[data-testid=intro-text]')", 5))
    await asyncio.sleep(0.7)
    await p.shot(out, "d27_intro_market")
    check("act two mounts", await p.wait_for("document.querySelector('[data-testid=play-view]')?.dataset.scene === 'market'", 12))
    check("cash and clock carry over", await p.wait_for("document.querySelector('[data-testid=cash]')?.dataset.wallet === '40'", 5))
    await p.wait_for("document.querySelector('[data-lit=\"1\"]')", 12, 0.05)
    await asyncio.sleep(0.4)
    await p.shot(out, "d28_market_opening")
    await wait_idle(p)
    await check_registration(p, "1440x900 market")

    # Pressure: the last quarter hour changes the clock.
    left = int(await p.eval("document.querySelector('[data-testid=clock]').dataset.minutesLeft"))
    await p.eval(f"window.__polytaleMock.skipMinutes({left - 17}); true")
    await verb(p, "photo", "show")
    check("clock turns urgent in the last 15 minutes", await p.wait_for("document.querySelector('[data-testid=clock]').dataset.urgent === '1'", 8))
    await asyncio.sleep(0.5)
    await p.shot(out, "d29_clock_pressure")
    await wait_idle(p)

    # Haggle: the price tag strikes the old price.
    await p.type_and_send("tai gui le")
    check("haggling changes the tag: old price struck, new shown", await p.wait_for(
        "(() => { const t = document.querySelector('[data-testid=price-noodles]'); return t?.dataset.changed === '1' && !!t.querySelector('s') && t.textContent.includes('10') && getComputedStyle(t).opacity > 0.5; })()", 8, 0.05))
    await asyncio.sleep(0.4)
    await p.shot(out, "d30_haggled_price")
    await wait_idle(p)

    await verb(p, "noodles", "eat")
    await p.wait_for("document.querySelector('[data-testid=object-noodles]').dataset.zone === 'counter'", 8)
    await wait_idle(p)
    await check_registration(p, "1440x900 market served")
    await reload(p)
    check("refresh restores mid-scene (zones, cash, clues, narration)", await p.wait_for(
        "document.querySelector('[data-testid=play-view]')?.dataset.scene === 'market' && document.querySelector('[data-testid=object-noodles]')?.dataset.zone === 'counter'"
        " && document.querySelector('[data-testid=cash]')?.dataset.wallet === '40' && document.querySelector('[data-testid=narration]')", 10))
    await asyncio.sleep(0.8)
    await p.shot(out, "d31_market_restored")
    await p.mouse_click("[data-testid=object-money]")
    check("paid the haggled price", await p.wait_for("document.querySelector('[data-testid=cash]')?.dataset.wallet === '30'", 8))

    # Ending.
    check("the ending follows the last line", await p.wait_for("document.querySelector('[data-testid=ending]')", 25))
    await asyncio.sleep(1.2)
    await p.shot(out, "d32_ending")
    check("ending: title, text, stats", await p.eval(
        "document.querySelector('[data-testid=ending-title]')?.textContent.length > 3 && document.querySelector('[data-testid=ending-text]')?.textContent.length > 40"
        " && document.querySelectorAll('[data-testid=ending-stats] dd').length >= 3"))
    check("a good ending, because the platform clue was found in time", await p.eval("document.querySelector('[data-testid=ending]').dataset.ending") in ("reunited", "seconds"))
    await p.eval("document.querySelector('[data-testid=summary]').scrollTo(0, 900); true")
    await asyncio.sleep(0.5)
    await p.shot(out, "d33_ending_words")
    check("then what you picked up, with your phrases", await p.exists("[data-testid=word-list]") and await p.exists("[data-testid=summary-phrases]"))
    await p.click("[data-testid=word-row]")
    await reload(p)
    check("refresh restores the ending", await p.wait_for("document.querySelector('[data-testid=ending]')", 10))
    check("play again / try the other difficulty", await p.exists("[data-testid=start-over]") and "Immersion" in (await p.eval("document.querySelector('[data-testid=play-other]')?.textContent || ''")))
    await p.click("[data-testid=play-other]")
    check("'try Immersion' returns to the title with it chosen", await p.wait_for("document.querySelector('[data-testid=start-difficulty-immersion]')?.dataset.active === '1'", 6))


async def mobile_run(p: Page, out: Path) -> None:
    print("mobile 390x844")
    await p.viewport(390, 844, mobile=True)
    await fresh_load(p)
    await p.eval("window.__polytaleMock.actMs = 800; window.__polytaleMock.sceneMs = 1600; true")
    await begin(p, out, "m")
    check("no horizontal overflow (intro/start)", await p.eval(NO_OVERFLOW))
    await opening_checks(p, out, "m")
    await check_registration(p, "390x844")

    await verb(p, "photo", "show", touch=True)
    check("clue toast (mobile)", await p.wait_for("document.querySelector('[data-testid=clue-toast]')", 8, 0.05))
    await asyncio.sleep(0.5)
    await p.shot(out, "m06_clue_toast")
    await wait_idle(p)

    await p.tap("[data-testid=object-beer]")
    await p.wait_for("document.querySelector('[data-testid=verb-menu]')", 3)
    await asyncio.sleep(0.25)
    await p.shot(out, "m07_verb_menu")
    check("verb menu stays on screen (mobile)", await p.eval("(() => { const r = document.querySelector('[data-testid=verb-menu]').getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth; })()"))
    await p.tap("[data-testid=verb-menu] [data-testid=verb-drink]")
    await p.wait_for("document.querySelector('[data-testid=object-beer]').dataset.zone === 'counter'", 8)
    await wait_idle(p)
    await check_registration(p, "390x844 served")
    await p.shot(out, "m08_beer_served")

    await p.click("[data-testid=phrasebook-open]")
    await p.wait_for("document.querySelector('[data-testid=phrase-input]')", 3)
    await p.eval("document.querySelector('[data-testid=phrase-input]').focus(); true")
    await p.call("Input.insertText", text="How much is it?")
    await p.click("[data-testid=phrase-ask]")
    check("phrasebook is a bottom sheet on a phone", await p.wait_for("document.querySelector('[data-testid=phrase-result]')", 5) and await p.eval(
        "(() => { const r = document.querySelector('[data-testid=phrasebook] aside').getBoundingClientRect(); return r.left === 0 && Math.round(r.bottom) === innerHeight && r.top > 80; })()"))
    await asyncio.sleep(0.4)
    await p.shot(out, "m09_phrasebook_sheet")
    check("no horizontal overflow (phrasebook)", await p.eval(NO_OVERFLOW))
    await p.click("[data-testid=phrase-use]")
    check("'Use it' closes the sheet and fills the input", await p.wait_for("!document.querySelector('[data-testid=phrasebook]') && document.querySelector('[data-testid=text-input]').value.length >= 3", 3))
    await p.shot(out, "m10_phrase_in_input")
    await p.click("[data-testid=send-button]")
    await p.wait_for("document.querySelector('[data-testid=input-bar]').dataset.state === 'waiting'", 3, 0.05)
    await wait_idle(p)

    await p.queue(HOW_MUCH)
    x, y = await p.center("[data-testid=mic-button]")
    await p.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
    check("touch hold listens", await p.wait_for("document.querySelector('[data-testid=input-bar]').dataset.state === 'listening'", 4))
    await asyncio.sleep(0.8)
    await p.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
    check("preview (touch)", await p.wait_for("document.querySelector('[data-testid=preview]')", 5, 0.05))
    await asyncio.sleep(0.25)
    await p.shot(out, "m11_preview")
    await p.wait_for("document.querySelector('[data-testid=input-bar]').dataset.state === 'waiting'", 4, 0.05)
    await wait_idle(p)

    await p.click("[data-testid=notebook-button]")
    await p.wait_for("document.querySelector('[data-testid=notebook]')", 3)
    await asyncio.sleep(0.4)
    await p.shot(out, "m12_notebook")
    check("no horizontal overflow (notebook)", await p.eval(NO_OVERFLOW))
    await p.click("[data-testid=notebook-close]")
    await p.click("[data-testid=menu-button]")
    await asyncio.sleep(0.3)
    await p.shot(out, "m13_menu")
    await p.eval("document.body.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true})); true")

    await p.tap("[data-testid=object-money]")  # one verb: it acts at once
    check("a one-verb object acts immediately (mobile)", await p.wait_for("document.querySelector('[data-testid=cash]')?.dataset.wallet === '40'", 8))
    await wait_idle(p)
    await verb(p, "beer", "drink", touch=True)
    check("summary (mobile)", await p.wait_for("document.querySelector('[data-testid=summary]')", 25))
    await asyncio.sleep(1.0)
    await p.shot(out, "m14_summary")
    check("no horizontal overflow (summary)", await p.eval(NO_OVERFLOW))
    await p.click("[data-testid=continue-button]")
    await p.wait_for("document.querySelector('[data-testid=play-view]')?.dataset.scene === 'market'", 12)
    await p.wait_for("document.querySelector('[data-lit=\"1\"]')", 12, 0.05)
    await asyncio.sleep(0.4)
    await p.shot(out, "m15_market_opening")
    await wait_idle(p)
    await check_registration(p, "390x844 market")
    await verb(p, "photo", "show", touch=True)
    await wait_idle(p)
    await verb(p, "noodles", "eat", touch=True)
    await wait_idle(p)
    await p.tap("[data-testid=object-money]")
    check("ending (mobile)", await p.wait_for("document.querySelector('[data-testid=ending]')", 25))
    await asyncio.sleep(1.2)
    await p.shot(out, "m16_ending")
    check("no horizontal overflow (ending)", await p.eval(NO_OVERFLOW))


async def aspects_run(p: Page, out: Path) -> None:
    """Registration at several aspect ratios, the panel open at 1920, and the edge cases."""
    print("aspect ratios")
    await p.viewport(1440, 900, mobile=False)
    await fresh_load(p)
    await p.eval("window.__polytaleMock.actMs = 500; window.__polytaleMock.sceneMs = 800; true")
    await p.click("[data-testid=begin-button]")
    await p.wait_for("document.querySelector('[data-testid=play-view]')", 12)
    await wait_idle(p)
    await verb(p, "beer", "drink")
    await p.wait_for("document.querySelector('[data-testid=object-beer]').dataset.zone === 'counter'", 8)
    await wait_idle(p)
    for w, h, mobile in ((1440, 900, False), (1920, 1080, False), (1024, 768, False), (2560, 1080, False), (390, 844, True), (844, 390, True)):
        await p.viewport(w, h, mobile)
        await asyncio.sleep(0.9)
        await check_registration(p, f"{w}x{h}")
        await p.shot(out, f"a_{w}x{h}")

    # 1920x1080 with the phrasebook open and a result in it: the busiest the screen gets.
    await p.viewport(1920, 1080, mobile=False)
    await asyncio.sleep(0.6)
    await p.click("[data-testid=phrasebook-tab]")
    await p.wait_for("document.querySelector('[data-testid=phrase-input]')", 3)
    await p.eval("document.querySelector('[data-testid=phrase-input]').focus(); true")
    await p.call("Input.insertText", text="I want a beer")
    await p.click("[data-testid=phrase-ask]")
    await p.wait_for("document.querySelector('[data-testid=phrase-result]')", 5)
    await asyncio.sleep(0.4)
    await p.shot(out, "a_1920x1080_phrasebook_open")
    await check_registration(p, "1920x1080 panel open")
    await p.click("[data-testid=phrasebook-close]")

    # The clock runs out: the act ends at the turn boundary and the story still ends.
    await p.viewport(1440, 900, mobile=False)
    await p.eval("window.__polytaleMock.skipMinutes(80); true")
    await p.type_and_send("ni hao")
    check("clock out -> fail forward to an ending", await p.wait_for("document.querySelector('[data-testid=ending]')?.dataset.ending === 'late'", 25))
    await asyncio.sleep(1.0)
    await p.shot(out, "a_ending_missed")

    # A language without romanization and with spaced words: no ruby row at all.
    await fresh_load(p, "&noroman=1&spaced=1")
    await p.click("[data-testid=begin-button]")
    await p.wait_for("document.querySelector('[data-testid=play-view]')", 12)
    await p.wait_for("document.querySelectorAll('[data-testid=subtitle-line]').length >= 2", 12)
    check("romanization_label null -> no ruby row", await p.eval("!document.querySelector('[data-testid=subtitle-line] rt') && !!document.querySelector('[data-testid=subtitle-line] [data-seg=word]')"))
    await p.shot(out, "a_no_romanization")

    # The Japanese lexicon through the same client (language-agnostic).
    await fresh_load(p, "&lang=ja-JP")
    check("language line follows the API (ja-JP)", "Japanese" in (await p.eval("document.querySelector('[data-testid=language-line]')?.textContent || ''")))
    await p.click("[data-testid=begin-button]")
    await p.wait_for("document.querySelector('[data-testid=play-view]')", 12)
    check("ja-JP lines render with ruby", await p.wait_for("document.querySelector('[data-testid=subtitle-line] ruby rt')", 12))
    await asyncio.sleep(1.0)
    await p.shot(out, "a_ja_JP")

    # Art failure: the background 404s, the screen must not go blank.
    await fresh_load(p)
    await p.call("Network.enable")
    await p.call("Network.setBlockedURLs", urls=["*bg.webp*", "*cover.webp*", "*title.webp*"])
    await p.call("Page.reload", ignoreCache=True)
    await p.wait_for("document.querySelector('[data-testid=begin-button]')", 15)
    await p.click("[data-testid=begin-button]")
    ok = await p.wait_for("document.querySelector('[data-testid=play-view]')", 12)
    await p.wait_for("document.querySelectorAll('[data-testid=subtitle-line]').length >= 1", 12)
    check("art 404 -> still playable, not blank", ok and await p.exists("[data-testid=object-beer]") and await p.exists("[data-testid=text-input]"))
    await asyncio.sleep(0.8)
    await p.shot(out, "a_art_missing")
    await p.call("Network.setBlockedURLs", urls=[])


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
        if which in ("all", "aspects"):
            await aspects_run(p, out)
        errs = [e for e in p.errors if "favicon" not in e and "[vite]" not in e and "ERR_BLOCKED_BY_CLIENT" not in e]
        check("no page exceptions", not errs, "; ".join(errs[:3]))
    finally:
        if proc is not None:
            proc.terminate()
    print(f"\n{len(FAILURES)} failure(s)" + (": " + ", ".join(FAILURES) if FAILURES else ""))
    print(f"screenshots: {out}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
