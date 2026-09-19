#!/usr/bin/env bash
# Polytale dev runner.
#   bash run.sh            API on :8100 + Vite on :5180, then tail logs (Ctrl-C stops both)
#   bash run.sh --quiet    same, detached; logs in .logs/, URL in .logs/web.url
#   bash run.sh --stop     stop everything this project is running on its ports
#   bash run.sh --prod     build web/dist and serve SPA + API from :8100
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"

VENV="${POLYTALE_VENV:-$HOME/.venvs/polytale}"
PY="$VENV/bin/python"
API_PORT="${POLYTALE_PORT:-8100}"
WEB_PORT="${POLYTALE_WEB_PORT:-5180}"
mkdir -p .logs
for port in "$API_PORT" "$WEB_PORT"; do
  [[ $port =~ ^[0-9]+$ ]] || { echo "Invalid port: $port"; exit 1; }
done

# PIDs listening on a TCP port.
port_pids() {
  ss -ltnpH "sport = :$1" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u
}

# Kill a process and everything it spawned (npm → sh → node chains).
kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}

# Free a port, but only from a process that belongs to this project; anything else is
# reported instead of killed.
free_port() {
  local port=$1 pid cmd cwd
  for pid in $(port_pids "$port"); do
    cmd="$(tr '\0' ' ' </proc/"$pid"/cmdline 2>/dev/null || true)"
    cwd="$(readlink /proc/"$pid"/cwd 2>/dev/null || true)"
    if [[ $cmd == *"$HERE"* || $cwd == "$HERE"* ]]; then
      kill_tree "$pid"
    else
      echo "Port $port is used by another program (pid $pid: ${cmd:-unknown})."
      echo "Stop it, or pick other ports: POLYTALE_PORT=... POLYTALE_WEB_PORT=... bash run.sh"
      exit 1
    fi
  done
  for _ in $(seq 1 20); do
    [[ -z "$(port_pids "$port")" ]] && return 0
    sleep 0.25
  done
  echo "Port $port did not free up; stop the process holding it and retry."
  exit 1
}

stop() {
  for f in .logs/api.pid .logs/web.pid; do
    if [[ -f $f ]]; then kill_tree "$(cat "$f")"; fi
    rm -f "$f"
  done
  free_port "$API_PORT"
  free_port "$WEB_PORT"
}

# Wait until a URL answers, or fail with the tail of the log that explains why.
wait_up() {
  local name=$1 url=$2 log=$3 pidfile=$4
  for _ in $(seq 1 80); do
    curl -sf -o /dev/null "$url" && return 0
    if ! kill -0 "$(cat "$pidfile")" 2>/dev/null; then break; fi
    sleep 0.25
  done
  echo "The $name failed to start. Last lines of $log:"
  tail -n 20 "$log"
  stop
  exit 1
}

if [[ ! -x $PY ]]; then
  echo "Missing venv at $VENV. Create it with:"
  echo "  python3 -m venv $VENV && $VENV/bin/pip install -r requirements.txt"
  exit 1
fi
[[ -d web/node_modules ]] || (cd web && npm install --silent)

case "${1:-}" in
  --stop)
    stop
    echo "stopped"
    exit 0
    ;;
  --prod)
    stop
    (cd web && npm run build --silent)
    echo "Polytale → http://localhost:$API_PORT"
    exec env POLYTALE_SERVE_WEB=1 PYTHONPATH=. "$PY" -m uvicorn server.app:app \
      --port "$API_PORT" --host 0.0.0.0
    ;;
esac

stop
# Launch the real server processes (no npx/npm wrappers) so the saved PIDs are the servers.
PYTHONPATH=. nohup "$PY" -m uvicorn server.app:app --port "$API_PORT" >.logs/api.log 2>&1 &
echo $! >.logs/api.pid
(cd web && exec env POLYTALE_API_PORT="$API_PORT" nohup node node_modules/vite/bin/vite.js \
  --port "$WEB_PORT" --strictPort >../.logs/web.log 2>&1) &
echo $! >.logs/web.pid

wait_up "API" "http://localhost:$API_PORT/api/health" .logs/api.log .logs/api.pid
wait_up "web server" "http://localhost:$WEB_PORT/" .logs/web.log .logs/web.pid
echo "http://localhost:$WEB_PORT" >.logs/web.url
echo "Polytale → http://localhost:$WEB_PORT   (API :$API_PORT, logs in .logs/)"

if [[ "${1:-}" == "--quiet" ]]; then
  exit 0
fi
tail -n 0 -f .logs/api.log .logs/web.log &
TAIL_PID=$!
# `wait` (unlike a foreground tail) is interrupted by the trapped signal, so Ctrl-C and a
# plain SIGINT/SIGTERM to this script both stop the servers.
trap 'kill "$TAIL_PID" 2>/dev/null; echo; stop; echo stopped; exit 0' INT TERM
wait "$TAIL_PID"
