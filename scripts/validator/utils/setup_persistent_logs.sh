#!/usr/bin/env bash
#
# setup_persistent_logs.sh - Configure PM2 log rotation for persistent validator logs
#
# This script configures PM2 to keep historical logs with proper rotation,
# ensuring that old rounds can be queried even after validator restarts.
#

set -euo pipefail

echo "=== Setting up persistent logs for validator ==="
echo ""

# Check if pm2 is installed
if ! command -v pm2 >/dev/null 2>&1; then
    echo "Error: pm2 not found. Please install pm2 first." >&2
    exit 1
fi

# Install pm2-logrotate if not already installed
if ! pm2 ls | grep -q "pm2-logrotate" 2>/dev/null; then
    echo "Installing pm2-logrotate module..."
    pm2 install pm2-logrotate
    echo "✅ pm2-logrotate installed"
else
    echo "✅ pm2-logrotate already installed"
fi

echo ""
echo "Configuring log rotation settings..."

# Configure pm2-logrotate
# - max_size: Maximum size of log file before rotation (500MB)
# - retain: Number of rotated log files to keep (30 files)
# - compress: Compress rotated logs (true)
# - dateFormat: Date format for rotated files
# - rotateModule: Also rotate pm2 module logs (true)

pm2 set pm2-logrotate:max_size 500M
pm2 set pm2-logrotate:retain 30
pm2 set pm2-logrotate:compress true
pm2 set pm2-logrotate:dateFormat YYYY-MM-DD_HH-mm-ss
pm2 set pm2-logrotate:rotateModule true
pm2 set pm2-logrotate:workerInterval 30
pm2 set pm2-logrotate:rotateInterval '0 0 * * *'

echo "✅ Log rotation configured"
echo ""
echo "Current pm2-logrotate settings:"
pm2 conf pm2-logrotate

echo ""
echo "=== Configuration complete ==="
echo ""
echo "Your validator logs will now:"
echo "  • Rotate when they reach 500MB"
echo "  • Keep the last 30 rotated files"
echo "  • Compress old logs automatically"
echo "  • Be available for historical round queries"
echo ""
echo "Log files location: ~/.pm2/logs/"
echo "  - validator-wta-out.log (current)"
echo "  - validator-wta-out__YYYY-MM-DD_HH-mm-ss.log.gz (rotated)"
echo ""
echo "To query old rounds, use:"
echo "  ./report.sh --pm2 validator-wta --round N --lines 500000"
echo ""

