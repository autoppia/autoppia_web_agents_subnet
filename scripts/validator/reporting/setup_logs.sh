#!/usr/bin/env bash
#
# setup_logs.sh - Configure permanent logging with per-round organization
#
# This creates:
#   logs/validator_all.log         → ALL logs (never lost)
#   logs/rounds/round_72.log        → Logs for round 72
#   logs/rounds/round_73.log        → Logs for round 73
#   etc.
#

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../" && pwd)"
LOGS_DIR="$REPO_ROOT/logs"
ROUNDS_DIR="$LOGS_DIR/rounds"

echo "=== Setting up permanent validator logs ==="
echo ""

# Create directories
mkdir -p "$LOGS_DIR"
mkdir -p "$ROUNDS_DIR"

echo "✅ Log directories created:"
echo "   $LOGS_DIR"
echo "   $ROUNDS_DIR"

# Install pm2-logrotate
if ! pm2 describe pm2-logrotate >/dev/null 2>&1; then
    echo ""
    echo "Installing pm2-logrotate..."
    pm2 install pm2-logrotate
fi

# Configure pm2-logrotate
pm2 set pm2-logrotate:max_size 1000M
pm2 set pm2-logrotate:retain 100
pm2 set pm2-logrotate:compress true

echo "✅ pm2-logrotate configured (100 files x 1GB = 100GB history)"

# Create log splitter script
SPLITTER_SCRIPT="$REPO_ROOT/scripts/validator/utils/split_logs_by_round.py"
cat > "$SPLITTER_SCRIPT" <<'PYTHON_SPLITTER'
#!/usr/bin/env python3
"""
Split validator logs by round.
Reads from PM2 logs and writes to:
  - logs/validator_all.log (everything)
  - logs/rounds/round_X.log (per round)
"""

import re
import sys
import time
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parents[3]
LOGS_DIR = REPO_ROOT / "logs"
ROUNDS_DIR = LOGS_DIR / "rounds"
ALL_LOG = LOGS_DIR / "validator_all.log"

# Ensure directories exist
ROUNDS_DIR.mkdir(parents=True, exist_ok=True)

# Track current round
current_round = None
current_round_file = None

# Patterns
ROUND_START_PATTERN = re.compile(r'Starting Round:\s*(\d+)')

def process_line(line: str):
    global current_round, current_round_file
    
    # Always write to all.log
    with open(ALL_LOG, 'a') as f:
        f.write(line)
    
    # Check if new round starts
    match = ROUND_START_PATTERN.search(line)
    if match:
        new_round = int(match.group(1))
        
        # Close previous round file
        if current_round_file:
            current_round_file.close()
        
        # Open new round file
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
    
    # Read from stdin (PM2 logs)
    for line in sys.stdin:
        try:
            process_line(line)
        except Exception as e:
            print(f"[{datetime.now()}] Error: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
PYTHON_SPLITTER

chmod +x "$SPLITTER_SCRIPT"

# Start log splitter with PM2
pm2 delete validator-log-splitter 2>/dev/null || true

pm2 start bash --name "validator-log-splitter" -- -c \
    "pm2 logs validator-wta --nostream --raw --lines 0 | python3 $SPLITTER_SCRIPT"

pm2 save

echo ""
echo "✅ Log splitter started"
echo ""
echo "=== Configuration complete ==="
echo ""
echo "Logs are now organized:"
echo "  📁 $LOGS_DIR/validator_all.log"
echo "     → ALL logs (never lost)"
echo ""
echo "  📁 $ROUNDS_DIR/round_72.log"
echo "  📁 $ROUNDS_DIR/round_73.log"
echo "     → Per-round logs (easy to find!)"
echo ""
echo "To view logs:"
echo "  tail -f $LOGS_DIR/validator_all.log"
echo "  tail -f $ROUNDS_DIR/round_72.log"
echo ""

