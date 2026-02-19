#!/usr/bin/env bash
# update_deploy.sh - Force update and redeploy regardless of version check.
# Updates validator and always invokes the top-level demo deploy wrapper.

set -euo pipefail
IFS=$'\n\t'

########################################
# Total steps: 5
########################################
TOTAL_STEPS=5
CURRENT_STEP=0

step() {
  CURRENT_STEP=$((CURRENT_STEP+1))
  echo "[STEP $CURRENT_STEP/$TOTAL_STEPS] $1"
}

########################################
# 1. Configurable parameters
########################################
step "Loading configurable parameters"
PROCESS_NAME="${PROCESS_NAME:-subnet-36-validator}"
WALLET_NAME="${WALLET_NAME:-}"      # will prompt if empty
WALLET_HOTKEY="${WALLET_HOTKEY:-}"  # will prompt if empty
SUBTENSOR_PARAM="${SUBTENSOR_PARAM:---subtensor.network finney}"
# Optional extra flags for validator start (only used when PM2 process does not exist).
VALIDATOR_ARGS="${VALIDATOR_ARGS:-}"

# Override via args
if [ $# -ge 1 ]; then PROCESS_NAME="$1"; fi
if [ $# -ge 2 ]; then WALLET_NAME="$2"; fi
if [ $# -ge 3 ]; then WALLET_HOTKEY="$3"; fi
if [ $# -ge 4 ]; then SUBTENSOR_PARAM="$4"; fi

# Only prompt interactively for missing values
if [ -t 0 ]; then
  if [ -z "$PROCESS_NAME" ]; then
    read -rp "Enter process name (default: subnet-36-validator): " input_process
    PROCESS_NAME="${input_process:-subnet-36-validator}"
  fi
  if [ -z "$WALLET_NAME" ]; then
    read -rp "Enter your coldkey name: " WALLET_NAME
  fi
  if [ -z "$WALLET_HOTKEY" ]; then
    read -rp "Enter your hotkey: " WALLET_HOTKEY
  fi
fi

echo

########################################
# 2. Script and repo roots
########################################
step "Detecting script and repository roots"
SCRIPT_SOURCE="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
echo "Repo root detected at: $REPO_ROOT"
echo

########################################
# 3. Update repositories
########################################
step "Updating repositories"
pushd "$REPO_ROOT" > /dev/null
  echo "Pulling latest from main repository..."
  git pull origin main

  IWA_PATH="${IWA_PATH:-../autoppia_iwa}"
  if [ -d "$IWA_PATH/.git" ]; then
    echo "Updating autoppia_iwa at ${IWA_PATH}..."
    (cd "$IWA_PATH" && git pull origin main)
  else
    echo "autoppia_iwa not found at ${IWA_PATH}; skipping (set IWA_PATH to override)."
  fi
popd > /dev/null
echo

########################################
# 4. Deploy web demos via wrapper
########################################
step "Deploying web demos"
DEPLOY_DEMO_WRAPPER="$REPO_ROOT/scripts/validator/demo-webs/deploy_demo_webs.sh"
echo "Looking for demo deploy wrapper at: $DEPLOY_DEMO_WRAPPER"
if [ ! -x "$DEPLOY_DEMO_WRAPPER" ]; then
  echo "Error: demo deploy wrapper not found or not executable: $DEPLOY_DEMO_WRAPPER" >&2
  exit 1
fi
bash "$DEPLOY_DEMO_WRAPPER"
echo

########################################
# 5. Install and restart validator
########################################
step "Installing and restarting validator"
echo "Activating virtualenv and installing code..."
source "$REPO_ROOT/validator_env/bin/activate"
if [ -f "$REPO_ROOT/requirements.txt" ]; then
  pip install -r "$REPO_ROOT/requirements.txt"
fi
pip install -e .
if [ -d "$IWA_PATH" ]; then
  if [ -f "$IWA_PATH/requirements.txt" ]; then
    pip install -r "$IWA_PATH/requirements.txt"
  fi
  pip install -e "$IWA_PATH"
fi

if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$REPO_ROOT/.env"
  set +a
fi

echo "Restarting PM2 process '$PROCESS_NAME'..."
if ! pm2 restart "$PROCESS_NAME" --update-env; then
  echo "PM2 restart failed; starting fresh instance"
  pm2 start neurons/validator.py \
    --name "$PROCESS_NAME" \
    --interpreter python \
    -- --netuid 36 $SUBTENSOR_PARAM \
       --wallet.name "$WALLET_NAME" \
       --wallet.hotkey "$WALLET_HOTKEY" \
       $VALIDATOR_ARGS
fi

echo
step "Update and deploy completed successfully"
