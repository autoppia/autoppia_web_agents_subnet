#!/bin/bash
# check_validator_updates.sh - Checks for updates and redeploys the validator if changes are detected

set -e

# Configuration
CONFIG_FILE="src/config.py"    # File where the version is defined, e.g., __version__ = "1.0.0"
VERSION_VARIABLE="__version__"
SLEEP_INTERVAL=60  # Time in seconds between checks (60 seconds in this example)

# Function to extract the local version
get_local_version() {
    grep "$VERSION_VARIABLE" "$CONFIG_FILE" | head -n1 | sed -E 's/.*=[[:space:]]*["'"'"']?([^"'"'"' ]+)["'"'"']?.*/\1/'
}

# Function to extract the remote version (from the current branch)
get_remote_version() {
    git fetch origin
    branch=$(git rev-parse --abbrev-ref HEAD)
    git show origin/"$branch":"$CONFIG_FILE" 2>/dev/null | grep "$VERSION_VARIABLE" | head -n1 | sed -E 's/.*=[[:space:]]*["'"'"']?([^"'"'"' ]+)["'"'"']?.*/\1/'
}

# Function to compare versions (using sort -V)
# Returns true if the second argument is greater than the first
version_greater() {
    [ "$(printf '%s\n' "$1" "$2" | sort -V | head -n1)" != "$1" ]
}

while true; do
    LOCAL_VERSION=$(get_local_version)
    REMOTE_VERSION=$(get_remote_version)

    if [ -z "$REMOTE_VERSION" ]; then
        echo "[WARN] Unable to retrieve the remote version."
    else
        echo "[INFO] Local version: $LOCAL_VERSION | Remote version: $REMOTE_VERSION"
        if version_greater "$LOCAL_VERSION" "$REMOTE_VERSION"; then
            echo "[INFO] New version detected: $REMOTE_VERSION. Updating validator..."
            
            # Stop the validator process via PM2
            pm2 delete "subnet_36_validator" || echo "[WARN] Validator process not found."

            branch=$(git rev-parse --abbrev-ref HEAD)
            echo "[INFO] Current branch: $branch"
            if git pull origin "$branch"; then
                echo "[INFO] Repository updated. Running setup.sh to reinstall dependencies..."
                # Run setup.sh to update/install dependencies (ensure the path is correct)
                bash ./setup.sh

                echo "[INFO] Restarting the validator process..."
                # Restart the validator process using PM2 so that changes take effect
                pm2 restart "subnet_36_validator"
            else
                echo "[ERROR] git pull failed. Please resolve conflicts manually."
            fi
        else
            echo "[INFO] Local version ($LOCAL_VERSION) is up-to-date."
        fi
    fi

    sleep $SLEEP_INTERVAL
done
