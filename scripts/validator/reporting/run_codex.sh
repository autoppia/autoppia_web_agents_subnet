#!/usr/bin/env bash
set -euo pipefail

# Default OFF to avoid unexpected token spend. Enable explicitly:
#   export REPORT_MONITOR_RUN_CODEX=true
if [[ "${REPORT_MONITOR_RUN_CODEX:-false}" != "true" ]]; then
  echo "[run_codex] REPORT_MONITOR_RUN_CODEX is not true; skipping Codex."
  exit 0
fi

# Load .env if present to populate API keys and settings
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

ROUND=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --round)
      ROUND="${2:-}"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

if ! command -v codex >/dev/null 2>&1; then
  echo "[run_codex] codex CLI not found; skipping."
  exit 0
fi

# Read stdin (report) and forward to Codex. Keep it simple and deterministic.
# Operators can wrap this script to add richer prompting if desired.
REPORT_INPUT="$(cat)"

PROMPT="Autoppia validator round report"
if [[ -n "$ROUND" ]]; then
  PROMPT="$PROMPT (round $ROUND)"
fi

# Use stdin for the report body to avoid shell escaping issues.
# NOTE: codex CLI reads from stdin when no file is provided.
printf '%s\n\n%s\n' "$PROMPT" "$REPORT_INPUT" | codex --sandbox danger-full-access
