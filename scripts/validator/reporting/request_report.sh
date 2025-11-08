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

[[ -f "$REPO_ROOT/.env" ]] && source "$REPO_ROOT/.env"

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
    
    BACKEND="${IWAP_API_BASE_URL:-https://api-dev-leaderboard.autoppia.com}"
    REPORT_FILE="/tmp/report_backend_round_${ROUND}.txt"
    
    # Generate report from backend
    python3 "$SCRIPT_DIR/report_from_backend.py" --round "$ROUND" --backend "$BACKEND" > "$REPORT_FILE" 2>&1
    
    if [[ ! -s "$REPORT_FILE" ]]; then
        echo "❌ Failed to generate report from backend"
        exit 1
    fi
    
    echo "✅ Report generated from backend"
    
    # Send email
    python3 - "$ROUND" "$REPORT_FILE" <<'PYTHON_EMAIL'
import sys, os
from email.message import EmailMessage
import smtplib

round_num, report_file = sys.argv[1], sys.argv[2]

with open(report_file) as f:
    report = f.read()

smtp_host = os.getenv('REPORT_MONITOR_SMTP_HOST')
smtp_port = int(os.getenv('REPORT_MONITOR_SMTP_PORT', '587'))
smtp_user = os.getenv('REPORT_MONITOR_SMTP_USERNAME')
smtp_pass = os.getenv('REPORT_MONITOR_SMTP_PASSWORD')
email_from = os.getenv('REPORT_MONITOR_EMAIL_FROM')
email_to = os.getenv('REPORT_MONITOR_EMAIL_TO')
use_ssl = os.getenv('REPORT_MONITOR_SMTP_SSL', 'false').lower() == 'true'

if not smtp_host or not email_to:
    print("❌ Email not configured in .env")
    sys.exit(1)

msg = EmailMessage()
msg['Subject'] = f'[validator] Round {round_num} - Report from BACKEND'
msg['From'] = email_from
msg['To'] = email_to
msg.set_content(report)

try:
    if use_ssl:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as s:
            if smtp_user and smtp_pass:
                s.login(smtp_user, smtp_pass)
            s.send_message(msg)
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.starttls()
            if smtp_user and smtp_pass:
                s.login(smtp_user, smtp_pass)
            s.send_message(msg)
    print(f"✅ Email sent to {email_to}")
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
PYTHON_EMAIL
    
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

# Add Codex analysis
if [[ -f "$SCRIPT_DIR/run_codex.sh" ]]; then
    echo "🤖 Running Codex analysis..."
    CODEX_OUTPUT=$("$SCRIPT_DIR/run_codex.sh" --round "$ROUND" --status "OK" < "$REPORT_FILE" 2>/dev/null || echo "")
    
    if [[ -n "$CODEX_OUTPUT" ]]; then
        echo "" >> "$REPORT_FILE"
        echo "==================== CODEX ANALYSIS ====================" >> "$REPORT_FILE"
        echo "$CODEX_OUTPUT" >> "$REPORT_FILE"
        echo "========================================================" >> "$REPORT_FILE"
        echo "✅ Codex analysis completed"
    fi
fi

echo "Sending email..."

# Send email
python3 - "$ROUND" "$REPORT_FILE" <<'PYTHON_EMAIL'
import sys, os
from email.message import EmailMessage
import smtplib

round_num, report_file = sys.argv[1], sys.argv[2]

with open(report_file) as f:
    report = f.read()

smtp_host = os.getenv('REPORT_MONITOR_SMTP_HOST')
smtp_port = int(os.getenv('REPORT_MONITOR_SMTP_PORT', '587'))
smtp_user = os.getenv('REPORT_MONITOR_SMTP_USERNAME')
smtp_pass = os.getenv('REPORT_MONITOR_SMTP_PASSWORD')
email_from = os.getenv('REPORT_MONITOR_EMAIL_FROM')
email_to = os.getenv('REPORT_MONITOR_EMAIL_TO')
use_ssl = os.getenv('REPORT_MONITOR_SMTP_SSL', 'false').lower() == 'true'

if not smtp_host or not email_to:
    print("❌ Email not configured in .env")
    sys.exit(1)

msg = EmailMessage()
msg['Subject'] = f'[validator] Round {round_num} - Report from LOGS + Codex'
msg['From'] = email_from
msg['To'] = email_to
msg.set_content(report)

try:
    if use_ssl:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as s:
            if smtp_user and smtp_pass:
                s.login(smtp_user, smtp_pass)
            s.send_message(msg)
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.starttls()
            if smtp_user and smtp_pass:
                s.login(smtp_user, smtp_pass)
            s.send_message(msg)
    print(f"✅ Email sent to {email_to}")
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
PYTHON_EMAIL

rm -f "$REPORT_FILE"
echo "✅ Done!"
