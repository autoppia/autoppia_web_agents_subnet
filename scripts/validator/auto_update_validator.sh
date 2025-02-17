#!/bin/bash
# check_updates.sh - Check for updates and redeploy if a new version is available

PROCESS_NAME="subnet-36-validator"
CONFIG_FILE="autoppia_web_agents_subnet/__init__.py"
VERSION_VARIABLE="__version__"

# Set this to how often (in seconds) you want to check. (1800 = 30 minutes)
SLEEP_INTERVAL=5

get_local_version() {
    grep "$VERSION_VARIABLE" "$CONFIG_FILE" | head -n1 | sed -E 's/.*=[[:space:]]*["'\'']?([^"'\'' ]+)["'\'']?.*/\1/'
}

get_remote_version() {
    git fetch origin
    branch=$(git rev-parse --abbrev-ref HEAD)
    git show origin/$branch:"$CONFIG_FILE" 2>/dev/null | grep "$VERSION_VARIABLE" | head -n1 | sed -E 's/.*=[[:space:]]*["'\'']?([^"'\'' ]+)["'\'']?.*/\1/'
}

version_greater() {
    # Returns true if $2 > $1 in semver ordering
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
            
            branch=$(git rev-parse --abbrev-ref HEAD)
            if git pull origin "$branch"; then
                # Pull updates for autoppia_iwa_module as well
                cd autoppia_iwa_module
                git pull origin main
                cd ..

                # Activate the Python environment (adjust if your path differs)
                source validator_env/bin/activate

                # Reinstall local modules
                pip install -e .
                pip install -e autoppia_iwa_module

                # Restart (or start) the validator in PM2
                pm2 restart "$PROCESS_NAME" || pm2 start neurons/validator.py \
                    --name "$PROCESS_NAME" \
                    --interpreter python \
                    -- \
                    --netuid 36 \
                    --subtensor.network finney \
                    --wallet.name your_coldkey \
                    --wallet.hotkey your_hotkey

                echo "Redeployment completed."
            else
                echo "git pull failed. Please resolve conflicts manually."
            fi
        else
            echo "No update available. Local version ($LOCAL_VERSION) is up-to-date."
        fi
    fi
    
    echo "Checking again in $SLEEP_INTERVAL seconds. Local:$LOCAL_VERSION, Remote:$REMOTE_VERSION"
    sleep $SLEEP_INTERVAL
done
