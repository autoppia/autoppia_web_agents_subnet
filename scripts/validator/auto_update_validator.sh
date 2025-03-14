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

echo "Starting auto-update service for process: $PROCESS_NAME"

get_local_version() {
    grep "$VERSION_VARIABLE" "$CONFIG_FILE" 2>/dev/null \
        | head -n1 \
        | sed -E 's/.*=[[:space:]]*["'\''"]?([^"'\'' ]+)["'\''"]?.*/\1/'
}

get_remote_version() {
    git fetch origin
    # Compare against 'main' branch
    git show origin/main:"$CONFIG_FILE" 2>/dev/null \
        | grep "$VERSION_VARIABLE" \
        | head -n1 \
        | sed -E 's/.*=[[:space:]]*["'\''"]?([^"'\'' ]+)["'\''"]?.*/\1/'
}

# Returns 0 (true) if v2 > v1, else 1 (false).
version_greater() {
    [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" != "$1" ]
}

while true; do
    LOCAL_VERSION=$(get_local_version)
    REMOTE_VERSION=$(get_remote_version)

    if [ -z "$REMOTE_VERSION" ]; then
        echo "Unable to retrieve remote version (or no remote version found)."
    else
        if version_greater "$REMOTE_VERSION" "$LOCAL_VERSION"; then
            echo "New version detected: $REMOTE_VERSION (local: $LOCAL_VERSION)."
            echo "Invoking update.sh..."
            bash update.sh "$PROCESS_NAME" "$WALLET_NAME" "$WALLET_HOTKEY"
            
            # Check exit code if desired:
            # if [ $? -eq 0 ]; then
            #     echo "update.sh completed successfully."
            # else
            #     echo "update.sh failed."
            # fi
        else
            echo "No update available (local: $LOCAL_VERSION, remote: $REMOTE_VERSION)."
        fi
    fi

    echo "Sleeping for $(($SLEEP_INTERVAL/60)) minutes..."
    sleep $SLEEP_INTERVAL
done
