#!/bin/bash
# check_updates.sh - Check for updates and redeploy if a new version is available
# If deployment fails, revert to the previous codebase and redeploy the old version.

PROCESS_NAME="subnet-36-validator"
CONFIG_FILE="autoppia_web_agents_subnet/__init__.py"
VERSION_VARIABLE="__version__"
SLEEP_INTERVAL=5  # 30 minutes

get_local_version() {
    grep "$VERSION_VARIABLE" "$CONFIG_FILE" | head -n1 | sed -E 's/.*=[[:space:]]*["'\''"]?([^"'\'' ]+)["'\''"]?.*/\1/'
}

get_remote_version() {
    git fetch origin
    # Compare with 'main' branch
    git show origin/main:"$CONFIG_FILE" 2>/dev/null \
        | grep "$VERSION_VARIABLE" \
        | head -n1 \
        | sed -E 's/.*=[[:space:]]*["'\''"]?([^"'\'' ]+)["'\''"]?.*/\1/'
}

version_greater() {
    [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" != "$1" ]
}

redeploy_old_version() {
    echo "Reverting to previous commits..."
    # Revert autoppia_iwa_module
    cd autoppia_iwa_module
    git reset --hard "$PREV_IWA_HEAD"
    cd ..

    # Revert main repo
    git reset --hard "$PREV_MAIN_HEAD"

    echo "Reinstalling old version..."
    source validator_env/bin/activate
    pip install -e .
    pip install -e autoppia_iwa_module

    echo "Restarting old version in PM2..."
    pm2 restart "$PROCESS_NAME" || pm2 start neurons/validator.py \
        --name "$PROCESS_NAME" \
        --interpreter python \
        -- \
        --netuid 36 \
        --subtensor.network finney \
        --wallet.name your_coldkey \
        --wallet.hotkey your_hotkey

    echo "Old version redeployed."
}

update_and_deploy() {
    echo "Pulling new code..."
    if ! git pull origin main; then
        echo "Failed to pull main repo."
        redeploy_old_version
        return 1
    fi

    cd autoppia_iwa_module
    if ! git pull origin main; then
        echo "Failed to pull autoppia_iwa_module."
        cd ..
        redeploy_old_version
        return 1
    fi
    cd ..

    echo "Installing new code..."
    source validator_env/bin/activate

    if ! pip install -e .; then
        echo "pip install -e . failed"
        redeploy_old_version
        return 1
    fi

    if ! pip install -e autoppia_iwa_module; then
        echo "pip install -e autoppia_iwa_module failed"
        redeploy_old_version
        return 1
    fi

    echo "Restarting PM2 process..."
    if ! pm2 restart "$PROCESS_NAME"; then
        echo "PM2 restart failed"
        # Attempt fallback: start if restart fails
        if ! pm2 start neurons/validator.py \
            --name "$PROCESS_NAME" \
            --interpreter python \
            -- \
            --netuid 36 \
            --subtensor.network finney \
            --wallet.name your_coldkey \
            --wallet.hotkey your_hotkey; then
            echo "Fallback PM2 start also failed. Reverting..."
            redeploy_old_version
            return 1
        fi
    fi

    echo "Deployment completed successfully."
    return 0
}

while true; do
    LOCAL_VERSION=$(get_local_version)
    REMOTE_VERSION=$(get_remote_version)

    if [ -z "$REMOTE_VERSION" ]; then
        echo "Unable to retrieve remote version."
    else
        if version_greater "$REMOTE_VERSION" "$LOCAL_VERSION"; then
            echo "New version detected: $REMOTE_VERSION (local: $LOCAL_VERSION)"

            # Capture current commits before updating
            PREV_MAIN_HEAD=$(git rev-parse HEAD)
            PREV_IWA_HEAD=$(cd autoppia_iwa_module && git rev-parse HEAD)

            if update_and_deploy; then
                echo "Update successful: now at version $REMOTE_VERSION."
            else
                echo "Update failed; reverted to previous version ($LOCAL_VERSION)."
            fi
        else
            echo "No update available (local: $LOCAL_VERSION, remote: $REMOTE_VERSION)."
        fi
    fi

    sleep $SLEEP_INTERVAL
done
