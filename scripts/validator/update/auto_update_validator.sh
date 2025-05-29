#!/bin/bash
# auto_update_validator.sh - Check for updates only. If a new version is available, runs update.sh.
# Run this script in the background (via PM2 or another process manager)
# so it checks periodically for new versions.

PROCESS_NAME="subnet-36-validator"
WALLET_NAME="your_coldkey"
WALLET_HOTKEY="your_hotkey"

# Parse command line arguments
if [ $# -ge 1 ]; then
    PROCESS_NAME="$1"
fi
if [ $# -ge 2 ]; then
    WALLET_NAME="$2"
fi
if [ $# -ge 3 ]; then
    WALLET_HOTKEY="$3"
fi

CONFIG_FILE="autoppia_web_agents_subnet/__init__.py"
VERSION_VARIABLE="__version__"
SLEEP_INTERVAL=120  # 2 minutes in seconds

# Get script directory and repo root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
UPDATE_SCRIPT="$SCRIPT_DIR/update.sh"

echo "Starting auto-update service for process: $PROCESS_NAME"
echo "Repo root: $REPO_ROOT"
echo "Update script: $UPDATE_SCRIPT"
echo "Config file: $CONFIG_FILE"
echo "Check interval: $(($SLEEP_INTERVAL/60)) minutes"

get_local_version() {
    if [ -f "$CONFIG_FILE" ]; then
        grep "$VERSION_VARIABLE" "$CONFIG_FILE" 2>/dev/null \
            | head -n1 \
            | sed -E 's/.*=[[:space:]]*["'\''"]?([^"'\'' ]+)["'\''"]?.*/\1/'
    else
        echo ""
    fi
}

get_remote_version() {
    cd "$REPO_ROOT" || return 1
    
    # Fetch latest changes (with error handling)
    if ! git fetch origin 2>/dev/null; then
        echo "Warning: Failed to fetch from origin" >&2
        return 1
    fi
    
    # Get version from remote main branch
    git show origin/main:"$CONFIG_FILE" 2>/dev/null \
        | grep "$VERSION_VARIABLE" \
        | head -n1 \
        | sed -E 's/.*=[[:space:]]*["'\''"]?([^"'\'' ]+)["'\''"]?.*/\1/'
}

# Returns 0 (true) if v2 > v1, else 1 (false).
version_greater() {
    if [ -z "$1" ] || [ -z "$2" ]; then
        return 1
    fi
    [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" != "$1" ]
}

check_prerequisites() {
    # Check if we're in the right directory
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "Error: Config file not found: $CONFIG_FILE" >&2
        echo "Make sure you're running from the repository root" >&2
        exit 1
    fi
    
    # Check if update script exists
    if [ ! -f "$UPDATE_SCRIPT" ]; then
        echo "Error: Update script not found: $UPDATE_SCRIPT" >&2
        exit 1
    fi
    
    # Check if git repository
    if ! git rev-parse --git-dir >/dev/null 2>&1; then
        echo "Error: Not a git repository" >&2
        exit 1
    fi
}

run_update() {
    echo "New version detected: $REMOTE_VERSION (local: $LOCAL_VERSION)"
    echo "Invoking update.sh..."
    
    cd "$REPO_ROOT" || {
        echo "Error: Failed to navigate to repo root" >&2
        return 1
    }
    
    if bash "$UPDATE_SCRIPT" "$PROCESS_NAME" "$WALLET_NAME" "$WALLET_HOTKEY"; then
        echo "Update completed successfully"
        return 0
    else
        echo "Update failed with exit code $?" >&2
        return 1
    fi
}

# Initial checks
check_prerequisites

echo "Auto-update service started successfully"
echo "Monitoring for version changes..."

while true; do
    # Ensure we're in the right directory
    cd "$REPO_ROOT" || {
        echo "Error: Failed to navigate to repo root" >&2
        sleep $SLEEP_INTERVAL
        continue
    }
    
    LOCAL_VERSION=$(get_local_version)
    REMOTE_VERSION=$(get_remote_version)
    
    if [ -z "$LOCAL_VERSION" ]; then
        echo "Warning: Unable to retrieve local version"
    elif [ -z "$REMOTE_VERSION" ]; then
        echo "Warning: Unable to retrieve remote version (network issue?)"
    else
        if version_greater "$LOCAL_VERSION" "$REMOTE_VERSION"; then
            if run_update; then
                echo "Update cycle completed successfully"
            else
                echo "Update cycle failed, will try again in next cycle"
            fi
        else
            echo "No update available (local: $LOCAL_VERSION, remote: $REMOTE_VERSION)"
        fi
    fi
    
    echo "Sleeping for $(($SLEEP_INTERVAL/60)) minutes..."
    sleep $SLEEP_INTERVAL
done