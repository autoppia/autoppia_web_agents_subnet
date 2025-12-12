#!/usr/bin/env bash
# update_all.sh - Simple script to update validator, IWA, and webs_demo repos, then reinstall packages

set -euo pipefail

########################################
# Detect script and repo roots
########################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
echo "📁 Repo root: $REPO_ROOT"
echo

########################################
# Step 1: Update repositories
########################################
echo "🔄 [1/3] Updating repositories..."
cd "$REPO_ROOT"

echo "  📥 Updating validator repo..."
git pull origin main || echo "  ⚠️  Warning: Could not pull validator repo"

# Update IWA (sibling repo)
IWA_PATH="${IWA_PATH:-../autoppia_iwa}"
if [ -d "$IWA_PATH/.git" ]; then
  echo "  📥 Updating IWA at $IWA_PATH..."
  (cd "$IWA_PATH" && git pull origin main) || echo "  ⚠️  Warning: Could not pull IWA repo"
else
  echo "  ⏭️  IWA not found at $IWA_PATH (set IWA_PATH to override)"
fi

# Update webs_demo (sibling repo)
WEBS_DEMO_PATH="${WEBS_DEMO_PATH:-../autoppia_webs_demo}"
if [ -d "$WEBS_DEMO_PATH/.git" ]; then
  echo "  📥 Updating webs_demo at $WEBS_DEMO_PATH..."
  (cd "$WEBS_DEMO_PATH" && git pull origin main) || echo "  ⚠️  Warning: Could not pull webs_demo repo"
else
  echo "  ⏭️  webs_demo not found at $WEBS_DEMO_PATH (set WEBS_DEMO_PATH to override)"
fi

echo

########################################
# Step 2: Activate virtualenv
########################################
echo "🐍 [2/3] Activating virtualenv..."
VENV_PATH="$REPO_ROOT/validator_env"
if [ ! -d "$VENV_PATH" ]; then
  echo "  ❌ Virtualenv not found at $VENV_PATH"
  echo "  💡 Run scripts/validator/main/setup.sh first"
  exit 1
fi

source "$VENV_PATH/bin/activate" || {
  echo "  ❌ Failed to activate virtualenv"
  exit 1
}
echo "  ✅ Virtualenv activated"
echo

########################################
# Step 3: Install/update packages
########################################
echo "📦 [3/3] Installing/updating packages..."

echo "  📦 Installing validator package..."
pip install -e "$REPO_ROOT" || {
  echo "  ❌ Failed to install validator package"
  exit 1
}

if [ -d "$IWA_PATH" ]; then
  echo "  📦 Installing IWA package..."
  pip install -e "$IWA_PATH" || echo "  ⚠️  Warning: Failed to install IWA (continuing anyway)"
fi

echo
echo "✅ Update completed successfully!"
echo "💡 To restart the validator, run: pm2 restart <process-name>"

