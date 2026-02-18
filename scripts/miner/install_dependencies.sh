#!/bin/bash
# install_dependencies.sh - Install ONLY system dependencies for miner runtime
set -euo pipefail

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

install_system_dependencies() {
  info_msg "Updating apt package lists..."
  sudo apt update -y || handle_error "Failed to update apt lists"

  info_msg "Installing core tools..."
  sudo apt install -y sudo software-properties-common lsb-release curl git \
    || handle_error "Failed to install core tools"

  info_msg "Adding Python 3.11 PPA..."
  sudo add-apt-repository ppa:deadsnakes/ppa -y \
    || handle_error "Failed to add Python PPA"
  sudo apt update -y || handle_error "Failed to refresh apt lists"

  # Minimal runtime deps: miner only responds to round handshake metadata.
  info_msg "Installing minimal miner runtime dependencies..."
  sudo apt install -y python3.11 python3.11-venv python3.11-dev build-essential \
    || handle_error "Failed to install miner runtime dependencies"
}

install_pm2() {
  if command -v pm2 &>/dev/null; then
    info_msg "PM2 is already installed. Skipping."
  else
    info_msg "Installing PM2..."
    sudo apt install -y npm || handle_error "Failed to install npm"
    sudo npm install -g pm2 || handle_error "Failed to install PM2"
    pm2 update || handle_error "Failed to update PM2"
  fi
}

verify_installation() {
  info_msg "Verifying system dependencies..."

  # Check Python
  python3.11 --version || handle_error "Python 3.11 verification failed"

  # Check PM2
  pm2 --version || handle_error "PM2 verification failed"

  success_msg "System dependencies verification passed"
}

main() {
  info_msg "Installing miner system dependencies..."
  install_system_dependencies
  install_pm2
  verify_installation

  success_msg "System dependencies installed successfully!"
  echo -e "\e[33m[NEXT]\e[0m Run: ./scripts/miner/setup.sh"
}

main "$@"
