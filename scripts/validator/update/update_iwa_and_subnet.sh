#!/usr/bin/env bash
# update_iwa_and_subnet.sh - Update subnet + IWA and restart validator.

set -euo pipefail
IFS=$'\n\t'

########################################
# 1. Configurable parameters
########################################
PROCESS_NAME="${PROCESS_NAME:-subnet-36-validator}"
WALLET_NAME="${WALLET_NAME:-}"      # only used if PM2 process does not exist
WALLET_HOTKEY="${WALLET_HOTKEY:-}"  # only used if PM2 process does not exist
SUBTENSOR_PARAM="${SUBTENSOR_PARAM:---subtensor.network finney}"
VALIDATOR_ARGS="${VALIDATOR_ARGS:-}"  # only used if PM2 process does not exist
IWA_PATH="${IWA_PATH:-../autoppia_iwa}"

# Override via args
if [ $# -ge 1 ]; then PROCESS_NAME="$1"; fi
if [ $# -ge 2 ]; then WALLET_NAME="$2"; fi
if [ $# -ge 3 ]; then WALLET_HOTKEY="$3"; fi
if [ $# -ge 4 ]; then SUBTENSOR_PARAM="$4"; fi

########################################
# 2. Paths
########################################
SCRIPT_SOURCE="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
if [[ "$IWA_PATH" != /* ]]; then
  IWA_PATH="$REPO_ROOT/$IWA_PATH"
fi

echo "[INFO] Repo root: $REPO_ROOT"
echo "[INFO] IWA path:  $IWA_PATH"

########################################
# 3. Pull subnet + IWA
########################################
pushd "$REPO_ROOT" > /dev/null
  echo "[INFO] Pulling subnet (main)..."
  git pull origin main

  if [ -d "$IWA_PATH/.git" ]; then
    echo "[INFO] Pulling autoppia_iwa (main) from $IWA_PATH..."
    (cd "$IWA_PATH" && git pull origin main)
  else
    echo "[WARN] autoppia_iwa not found at ${IWA_PATH}; skipping"
  fi
popd > /dev/null

########################################
# 4. Install Python dependencies
########################################
echo "[INFO] Installing/updating Python packages..."
source "$REPO_ROOT/validator_env/bin/activate"
if [ -f "$REPO_ROOT/requirements.txt" ]; then
  pip install -r "$REPO_ROOT/requirements.txt"
fi
pip install -e "$REPO_ROOT"
if [ -d "$IWA_PATH" ]; then
  if [ -f "$IWA_PATH/requirements.txt" ]; then
    pip install -r "$IWA_PATH/requirements.txt"
  fi
  pip install -e "$IWA_PATH"
fi

########################################
# 5. Restart validator
########################################
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$REPO_ROOT/.env"
  set +a
fi

echo "[INFO] Restarting PM2 process '$PROCESS_NAME'..."
if ! pm2 restart "$PROCESS_NAME" --update-env; then
  if [ -z "$WALLET_NAME" ] || [ -z "$WALLET_HOTKEY" ]; then
    echo "[ERROR] PM2 process '$PROCESS_NAME' not found and wallet params are missing." >&2
    echo "[ERROR] Set WALLET_NAME and WALLET_HOTKEY (env or args) to create the process." >&2
    exit 1
  fi
  echo "[WARN] PM2 restart failed; starting new validator process"
  pm2 start "$REPO_ROOT/neurons/validator.py" \
    --name "$PROCESS_NAME" \
    --interpreter python \
    -- --netuid 36 $SUBTENSOR_PARAM \
       --wallet.name "$WALLET_NAME" \
       --wallet.hotkey "$WALLET_HOTKEY" \
       $VALIDATOR_ARGS
fi

echo "[INFO] Subnet + IWA update completed"
