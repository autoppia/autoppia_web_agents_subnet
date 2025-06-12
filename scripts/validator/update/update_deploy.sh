#!/usr/bin/env bash
# update_deploy.sh - Force update and redeploy regardless of version check.

set -euo pipefail
IFS=$'\n\t'

########################################
# 1. Configurable parameters
########################################

PROCESS_NAME="${PROCESS_NAME:-subnet-36-validator}"
WALLET_NAME="${WALLET_NAME:-}"
WALLET_HOTKEY="${WALLET_HOTKEY:-}"
SUBTENSOR_PARAM="${SUBTENSOR_PARAM:---subtensor.network finney}"

[ $# -ge 1 ] && PROCESS_NAME="$1"
[ $# -ge 2 ] && WALLET_NAME="$2"
[ $# -ge 3 ] && WALLET_HOTKEY="$3"
[ $# -ge 4 ] && SUBTENSOR_PARAM="$4"

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
# update_deploy.sh está en scripts/validator/update,
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

########################################
# 3. Update and deploy function
########################################

update_and_deploy() {
  pushd "$REPO_ROOT" > /dev/null

  echo "[INFO] Pulling latest from main repository..."
  git pull origin main

  if [ -d autoppia_iwa_module ]; then
    echo "[INFO] Updating autoppia_iwa_module..."
    cd autoppia_iwa_module
    git pull origin main
    cd - > /dev/null
  fi

  if [ -d autoppia_iwa_module/modules/webs_demo ]; then
    echo "[INFO] Updating webs_demo module..."
    cd autoppia_iwa_module/modules/webs_demo
    git pull origin main
    cd - > /dev/null
  fi

  # Run demo webs deploy if script exists
  deploy_script="scripts/demo-webs/deploy_demo_webs.sh"
  if [ -x "$deploy_script" ]; then
    echo "[INFO] Executing deploy_demo_webs.sh..."
    "$deploy_script"
  fi

  echo "[INFO] Installing updated code..."

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

  popd > /dev/null
  echo "[SUCCESS] Update and deploy completed successfully."
}

########################################
# 4. Execute
########################################

update_and_deploy
