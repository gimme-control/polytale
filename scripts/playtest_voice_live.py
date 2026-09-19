"""Live end-to-end voice playtest over HTTP against a running server (real STT, DM, TTS).

Plays the golden path with recorded learner audio from scripts/fixtures/learner_audio/:
  kagi.wav → key_kudasai.wav (mixed-language request) → chizu_please.wav (transfer)
and checks the world, the ledger, audio for every NPC line, refresh restoration and the recap.

Needs the API running (bash run.sh --quiet, or uvicorn on POLYTALE_API).
Run: PYTHONPATH=. python scripts/playtest_voice_live.py [--runs N] [--keep-going]
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import httpx

from scripts.testkit import CARTRIDGE_ID, ROOT, Checker

API = __import__("os").environ.get("POLYTALE_API", "http://127.0.0.1:8100")
AUDIO = ROOT / "scripts" / "fixtures" / "learner_audio"
T = Checker("playtest_voice_live")
LATENCY: dict[str, list[float]] = {"stt": [], "turn": [], "first_audio": []}


def timed(fn, *a, **kw) -> tuple[Any, float]:
    t0 = time.monotonic()
    out = fn(*a, **kw)
    return out, time.monotonic() - t0


def fetch_audio(http: httpx.Client, sid: str, token: str, line: dict) -> float:
    r, dt = timed(http.get, f"{API}{line['audio_url']}", params={"token": token})
    T.check(f"audio {line['line_id']} 200 ({dt:.2f}s)", r.status_code == 200
            and len(r.content) > 1000, (r.status_code, len(r.content)))
    return dt


def show(result: dict) -> None:
    print(f"   narration: {result['narration']}")
    for line in result["spoken_lines"]:
        print(f"   {line['speaker_name']}: {line['text']}  /  {line['romanization']}"
              f"  [{line['translation']}] pattern={line['pattern_id']}")
    for ev in result["evidence"]:
        print(f"   evidence: {ev['evidence_type']} {ev['outcome']} {ev['stage_after']} "
              f"support={ev['support_level']}")


def speak(http: httpx.Client, sid: str, hdr: dict, clip: str) -> dict:
    wav = (AUDIO / clip).read_bytes()
    r, dt = timed(http.post, f"{API}/api/sessions/{sid}/transcribe",
                  files={"audio": (clip, wav, "audio/wav")}, headers=hdr)
    LATENCY["stt"].append(dt)
    T.check(f"transcribe {clip} 200", r.status_code == 200, r.text)
    tr = r.json()
    print(f"\n>> {clip}: heard {tr['transcript']!r} ({tr['romanized']}) "
          f"langs={tr['detected_languages']} conf={tr['confidence']} [{dt:.2f}s]")
    r, dt = timed(http.post, f"{API}/api/sessions/{sid}/act",
                  json={"attempt_id": tr["attempt_id"]}, headers=hdr)
    LATENCY["turn"].append(dt)
    T.check(f"act {clip} 200 ({dt:.2f}s)", r.status_code == 200, r.text)
    result = r.json()
    show(result)
    for line in result["spoken_lines"]:
        T.check(f"{line['line_id']} has romanization+translation",
                bool(line["romanization"]) and bool(line["translation"]), line)
    if result["spoken_lines"]:
        LATENCY["first_audio"].append(
            fetch_audio(http, sid, hdr["X-Session-Token"], result["spoken_lines"][0]))
    return result


def play_once(http: httpx.Client, keep_going: bool) -> bool:
    before = len(T.failed)
    r = http.post(f"{API}/api/sessions", json={"cartridge_id": CARTRIDGE_ID})
    body = r.json()
    sid, token = body["session_id"], body["token"]
    hdr = {"X-Session-Token": token}
    opening = http.post(f"{API}/api/sessions/{sid}/start", headers=hdr).json()
    show(opening)
    fetch_audio(http, sid, token, opening["spoken_lines"][0])

    # Beat 1: recognition. The learner repeats the word; a second try if she needed more.
    res = speak(http, sid, hdr, "kagi.wav")
    if res["learning"]["active_beat"]["id"] == "ground_key":
        res = speak(http, sid, hdr, "kagi.wav")
    T.check("recognized → request_key", res["learning"]["active_beat"]["id"] == "request_key",
            res["learning"]["active_beat"])

    # Beat 2: a mixed-language, fragmentary request.
    res = speak(http, sid, hdr, "key_kudasai.wav")
    if res["world"]["holders"]["obj.engine_key"] != "player":
        res = speak(http, sid, hdr, "kagi_o_kudasai.wav")
    T.check("key given to player", res["world"]["holders"]["obj.engine_key"] == "player")
    T.check("engine panel open", res["world"]["fixtures"]["fx.engine_panel"] == "open")
    T.check("plate shows open panel", res["world"]["plate_url"].endswith("plate_panel_open.png"))
    T.check("now on transfer_map", (res["learning"]["active_beat"] or {}).get("id") ==
            "transfer_map", res["learning"]["active_beat"])
    modeled = [ln for ln in res["spoken_lines"]
               if ln["pattern_id"] and "object.map" in ln["concept_ids"]]
    T.check("map request NOT modeled before the learner tries", not modeled, modeled)

    # Refresh mid-episode restores everything.
    ps = http.get(f"{API}/api/sessions/{sid}", headers=hdr).json()
    T.check("refresh keeps world", ps["world"] == res["world"])
    T.check("refresh keeps transcript", len(ps["transcript"]) >= 8, len(ps["transcript"]))

    # Beat 3: transfer to a new slot without a completed sentence.
    res = speak(http, sid, hdr, "chizu_please.wav")
    if not res["episode_complete"]:
        res = speak(http, sid, hdr, "chizu_o_kudasai.wav")
    T.check("map given", res["world"]["holders"]["obj.route_map"] == "player")
    T.check("airship launched", res["world"]["fixtures"]["fx.airship"] == "launched")
    T.check("episode complete", res["episode_complete"] is True)
    recap = http.get(f"{API}/api/sessions/{sid}/recap", headers=hdr).json()
    print("\n   RECAP:", *recap["lines"], sep="\n     ")
    stages = res["learning"]["concept_stage"]
    T.check("key produced", stages["object.key"] in {"produced_with_cue",
                                                     "produced_independently", "transferred"},
            stages)
    T.check("map transferred (or honestly downgraded)", stages["object.map"] in {
        "transferred", "produced_with_cue"}, stages)
    T.check("recap recognized both words", {c["concept_id"] for c in recap["recognized"]} >=
            {"object.key", "object.map"}, recap["recognized"])
    ok = len(T.failed) == before
    print(f"\n== run {'PASSED' if ok else 'FAILED'} (session {sid})")
    return ok or keep_going


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--keep-going", action="store_true")
    args = ap.parse_args()
    with httpx.Client(timeout=90) as http:
        try:
            health = http.get(f"{API}/api/health").json()
        except httpx.HTTPError:
            sys.exit(f"API not reachable at {API}; start it with: bash run.sh --quiet")
        print("health:", health)
        passes = 0
        for i in range(args.runs):
            print(f"\n================ run {i + 1}/{args.runs}")
            before = len(T.failed)
            if not play_once(http, args.keep_going):
                break
            passes += len(T.failed) == before
    for k, v in LATENCY.items():
        if v:
            s = sorted(v)
            print(f"latency {k}: median {s[len(s) // 2]:.2f}s max {s[-1]:.2f}s n={len(s)}")
    print(f"golden path runs passed: {passes}/{args.runs}")
    T.finish()


if __name__ == "__main__":
    main()
