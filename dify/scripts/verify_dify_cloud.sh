#!/usr/bin/env bash
# Proof run for the Dify task: drive the *published Dify app* for two nights,
# restarting the tavern backend in between, and keep Dify's own node traces.
#
# Prerequisites:
#   1. The Chatflow is imported and published on Dify Cloud.
#   2. Dify can reach the backend. For Dify Cloud + a local backend, expose
#      port 8770 with a tunnel and set TAVERN_API in the app to that URL, e.g.
#        cloudflared tunnel --url http://127.0.0.1:8770
#   3. Export DIFY_APP_CODE=<code after https://udify.app/chat/>.
#
# Usage:
#   DIFY_APP_CODE=xxxx ./scripts/verify_dify_cloud.sh
#   DIFY_PROXY=http://127.0.0.1:7897 DIFY_APP_CODE=xxxx ./scripts/verify_dify_cloud.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE/backend"

PY="${PY:-python3}"
PORT="${TAVERN_PORT:-8770}"
OUT="$HERE/evidence/dify/cloud"
export TAVERN_DB_BACKEND="${TAVERN_DB_BACKEND:-seekdb}"
export TAVERN_DATA_DIR="${TAVERN_DATA_DIR:-$HERE/data}"
export TAVERN_LOG_DIR="${TAVERN_LOG_DIR:-$HERE/evidence/logs}"
export TAVERN_EVIDENCE_DIR="${TAVERN_EVIDENCE_DIR:-$HERE/evidence}"
export TAVERN_API="http://127.0.0.1:$PORT"
export POWERCONTEXT_URL="${POWERCONTEXT_URL:-http://127.0.0.1:8000}"
export DIFY_EVIDENCE_DIR="${DIFY_EVIDENCE_DIR:-$OUT}"

mkdir -p "$TAVERN_LOG_DIR" "$TAVERN_EVIDENCE_DIR" "$OUT"

if [ -z "${DIFY_APP_CODE:-}" ]; then
  echo "[error] export DIFY_APP_CODE=<code from https://udify.app/chat/...>" >&2
  exit 1
fi

PID=""

start() {
  local name="$1"
  "$PY" -m uvicorn app:app --host 0.0.0.0 --port "$PORT" >> "$TAVERN_LOG_DIR/server-$name.log" 2>&1 &
  PID=$!
  for _ in $(seq 1 40); do
    if curl -sf "http://127.0.0.1:$PORT/health" > /dev/null; then
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

echo "[info] Dify app code: $DIFY_APP_CODE"
echo "[info] evidence: $OUT"

start night1
"$PY" "$HERE/scripts/verify_dify_cloud.py" night1 | tee "$OUT/night1.log"
stop

# The restart is what makes night 2 a cross-process, cross-conversation recall.
start night2
"$PY" "$HERE/scripts/verify_dify_cloud.py" night2 | tee "$OUT/night2.log"
stop

echo "[done] Dify workflow/node traces and backend logs are in $OUT"
