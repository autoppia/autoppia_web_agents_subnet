#!/usr/bin/env bash
# auto_update_deploy.sh - Periodically check for new version and invoke update_deploy.sh if changed

set -euo pipefail
IFS=$'\n\t'

########################################
# Configuration (edit these defaults directly to customize)
########################################
# Set your validator process name, wallet coldkey and hotkey below:
PROCESS_NAME="subnet-36-validator"      # change this to your pm2 process name
WALLET_NAME="my_wallet"                 # change to your coldkey name
WALLET_HOTKEY="my_hotkey"               # change to your hotkey
SUBTENSOR_PARAM="--subtensor.network finney"  # change subtensor network param

########################################
# Interval (seconds)
########################################
# Adjust how often the script checks for a new version
SLEEP_INTERVAL=600

########################################
# Paths
########################################
# Determine repo root
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
if [ -z "$REPO_ROOT" ]; then
  echo "Error: not inside a Git repository" >&2
  exit 1
fi
# Path to update script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPDATE_SCRIPT="$SCRIPT_DIR/update_deploy.sh"

########################################
# Helpers: version extraction & comparison
########################################
extract_version() {
  # Extract __version__ value from file
  grep "^__version__" "$1" 2>/dev/null | \
    head -n1 | \
    sed -E "s/.*=[[:space:]]*[\"']?([^\"']+)[\"']?.*/\1/"
}

get_local_version() {
  extract_version "$REPO_ROOT/autoppia_web_agents_subnet/__init__.py" || echo ""
}

get_remote_version() {
  git -C "$REPO_ROOT" fetch origin main --quiet || return 1
  git -C "$REPO_ROOT" show origin/main:"autoppia_web_agents_subnet/__init__.py" 2>/dev/null | \
    extract_version /dev/stdin || echo ""
}

version_greater() {
  [ -z "$1" ] && return 1
  [ -z "$2" ] && return 1
  [ "$(printf '%s\n' "$1" "$2" | sort -V | head -n1)" = "$1" ] && \
    [ "$1" != "$2" ]
}

########################################
# Sanity checks
########################################
[ -f "$UPDATE_SCRIPT" ] || { echo "Error: update_deploy.sh not found at $UPDATE_SCRIPT" >&2; exit 1; }
chmod +x "$UPDATE_SCRIPT" || echo "[WARN] Could not chmod +x $UPDATE_SCRIPT"

echo "[INFO] Auto-update service starting in $REPO_ROOT"
echo "[INFO] Using parameters: process=$PROCESS_NAME, wallet=$WALLET_NAME, hotkey=$WALLET_HOTKEY, subtensor='$SUBTENSOR_PARAM'"
echo "[INFO] Checking every $((SLEEP_INTERVAL/60)) minutes for new release"

########################################
# Watch loop
########################################
while true; do
  LOCAL_VERSION=$(get_local_version)
  REMOTE_VERSION=$(get_remote_version)
  echo "[INFO] Local: $LOCAL_VERSION, Remote: $REMOTE_VERSION"
  if version_greater "$LOCAL_VERSION" "$REMOTE_VERSION"; then
    echo "[INFO] New version! Invoking update_deploy.sh with trace..."
    bash -x "$UPDATE_SCRIPT" "$PROCESS_NAME" "$WALLET_NAME" "$WALLET_HOTKEY" "$SUBTENSOR_PARAM"
    echo "[INFO] update_deploy.sh completed"
    git -C "$REPO_ROOT" reset --hard origin/main && echo "[INFO] Reset to origin/main"
  else
    echo "[INFO] No update needed"
  fi
  echo "[INFO] Sleeping $((SLEEP_INTERVAL/60)) min..."
  sleep "$SLEEP_INTERVAL"
done
