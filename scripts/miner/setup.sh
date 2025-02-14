#!/bin/bash
#
# setup.sh - Setup environment dependencies for Validator
#
# This script is divided into functional sections to group related setup steps.
# Each function explains what it's installing or configuring.

set -e  # Exit immediately on error

# ---------------------------------------------------------
# Error Handling and Helpers
# ---------------------------------------------------------

# Handles errors by printing a message and exiting.
handle_error() {
  echo -e "\e[31m[ERROR]\e[0m $1" >&2
  exit 1
}

# Prints success messages in green.
success_msg() {
  echo -e "\e[32m[SUCCESS]\e[0m $1"
}

# Attempts to install a package and (optionally) an alternative name.
try_install() {
  local PKG="$1"
  local ALT="$2"
  echo -e "\e[34m[INFO]\e[0m Attempting to install '$PKG'..."
  if apt-cache show "$PKG" &>/dev/null; then
    sudo apt-get install -y "$PKG" && return 0
  fi

  if [ -n "$ALT" ]; then
    echo -e "\e[33m[WARN]\e[0m '$PKG' not found, trying alternative '$ALT'..."
    if apt-cache show "$ALT" &>/dev/null; then
      sudo apt-get install -y "$ALT" && return 0
    fi
  fi

  echo -e "\e[33m[WARN]\e[0m Neither '$PKG' nor '$ALT' is available on this system."
  return 1
}

# ---------------------------------------------------------
# Section 1: System Dependencies
# Updates apt, upgrades packages, installs sudo, etc.
# ---------------------------------------------------------
install_system_dependencies() {
  echo -e "\e[34m[INFO]\e[0m Installing system dependencies..."
  sudo apt update -y || handle_error "Failed to update package list"
  sudo apt upgrade -y || handle_error "Failed to upgrade packages"
  sudo apt install -y sudo || handle_error "Failed to install sudo"
}

# ---------------------------------------------------------
# Section 2: Python 3.11 and Libraries
# Installs Python 3.11, dev tools, cmake, fallback for sqlite, etc.
# ---------------------------------------------------------
install_python311() {
  echo -e "\e[34m[INFO]\e[0m Installing Python 3.11 and dependencies..."
  try_install python3.11
  try_install python3.11-venv
  try_install python3.11-dev
  try_install build-essential
  try_install cmake
  try_install wget
  # SQLite fallback
  try_install sqlite sqlite3
  # Audio library fallback
  try_install libasound2 libasound2t64
  # Additional libs
  try_install libnss3
  try_install libnss3-dev
  try_install libatk1.0-0 libatk1.0-0t64
  try_install libatk-bridge2.0-0 libatk-bridge2.0-0t64
  try_install libcups2 libcups2t64
  try_install libx11-xcb1
  try_install libxcomposite1
  try_install libxcursor1
  try_install libxdamage1
  try_install libxrandr2
  try_install libgbm1
  try_install libpango-1.0-0
  try_install libgtk-3-0 libgtk-3-0t64
  try_install libvpx-dev
  try_install libevent-dev
  try_install libopus0
  try_install libgstreamer1.0-0
  try_install unzip
  try_install libgstreamer-plugins-base1.0-0
  try_install libgstreamer-plugins-good1.0-0
  try_install libgstreamer-plugins-bad1.0-0
  try_install libwebp-dev
  try_install libharfbuzz-dev
  try_install libsecret-1-dev
  try_install libhyphen0
  try_install libflite1
  # Mesa fallback
  try_install libgles2-mesa libgl1-mesa-dev
  # Video encoding
  try_install libx264-dev
}

# ---------------------------------------------------------
# Section 3: PM2 Node.js Process Manager
# Installs npm and pm2 globally, ensures pm2 is updated.
# ---------------------------------------------------------
install_pm2() {
  echo -e "\e[34m[INFO]\e[0m Installing and configuring PM2 service..."
  sudo apt install -y npm || handle_error "Failed to install npm"
  sudo npm install -g pm2 || handle_error "Failed to install PM2"
  pm2 update || handle_error "Failed to update PM2"
}

# ---------------------------------------------------------
# Section 4: UV Python Environment Manager
# Installs uv if not present, sets path.
# ---------------------------------------------------------
install_uv() {
  if ! command -v uv &>/dev/null; then
    echo -e "\e[34m[INFO]\e[0m Installing uv (Python package manager)..."
    curl -L https://astral.sh/uv/install.sh | sh || handle_error "Failed to install uv"
    export PATH="$HOME/.local/bin:$PATH"
    success_msg "uv installed successfully."
  else
    echo -e "\e[32m[INFO]\e[0m uv is already installed. Skipping."
  fi
}

# ---------------------------------------------------------
# Section 5: Virtual Environment Setup
# Creates a new venv with Python 3.11, then activates it.
# ---------------------------------------------------------
create_and_activate_venv() {
  local VENV_DIR="miner_env"
  echo -e "\e[34m[INFO]\e[0m Creating virtual environment..."
  if [ ! -d "$VENV_DIR" ]; then
    uv venv --python=3.11 "$VENV_DIR" || handle_error "Failed to create virtual environment with uv"
    success_msg "Virtual environment created successfully."
  else
    echo -e "\e[32m[INFO]\e[0m Virtual environment already exists. Skipping."
  fi

  echo -e "\e[34m[INFO]\e[0m Activating virtual environment..."
  # shellcheck source=/dev/null
  source "$VENV_DIR/bin/activate" || handle_error "Failed to activate virtual environment"
}

# ---------------------------------------------------------
# Section 6: Upgrade PIP/Setuptools
# Ensures pip/setuptools are up-to-date in the new venv.
# ---------------------------------------------------------
upgrade_pip_setuptools() {
  echo -e "\e[34m[INFO]\e[0m Upgrading pip and setuptools..."
  python3.11 -m ensurepip
  uv pip install --upgrade pip setuptools || handle_error "Failed to upgrade pip and setuptools"
  success_msg "pip and setuptools upgraded successfully."
}

# ---------------------------------------------------------
# Section 7: Install Python Requirements
# Installs project dependencies from requirements.txt.
# ---------------------------------------------------------
install_python_requirements() {
  echo -e "\e[34m[INFO]\e[0m Installing Python dependencies..."
  if ! uv pip install -r requirements.txt; then
    handle_error "Failed to install Python dependencies"
  fi
  success_msg "Python dependencies installed successfully."
}

# ---------------------------------------------------------
# Section 8: Install autoppia_iwa_module
# Installs the submodule in editable mode.
# ---------------------------------------------------------
install_autoppia_iwa_module() {
  echo -e "\e[34m[INFO]\e[0m Installing autoppia_iwa_module package..."
  if cd autoppia_iwa_module && uv pip install -e . && cd ..; then
    success_msg "autoppia_iwa_module package installed successfully."
  else
    handle_error "Failed to install autoppia_iwa_module package"
  fi
  uv pip install -e .
}

# ---------------------------------------------------------
# Section 9: Install Bittensor
# Uses the official install script for Bittensor.
# ---------------------------------------------------------
install_bittensor() {
  echo -e "\e[34m[INFO]\e[0m Installing Bittensor..."
  git clone git clone https://github.com/opentensor/bittensor.git && cd bittensor && pip install . && pip install bittensor==9.0.0 && cd .. && rm -rf bittensor
  success_msg "Bittensor installed successfully."
}

# ---------------------------------------------------------
# Main Execution Flow
# ---------------------------------------------------------
main() {
  install_system_dependencies
  install_python311
  install_pm2
  install_uv

  # Verify Python 3.11 is installed
  echo -e "\e[34m[INFO]\e[0m Checking Python version..."
  python3.11 --version || handle_error "Python 3.11 not found"

  create_and_activate_venv
  upgrade_pip_setuptools
  install_python_requirements
  install_autoppia_iwa_module
  install_bittensor
}

main "$@"
