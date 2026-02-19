#!/usr/bin/env bash
# auto_update_deploy.sh - Periodically check for updates and run scoped update scripts.

set -euo pipefail
IFS=$'\n\t'

########################################
# Configuration
########################################
PROCESS_NAME="${PROCESS_NAME:-subnet-36-validator}"             # Validator PM2 process name
WALLET_NAME="${WALLET_NAME:-}"                                  # Needed only if PM2 process must be created
WALLET_HOTKEY="${WALLET_HOTKEY:-}"                              # Needed only if PM2 process must be created
SUBTENSOR_PARAM="${SUBTENSOR_PARAM:---subtensor.network finney}" # Subtensor network
IWA_PATH="${IWA_PATH:-../autoppia_iwa}"                         # Relative to subnet repo
WEBS_DEMO_PATH="${WEBS_DEMO_PATH:-../autoppia_webs_demo}"       # Relative to subnet repo

########################################
# Interval (seconds)
########################################
# Adjust how often the script checks for new versions
SLEEP_INTERVAL="${SLEEP_INTERVAL:-600}"

########################################
# Paths
########################################
# Determine repo root
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
if [ -z "$REPO_ROOT" ]; then
  echo "Error: not inside a Git repository" >&2
  exit 1
fi
if [[ "$IWA_PATH" != /* ]]; then
  IWA_PATH="$REPO_ROOT/$IWA_PATH"
fi
if [[ "$WEBS_DEMO_PATH" != /* ]]; then
  WEBS_DEMO_PATH="$REPO_ROOT/$WEBS_DEMO_PATH"
fi
# Paths to update scripts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPDATE_SUBNET_IWA_SCRIPT="$SCRIPT_DIR/update_iwa_and_subnet.sh"
UPDATE_WEBS_DEMO_SCRIPT="$SCRIPT_DIR/update_webs_demo.sh"

########################################
# Helpers: version extraction and comparison
########################################
VERSION_GATES_FILE="autoppia_web_agents_subnet/__init__.py"

extract_named_version() {
  local key="$1"
  local file="$2"
  grep "^${key}[[:space:]]*=" "$file" 2>/dev/null | \
    head -n1 | \
    sed -E "s/^${key}[[:space:]]*=[[:space:]]*[\"']?([^\"']+)[\"']?.*/\1/"
}

get_local_subnet_iwa_version() {
  extract_named_version "SUBNET_IWA_VERSION" "$REPO_ROOT/$VERSION_GATES_FILE" || echo ""
}

get_remote_subnet_iwa_version() {
  git -C "$REPO_ROOT" fetch origin main --quiet || return 1
  git -C "$REPO_ROOT" show origin/main:"$VERSION_GATES_FILE" 2>/dev/null | \
    extract_named_version "SUBNET_IWA_VERSION" /dev/stdin || echo ""
}

get_local_webs_demo_version() {
  extract_named_version "WEBS_DEMO_VERSION" "$REPO_ROOT/$VERSION_GATES_FILE" || echo ""
}

get_remote_webs_demo_version() {
  git -C "$REPO_ROOT" fetch origin main --quiet || return 1
  git -C "$REPO_ROOT" show origin/main:"$VERSION_GATES_FILE" 2>/dev/null | \
    extract_named_version "WEBS_DEMO_VERSION" /dev/stdin || echo ""
}

is_remote_newer() {
  # Returns true when local_version < remote_version
  [ -z "$1" ] && return 1
  [ -z "$2" ] && return 1
  [ "$(printf '%s\n' "$1" "$2" | sort -V | head -n1)" = "$1" ] && \
    [ "$1" != "$2" ]
}

########################################
# Sanity checks
########################################
[ -f "$UPDATE_SUBNET_IWA_SCRIPT" ] || {
  echo "Error: update_iwa_and_subnet.sh not found at $UPDATE_SUBNET_IWA_SCRIPT" >&2
  exit 1
}
[ -f "$UPDATE_WEBS_DEMO_SCRIPT" ] || {
  echo "Error: update_webs_demo.sh not found at $UPDATE_WEBS_DEMO_SCRIPT" >&2
  exit 1
}

chmod +x "$UPDATE_SUBNET_IWA_SCRIPT" || echo "[WARN] Could not chmod +x $UPDATE_SUBNET_IWA_SCRIPT"
chmod +x "$UPDATE_WEBS_DEMO_SCRIPT" || echo "[WARN] Could not chmod +x $UPDATE_WEBS_DEMO_SCRIPT"
[ -f "$REPO_ROOT/$VERSION_GATES_FILE" ] || {
  echo "Error: version gates file not found at $REPO_ROOT/$VERSION_GATES_FILE" >&2
  exit 1
}

echo "[INFO] Auto-update service starting in $REPO_ROOT"
if [ -z "$WALLET_NAME" ] || [ -z "$WALLET_HOTKEY" ]; then
  echo "[WARN] WALLET_NAME/WALLET_HOTKEY are empty. This is okay if PM2 process already exists."
fi
echo "[INFO] Using parameters: process=$PROCESS_NAME, wallet=$WALLET_NAME, hotkey=$WALLET_HOTKEY, subtensor='$SUBTENSOR_PARAM'"
echo "[INFO] Paths: iwa=$IWA_PATH webs_demo=$WEBS_DEMO_PATH"
echo "[INFO] Checking every $((SLEEP_INTERVAL/60)) minutes for new release"

########################################
# Watch loop
########################################
while true; do
  SUBNET_LOCAL_VERSION=$(get_local_subnet_iwa_version)
  SUBNET_REMOTE_VERSION=$(get_remote_subnet_iwa_version)
  echo "[INFO] SUBNET_IWA_VERSION local=$SUBNET_LOCAL_VERSION remote=$SUBNET_REMOTE_VERSION"

  if is_remote_newer "$SUBNET_LOCAL_VERSION" "$SUBNET_REMOTE_VERSION"; then
    echo "[INFO] SUBNET_IWA_VERSION bump detected -> updating subnet + IWA"
    IWA_PATH="$IWA_PATH" bash -x "$UPDATE_SUBNET_IWA_SCRIPT" \
      "$PROCESS_NAME" "$WALLET_NAME" "$WALLET_HOTKEY" "$SUBTENSOR_PARAM"
    echo "[INFO] Subnet + IWA update completed"
  else
    echo "[INFO] Subnet + IWA: no update needed"
  fi

  WEBS_DEMO_LOCAL_VERSION=$(get_local_webs_demo_version)
  WEBS_DEMO_REMOTE_VERSION=$(get_remote_webs_demo_version)
  if [ -n "${WEBS_DEMO_LOCAL_VERSION:-}" ] || [ -n "${WEBS_DEMO_REMOTE_VERSION:-}" ]; then
    echo "[INFO] WEBS_DEMO_VERSION local=$WEBS_DEMO_LOCAL_VERSION remote=$WEBS_DEMO_REMOTE_VERSION"
  else
    echo "[WARN] WEBS_DEMO_VERSION not available in $VERSION_GATES_FILE"
  fi

  if is_remote_newer "$WEBS_DEMO_LOCAL_VERSION" "$WEBS_DEMO_REMOTE_VERSION"; then
    echo "[INFO] WEBS_DEMO_VERSION bump detected -> updating webs_demo"
    WEBS_DEMO_PATH="$WEBS_DEMO_PATH" bash -x "$UPDATE_WEBS_DEMO_SCRIPT"
    echo "[INFO] webs_demo update completed"
  else
    echo "[INFO] WebsDemo: no update needed"
  fi

  echo "[INFO] Sleeping $((SLEEP_INTERVAL/60)) min..."
  sleep "$SLEEP_INTERVAL"
done
