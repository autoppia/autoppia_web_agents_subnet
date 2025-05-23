#!/bin/bash
#
# setup.sh - Setup environment dependencies for Validator
#
# This script installs and configures:
#  - System dependencies
#  - Python 3.11 (via deadsnakes PPA)
#  - Node.js 18.x and PM2
#  - A virtual environment using python3.11 -m venv
#  - Your project's Python requirements
#  - autoppia_iwa (editable)
#  - Bittensor library & CLI (v9.6.0)

set -e  # Exit immediately on error

# ---------------------------------------------------------
# Error Handling and Helpers
# ---------------------------------------------------------
handle_error() {
  echo -e "\e[31m[ERROR]\e[0m $1" >&2
  exit 1
}

success_msg() {
  echo -e "\e[32m[SUCCESS]\e[0m $1"
}

# ---------------------------------------------------------
# 1. System Dependencies
# ---------------------------------------------------------
install_system_dependencies() {
  echo -e "\e[34m[INFO]\e[0m Installing system dependencies..."
  sudo apt update || echo -e "\e[33m[WARN]\e[0m 'apt update' failed, continuing..."
  sudo apt upgrade -y || echo -e "\e[33m[WARN]\e[0m 'apt upgrade' failed, continuing..."
  sudo apt install -y \
    sudo software-properties-common curl git build-essential \
    cmake wget unzip \
    || handle_error "Could not install basic system dependencies"
  success_msg "System dependencies installed."
}

# ---------------------------------------------------------
# 2. Python 3.11 and Libraries
# ---------------------------------------------------------
install_python311() {
  echo -e "\e[34m[INFO]\e[0m Adding deadsnakes PPA and installing Python 3.11..."
  sudo add-apt-repository -y ppa:deadsnakes/ppa || handle_error "Failed to add deadsnakes PPA"
  sudo apt update || handle_error "Failed to update apt repositories"
  sudo apt install -y \
    python3.11 python3.11-venv python3.11-dev sqlite3 \
    libasound2 libnss3 libnss3-dev \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libx11-xcb1 libxcomposite1 libxcursor1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libgtk-3-0 \
    libvpx-dev libevent-dev libopus0 \
    libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 libgstreamer-plugins-good1.0-0 libgstreamer-plugins-bad1.0-0 \
    libwebp-dev libharfbuzz-dev libsecret-1-dev libhyphen0 libflite1 \
    libgles2-mesa libgl1-mesa-dev libx264-dev \
    || handle_error "Could not install Python 3.11 and related libraries"
  success_msg "Python 3.11 and its libraries installed."
}

# ---------------------------------------------------------
# 3. Node.js 18.x and PM2
# ---------------------------------------------------------
install_pm2() {
  echo -e "\e[34m[INFO]\e[0m Installing Node.js 18.x and PM2..."
  curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash - || handle_error "Failed to configure NodeSource repo"
  sudo apt install -y nodejs || handle_error "Could not install Node.js"
  sudo npm install -g pm2 || handle_error "Could not install PM2"
  pm2 update || handle_error "Failed to update PM2"
  # Configure PM2 to start on boot
  sudo env PATH="$PATH" pm2 startup systemd -u "$(whoami)" --hp "$HOME" \
    || handle_error "Failed to configure PM2 startup"
  success_msg "Node.js and PM2 configured."
}

# ---------------------------------------------------------
# 4. Create and activate virtual environment with python -m venv
# ---------------------------------------------------------
create_and_activate_venv() {
  local VENV_DIR="miner_env"
  echo -e "\e[34m[INFO]\e[0m Creating virtual environment with python3.11 in '$VENV_DIR'..."
  if [ ! -d "$VENV_DIR" ]; then
    python3.11 -m venv "$VENV_DIR" || handle_error "Failed to create virtual environment"
    success_msg "Virtual environment created."
  else
    echo -e "\e[32m[INFO]\e[0m Virtual environment already exists, reusing."
  fi
  echo -e "\e[34m[INFO]\e[0m Activating virtual environment..."
  # shellcheck source=/dev/null
  source "$VENV_DIR/bin/activate" || handle_error "Failed to activate virtual environment"
}

# ---------------------------------------------------------
# 5. Install Python dependencies (pip + requirements.txt)
# ---------------------------------------------------------
install_python_requirements() {
  echo -e "\e[34m[INFO]\e[0m Upgrading pip and setuptools..."
  pip install --upgrade pip setuptools || handle_error "Failed to upgrade pip/setuptools"
  echo -e "\e[34m[INFO]\e[0m Installing Python requirements..."
  pip install -r requirements.txt || handle_error "Failed to install requirements.txt"
  success_msg "Python dependencies installed."
}

# ---------------------------------------------------------
# 6. Install autoppia_iwa in editable mode
# ---------------------------------------------------------
install_autoppia_iwa() {
  echo -e "\e[34m[INFO]\e[0m Installing autoppia_iwa dependencies..."
  pip install loguru numpy pydantic pytest rich || handle_error "Failed to install autoppia_iwa deps"
  echo -e "\e[34m[INFO]\e[0m Installing autoppia_iwa_module..."
  if [ -d autoppia_iwa_module ]; then
    (cd autoppia_iwa_module && pip install -e .) || handle_error "Failed to install autoppia_iwa_module"
    success_msg "autoppia_iwa_module installed."
  else
    echo -e "\e[33m[WARN]\e[0m Directory autoppia_iwa_module not found, skipping."
  fi
  echo -e "\e[34m[INFO]\e[0m Installing main package in editable mode..."
  pip install -e . || handle_error "Failed to install main package"
  success_msg "autoppia_iwa installed in editable mode."
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

  echo -e "\e[34m[INFO]\e[0m Checking installed Python version..."
  python3.11 --version || handle_error "Python 3.11 not found"

  create_and_activate_venv
  install_python_requirements
  install_autoppia_iwa
  install_bittensor

  echo -e "\n\e[32m[ALL DONE]\e[0m Validator environment setup complete."
}

main "$@"
