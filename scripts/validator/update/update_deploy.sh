#!/usr/bin/env bash
# update_deploy.sh - Force update and redeploy regardless of version check.
# Updates validator and always invokes the top-level demo deploy wrapper.

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
if [ $# -ge 1 ]; then PROCESS_NAME="$1"; fi
if [ $# -ge 2 ]; then WALLET_NAME="$2"; fi
if [ $# -ge 3 ]; then WALLET_HOTKEY="$3"; fi
if [ $# -ge 4 ]; then SUBTENSOR_PARAM="$4"; fi

# Prompt for process name
read -rp "Enter process name [${PROCESS_NAME}]: " input_process
PROCESS_NAME="${input_process:-$PROCESS_NAME}"

# Prompt for wallet/hotkey
read -rp "Enter your coldkey name (WALLET_NAME) [${WALLET_NAME}]: " input_wallet
WALLET_NAME="${input_wallet:-$WALLET_NAME}"
read -rp "Enter your hotkey (WALLET_HOTKEY) [${WALLET_HOTKEY}]: " input_hotkey
WALLET_HOTKEY="${input_hotkey:-$WALLET_HOTKEY}"

echo "[INFO] Using parameters:"
echo "  PROCESS_NAME    = $PROCESS_NAME"
echo "  WALLET_NAME     = $WALLET_NAME"
echo "  WALLET_HOTKEY   = $WALLET_HOTKEY"
echo "  SUBTENSOR_PARAM = $SUBTENSOR_PARAM"
echo

########################################
# 2. Script and repo roots
########################################

SCRIPT_SOURCE="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
# update_deploy.sh lives in scripts/validator/update
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
# 4. Deploy web demos via wrapper
########################################

DEPLOY_DEMO_WRAPPER="$REPO_ROOT/scripts/validator/demo-webs/deploy_demo_webs.sh"

echo "[INFO] Looking for demo deploy wrapper at: $DEPLOY_DEMO_WRAPPER"
if [ ! -x "$DEPLOY_DEMO_WRAPPER" ]; then
  echo "Error: demo deploy wrapper not found or not executable: $DEPLOY_DEMO_WRAPPER" >&2
  exit 1
fi

echo "[INFO] Executing demo deploy wrapper: $DEPLOY_DEMO_WRAPPER"
bash "$DEPLOY_DEMO_WRAPPER"
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
