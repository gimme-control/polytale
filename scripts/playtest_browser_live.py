#!/usr/bin/env python3
"""Live browser playtest: the REAL stack (Gemini DM + STT + TTS), headless Chrome over CDP.

Microphone input is real learner audio: a test-only override of
navigator.mediaDevices.getUserMedia (installed with Page.addScriptToEvaluateOnNewDocument,
never shipped in the bundle) returns a MediaStream fed by an AudioBufferSourceNode. For
each utterance the driver holds the mic (Space on desktop, touch on a phone), plays the
chosen WAV fixture into that stream, and lets go. The real /transcribe -> "Heard" preview
-> auto-submit -> /act -> TTS pipeline runs.

The character is a live model, so the driver is adaptive: every step has a goal, a list of
moves to try (speak, type, tap), and a cap. HARD checks are about the client and the
contract (no console errors, no failed API calls, audio 200/206, nothing translated on
screen, objects registered to the painting). SOFT checks describe what the character did
and never fail the run; they are printed and saved for a human to read.

Desktop 1440x900 (full journey, both scenes) and phone 390x844 (bar, then market opening).
Screenshots, transcript_*.json and timings.json land in logs/playtests/browser_live_<ts>/.

Needs `bash run.sh --quiet` (API :8100, web :5180).
Run: PYTHONPATH=. ~/.venvs/polytale/bin/python scripts/playtest_browser_live.py [desktop|mobile|all]
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
import time
import wave
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

from scripts.playtest_web_mock import NO_OVERFLOW, REGISTRATION, Page, launch_chrome, open_page

ROOT = Path(__file__).resolve().parents[1]
WEB = os.environ.get("POLYTALE_WEB", "http://localhost:5180")
API = os.environ.get("POLYTALE_API", "http://127.0.0.1:8100")
LOCALE = os.environ.get("POLYTALE_LANGUAGE", "zh-CN")
FIX = ROOT / "scripts" / "fixtures" / "learner_audio" / LOCALE
FAILURES: list[str] = []
NOTES: list[str] = []
TIMINGS: list[dict] = []
MAX_TRIES = 4

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
  if (navigator.mediaDevices) navigator.mediaDevices.getUserMedia = async () => ensure().dest.stream;
})();
"""


def check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"  [{'ok' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)
    return bool(cond)


def soft(name: str, cond: bool, detail: str = "") -> bool:
    """The character's behaviour: reported, never a failure."""
    line = f"{'as hoped' if cond else 'NOTE'}: {name}" + (f"  {detail}" if detail else "")
    print(f"  [{'..' if cond else '!!'}] {line}")
    NOTES.append(line)
    return bool(cond)


class LivePage(Page):
    """Page that also records API traffic: status codes and durations."""

    def __init__(self, ws) -> None:
        super().__init__(ws)
        self.requests: dict[str, dict] = {}
        self.api: list[dict] = []

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
            elif m == "Network.requestWillBeSent":
                r = msg["params"]
                if "/api/" in r["request"]["url"]:
                    self.requests[r["requestId"]] = {"url": r["request"]["url"], "method": r["request"]["method"], "t0": r["timestamp"]}
            elif m == "Network.responseReceived":
                r = msg["params"]
                req = self.requests.get(r["requestId"])
                if req:
                    req.update(status=r["response"]["status"], mime=r["response"].get("mimeType", ""), t1=r["timestamp"])
            elif m == "Network.loadingFinished":
                req = self.requests.pop(msg["params"]["requestId"], None)
                if req and "status" in req:
                    req["ms"] = round((msg["params"]["timestamp"] - req["t0"]) * 1000)
                    self.api.append(req)
            elif m == "Network.loadingFailed":
                req = self.requests.pop(msg["params"]["requestId"], None)
                if req and not msg["params"].get("canceled"):
                    req.update(status=req.get("status", 0), failed=msg["params"].get("errorText"))
                    self.api.append(req)
            if msg.get("id") == my:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})


async def live_page() -> LivePage:
    base = await open_page()
    p = LivePage(base.ws)
    await p.call("Network.enable")
    await p.call("Page.addScriptToEvaluateOnNewDocument", source=MIC_OVERRIDE)
    return p


def clip_seconds(name: str) -> float:
    with wave.open(str(FIX / name)) as w:
        return w.getnframes() / w.getframerate()


async def load_clips(p: Page) -> None:
    for f in sorted(FIX.glob("*.wav")):
        await p.eval(f"window.__ptMic.load({json.dumps(f.name)}, {json.dumps(base64.b64encode(f.read_bytes()).decode())})")


SNAP = """(() => {
  const bar = document.querySelector('[data-testid=input-bar]');
  const zones = {};
  for (const b of document.querySelectorAll('[data-object]')) zones[b.dataset.object] = b.dataset.zone;
  return {
    screen: document.querySelector('[data-screen]')?.dataset.screen,
    scene: document.querySelector('[data-testid=play-view]')?.dataset.scene || null,
    state: bar?.dataset.state || null,
    audible: bar?.dataset.audible === '1',
    lines: [...document.querySelectorAll('[data-testid=subtitle-line]')].map(e => e.dataset.line),
    lit: [...document.querySelectorAll('[data-lit="1"]')].map(e => e.dataset.object),
    preview: document.querySelector('[data-testid=preview]')?.textContent || null,
    notice: document.querySelector('[data-testid=notice]')?.textContent || null,
    mood: document.querySelector('[data-testid=scene]')?.dataset.mood || null,
    goals: [...document.querySelectorAll('[data-goal][data-done="1"]')].map(e => e.dataset.goal),
    zones,
  };
})()"""

STATE = """(async () => {
  const s = JSON.parse(localStorage.getItem('polytale.journey') || 'null');
  if (!s) return null;
  const r = await fetch('/api/journeys/' + s.journey_id, { headers: { 'X-Journey-Token': s.token } });
  return r.ok ? await r.json() : { error: r.status };
})()"""


async def snap(p: Page) -> dict:
    return await p.eval(SNAP)


async def server_state(p: Page) -> dict:
    return await p.eval(STATE) or {}


def say(entry: dict) -> str:
    if entry["kind"] == "npc":
        ln = entry["line"]
        hl = f"  [highlights {', '.join(ln['highlight_object_ids'])}]" if ln["highlight_object_ids"] else ""
        return f"      {ln['speaker_name']}: {ln['text']}  ({ln['romanization']}){hl}"
    if entry["kind"] == "direction":
        return f"      ({entry['text']})"
    if entry["kind"] == "learner":
        what = f"points at {entry['tapped_object_id']}" if entry["input_mode"] == "tap" else f"{entry['input_mode']}: {entry['transcript']!r}"
        return f"    YOU {what}"
    if entry["event"] == "object_moved":
        return f"      * {entry.get('object_id')} {entry.get('from')} -> {entry.get('to')}"
    return f"      * goal done: {entry.get('goal_id')}"


class Run:
    """One viewport's journey: knows how to act, wait, time, and print what was said."""

    def __init__(self, p: LivePage, out: Path, tag: str, mobile: bool) -> None:
        self.p, self.out, self.tag, self.mobile = p, out, tag, mobile
        self.printed = 0
        self.scene_id = ""
        self.log: list[dict] = []
        self.shots = 0

    async def shot(self, name: str) -> None:
        self.shots += 1
        await self.p.shot(self.out, f"{self.tag}{self.shots:02d}_{name}")

    async def print_new(self) -> list[dict]:
        st = await server_state(self.p)
        scene = (st.get("scene") or {}).get("id", "")
        if scene != self.scene_id:
            self.scene_id, self.printed = scene, 0
        entries = st.get("transcript") or []
        new = entries[self.printed :]
        self.printed = len(entries)
        for e in new:
            print(say(e))
            self.log.append({"scene": scene, **e})
        return new

    async def settle(self, timeout: float = 120) -> dict:
        """Turn finished and the character done speaking, or the summary is up."""
        await self.p.wait_for(
            "(() => { const b = document.querySelector('[data-testid=input-bar]'); const s = document.querySelector('[data-screen]')?.dataset.screen;"
            " return s === 'summary' || (b && (b.dataset.state === 'idle' || b.dataset.state === 'error')); })()",
            timeout, 0.2)
        return await snap(self.p)

    async def watch(self, t0: float, label: str, kind: str, before: dict, extra: dict | None = None) -> dict:
        """Poll the pipeline at ~40 ms from `t0`: preview, character text, first audio."""
        t: dict = {"viewport": self.tag, "step": label, "kind": kind, **(extra or {})}
        seen_lit: set[str] = set()
        lit_while_audible = False
        deadline = t0 + 150
        while time.monotonic() < deadline:
            s = await snap(self.p)
            now = round(time.monotonic() - t0, 2)
            if kind == "speech" and "preview_s" not in t and (s["preview"] or s["state"] in ("waiting", "idle") and s["notice"]):
                t["preview_s"] = now
                t["heard"] = (s["preview"] or s["notice"] or "").replace("Heard", "", 1).strip()
                await self.shot(f"{label}_preview")
            if "waiting_s" not in t and s["state"] == "waiting":
                t["waiting_s"] = now
            new_line = [ln for ln in s["lines"] if ln not in before["lines"]]
            if "text_s" not in t and (new_line or s["screen"] == "summary") and s["state"] != "waiting":
                t["text_s"] = now
            if "text_s" in t and "audio_s" not in t and s["audible"]:
                t["audio_s"] = now
                await self.shot(f"{label}_speaking")
            seen_lit.update(s["lit"])
            lit_while_audible = lit_while_audible or (bool(s["lit"]) and s["audible"])
            if "text_s" in t and (s["state"] in ("idle", "error") or s["screen"] == "summary"):
                break
            if "text_s" not in t and s["state"] in ("idle", "error") and now > 1.5 and (kind != "speech" or "preview_s" in t) and "waiting_s" not in t:
                t["rejected"] = s["notice"] or "returned to idle"
                break
            if s["state"] == "error":
                t["error"] = s["notice"]
                break
            await asyncio.sleep(0.04)
        t["highlighted"] = sorted(seen_lit)
        t["highlight_while_audible"] = lit_while_audible
        TIMINGS.append(t)
        print(f"    timing {label}: " + ", ".join(f"{k}={v}" for k, v in t.items() if k.endswith("_s") or k in ("heard", "rejected", "error")))
        return t

    async def speak(self, clip: str, label: str) -> dict:
        p = self.p
        before = await snap(p)
        dur = clip_seconds(clip)
        print(f"    YOU (mic) {clip}")
        if self.mobile:
            x, y = await p.center("[data-testid=mic-button]")
            await p.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
        else:
            await p.space_down()
        check(f"[{self.tag}] {label}: mic listening", await p.wait_for("document.querySelector('[data-testid=input-bar]').dataset.state === 'listening'", 5, 0.05))
        await asyncio.sleep(0.15)
        await p.eval(f"window.__ptMic.play({json.dumps(clip)})")
        await asyncio.sleep(dur * 0.6)
        await self.shot(f"{label}_listening")
        await asyncio.sleep(dur * 0.4 + 0.35)
        if self.mobile:
            await p.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        else:
            await p.space_up()
        t = await self.watch(time.monotonic(), label, "speech", before, {"clip": clip, "clip_s": round(dur, 2)})
        await self.settle()
        await self.print_new()
        return t

    async def type(self, text: str, label: str) -> dict:
        before = await snap(self.p)
        print(f"    YOU (typed) {text!r}")
        await self.p.type_and_send(text)
        t = await self.watch(time.monotonic(), label, "text", before, {"typed": text})
        await self.settle()
        await self.print_new()
        return t

    async def tap(self, object_id: str, label: str) -> dict:
        before = await snap(self.p)
        print(f"    YOU (tap) {object_id}")
        sel = f"[data-testid=object-{object_id}]"
        if self.mobile:
            await self.p.tap(sel)
        else:
            await self.p.mouse_click(sel)
        t = await self.watch(time.monotonic(), label, "tap", before, {"tapped": object_id})
        await self.settle()
        await self.print_new()
        return t

    async def pursue(self, goal: str, done, moves: list[tuple[str, str]]) -> bool:
        """Try moves in order until `done(snapshot)`; the character may need more than one."""
        for i, (how, what) in enumerate(moves[:MAX_TRIES]):
            s = await snap(self.p)
            if s["screen"] == "summary" or done(s):
                return True
            if (await server_state(self.p)).get("scene_complete"):
                # The last line is still playing; the summary follows it.
                return await self.p.wait_for("document.querySelector('[data-testid=summary]')", 60)
            label = f"{goal}{i + 1}"
            t = await (self.speak(what, label) if how == "speak" else self.type(what, label) if how == "type" else self.tap(what, label))
            if t.get("error"):
                check(f"[{self.tag}] {label}: turn went through", False, str(t["error"]))
                await self.p.click("[data-testid=retry-send]")
                await self.settle()
                await self.print_new()
        s = await snap(self.p)
        return s["screen"] == "summary" or done(s)


async def registration(p: Page, label: str) -> None:
    reg = await p.eval(REGISTRATION)
    check(f"objects registered to the painting ({label})", reg["n"] >= 2 and reg["worst"] <= 1.5, f"worst {reg['worst']:.2f}px / {reg['n']} objects, frame {reg['frame']}")
    check(f"every object on screen ({label})", not reg["offscreen"], str(reg["offscreen"]))
    check(f"subtitles clear of the face ({label})", reg["subtitlesClearOfFace"])
    check(f"subtitles do not cover an object ({label})", not reg["covered"], str(reg["covered"]))
    check(f"no horizontal overflow ({label})", await p.eval(NO_OVERFLOW))


def glosses() -> list[str]:
    items = json.loads((ROOT / "content" / "languages" / f"{LOCALE}.json").read_text(encoding="utf-8"))["items"]
    words: set[str] = set()
    for it in items.values():
        for w in re.findall(r"[a-z]+", it["gloss"].lower()):
            if len(w) > 3 and w not in ("want", "have", "this", "much", "that"):
                words.add(w)
    return sorted(words)


async def no_translation(p: Page, label: str) -> None:
    check(f"no gloss element during play ({label})", not await p.exists("[data-role=gloss]") and not await p.exists("[data-testid=word-list]"))
    text = (await p.eval("document.querySelector('[data-testid=play-view]')?.innerText || ''")).lower()
    leaked = [g for g in glosses() if re.search(rf"\b{g}\b", text)]
    # Stage directions and hints are the server's prose; a gloss word there is a prompt issue.
    soft(f"no gloss word in any visible text ({label})", not leaked, f"visible: {leaked}" if leaked else "")


async def begin(r: Run) -> None:
    p = r.p
    await p.call("Page.navigate", url=WEB + "/")
    await p.wait_for("document.readyState === 'complete'", 15)
    await p.eval("localStorage.clear(); true")
    p.errors.clear()
    p.api.clear()
    await p.call("Page.reload", ignoreCache=True)
    check(f"[{r.tag}] start screen", await p.wait_for("document.querySelector('[data-testid=begin-button]')", 20))
    await p.eval("document.fonts.ready.then(() => true)")
    await load_clips(p)
    await asyncio.sleep(0.8)
    check(f"[{r.tag}] language line from the API", await p.eval("(document.querySelector('[data-testid=language-line]')?.textContent || '').includes('·')"))
    await r.shot("start")
    await p.click("[data-testid=begin-button]")


async def opening(r: Run, scene: str) -> None:
    """Intro card -> scene -> first lines; times POST /scene as the browser saw it."""
    p = r.p
    t0 = time.monotonic()
    check(f"[{r.tag}] {scene}: intro card", await p.wait_for("document.querySelector('[data-testid=intro-text]')?.textContent.length > 20", 8))
    await asyncio.sleep(0.5)
    await r.shot(f"{scene}_intro")
    check(f"[{r.tag}] {scene}: scene mounts", await p.wait_for(f"document.querySelector('[data-testid=play-view]')?.dataset.scene === '{scene}'", 90, 0.1))
    mounted = round(time.monotonic() - t0, 2)
    before = {"lines": []}
    t = await r.watch(time.monotonic(), f"{scene}_opening", "opening", before)
    post = next((a for a in reversed(p.api) if a["url"].endswith("/scene") and a["method"] == "POST"), None)
    t.update(intro_to_scene_s=mounted, post_scene_ms=post["ms"] if post else None)
    print(f"    POST /scene {post['ms'] if post else '?'} ms; intro card up for {mounted}s")
    await r.settle()
    new = await r.print_new()
    lines = [e for e in new if e["kind"] == "npc"]
    check(f"[{r.tag}] {scene}: opening has 1-3 lines", 1 <= len(lines) <= 3, str(len(lines)))
    check(f"[{r.tag}] {scene}: ruby over each word", await p.eval(
        "(() => { const r = document.querySelector('[data-testid=subtitle-line] ruby'); const rt = r?.querySelector('rt');"
        " return !!rt && rt.textContent.trim().length > 0 && rt.getBoundingClientRect().bottom <= r.getBoundingClientRect().bottom - 6; })()"))
    wanted = sorted({o for e in lines for o in e["line"]["highlight_object_ids"]})
    if wanted:
        check(f"[{r.tag}] {scene}: highlights drawn for the ids the character named", set(wanted) <= set(t["highlighted"]), f"named {wanted}, drawn {t['highlighted']}")
        check(f"[{r.tag}] {scene}: highlighted while the line's audio played", t["highlight_while_audible"])
    else:
        soft(f"{scene}: opening highlights something", False, "the character named no object to highlight")
    check(f"[{r.tag}] {scene}: first audio played", "audio_s" in t, str(t))
    await r.shot(f"{scene}_opening_idle")
    await registration(p, f"{r.tag} {scene}")
    await no_translation(p, f"{r.tag} {scene}")


async def reload_restores(r: Run, label: str, expect: str) -> None:
    p = r.p
    before = await snap(p)
    await p.eval("window.__stale = true")
    await p.call("Page.reload")
    await p.wait_for("!window.__stale && document.querySelector('[data-screen]') && document.querySelector('[data-screen]').dataset.screen !== 'boot'", 20)
    await asyncio.sleep(1.0)
    after = await snap(p)
    ok = after["screen"] == expect and (expect != "play" or (after["zones"] == before["zones"] and after["goals"] == before["goals"] and len(after["lines"]) >= 1))
    check(f"[{r.tag}] refresh restores ({label})", ok, f"{after['screen']} zones={after['zones']}")
    await load_clips(p)
    await r.shot(f"restored_{label}")


async def summary_checks(r: Run, scene: str) -> dict:
    p = r.p
    check(f"[{r.tag}] {scene}: summary", await p.wait_for("document.querySelector('[data-testid=summary]')", 60))
    await asyncio.sleep(1.0)
    await r.shot(f"{scene}_summary")
    st = await server_state(p)
    summary = st.get("summary") or {}
    rows = await p.eval("[...document.querySelectorAll('[data-testid=word-row]')].map(e => ({item: e.dataset.item, state: e.dataset.state, recall: e.dataset.recall, text: e.innerText.replace(/\\n+/g, ' | ')}))")
    for row in rows:
        print(f"      {row['text']}")
    for line in summary.get("lines", []):
        print(f"      > {line}")
    check(f"[{r.tag}] {scene}: every target listed with a gloss", len(rows) == len(summary.get("items", [])) >= 8 and await p.eval("document.querySelectorAll('[data-role=gloss]').length") == len(rows))
    check(f"[{r.tag}] {scene}: states match the server", all(row["state"] == next(i["state"] for i in summary["items"] if i["item_id"] == row["item"]) for row in rows))
    n_audio = len([a for a in p.api if "/items/" in a["url"]])
    await p.click("[data-testid=word-row]:not([data-state=not_encountered])")
    got = await p.wait_for("true", 0.1) and await wait_api(p, "/items/", n_audio, 30)
    check(f"[{r.tag}] {scene}: tap a word to hear it", got)
    recalled = summary.get("recalled") or []
    check(f"[{r.tag}] {scene}: recall callout matches the server", (await p.exists("[data-testid=recall-callout]")) == bool(recalled), str(recalled))
    check(f"[{r.tag}] {scene}: no horizontal overflow on the summary", await p.eval(NO_OVERFLOW))
    return summary


async def wait_api(p: LivePage, needle: str, seen: int, timeout: float) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        await p.eval("1")
        if len([a for a in p.api if needle in a["url"]]) > seen:
            return True
        await asyncio.sleep(0.2)
    return False


async def help_two_steps(r: Run) -> None:
    p = r.p
    label1 = await p.eval("document.querySelector('[data-testid=help-button]').textContent.trim()")
    await p.click("[data-testid=help-button]")
    ok = await p.wait_for("document.querySelector('[data-testid=input-bar]').dataset.state === 'speaking'", 10, 0.05)
    check(f"[{r.tag}] help 1 ({label1!r}) replays the exchange", ok)
    await p.wait_for("document.querySelector('[data-testid=input-bar]').dataset.audible === '1'", 20, 0.05)
    await asyncio.sleep(0.4)
    s = await snap(p)
    soft("help 1 highlights what was just named", bool(s["lit"]), f"lit: {s['lit']}")
    await r.shot("help1")
    check(f"[{r.tag}] help 1 shows no hint text", not await p.exists("[data-testid=help-hint]"))
    await r.settle()
    label2 = await p.eval("document.querySelector('[data-testid=help-button]').textContent.trim()")
    await p.click("[data-testid=help-button]")
    check(f"[{r.tag}] help 2 ({label2!r}) shows the intent hint", await p.wait_for("document.querySelector('[data-testid=help-hint]')?.textContent.length > 8", 10))
    hint = await p.eval("document.querySelector('[data-testid=help-hint]')?.textContent")
    print(f"      hint: {hint}")
    NOTES.append(f"help 2 hint: {hint}")
    check(f"[{r.tag}] no third help step", await p.wait_for("document.querySelector('[data-testid=help-button]').disabled", 5))
    await asyncio.sleep(0.3)
    await r.shot("help2")
    await registration(p, f"{r.tag} help 2")


async def desktop_run(p: LivePage, out: Path) -> None:
    print("desktop 1440x900")
    await p.viewport(1440, 900, mobile=False)
    r = Run(p, out, "d", mobile=False)
    await begin(r)
    await opening(r, "bar")

    # The support language: the character must not understand, and nothing should happen.
    await r.type("can I get a beer?", "english_typed")
    s = await snap(p)
    soft("typed English -> puzzled mood", s["mood"] == "puzzled", f"mood={s['mood']}")
    soft("typed English -> no goal, nothing served", not s["goals"] and "counter" not in s["zones"].values(), f"goals={s['goals']} zones={s['zones']}")
    await r.shot("english_typed")
    await registration(p, "d after English")

    await help_two_steps(r)

    t = await r.speak("a_beer_please_en.wav", "english_mic")
    s = await snap(p)
    soft("spoken English -> no goal, nothing served", not s["goals"] and "counter" not in s["zones"].values(), f"heard={t.get('heard')!r} goals={s['goals']} zones={s['zones']}")

    await p.mouse_click("[data-testid=persona-brisk]")
    check("[d] persona toast", await p.wait_for("(document.querySelector('[data-testid=toast]')?.textContent || '').includes('next reply')", 5))
    await r.shot("persona_brisk")

    served = lambda s: any(s["zones"].get(o) == "counter" for o in ("beer", "water", "tea"))  # noqa: E731
    ok = await r.pursue("order", lambda s: s["zones"].get("beer") == "counter", [("speak", "pijiu.wav"), ("speak", "wo_yao_pijiu.wav"), ("tap", "beer")])
    s = await snap(p)
    soft("beer on the counter after asking for it", ok, f"zones={s['zones']}")
    check("[d] a drink was served", served(s), str(s["zones"]))
    check("[d] first goal checked off in the chrome", "order" in s["goals"], str(s["goals"]))
    first = next((t for t in TIMINGS if t["step"] == "order1"), {})
    check("[d] speech: preview appeared, then auto-submitted", "preview_s" in first and "waiting_s" in first and first["waiting_s"] - first["preview_s"] >= 1.0, str(first))
    await r.shot("drink_served")
    await registration(p, "d drink served")
    await no_translation(p, "d drink served")

    await reload_restores(r, "mid-scene", "play")

    await r.type("duoshao qian", "price")
    s = await snap(p)
    await r.shot("asked_price")
    await registration(p, "d asked price")

    paid = await r.pursue("pay", lambda s: False, [("tap", "money"), ("type", "qian"), ("tap", "money"), ("speak", "xiexie.wav")])
    check("[d] bar completes after paying", paid and (await snap(p))["screen"] == "summary" or await p.wait_for("document.querySelector('[data-testid=summary]')", 60))
    bar = await summary_checks(r, "bar")
    (out / "transcript_bar_desktop.json").write_text(json.dumps([e for e in r.log if e["scene"] == "bar"], ensure_ascii=False, indent=1), encoding="utf-8")
    await reload_restores(r, "summary", "summary")
    beer_bar = next((i for i in bar.get("items", []) if i["item_id"] == "beer"), {})
    print(f"    bar verdict on beer: {beer_bar.get('state')} {beer_bar.get('outcomes')}")

    # Scene 2.
    check("[d] continue names the next scene", "Night Market" in (await p.eval("document.querySelector('[data-testid=continue-button]')?.textContent || ''")))
    await p.click("[data-testid=continue-button]")
    await opening(r, "market")
    await r.pursue("food", lambda s: any(s["zones"].get(o) == "counter" for o in ("noodles", "dumplings")), [("speak", "wo_yao_mian.wav"), ("tap", "noodles"), ("tap", "noodles")])
    s = await snap(p)
    check("[d] market: food served", "food" in s["goals"], str(s))
    await r.shot("market_food")
    await registration(p, "d market food")
    await r.pursue("recall", lambda s: any(s["zones"].get(o) == "counter" for o in ("beer", "water")), [("type", "啤酒"), ("type", "wo yao pijiu"), ("tap", "beer")])
    s = await snap(p)
    check("[d] market: drink served", "drink" in s["goals"], str(s))
    await r.shot("market_drink")
    await registration(p, "d market drink")
    await no_translation(p, "d market")
    await r.pursue("pay", lambda s: False, [("type", "duoshao qian"), ("tap", "money"), ("tap", "money"), ("type", "qian")])
    market = await summary_checks(r, "market")
    (out / "transcript_market_desktop.json").write_text(json.dumps([e for e in r.log if e["scene"] == "market"], ensure_ascii=False, indent=1), encoding="utf-8")

    lit_beer = [e["line"]["text"] for e in r.log if e["scene"] == "market" and e["kind"] == "npc" and "beer" in e["line"]["highlight_object_ids"]]
    if beer_bar.get("state") == "mastered":
        soft("recall: beer never highlighted in scene 2 (it was mastered in the bar)", not lit_beer, f"highlighted on: {lit_beer}")
        soft("recall: beer in the scene-2 recall callout", "beer" in (market.get("recalled") or []), f"recalled={market.get('recalled')}")
    else:
        soft("recall precondition: the bar marked beer mastered", False, f"bar said {beer_bar.get('state')} {beer_bar.get('outcomes')}; scene 2 highlighted beer on {lit_beer}; recalled={market.get('recalled')}")
    check("[d] last scene offers Start over only", await p.exists("[data-testid=start-over]") and not await p.exists("[data-testid=continue-button]"))


async def mobile_run(p: LivePage, out: Path) -> None:
    print("mobile 390x844")
    await p.viewport(390, 844, mobile=True)
    r = Run(p, out, "m", mobile=True)
    await begin(r)
    await opening(r, "bar")
    ok = await r.pursue("order", lambda s: any(s["zones"].get(o) == "counter" for o in ("beer", "water", "tea")), [("speak", "pijiu.wav"), ("speak", "wo_yao_pijiu.wav"), ("tap", "beer")])
    check("[m] a drink was served", ok)
    await r.shot("drink_served")
    await registration(p, "m drink served")
    await help_two_steps(r)
    await r.type("duoshao qian", "price")
    await r.shot("asked_price")
    await p.click("[data-testid=history-button]")
    await p.wait_for("document.querySelector('[data-testid=history]')", 5)
    await asyncio.sleep(0.4)
    await r.shot("history")
    check("[m] no horizontal overflow (history)", await p.eval(NO_OVERFLOW))
    await p.click("[data-testid=history-close]")
    await r.pursue("pay", lambda s: False, [("tap", "money"), ("type", "qian"), ("tap", "money")])
    await summary_checks(r, "bar")
    await p.eval("document.querySelector('[data-testid=summary]').scrollTo(0, 99999); true")
    await asyncio.sleep(0.3)
    await r.shot("bar_summary_end")
    (out / "transcript_bar_mobile.json").write_text(json.dumps(r.log, ensure_ascii=False, indent=1), encoding="utf-8")
    await p.click("[data-testid=continue-button]")
    await opening(r, "market")


def verdict(p: LivePage) -> None:
    errs = [e for e in p.errors if "favicon" not in e and "[vite]" not in e]
    check("no console errors / page exceptions", not errs, "; ".join(errs[:4]))
    bad = [a for a in p.api if not (200 <= a.get("status", 0) < 300 or a.get("status") in (206, 304))]
    check("no failed API calls", not bad, "; ".join(f"{a['method']} {a['url'].split('/api/')[1][:60]} -> {a.get('status')} {a.get('failed', '')}" for a in bad[:6]))
    audio = [a for a in p.api if a["url"].split("?")[0].endswith("/audio")]
    check("all audio 200/206", bool(audio) and all(a["status"] in (200, 206) for a in audio), f"{len(audio)} clips")
    slow = sorted((a for a in audio), key=lambda a: -a["ms"])[:3]
    print("    slowest audio fetches: " + ", ".join(f"{a['ms']} ms" for a in slow))


async def main() -> int:
    out = ROOT / "logs" / "playtests" / f"browser_live_{datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    print(f"live browser playtest -> {out}")
    for url, what in ((WEB, "web"), (API + "/api/health", "API")):
        try:
            urlopen(url, timeout=5).read(64)
        except Exception:
            raise SystemExit(f"{what} not reachable at {url} (bash run.sh --quiet)")
    proc = launch_chrome()
    try:
        p = await live_page()
        which = sys.argv[1] if len(sys.argv) > 1 else "all"
        try:
            if which in ("all", "desktop"):
                await desktop_run(p, out)
                verdict(p)
            if which in ("all", "mobile"):
                await mobile_run(p, out)
                verdict(p)
        finally:
            (out / "timings.json").write_text(json.dumps({"timings": TIMINGS, "notes": NOTES, "failures": FAILURES, "api": p.api}, ensure_ascii=False, indent=1), encoding="utf-8")
    finally:
        if proc is not None:
            proc.terminate()
    print("\nnotes on the character:")
    for n in NOTES:
        print(f"  - {n}")
    print(f"\n{len(FAILURES)} failure(s)" + (": " + "; ".join(FAILURES) if FAILURES else ""))
    print(f"artifacts: {out}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
