#!/bin/bash
# install_dependencies.sh
# Install only system (APT) dependencies and PM2. Does NOT touch virtualenv or Playwright.

set -e

handle_error() {
  echo -e "\e[31m[ERROR]\e[0m $1" >&2
  exit 1
}

success_msg() {
  echo -e "\e[32m[SUCCESS]\e[0m $1"
}

install_system_dependencies() {
  echo -e "\e[34m[INFO]\e[0m Updating apt package lists..."
  sudo apt update -y || handle_error "Failed to update apt lists"
  sudo apt upgrade -y || handle_error "Failed to upgrade packages"
  
  echo -e "\e[34m[INFO]\e[0m Installing core tools..."
  sudo apt install -y sudo software-properties-common lsb-release \
    || handle_error "Failed to install core tools"
  
  echo -e "\e[34m[INFO]\e[0m Adding Python 3.11 PPA..."
  sudo add-apt-repository ppa:deadsnakes/ppa -y \
    || handle_error "Failed to add Python PPA"
  sudo apt update -y || handle_error "Failed to refresh apt lists"
  
  # Common packages for all Ubuntu versions
  COMMON_PACKAGES=(
    python3.11 python3.11-venv python3.11-dev
    build-essential cmake wget unzip sqlite3
    libnss3 libnss3-dev
    libatk1.0-0 libatk-bridge2.0-0 libcups2
    libx11-xcb1 libxcomposite1 libxcursor1 libxdamage1 libxrandr2
    libgbm1 libpango-1.0-0 libgtk-3-0
    libvpx-dev libevent-dev libopus0
    libgstreamer1.0-0
    libgstreamer-plugins-base1.0-0 libgstreamer-plugins-good1.0-0 libgstreamer-plugins-bad1.0-0
    libwebp-dev libharfbuzz-dev libsecret-1-dev libhyphen0 libflite1 libgles2-mesa-dev
    libx264-dev gnupg curl
  )
  
  # Add version-specific audio package
  UBUNTU_CODENAME=$(lsb_release -cs)
  case "$UBUNTU_CODENAME" in
    jammy)  EXTRA_PACKAGES=(libasound2)   ;;
    noble)  EXTRA_PACKAGES=(libasound2t64) ;;
    *)      EXTRA_PACKAGES=(libasound2)   ;;
  esac
  
  echo -e "\e[34m[INFO]\e[0m Installing apt dependencies for $UBUNTU_CODENAME..."
  sudo apt install -y "${COMMON_PACKAGES[@]}" "${EXTRA_PACKAGES[@]}" \
    || handle_error "Failed to install apt dependencies"
}

install_pm2() {
  if command -v pm2 &>/dev/null; then
    echo -e "\e[32m[INFO]\e[0m PM2 is already installed. Skipping."
  else
    echo -e "\e[34m[INFO]\e[0m Installing PM2..."
    sudo apt install -y npm || handle_error "Failed to install npm"
    sudo npm install -g pm2 || handle_error "Failed to install PM2"
    pm2 update || handle_error "Failed to update PM2"
  fi
}

main() {
  install_system_dependencies
  install_pm2
  success_msg "System dependencies installed successfully."
  echo -e "\e[33m[NEXT]\e[0m Run: ./scripts/validator/setup.sh"
}

main "$@"
