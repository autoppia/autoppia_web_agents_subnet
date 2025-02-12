#!/bin/bash
# check_updates.sh - Check for updates and redeploy if a new version is available

PROCESS_NAME="subnet_36_web_agents_validation"
CONFIG_FILE="src/config.py"
VERSION_VARIABLE="__version__"
SLEEP_INTERVAL=60 # Check every 30 minutes

get_local_version() {
    grep "$VERSION_VARIABLE" "$CONFIG_FILE" | head -n1 | sed -E 's/.*=[[:space:]]*["'\'']?([^"'\'' ]+)["'\'']?.*/\1/'
}

get_remote_version() {
    git fetch origin
    branch=$(git rev-parse --abbrev-ref HEAD)
    git show origin/$branch:"$CONFIG_FILE" 2>/dev/null | grep "$VERSION_VARIABLE" | head -n1 | sed -E 's/.*=[[:space:]]*["'\'']?([^"'\'' ]+)["'\'']?.*/\1/'
}

version_greater() {
    [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" != "$1" ]
}

while true; do
    LOCAL_VERSION=$(get_local_version)
    REMOTE_VERSION=$(get_remote_version)
    
    if [ -z "$REMOTE_VERSION" ]; then
        echo "Unable to retrieve remote version."
    else
        if version_greater "$REMOTE_VERSION" "$LOCAL_VERSION"; then
            echo "New version detected: $REMOTE_VERSION (local: $LOCAL_VERSION)"
            echo "Updating validator..."

            pm2 delete "$PROCESS_NAME"
            
            branch=$(git rev-parse --abbrev-ref HEAD)
            if git pull origin "$branch"; then
                pip install -e .
                bash deploy.sh
            else
                echo "git pull failed. Please resolve conflicts manually."
            fi
        else
            echo "No update available. Local version ($LOCAL_VERSION) is up-to-date."
        fi
    fi
    
    echo "Checking Version. Local:$LOCAL_VERSION. Remote:$REMOTE_VERSION"
    sleep $SLEEP_INTERVAL
done
