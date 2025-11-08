#!/usr/bin/env bash
#
# setup_logs.sh - Setup permanent logging with per-round organization
#
# Creates:
#   logs/validator_all.log         → ALL logs
#   logs/rounds/round_72.log        → Round 72 only
#   logs/rounds/round_73.log        → Round 73 only
#

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../" && pwd)"
LOGS_DIR="$REPO_ROOT/logs"
ROUNDS_DIR="$LOGS_DIR/rounds"

echo "=== Setting up validator logs ==="
echo ""

# Create directories
mkdir -p "$LOGS_DIR"
mkdir -p "$ROUNDS_DIR"

echo "✅ Log directories created:"
echo "   $LOGS_DIR"
echo "   $ROUNDS_DIR"
echo ""

# Create log splitter script
SPLITTER_SCRIPT="$REPO_ROOT/scripts/validator/utils/split_logs_by_round.py"
cat > "$SPLITTER_SCRIPT" <<'PYTHON_SPLITTER'
#!/usr/bin/env python3
"""Split validator logs by round."""

import re
import sys
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parents[3]
LOGS_DIR = REPO_ROOT / "logs"
ROUNDS_DIR = LOGS_DIR / "rounds"
ALL_LOG = LOGS_DIR / "validator_all.log"

ROUNDS_DIR.mkdir(parents=True, exist_ok=True)

current_round = None
current_round_file = None

ROUND_START_PATTERN = re.compile(r'🚦 Starting Round:\s*(\d+)')

def process_line(line: str):
    global current_round, current_round_file
    
    # Write to all.log
    with open(ALL_LOG, 'a') as f:
        f.write(line)
    
    # Check if new round starts
    match = ROUND_START_PATTERN.search(line)
    if match:
        new_round = int(match.group(1))
        
        if current_round_file:
            current_round_file.close()
        
        current_round = new_round
        round_log = ROUNDS_DIR / f"round_{current_round}.log"
        current_round_file = open(round_log, 'a')
        print(f"[{datetime.now()}] Started logging round {current_round}", file=sys.stderr)
    
    # Write to current round file
    if current_round_file:
        current_round_file.write(line)
        current_round_file.flush()

def main():
    print(f"[{datetime.now()}] Log splitter started", file=sys.stderr)
    print(f"[{datetime.now()}] All logs: {ALL_LOG}", file=sys.stderr)
    print(f"[{datetime.now()}] Round logs: {ROUNDS_DIR}/", file=sys.stderr)
    
    for line in sys.stdin:
        try:
            process_line(line)
        except Exception as e:
            print(f"[{datetime.now()}] Error: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
PYTHON_SPLITTER

chmod +x "$SPLITTER_SCRIPT"

echo "✅ Log splitter script created"
echo ""

# Start log splitter with PM2
pm2 delete report-log-splitter 2>/dev/null || true

pm2 start bash --name "report-log-splitter" -- -c \
    "pm2 logs validator-wta --nostream --raw --lines 0 | python3 $SPLITTER_SCRIPT"

pm2 save

echo "✅ Log splitter started"
echo ""
echo "=== Setup complete ==="
echo ""
echo "Logs are organized as:"
echo "  📁 $LOGS_DIR/validator_all.log"
echo "     → ALL validator logs"
echo ""
echo "  📁 $ROUNDS_DIR/round_72.log"
echo "  📁 $ROUNDS_DIR/round_73.log"
echo "     → Per-round logs"
echo ""
echo "To verify:"
echo "  pm2 logs report-log-splitter"
echo "  ls -lh $ROUNDS_DIR/"
echo ""
