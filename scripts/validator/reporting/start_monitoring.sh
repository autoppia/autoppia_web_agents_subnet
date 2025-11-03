#!/usr/bin/env bash

# Start / restart the validator round monitor under pm2.
# This script loads .env, ensures Codex is available, and launches monitor_rounds.py
# with sensible defaults for local testing (pm2 process "validator").

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

PM2_NAME="${PM2_MONITOR_NAME:-validator_monitor}"
PM2_TARGET="${PM2_MONITOR_PM2:-validator}"
BLOCK_DELAY="${PM2_MONITOR_BLOCK_DELAY:-2}"
SECONDS_PER_BLOCK="${PM2_MONITOR_SECONDS_PER_BLOCK:-12}"
POLL_INTERVAL="${PM2_MONITOR_POLL_INTERVAL:-5}"

if ! command -v pm2 >/dev/null 2>&1; then
  echo "[start_monitoring] pm2 CLI not found. Install pm2 or adjust PATH." >&2
  exit 1
fi

if ! command -v codex >/dev/null 2>&1; then
  echo "[start_monitoring] Warning: codex CLI not found. Codex assessments will fail." >&2
fi

MONITOR_SCRIPT="$SCRIPT_DIR/monitor_rounds.py"
if [[ ! -f "$MONITOR_SCRIPT" ]]; then
  echo "[start_monitoring] monitor_rounds.py not found at $MONITOR_SCRIPT" >&2
  exit 1
fi

if pm2 describe "$PM2_NAME" >/dev/null 2>&1; then
  pm2 restart "$PM2_NAME" --update-env
else
  pm2 start "$MONITOR_SCRIPT" \
    --name "$PM2_NAME" \
    --interpreter python3 \
    -- --pm2 "$PM2_TARGET" \
       --block-delay "$BLOCK_DELAY" \
       --seconds-per-block "$SECONDS_PER_BLOCK" \
       --poll-interval "$POLL_INTERVAL"
fi

pm2 save >/dev/null 2>&1 || true

echo "[start_monitoring] pm2 process '$PM2_NAME' is running. Logs:"
pm2 logs "$PM2_NAME" --lines 10 --nostream || true
