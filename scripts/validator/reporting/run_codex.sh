#!/usr/bin/env bash

# Launch Codex with round context and report data.
# Usage:
#   run_codex.sh --round 598 <<'EOF'
#   ...report output...
#   EOF

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_CANDIDATE="$REPO_ROOT/.env"
CONTEXT_FILE="$REPO_ROOT/Agents.md"

# Load .env if present
if [[ -f "$ENV_CANDIDATE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_CANDIDATE"
  set +a
fi

CONTEXT_CANDIDATES=(
  "$REPO_ROOT/Agents.md"
  "$SCRIPT_DIR/../../Agents.md"
  "$REPO_ROOT/../Agents.md"
  "$SCRIPT_DIR/../../docs/Agents.md"
)

CONTEXT_FILE=""
for candidate in "${CONTEXT_CANDIDATES[@]}"; do
  if [[ -f "$candidate" ]]; then
    CONTEXT_FILE="$candidate"
    break
  fi
done

ROUND_ID=""
STATUS="UNKNOWN"
LLM_SNIPPET=""
REPORT_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --round)
      ROUND_ID="$2"
      shift 2
      ;;
    --status)
      STATUS="$2"
      shift 2
      ;;
    --llm-summary)
      LLM_SNIPPET="$2"
      shift 2
      ;;
    --report-file)
      REPORT_FILE="$2"
      shift 2
      ;;
    *)
      echo "[run_codex] Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$REPORT_FILE" ]]; then
  REPORT_FILE="$(mktemp)"
  trap 'rm -f "$REPORT_FILE"' EXIT
  cat > "$REPORT_FILE"
fi

if [[ ! -s "$REPORT_FILE" ]]; then
  echo "[run_codex] Report content is empty; aborting." >&2
  exit 1
fi

PROMPT_FILE="$(mktemp)"
trap 'rm -f "$PROMPT_FILE"' EXIT

cat > "$PROMPT_FILE" <<EOF
You are Autoppia's validator Codex auditor.
- Round: ${ROUND_ID:-unknown}
- Status label from monitoring: ${STATUS}

Primary tasks:
1. Inspect the round report attached below (a recent log tail may follow it). If needed, rerun it with:
   scripts/validator/reporting/report.sh --pm2 validator --round ${ROUND_ID:-<fill-in>}
2. Highlight consensus or evaluation failures. If urgent, call:
   python scripts/validator/utils/alert_admins.py "Validator Round ${ROUND_ID:-?} Alert" "<reason>"
3. Keep notes concise and reference relevant log lines or sections in this transcript.

Respond using this exact structure (keep it short—bullets max 5):
- Overall Status: <OK|WARN|FAIL> — one-sentence justification.
- Highlights:
  - key finding with file:line reference (if none, write "None").
- Actions:
  - remediation or follow-up (if none, write "None").

Round report:
EOF

cat "$REPORT_FILE" >> "$PROMPT_FILE"

if [[ -n "$LLM_SNIPPET" ]]; then
  {
    echo ""
    echo "Monitoring LLM summary:"
    echo "$LLM_SNIPPET"
  } >> "$PROMPT_FILE"
fi

if [[ -f "$ENV_CANDIDATE" ]]; then
  {
    echo ""
    echo "Environment (.env) variables:"
    sed 's/^/  /' "$ENV_CANDIDATE"
  } >> "$PROMPT_FILE"
fi

if [[ -n "$CONTEXT_FILE" ]]; then
  if codex --help 2>/dev/null | grep -q -- "--context-file"; then
    CONTEXT_ARGS=(--context-file "$CONTEXT_FILE")
  else
    {
      echo ""
      echo "Reference context from ${CONTEXT_FILE}:"
      sed 's/^/  /' "$CONTEXT_FILE"
    } >> "$PROMPT_FILE"
    CONTEXT_ARGS=()
  fi
else
  CONTEXT_ARGS=()
fi

PROMPT_CONTENT="$(cat "$PROMPT_FILE")"

if ! command -v codex >/dev/null 2>&1; then
  echo "[run_codex] codex CLI not found in PATH." >&2
  exit 1
fi

CODEX_COMMAND=(codex exec --sandbox danger-full-access)
if ((${#CONTEXT_ARGS[@]})); then
  CODEX_COMMAND+=( "${CONTEXT_ARGS[@]}" )
fi
CODEX_COMMAND+=(-)

"${CODEX_COMMAND[@]}" <<<"$PROMPT_CONTENT"
