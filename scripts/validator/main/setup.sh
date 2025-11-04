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

init_submodules() {
  echo -e "\e[34m[INFO]\e[0m Initializing Git submodules (autoppia_iwa_module, etc.)..."
  
  # Go to repo root (parent of scripts/)
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
  cd "$REPO_ROOT" || handle_error "Failed to navigate to repo root"
  
  # Check if this is a git repository
  if [ ! -d ".git" ]; then
    echo -e "\e[34m[INFO]\e[0m Not a git repository. Skipping submodule initialization."
    return 0
  fi
  
  # Initialize and update submodules
  git submodule update --init --recursive --remote \
    || handle_error "Failed to initialize git submodules. Make sure git is installed and you have access to the submodule repos."
  
  success_msg "Git submodules initialized."
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

  echo -e "\e[34m[INFO]\e[0m Installing autoppia_iwa_module..."
  [ -d "autoppia_iwa_module" ] || handle_error "autoppia_iwa_module directory not found"

  pushd autoppia_iwa_module >/dev/null
    pip install -e . \
      || handle_error "Failed to install autoppia_iwa_module"
  popd >/dev/null
  success_msg "autoppia_iwa_module installed."
}

install_bittensor() {
  echo -e "\e[34m[INFO]\e[0m Installing Bittensor v9.9.0 and CLI v9.4.2..."
  pip install bittensor==9.9.0 bittensor-cli==9.9.0 \
    || handle_error "Failed to install Bittensor"
  success_msg "Bittensor installed."
}

main() {
  check_python
  create_activate_venv
  upgrade_pip
  init_submodules
  install_python_reqs
  install_modules
  install_bittensor
  success_msg "Setup completed successfully."
  echo -e "\e[33m[INFO]\e[0m Virtual environment: $(pwd)/validator_env"
  echo -e "\e[33m[INFO]\e[0m To activate: source validator_env/bin/activate"
}

main "$@"
