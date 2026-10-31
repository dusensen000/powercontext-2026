#!/usr/bin/env bash
# Reproduce the two-session verification: the backend is restarted between
# sessions, so the second recall can only succeed through seekdb + PowerContext.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE/backend"

PY="${PY:-python3}"
PORT="${TAVERN_PORT:-8770}"
export TAVERN_DB_BACKEND="${TAVERN_DB_BACKEND:-seekdb}"
export TAVERN_DATA_DIR="${TAVERN_DATA_DIR:-$HERE/data}"
export TAVERN_LOG_DIR="${TAVERN_LOG_DIR:-$HERE/evidence/logs}"
export TAVERN_EVIDENCE_DIR="${TAVERN_EVIDENCE_DIR:-$HERE/evidence}"
export TAVERN_API="http://127.0.0.1:$PORT"
export POWERCONTEXT_URL="${POWERCONTEXT_URL:-http://127.0.0.1:8000}"

mkdir -p "$TAVERN_LOG_DIR" "$TAVERN_EVIDENCE_DIR"
PID=""

start() {
  local name="$1"
  "$PY" -m uvicorn app:app --host 127.0.0.1 --port "$PORT" >> "$TAVERN_LOG_DIR/server-$name.log" 2>&1 &
  PID=$!
  for _ in $(seq 1 40); do
    if curl -sf "http://127.0.0.1:$PORT/health" > "$TAVERN_EVIDENCE_DIR/health-$name.json"; then
      echo "[start] backend up for $name (pid $PID)"
      return 0
    fi
    sleep 0.5
  done
  echo "[error] backend did not start; see $TAVERN_LOG_DIR/server-$name.log" >&2
  exit 1
}

stop() {
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    wait "$PID" 2>/dev/null || true
    echo "[stop] backend pid $PID"
  fi
  PID=""
}

trap stop EXIT

if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  echo "[error] port $PORT is already serving /health; stop that process first" >&2
  exit 1
fi

start session1
"$PY" selftest.py session1 | tee "$TAVERN_EVIDENCE_DIR/session1.log"
stop

start session2
"$PY" selftest.py session2 | tee "$TAVERN_EVIDENCE_DIR/session2.log"
stop

echo "[done] evidence in $TAVERN_EVIDENCE_DIR"
