#!/bin/bash
# setup.sh — create venv, install Python deps & Playwright

set -e

# Print error and exit
handle_error() {
  echo -e "\e[31m[ERROR]\e[0m $1" >&2
  exit 1
}

# Print success message
success_msg() {
  echo -e "\e[32m[SUCCESS]\e[0m $1"
}

check_python() {
  echo -e "\e[34m[INFO]\e[0m Checking for Python 3.11..."
  python3.11 --version || handle_error "Python 3.11 is required. Run install_dependencies.sh first."
}

create_activate_venv() {
  VENV_DIR="validator_env"
  echo -e "\e[34m[INFO]\e[0m Creating virtualenv in $VENV_DIR..."
  if [ ! -d "$VENV_DIR" ]; then
    python3.11 -m venv "$VENV_DIR" \
      || handle_error "Failed to create virtualenv"
    success_msg "Virtualenv created."
  else
    echo -e "\e[32m[INFO]\e[0m Virtualenv already exists. Skipping creation."
  fi

  echo -e "\e[34m[INFO]\e[0m Activating virtualenv..."
  source "$VENV_DIR/bin/activate" \
    || handle_error "Failed to activate virtualenv"
}

upgrade_pip() {
  echo -e "\e[34m[INFO]\e[0m Upgrading pip and setuptools..."
  python -m pip install --upgrade pip setuptools \
    || handle_error "Failed to upgrade pip/setuptools"
  success_msg "pip and setuptools upgraded."
}

sync_repo() {
  local NAME="$1"
  local PATH_VAR="$2"
  local URL="$3"

  if [ -d "$PATH_VAR/.git" ]; then
    echo -e "\e[34m[INFO]\e[0m Updating $NAME at $PATH_VAR..."
    pushd "$PATH_VAR" >/dev/null || handle_error "Failed to enter $PATH_VAR"
      git fetch --all --prune || echo "⚠️ Could not fetch $NAME (non-fatal)"
      git checkout main 2>/dev/null || true
      git pull origin main || echo "⚠️ Could not pull $NAME (non-fatal)"
    popd >/dev/null || true
  elif [ -d "$PATH_VAR" ]; then
    echo -e "\e[34m[INFO]\e[0m Found $NAME at $PATH_VAR (non-git); skipping pull."
  else
    echo -e "\e[34m[INFO]\e[0m Cloning $NAME into $PATH_VAR..."
    git clone "$URL" "$PATH_VAR" || handle_error "Failed to clone $NAME from $URL"
  fi
}

sync_external_repos() {
  local REPO_ROOT="$1"
  IWA_PATH="${IWA_PATH:-${REPO_ROOT}/../autoppia_iwa}"
  WEBS_DEMO_PATH="${WEBS_DEMO_PATH:-${REPO_ROOT}/../autoppia_webs_demo}"
  IWA_URL="${IWA_URL:-https://github.com/autoppia/autoppia_iwa.git}"
  WEBS_DEMO_URL="${WEBS_DEMO_URL:-https://github.com/autoppia/autoppia_webs_demo.git}"

  sync_repo "autoppia_iwa" "$IWA_PATH" "$IWA_URL"
  # webs_demo is optional; clone/update if present/missing
  sync_repo "autoppia_webs_demo" "$WEBS_DEMO_PATH" "$WEBS_DEMO_URL"
}

install_python_reqs() {
  echo -e "\e[34m[INFO]\e[0m Installing Python dependencies from requirements.txt..."
  [ -f "requirements.txt" ] || handle_error "requirements.txt not found"

  pip install -r requirements.txt \
    || handle_error "Failed to install Python dependencies"

  echo -e "\e[34m[INFO]\e[0m Installing Playwright package..."
  pip install playwright \
    || handle_error "Failed to install Playwright package"

  # Verify that the playwright CLI is available
  if ! command -v playwright >/dev/null 2>&1; then
    handle_error "playwright CLI not found after installation. Make sure 'playwright' is in PATH."
  fi

  echo -e "\e[34m[INFO]\e[0m Downloading Playwright browsers..."
  python -m playwright install \
    || handle_error "Failed to download Playwright browsers"

  # Install any additional OS dependencies for Playwright (silently ignore errors)
  python -m playwright install-deps 2>/dev/null || true

  success_msg "Playwright and browsers installed."
}

install_modules() {
  echo -e "\e[34m[INFO]\e[0m Installing current package in editable mode..."
  pip install -e . \
    || handle_error "Failed to install current package"
  success_msg "Main package installed."

  IWA_PATH="${IWA_PATH:-${REPO_ROOT}/../autoppia_iwa}"
  echo -e "\e[34m[INFO]\e[0m Installing autoppia_iwa from ${IWA_PATH}..."
  [ -d "$IWA_PATH" ] || handle_error "IWA_PATH not found: ${IWA_PATH}. Clone autoppia_iwa as a sibling repo or set IWA_PATH."

  pushd "$IWA_PATH" >/dev/null
    pip install -e . \
      || handle_error "Failed to install autoppia_iwa"
  popd >/dev/null
  success_msg "autoppia_iwa installed."
}

install_bittensor() {
  echo -e "\e[34m[INFO]\e[0m Installing Bittensor v9.9.0 and CLI v9.4.2..."
  pip install bittensor==9.9.0 bittensor-cli==9.9.0 \
    || handle_error "Failed to install Bittensor"
  success_msg "Bittensor installed."
}

main() {
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
  cd "$REPO_ROOT" || handle_error "Failed to navigate to repo root"

  check_python
  create_activate_venv
  upgrade_pip
  sync_external_repos "$REPO_ROOT"
  install_python_reqs
  install_bittensor  # Install bittensor first
  install_modules    # Install IWA with flexible version ranges that work with bittensor
  success_msg "Setup completed successfully."
  echo -e "\e[33m[INFO]\e[0m Virtual environment: $(pwd)/validator_env"
  echo -e "\e[33m[INFO]\e[0m To activate: source validator_env/bin/activate"
}

main "$@"
