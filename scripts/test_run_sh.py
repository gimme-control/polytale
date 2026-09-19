"""run.sh process handling: stale servers, reruns, stop, foreign port owners, bad config.

Uses spare ports (8190/5190) so it never disturbs a running dev stack.
Run: PYTHONPATH=. python scripts/test_run_sh.py
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request

from scripts.testkit import ROOT, Checker

T = Checker("test_run_sh")
API, WEB = 8190, 5190
ENV = {**os.environ, "POLYTALE_PORT": str(API), "POLYTALE_WEB_PORT": str(WEB)}


def run(*args: str, env: dict | None = None, timeout: float = 90) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "run.sh", *args], cwd=ROOT, env=env or ENV, text=True,
                          capture_output=True, timeout=timeout)


def listening(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def ok(url: str) -> bool:
    try:
        return urllib.request.urlopen(url, timeout=5).status == 200
    except OSError:
        return False


def wait_listening(port: int, seconds: float = 15) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if listening(port):
            return True
        time.sleep(0.25)
    return False


def test_lifecycle() -> None:
    # A leftover dev server from this project (started outside run.sh) holds the web port.
    stale = subprocess.Popen(["npx", "vite", "--port", str(WEB)], cwd=ROOT / "web",
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    T.check("stale vite holds the port", wait_listening(WEB))
    r = run("--quiet")
    T.check("start replaces a stale project server", r.returncode == 0, r.stdout + r.stderr)
    T.check("web answers", ok(f"http://127.0.0.1:{WEB}/"))
    T.check("api answers through the web proxy", ok(f"http://127.0.0.1:{WEB}/api/health"))
    stale.wait(10)

    r = run("--quiet")
    T.check("rerun while running succeeds", r.returncode == 0, r.stdout + r.stderr)
    pid = int((ROOT / ".logs" / "web.pid").read_text())
    T.check("saved web pid is the live server", os.path.exists(f"/proc/{pid}"))

    r = run("--stop")
    T.check("stop succeeds", r.returncode == 0, r.stdout + r.stderr)
    T.check("stop frees both ports", not listening(API) and not listening(WEB))


def test_foreground_ctrl_c() -> None:
    for label, deliver in [
        # a terminal's Ctrl-C signals the whole foreground process group
        ("terminal ctrl-c", lambda p: os.killpg(p.pid, signal.SIGINT)),
        # `kill -INT` aimed at the script alone
        ("sigint to script", lambda p: p.send_signal(signal.SIGINT)),
    ]:
        proc = subprocess.Popen(["bash", "run.sh"], cwd=ROOT, env=ENV, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            T.check(f"{label}: foreground start comes up",
                    wait_listening(WEB, 30) and wait_listening(API, 30))
            time.sleep(1)
            deliver(proc)
            out, _ = proc.communicate(timeout=30)
            T.check(f"{label}: exits cleanly", proc.returncode == 0, out)
            T.check(f"{label}: frees both ports",
                    not listening(API) and not listening(WEB), out)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                run("--stop")


def test_foreign_owner_is_not_killed() -> None:
    foreign = subprocess.Popen([sys.executable, "-m", "http.server", str(WEB)], cwd="/tmp",
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        T.check("foreign server listening", wait_listening(WEB))
        r = run("--quiet")
        T.check("refuses when another program owns the port", r.returncode == 1, r.stdout)
        T.check("explains who holds the port", "used by another program" in r.stdout, r.stdout)
        T.check("foreign process left alive", foreign.poll() is None)
        T.check("nothing of ours left running", not listening(API))
    finally:
        foreign.kill()
        foreign.wait()


def test_bad_config() -> None:
    r = run("--quiet", env={**ENV, "POLYTALE_PORT": "abc"})
    T.check("invalid port rejected", r.returncode == 1 and "Invalid port" in r.stdout, r.stdout)
    r = run("--quiet", env={**ENV, "POLYTALE_TURN_TIMEOUT_S": "oops"})
    T.check("api crash at startup reported", r.returncode == 1
            and "failed to start" in r.stdout and "ValueError" in r.stdout, r.stdout)
    T.check("crash leaves nothing running", not listening(API) and not listening(WEB))


try:
    for name, fn in [("lifecycle", test_lifecycle), ("ctrl_c", test_foreground_ctrl_c),
                     ("foreign", test_foreign_owner_is_not_killed), ("bad_config", test_bad_config)]:
        T.run(name, fn)
finally:
    run("--stop")
T.finish()
