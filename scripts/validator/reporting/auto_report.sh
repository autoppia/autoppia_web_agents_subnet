#!/usr/bin/env bash
#
# auto_report.sh - Automatic round reporting with Codex analysis
#
# Detects when rounds complete and sends email reports automatically
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LOGS_DIR="$REPO_ROOT/logs"
ROUNDS_DIR="$LOGS_DIR/rounds"
STATE_FILE="$LOGS_DIR/last_reported_round.txt"

# Load .env
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    source "$REPO_ROOT/.env"
    set +a
fi

echo "[$(date)] 🚀 Auto-reporter started"
echo "[$(date)] 📁 Watching: $ROUNDS_DIR"

# Create state file
touch "$STATE_FILE"
LAST_REPORTED=$(cat "$STATE_FILE" 2>/dev/null || echo "0")

echo "[$(date)] 📊 Last reported round: $LAST_REPORTED"

send_report() {
    local round=$1
    local round_log="$ROUNDS_DIR/round_${round}.log"
    
    if [[ ! -f "$round_log" ]]; then
        echo "[$(date)] ⚠️  Round log not found: $round_log"
        return 1
    fi
    
    echo "[$(date)] 📧 Generating report for round $round..."
    
    # Generate report
    local report_file="/tmp/report_round_${round}.txt"
    "$SCRIPT_DIR/report.sh" --path "$round_log" --round "$round" --lines 999999999 > "$report_file" 2>&1
    
    if [[ ! -s "$report_file" ]]; then
        echo "[$(date)] ❌ Failed to generate report"
        return 1
    fi
    
    # Add Codex analysis (with timeout)
    if [[ -f "$SCRIPT_DIR/run_codex.sh" ]]; then
        echo "[$(date)] 🤖 Running Codex analysis (30s timeout)..."
        local codex_output=$(timeout 30 "$SCRIPT_DIR/run_codex.sh" --round "$round" --status "OK" < "$report_file" 2>/dev/null || echo "")
        
        if [[ -n "$codex_output" ]]; then
            echo "" >> "$report_file"
            echo "==================== CODEX ANALYSIS ====================" >> "$report_file"
            echo "$codex_output" >> "$report_file"
            echo "========================================================" >> "$report_file"
            echo "[$(date)] ✅ Codex analysis completed"
        else
            echo "[$(date)] ⚠️  Codex analysis skipped (timeout or not available)"
        fi
    fi
    
    # Send email
    python3 - "$round" "$report_file" <<'PYTHON_EMAIL'
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
    print(f"❌ Email not configured")
    sys.exit(1)

msg = EmailMessage()
msg['Subject'] = f'[validator] Round {round_num} - Complete Report + Codex Analysis'
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
    
    if [[ $? -eq 0 ]]; then
        echo "[$(date)] ✅ Report sent successfully"
        echo "$round" > "$STATE_FILE"
        rm -f "$report_file"
        return 0
    else
        echo "[$(date)] ❌ Failed to send email"
        return 1
    fi
}

# Main loop
echo "[$(date)] 🔄 Starting monitoring loop..."
while true; do
    # Find all round log files
    for round_log in "$ROUNDS_DIR"/round_*.log; do
        [[ ! -f "$round_log" ]] && continue
        
        # Extract round number
        round=$(basename "$round_log" | grep -oP 'round_\K\d+')
        [[ -z "$round" ]] && continue
        
        # Skip if already reported
        [[ "$round" -le "$LAST_REPORTED" ]] && continue
        
        # Check if round is complete (next round started or "Round completed" found)
        next_round=$((round + 1))
        next_log="$ROUNDS_DIR/round_${next_round}.log"
        
        if [[ -f "$next_log" ]] || grep -q "✅ Round completed" "$round_log" 2>/dev/null || grep -q "Phase → complete" "$round_log" 2>/dev/null; then
            echo "[$(date)] 🎯 Round $round completed, sending report..."
            sleep 10  # Small delay to ensure all data is written
            
            if send_report "$round"; then
                LAST_REPORTED="$round"
            fi
        fi
    done
    
    sleep 20
done

