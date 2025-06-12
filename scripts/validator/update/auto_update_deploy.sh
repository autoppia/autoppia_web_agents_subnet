#!/usr/bin/env bash
# auto_update_validator.sh - Periodically check for new version and invoke update_deploy.sh if changed

set -euo pipefail
IFS=$'\n\t'

########################################
# Configuration
########################################

# Version file and variable (relative to repo root)
CONFIG_FILE="autoppia_web_agents_subnet/__init__.py"
VERSION_VARIABLE="__version__"

# Check interval in seconds
SLEEP_INTERVAL=${SLEEP_INTERVAL:-120}  # default: 2 minutes

# Determine Git repository root (run anywhere inside the repo)
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
if [ -z "$REPO_ROOT" ]; then
  echo "Error: not inside a Git repository" >&2
  exit 1
fi

# Path to update script (ensure this script lives in scripts/validator/update/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPDATE_SCRIPT="$SCRIPT_DIR/update_deploy.sh"

########################################
# Helper functions
########################################

# Extract version string from a file or stdin
extract_version() {
  grep "^$VERSION_VARIABLE" "$1" 2>/dev/null \
    | head -n1 \
    | sed -E "s/.*=[[:space:]]*[\"']?([^\"']+)[\"']?.*/\1/"
}

get_local_version() {
  extract_version "$REPO_ROOT/$CONFIG_FILE" || echo ""
}

get_remote_version() {
  git -C "$REPO_ROOT" fetch origin main --quiet || return 1
  git -C "$REPO_ROOT" show origin/main:"$CONFIG_FILE" 2>/dev/null \
    | extract_version /dev/stdin || echo ""
}

# Compare semantic versions: returns 0 if remote > local
version_greater() {
  [ -n "$1" ] && [ -n "$2" ] && \
    [ "$(printf '%s\n' "$1" "$2" | sort -V | head -n1)" = "$1" ] && \
    [ "$1" != "$2" ]
}

########################################
# Initial checks
########################################

# Ensure update script exists and is executable
if [ ! -f "$UPDATE_SCRIPT" ]; then
  echo "Error: update_deploy.sh not found at $UPDATE_SCRIPT" >&2
  exit 1
fi
chmod +x "$UPDATE_SCRIPT" || echo "[WARN] Failed to chmod +x $UPDATE_SCRIPT"

# Warn if version file missing
if [ ! -f "$REPO_ROOT/$CONFIG_FILE" ]; then
  echo "Warning: version file not found: $CONFIG_FILE" >&2
fi

echo "[INFO] Auto-update service started in $REPO_ROOT"
echo "[INFO] Checking every $((SLEEP_INTERVAL/60)) minutes for changes in $CONFIG_FILE"

########################################
# Watch loop
########################################

while true; do
  LOCAL_VERSION=$(get_local_version)
  REMOTE_VERSION=$(get_remote_version)

  echo "[INFO] Current local version: $LOCAL_VERSION, Remote version: $REMOTE_VERSION"

  if version_greater "$LOCAL_VERSION" "$REMOTE_VERSION"; then
    echo "[INFO] New version detected: remote=$REMOTE_VERSION, local=$LOCAL_VERSION. Invoking update_deploy.sh..."
    bash "$UPDATE_SCRIPT"
    echo "[INFO] update_deploy.sh finished successfully"
    # After update, reset local branch to match origin/main
    git -C "$REPO_ROOT" reset --hard origin/main
    echo "[INFO] Git reset to origin/main complete"
  else
    echo "[INFO] No update: local=$LOCAL_VERSION, remote=$REMOTE_VERSION"
  fi

  echo "[INFO] Sleeping for $((SLEEP_INTERVAL/60)) minutes..."
  sleep "$SLEEP_INTERVAL"
done
