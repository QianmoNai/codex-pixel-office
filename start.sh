#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HOST="${CODEX_PIXEL_HOST:-127.0.0.1}"
PORT="${CODEX_PIXEL_PORT:-8765}"
OPEN_ARGS=()

if [[ "${CODEX_PIXEL_NO_BROWSER:-0}" != "1" ]]; then
  OPEN_ARGS+=(--open-browser)
fi

exec python3 "$ROOT_DIR/server.py" --host "$HOST" --port "$PORT" "${OPEN_ARGS[@]}" "$@"
