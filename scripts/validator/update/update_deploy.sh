#!/usr/bin/env bash
# update_deploy.sh - Force update and redeploy regardless of version check.
# Updates validator and redeploys web demos (cleanup + redeploy).

set -euo pipefail
IFS=$'\n\t'

########################################
# 1. Configurable parameters
########################################

PROCESS_NAME="${PROCESS_NAME:-subnet-36-validator}"
WALLET_NAME="${WALLET_NAME:-}"
WALLET_HOTKEY="${WALLET_HOTKEY:-}"
SUBTENSOR_PARAM="${SUBTENSOR_PARAM:---subtensor.network finney}"

# Override via args
[ $# -ge 1 ] && PROCESS_NAME="$1"
[ $# -ge 2 ] && WALLET_NAME="$2"
[ $# -ge 3 ] && WALLET_HOTKEY="$3"
[ $# -ge 4 ] && SUBTENSOR_PARAM="$4"

# Prompt if missing
if [ -z "$WALLET_NAME" ]; then
  read -rp "Enter your coldkey name (WALLET_NAME): " WALLET_NAME
fi
if [ -z "$WALLET_HOTKEY" ]; then
  read -rp "Enter your hotkey (WALLET_HOTKEY): " WALLET_HOTKEY
fi

echo "[INFO] Using parameters:"
echo "  PROCESS_NAME    = $PROCESS_NAME"
echo "  WALLET_NAME     = $WALLET_NAME"
echo "  WALLET_HOTKEY   = $WALLET_HOTKEY"
echo "  SUBTENSOR_PARAM = $SUBTENSOR_PARAM"
echo

########################################
# 2. Script and repo roots
########################################

# Determine this script's directory
SCRIPT_SOURCE="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"

# update_deploy.sh lives in scripts/validator/update, so go three levels up
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo "[INFO] Repo root detected at: $REPO_ROOT"

echo

########################################
# 3. Update repositories
########################################

pushd "$REPO_ROOT" > /dev/null

echo "[INFO] Pulling latest from main repository..."
git pull origin main

if [ -d autoppia_iwa_module ]; then
  echo "[INFO] Updating autoppia_iwa_module..."
  (cd autoppia_iwa_module && git pull origin main)
fi

popd > /dev/null

echo

########################################
# 4. Deploy web demos
########################################

# First, try your top-level wrapper if present
DEPLOY_DEMO_WRAPPER="$REPO_ROOT/scripts/validator/demo-webs/deploy_demo_webs.sh"
echo "[INFO] Looking for top-level demo deploy wrapper at: $DEPLOY_DEMO_WRAPPER"
if [ -x "$DEPLOY_DEMO_WRAPPER" ]; then
  echo "[INFO] Executing top-level demo deploy wrapper: $DEPLOY_DEMO_WRAPPER"
  bash "$DEPLOY_DEMO_WRAPPER"
else
  # Fallback: call module scripts directly
  DEMO_SCRIPT_DIR="$REPO_ROOT/autoppia_iwa_module/modules/webs_demo/scripts"
  if [ -d "$DEMO_SCRIPT_DIR" ]; then
    echo "[INFO] No top-level wrapper found. Performing fallback deploy in $DEMO_SCRIPT_DIR"
    pushd "$DEMO_SCRIPT_DIR" > /dev/null
    chmod +x install_docker.sh setup.sh
    echo "[INFO] Running install_docker.sh (cleanup volumes)..."
    ./install_docker.sh
    echo "[INFO] Running setup.sh -y (deploy demos)..."
    ./setup.sh -y
    popd > /dev/null
  else
    echo "[WARN] Demo script directory not found: $DEMO_SCRIPT_DIR"
  fi
fi

echo
########################################
# 5. Install and restart validator
########################################

echo "[INFO] Activating virtualenv and installing code..."
source "$REPO_ROOT/validator_env/bin/activate"

pip install -e .
pip install -e autoppia_iwa_module || true

echo "[INFO] Restarting PM2 process '$PROCESS_NAME'..."
if ! pm2 restart "$PROCESS_NAME"; then
  echo "[WARN] PM2 restart failed. Performing fresh start..."
  pm2 start neurons/validator.py \
    --name "$PROCESS_NAME" \
    --interpreter python \
    -- --netuid 36 $SUBTENSOR_PARAM \
       --wallet.name "$WALLET_NAME" \
       --wallet.hotkey "$WALLET_HOTKEY"
fi

echo "[SUCCESS] Update and deploy completed successfully."
