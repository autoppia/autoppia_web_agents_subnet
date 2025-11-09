#!/usr/bin/env bash
#
# Setup round-specific log splitting for validator
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LOG_SPLITTER="$REPO_ROOT/scripts/validator/utils/simple_log_splitter.py"

echo "═══════════════════════════════════════"
echo "  Validator Round Logs Setup"
echo "═══════════════════════════════════════"
echo ""

# Check if log splitter exists
if [ ! -f "$LOG_SPLITTER" ]; then
    echo "❌ Error: Log splitter not found at $LOG_SPLITTER"
    exit 1
fi

echo "✅ Log splitter found"

# Make it executable
chmod +x "$LOG_SPLITTER"
echo "✅ Made executable"

# Create logs directory
mkdir -p "$REPO_ROOT/data/logs/rounds"
echo "✅ Created logs directory"

# Stop old log splitter if running
echo ""
echo "Stopping old log splitter..."
pm2 delete report-log-splitter 2>/dev/null || echo "  (no old splitter running)"

# Start new log splitter
echo ""
echo "Starting new log splitter..."

# Use proper PM2 command that won't crash
pm2 start "$LOG_SPLITTER" \
    --name "report-log-splitter" \
    --interpreter python3 \
    --log-date-format "YYYY-MM-DD HH:mm:ss" \
    --restart-delay 5000 \
    --max-restarts 10

pm2 save

echo ""
echo "✅ Log splitter started!"
echo ""
echo "═══════════════════════════════════════"
echo "  Setup Complete!"
echo "═══════════════════════════════════════"
echo ""
echo "📁 Round logs will be saved to:"
echo "   $REPO_ROOT/data/logs/rounds/round_N.log"
echo ""
echo "🔍 To verify:"
echo "   pm2 logs report-log-splitter"
echo "   ls -lh $REPO_ROOT/data/logs/rounds/"
echo ""
echo "⚠️  IMPORTANT: You need to pipe validator logs to the splitter:"
echo ""
echo "   Option 1 (Recommended): Run validator with output redirection"
echo "   python3 neurons/validator.py --netuid 36 2>&1 | python3 $LOG_SPLITTER"
echo ""
echo "   Option 2: Use PM2 ecosystem file with log piping"
echo ""

