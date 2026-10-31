#!/usr/bin/env bash
# Start the tavern backend with the settings the evidence was produced with.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE/backend"

export TAVERN_DB_BACKEND="${TAVERN_DB_BACKEND:-seekdb}"
export TAVERN_DATA_DIR="${TAVERN_DATA_DIR:-$HERE/data}"
export TAVERN_LOG_DIR="${TAVERN_LOG_DIR:-$HERE/evidence/logs}"
export TAVERN_EVIDENCE_DIR="${TAVERN_EVIDENCE_DIR:-$HERE/evidence}"
export TAVERN_HOST="${TAVERN_HOST:-0.0.0.0}"
export TAVERN_PORT="${TAVERN_PORT:-8770}"
export POWERCONTEXT_URL="${POWERCONTEXT_URL:-http://127.0.0.1:8000}"

exec "${PY:-python3}" -m uvicorn app:app --host "$TAVERN_HOST" --port "$TAVERN_PORT"
