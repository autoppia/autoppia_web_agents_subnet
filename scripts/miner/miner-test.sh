#!/bin/bash
#
# setup.sh - Setup environment dependencies for Miner
#
# Optimized for Bittensor miner operations with dependency isolation

set -eo pipefail  # Exit on error and handle piped commands

# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------
NODE_VERSION="18"
VENV_DIR="miner_env"
MINER_USER=$(whoami)

# ---------------------------------------------------------
# Colorized Output Helpers
# ---------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

handle_error() {
  echo -e "${RED}[ERROR]${NC} $1" >&2
  exit 1
}

success_msg() {
  echo -e "${GREEN}[SUCCESS]${NC} $1"
}

info_msg() {
  echo -e "${BLUE}[INFO]${NC} $1"
}

warn_msg() {
  echo -e "${YELLOW}[WARN]${NC} $1"
}

# ---------------------------------------------------------
# 1. Install System Dependencies
# ---------------------------------------------------------
install_system_dependencies() {
  info_msg "Updating system packages..."
  sudo apt-get update || warn_msg "apt update returned non-zero exit code"
  sudo apt-get upgrade -y || warn_msg "apt upgrade returned non-zero exit code"

  info_msg "Installing essential system packages..."
  sudo apt-get install -y \
    software-properties-common curl git build-essential cmake \
    wget unzip sqlite3 libsqlite3-dev \
    || handle_error "System dependencies installation failed"

  success_msg "System dependencies installed"
}

# ---------------------------------------------------------
# 2. Install Python 3.11 and Related Libraries
# ---------------------------------------------------------
install_python311() {
  info_msg "Adding Python 3.11 repository..."
  sudo add-apt-repository -y ppa:deadsnakes/ppa >/dev/null 2>&1 || handle_error "Failed to add deadsnakes PPA"
  sudo apt-get update || handle_error "apt update failed after PPA add"

  info_msg "Installing Python 3.11 and required libraries..."
  sudo apt-get install -y \
    python3.11 python3.11-venv python3.11-dev \
    libasound2 libnss3 libnss3-dev libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libx11-xcb1 libxcomposite1 libxcursor1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libgtk-3-0 libvpx-dev libevent-dev libopus0 \
    libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 \
    libgstreamer-plugins-good1.0-0 libgstreamer-plugins-bad1.0-0 \
    libwebp-dev libharfbuzz-dev libsecret-1-dev libhyphen0 libflite1 \
    libgles2-mesa libgl1-mesa-dev libx264-dev \
    || handle_error "Could not install Python 3.11 and related libraries"
  success_msg "Python 3.11 and its libraries installed."
}

# ---------------------------------------------------------
# 3. Install Node.js 18.x and PM2
# ---------------------------------------------------------
install_pm2() {
  info_msg "Removing previous Node.js installations..."
  sudo apt-get purge -y 'nodejs*' 'npm*' 'libnode*' >/dev/null 2>&1 || true
  sudo rm -rf /etc/apt/sources.list.d/nodesource.list >/dev/null 2>&1 || true

  info_msg "Installing Node.js v${NODE_VERSION}..."
  curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | sudo -E bash - >/dev/null 2>&1 || handle_error "NodeSource setup failed"
  sudo apt-get install -y nodejs || handle_error "Node.js installation failed"

  info_msg "Installing PM2 globally..."
  sudo npm install -g pm2 >/dev/null 2>&1 || handle_error "PM2 installation failed"

  info_msg "Configuring PM2 startup..."
  sudo env PATH="$PATH:/usr/bin" pm2 startup systemd -u "$MINER_USER" --hp "$HOME" >/dev/null 2>&1 || warn_msg "PM2 startup configuration skipped"

  pm2 update &>/dev/null || true
  success_msg "Node.js v${NODE_VERSION} and PM2 installed"
}

# ---------------------------------------------------------
# 4. Virtual Environment Setup
# ---------------------------------------------------------
setup_virtualenv() {
  info_msg "Setting up Python virtual environment..."

  if [[ ! -d "$VENV_DIR" ]]; then
    python3.11 -m venv "$VENV_DIR" || handle_error "Failed to create virtual environment"
  fi

  # shellcheck source=/dev/null
  source "$VENV_DIR/bin/activate" || handle_error "Virtual environment activation failed"

  python_version=$(python -V 2>&1)
  echo "$python_version" | grep -q "3.11" || handle_error "Python 3.11 not active in virtual environment"
  success_msg "Virtual environment activated with $python_version"
}

# ---------------------------------------------------------
# 5. Python Dependencies
# ---------------------------------------------------------
install_python_deps() {
  info_msg "Upgrading pip, setuptools, and wheel..."
  pip install --no-cache-dir --upgrade pip setuptools==70.0.0 wheel || handle_error "Python build tool upgrade failed"

  info_msg "Installing Python project requirements..."
  pip install --no-cache-dir -r requirements.txt || handle_error "Python dependencies installation failed"

  success_msg "Python dependencies installed"
}

# ---------------------------------------------------------
# 6. Application Setup
# ---------------------------------------------------------
setup_application() {
  # Install autoppia_iwa_module if present
  if [[ -d "autoppia_iwa_module" ]]; then
    info_msg "Installing autoppia_iwa_module..."
    (cd autoppia_iwa_module && pip install -e . >/dev/null) || handle_error "autoppia_iwa_module installation failed"
  fi

  info_msg "Installing main application in editable mode..."
  pip install -e . || handle_error "Main application installation failed"

  info_msg "Installing Bittensor..."
  pip install --no-cache-dir bittensor==9.6.0 bittensor-cli==9.4.1 || handle_error "Bittensor installation failed"

  success_msg "Application and Bittensor installed"
}

# ---------------------------------------------------------
# 7. Install Bittensor library & CLI (v9.6.0)
# ---------------------------------------------------------
install_bittensor() {
  echo -e "\e[34m[INFO]\e[0m Installing Bittensor library and CLI v9.6.0..."
  pip install bittensor==9.6.0 bittensor-cli==9.4.2\
    || handle_error "Failed to install Bittensor library and/or CLI"
  success_msg "Bittensor 9.6.0 and CLI installed."
}

# ---------------------------------------------------------
# Main execution flow
# ---------------------------------------------------------
main() {
  install_system_dependencies
  install_python311
  install_pm2
  setup_virtualenv
  install_python_deps
  setup_application

  echo -e "\n${GREEN}[MINER READY]${NC} Setup completed successfully!"
  echo -e "To activate the environment, run: ${YELLOW}source ${VENV_DIR}/bin/activate${NC}"
}

main "$@"
