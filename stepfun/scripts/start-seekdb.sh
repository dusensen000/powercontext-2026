#!/usr/bin/env bash
# Start a local seekdb server (Linux / WSL2) for the stepfun demo.
#
# On this Windows host the server runs inside the WSL2 distro `seekdb-fix1477`;
# Windows reaches it at the distro IP (WSL localhost forwarding is unavailable):
#   wsl.exe -d seekdb-fix1477 -e bash -lc '<this script>'
#   SEEKDB_HOST=$(wsl.exe -d seekdb-fix1477 hostname -I | awk '{print $1}')
set -euo pipefail

SEEKDB_BIN="${SEEKDB_BIN:-/srv/seekdb-fts-performance/build/seekdb}"
SEEKDB_BASE_DIR="${SEEKDB_BASE_DIR:-/srv/stepfun-probe-db}"
SEEKDB_PORT="${SEEKDB_PORT:-2881}"

if [[ ! -x "$SEEKDB_BIN" ]]; then
  echo "seekdb binary not found: $SEEKDB_BIN" >&2
  echo "Set SEEKDB_BIN to your seekdb 1.4.0 build, e.g. /usr/local/bin/seekdb" >&2
  exit 1
fi

mkdir -p "$SEEKDB_BASE_DIR"

# A fulltext index needs a POSIX filesystem: do not use an NTFS path via /mnt/c
# (fallocate is unsupported there and collection creation hangs).
exec "$SEEKDB_BIN" --nodaemon \
  --port "$SEEKDB_PORT" \
  --base-dir "$SEEKDB_BASE_DIR" \
  --parameter datafile_size=2G \
  --parameter log_disk_size=2G \
  --parameter memory_limit=4G
