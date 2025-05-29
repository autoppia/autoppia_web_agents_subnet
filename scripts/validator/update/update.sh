#!/bin/bash
# update.sh - Force update and redeploy regardless of version check.
# If deployment fails, revert to the previous codebase and redeploy the old version.

PROCESS_NAME="subnet-36-validator"
WALLET_NAME="your_coldkey"
WALLET_HOTKEY="your_hotkey"
SUBTENSOR_PARAM="--subtensor.network finney"

# Base directory of the repo
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
cd "$REPO_ROOT" || exit 1

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
if [ $# -ge 4 ]; then
    SUBTENSOR_PARAM="$4"
fi

echo "Starting forced update for process: $PROCESS_NAME"
echo "Using subtensor param: $SUBTENSOR_PARAM"

########################################
# Functions
########################################

redeploy_old_version() {
    echo "Reverting to previous commits..."
    cd "$REPO_ROOT" || exit 1

    if [ -d "autoppia_iwa_module" ]; then
        cd autoppia_iwa_module || exit 1
        git reset --hard "$PREV_IWA_HEAD"
        cd "$REPO_ROOT" || exit 1
    fi

    git reset --hard "$PREV_MAIN_HEAD"

    echo "Reinstalling old version..."
    source "$REPO_ROOT/validator_env/bin/activate"
    pip install -e .
    pip install -e autoppia_iwa_module

    echo "Restarting old version in PM2..."
    pm2 restart "$PROCESS_NAME" || pm2 start neurons/validator.py \
        --name "$PROCESS_NAME" \
        --interpreter python \
        -- \
        --netuid 36 \
        $SUBTENSOR_PARAM \
        --wallet.name "$WALLET_NAME" \
        --wallet.hotkey "$WALLET_HOTKEY"

    echo "Old version redeployed."
}

update_and_deploy() {
    echo "Pulling new code from main..."
    cd "$REPO_ROOT" || exit 1
    if ! git pull origin main; then
        echo "Failed to pull main repo."
        redeploy_old_version
        return 1
    fi

    if [ -d "$REPO_ROOT/autoppia_iwa_module" ]; then
        cd "$REPO_ROOT/autoppia_iwa_module" || exit 1
        if ! git pull origin main; then
            echo "Failed to pull autoppia_iwa_module."
            redeploy_old_version
            return 1
        fi
        cd "$REPO_ROOT" || exit 1
    fi

    # Update webs_demo submodule if it exists
    if [ -d "$REPO_ROOT/autoppia_iwa_module/modules/webs_demo" ]; then
        cd "$REPO_ROOT/autoppia_iwa_module/modules/webs_demo" || exit 1
        if ! git pull origin main; then
            echo "Failed to pull webs_demo submodule."
            redeploy_old_version
            return 1
        fi
        cd "$REPO_ROOT" || exit 1
    fi

    # Deploy demo webs if script exists
    if [ -f "$REPO_ROOT/scripts/demo-webs/deploy_demo_webs.sh" ]; then
        echo "Deploying webs demo..."
        chmod +x "$REPO_ROOT/scripts/demo-webs/deploy_demo_webs.sh"
        if ! "$REPO_ROOT/scripts/demo-webs/deploy_demo_webs.sh"; then
            echo "Failed to deploy webs demo."
            redeploy_old_version
            return 1
        fi
        echo "Webs demo deployed successfully."
    fi

    echo "Installing new code..."
    source "$REPO_ROOT/validator_env/bin/activate"

    if ! pip install -e "$REPO_ROOT"; then
        echo "pip install -e . failed."
        redeploy_old_version
        return 1
    fi

    if ! pip install -e "$REPO_ROOT/autoppia_iwa_module"; then
        echo "pip install -e autoppia_iwa_module failed."
        redeploy_old_version
        return 1
    fi

    echo "Restarting PM2 process..."
    if ! pm2 restart "$PROCESS_NAME"; then
        echo "PM2 restart failed. Attempting fallback start..."
        if ! pm2 start neurons/validator.py \
            --name "$PROCESS_NAME" \
            --interpreter python \
            -- \
            --netuid 36 \
            $SUBTENSOR_PARAM \
            --wallet.name "$WALLET_NAME" \
            --wallet.hotkey "$WALLET_HOTKEY"; then
            echo "Fallback PM2 start also failed. Reverting..."
            redeploy_old_version
            return 1
        fi
    fi

    echo "Deployment completed successfully."
    return 0
}

########################################
# Main
########################################

cd "$REPO_ROOT" || exit 1
PREV_MAIN_HEAD=$(git rev-parse HEAD)
PREV_IWA_HEAD=$(cd autoppia_iwa_module && git rev-parse HEAD && cd ..)

echo "Local HEAD (main repo): $PREV_MAIN_HEAD"
echo "Local HEAD (autoppia_iwa_module): $PREV_IWA_HEAD"

if update_and_deploy; then
    echo "Forced update successful."
else
    echo "Forced update failed; reverted to previous version."
fi