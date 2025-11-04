#!/bin/bash
# setup.sh - Setup miner Python environment and dependencies
set -e

handle_error() {
  echo -e "\e[31m[ERROR]\e[0m $1" >&2
  exit 1
}

success_msg() {
  echo -e "\e[32m[SUCCESS]\e[0m $1"
}

info_msg() {
  echo -e "\e[34m[INFO]\e[0m $1"
}

check_python() {
  info_msg "Checking for Python 3.11..."
  python3.11 --version || handle_error "Python 3.11 is required. Run install_dependencies.sh first."
}

create_activate_venv() {
  VENV_DIR="miner_env"
  info_msg "Creating virtualenv in $VENV_DIR..."
  if [ ! -d "$VENV_DIR" ]; then
    python3.11 -m venv "$VENV_DIR" \
      || handle_error "Failed to create virtualenv"
    success_msg "Virtualenv created."
  else
    info_msg "Virtualenv already exists. Skipping creation."
  fi

  info_msg "Activating virtualenv..."
  source "$VENV_DIR/bin/activate" \
    || handle_error "Failed to activate virtualenv"
}

upgrade_pip() {
  info_msg "Upgrading pip and setuptools..."
  python -m pip install --upgrade pip setuptools \
    || handle_error "Failed to upgrade pip/setuptools"
  success_msg "pip and setuptools upgraded."
}

init_submodules() {
  info_msg "Initializing Git submodules (autoppia_iwa_module, etc.)..."
  
  # Go to repo root (parent of scripts/)
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  cd "$REPO_ROOT" || handle_error "Failed to navigate to repo root"
  
  # Check if this is a git repository
  if [ ! -d ".git" ]; then
    info_msg "Not a git repository. Skipping submodule initialization."
    return 0
  fi
  
  # Initialize and update submodules
  git submodule update --init --recursive --remote \
    || handle_error "Failed to initialize git submodules. Make sure git is installed and you have access to the submodule repos."
  
  success_msg "Git submodules initialized."
}

install_python_reqs() {
  info_msg "Installing Python dependencies from requirements.txt..."
  [ -f "requirements.txt" ] || handle_error "requirements.txt not found"
  
  pip install -r requirements.txt \
    || handle_error "Failed to install Python dependencies"

  info_msg "Installing Playwright package..."
  pip install playwright \
    || handle_error "Failed to install Playwright package"
  
  # Verify that the playwright CLI is available
  if ! command -v playwright >/dev/null 2>&1; then
    handle_error "playwright CLI not found after installation. Make sure 'playwright' is in PATH."
  fi
  
  info_msg "Downloading Playwright browsers..."
  python -m playwright install \
    || handle_error "Failed to download Playwright browsers"
  
  # Install any additional OS dependencies for Playwright (silently ignore errors)
  python -m playwright install-deps 2>/dev/null || true
  
  success_msg "Playwright and browsers installed."
}

install_modules() {
  info_msg "Installing current package in editable mode..."
  pip install -e . \
    || handle_error "Failed to install current package"
  success_msg "Main package installed."

  info_msg "Installing autoppia_iwa_module..."
  [ -d "autoppia_iwa_module" ] || handle_error "autoppia_iwa_module directory not found"
  
  pushd autoppia_iwa_module >/dev/null
  pip install -e . \
    || handle_error "Failed to install autoppia_iwa_module"
  popd >/dev/null
  success_msg "autoppia_iwa_module installed."
}

install_bittensor() {
  info_msg "Installing Bittensor v9.9.0 and CLI v9.4.2..."
  pip install bittensor==9.9.0 bittensor-cli==9.9.0 \
    || handle_error "Failed to install Bittensor"
  success_msg "Bittensor installed."
}

verify_installation() {
  info_msg "Verifying miner environment setup..."
  
  # Check Bittensor
  python -c "import bittensor; print(f'✓ Bittensor: {bittensor.__version__}')" || \
    info_msg "⚠ Warning: Bittensor import failed"
  
  # Check Playwright
  python -c "import playwright; print('✓ Playwright: imported successfully')" || \
    info_msg "⚠ Warning: Playwright import failed"
  
  success_msg "Installation verification completed."
}

show_completion_info() {
  echo
  success_msg "Miner setup completed successfully!"
  echo
  echo -e "\e[33m[INFO]\e[0m Virtual environment: $(pwd)/miner_env"
  echo -e "\e[33m[INFO]\e[0m To activate: source miner_env/bin/activate"
  echo
  echo -e "\e[32m[READY]\e[0m Your miner environment is ready to use!"
  echo
  echo -e "\e[34m[NEXT STEPS]\e[0m"
  echo "1. Configure your .env file"
  echo "2. Start your miner with PM2:"
  echo "   source miner_env/bin/activate"
  echo "   pm2 start neurons/miner.py --name miner --interpreter python -- \\"
  echo "     --netuid 36 --subtensor.network finney \\"
  echo "     --wallet.name your_coldkey --wallet.hotkey your_hotkey"
}

main() {
  check_python
  create_activate_venv
  upgrade_pip
  init_submodules
  install_python_reqs
  install_modules
  install_bittensor
  verify_installation
  
  show_completion_info
}

main "$@"