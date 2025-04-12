#!/bin/bash
# update.sh - Force update and redeploy regardless of version check.
# If deployment fails, revert to the previous codebase and redeploy the old version.

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

echo "Starting forced update for process: $PROCESS_NAME"

########################################
# Functions
########################################

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
        --wallet.name "$WALLET_NAME" \
        --wallet.hotkey "$WALLET_HOTKEY"
    
    echo "Old version redeployed."
}

update_and_deploy() {
    echo "Pulling new code from main..."
    if ! git pull origin main; then
        echo "Failed to pull main repo."
        redeploy_old_version
        return 1
    fi
    
    # Deploy MongoDB if script exists
    if [ -f "./scripts/mongo/deploy_mongo_docker.sh" ]; then
        echo "Deploying MongoDB via Docker..."
        chmod +x ./scripts/mongo/deploy_mongo_docker.sh
        if ! ./scripts/mongo/deploy_mongo_docker.sh -y; then
            echo "MongoDB deployment failed."
            redeploy_old_version
            return 1
        fi
        echo "MongoDB deployment completed successfully."
    fi
    
    # Pull new code in autoppia_iwa_module
    cd autoppia_iwa_module
    if ! git pull origin main; then
        echo "Failed to pull autoppia_iwa_module."
        cd ..
        redeploy_old_version
        return 1
    fi

    # Pull new code in webs_demo as well
    if [ -d "modules/webs_demo" ]; then
      cd modules/webs_demo
      if ! git pull origin main; then
          echo "Failed to pull webs_demo submodule."
          cd ../../..
          redeploy_old_version
          return 1
      fi
      cd ../../..
    fi
    
    # Now back to main repo
    cd ..

    # Deploy webs demo if script exists
    if [ -f "./scripts/validator/deploy_demo_webs.sh" ]; then
        echo "Deploying webs demo..."
        chmod +x ./scripts/validator/deploy_demo_webs.sh
        if ! ./scripts/validator/deploy_demo_webs.sh; then
            echo "Failed to deploy webs demo."
            redeploy_old_version
            return 1
        fi
        echo "Webs demo deployed successfully."
    fi
    
    # Now install the updated code
    echo "Installing new code..."
    source validator_env/bin/activate
    
    if ! pip install -e .; then
        echo "pip install -e . failed."
        redeploy_old_version
        return 1
    fi
    
    if ! pip install -e autoppia_iwa_module; then
        echo "pip install -e autoppia_iwa_module failed."
        redeploy_old_version
        return 1
    fi
    
    # Restart PM2 process
    echo "Restarting PM2 process..."
    if ! pm2 restart "$PROCESS_NAME"; then
        echo "PM2 restart failed. Attempting fallback start..."
        if ! pm2 start neurons/validator.py \
            --name "$PROCESS_NAME" \
            --interpreter python \
            -- \
            --netuid 36 \
            --subtensor.network finney \
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

# Capture current commits before updating, for revert if needed
PREV_MAIN_HEAD=$(git rev-parse HEAD)
PREV_IWA_HEAD=$(cd autoppia_iwa_module && git rev-parse HEAD && cd ..)

echo "Local HEAD (main repo): $PREV_MAIN_HEAD"
echo "Local HEAD (autoppia_iwa_module): $PREV_IWA_HEAD"

# Perform the forced update
if update_and_deploy; then
    echo "Forced update successful."
else
    echo "Forced update failed; reverted to previous version."
fi
