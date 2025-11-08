#!/usr/bin/env bash
#
# request_report.sh - Request report for any round
#
# Usage:
#   ./request_report.sh 72              # From LOGS
#   ./request_report.sh 72 backend      # From BACKEND
#   ./request_report.sh current         # Current round from LOGS
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LOGS_DIR="$REPO_ROOT/logs"
ROUNDS_DIR="$LOGS_DIR/rounds"

if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    source "$REPO_ROOT/.env"
    set +a
fi

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <round_number|current> [backend]"
    echo ""
    echo "Examples:"
    echo "  $0 72              # From LOGS"
    echo "  $0 72 backend      # From BACKEND"
    echo "  $0 current         # Current round from LOGS"
    exit 1
fi

ROUND=$1
SOURCE=${2:-logs}

# Handle "current" keyword
if [[ "$ROUND" == "current" ]]; then
    LATEST_LOG=$(ls -1 "$ROUNDS_DIR"/round_*.log 2>/dev/null | sort -V | tail -1)
    if [[ -z "$LATEST_LOG" ]]; then
        echo "❌ No round logs found"
        exit 1
    fi
    ROUND=$(basename "$LATEST_LOG" | grep -oP 'round_\K\d+')
    echo "Current round detected: $ROUND"
fi

# ============================================================
# OPTION 1: FROM BACKEND
# ============================================================
if [[ "$SOURCE" == "backend" ]]; then
    echo "📊 Requesting round $ROUND from BACKEND..."
    
    BACKEND="${IWAP_API_BASE_URL:-https://dev-api-leaderboard.autoppia.com}"
    echo "🌐 Backend URL: $BACKEND"
    
    REPORT_FILE="/tmp/report_backend_round_${ROUND}.txt"
    
    # Generate report from backend
    echo "⏳ Fetching data from backend..."
    python3 "$SCRIPT_DIR/report_from_backend.py" --round "$ROUND" --backend "$BACKEND" > "$REPORT_FILE" 2>&1
    
    if [[ ! -s "$REPORT_FILE" ]]; then
        echo "❌ Failed to generate report from backend"
        cat "$REPORT_FILE"
        exit 1
    fi
    
    echo "✅ Report generated from backend"
    echo "📧 Sending HTML email..."
    
    # Send HTML email using monitor_rounds.py functions
    python3 "$SCRIPT_DIR/send_html_email.py" "$ROUND" "$REPORT_FILE"
    
    rm -f "$REPORT_FILE"
    echo "✅ Done!"
    exit 0
fi

# ============================================================
# OPTION 2: FROM LOGS (with Codex analysis)
# ============================================================
echo "📊 Requesting round $ROUND from LOGS..."

ROUND_LOG="$ROUNDS_DIR/round_${ROUND}.log"
if [[ ! -f "$ROUND_LOG" ]]; then
    echo "❌ Round log not found: $ROUND_LOG"
    echo "   Try: $0 $ROUND backend"
    exit 1
fi

REPORT_FILE="/tmp/report_logs_round_${ROUND}.txt"

# Generate report from logs
"$SCRIPT_DIR/report.sh" --path "$ROUND_LOG" --round "$ROUND" --lines 999999999 > "$REPORT_FILE" 2>&1

if [[ ! -s "$REPORT_FILE" ]]; then
    echo "❌ Failed to generate report from logs"
    exit 1
fi

echo "✅ Report generated from logs"

# Add Codex analysis (with timeout)
if [[ -f "$SCRIPT_DIR/run_codex.sh" ]]; then
    echo "🤖 Running Codex analysis (30s timeout)..."
    CODEX_OUTPUT=$(timeout 30 "$SCRIPT_DIR/run_codex.sh" --round "$ROUND" --status "OK" < "$REPORT_FILE" 2>/dev/null || echo "")
    
    if [[ -n "$CODEX_OUTPUT" ]]; then
        echo "" >> "$REPORT_FILE"
        echo "==================== CODEX ANALYSIS ====================" >> "$REPORT_FILE"
        echo "$CODEX_OUTPUT" >> "$REPORT_FILE"
        echo "========================================================" >> "$REPORT_FILE"
        echo "✅ Codex analysis completed"
    else
        echo "⚠️  Codex analysis skipped (timeout or not available)"
    fi
fi

echo "📧 Sending HTML email..."

# Send HTML email using monitor_rounds.py functions
python3 "$SCRIPT_DIR/send_html_email.py" "$ROUND" "$REPORT_FILE"

rm -f "$REPORT_FILE"
echo "✅ Done!"
