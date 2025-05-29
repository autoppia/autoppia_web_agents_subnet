#!/bin/bash
# install_dependencies.sh - Install Linux system dependencies

set -e

handle_error() {
  echo -e "\e[31m[ERROR]\e[0m $1" >&2
  exit 1
}

success_msg() {
  echo -e "\e[32m[SUCCESS]\e[0m $1"
}

install_system_dependencies() {
  echo -e "\e[34m[INFO]\e[0m Updating packages..."
  sudo apt update -y || handle_error "Failed to update package list"
  sudo apt upgrade -y || handle_error "Failed to upgrade packages"
  sudo apt install -y sudo software-properties-common || handle_error "Failed to install sudo and software-properties-common"

  echo -e "\e[34m[INFO]\e[0m Adding Python 3.11 repository..."
  sudo add-apt-repository ppa:deadsnakes/ppa -y || handle_error "Failed to add Python repository"
  sudo apt update -y || handle_error "Failed to update package list after adding Python repo"

  UBUNTU_CODENAME=$(lsb_release -cs)
  if [[ "$UBUNTU_CODENAME" == "jammy" ]]; then
    DEP_PACKAGES=(python3.11 python3.11-venv python3.11-dev build-essential cmake wget sqlite3 \
      libnss3 libnss3-dev libasound2 libatk1.0-0 libatk-bridge2.0-0 libcups2 libx11-xcb1 \
      libxcomposite1 libxcursor1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libgtk-3-0 \
      libvpx-dev libevent-dev libopus0 libgstreamer1.0-0 unzip \
      libgstreamer-plugins-base1.0-0 libgstreamer-plugins-good1.0-0 libgstreamer-plugins-bad1.0-0 \
      libwebp-dev libharfbuzz-dev libsecret-1-dev libhyphen0 libflite1 libgles2-mesa-dev \
      libx264-dev gnupg curl)
  elif [[ "$UBUNTU_CODENAME" == "noble" ]]; then
    DEP_PACKAGES=(python3.11 python3.11-venv python3.11-dev build-essential cmake wget sqlite3 \
      libnss3 libnss3-dev libasound2t64 libatk1.0-0 libatk-bridge2.0-0 libcups2 libx11-xcb1 \
      libxcomposite1 libxcursor1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libgtk-3-0 \
      libvpx-dev libevent-dev libopus0 libgstreamer1.0-0 unzip \
      libgstreamer-plugins-base1.0-0 libgstreamer-plugins-good1.0-0 libgstreamer-plugins-bad1.0-0 \
      libwebp-dev libharfbuzz-dev libsecret-1-dev libhyphen0 libflite1 libgles2-mesa-dev \
      libx264-dev gnupg curl)
  else
    DEP_PACKAGES=(python3.11 python3.11-venv python3.11-dev build-essential cmake wget sqlite3 \
      libnss3 libnss3-dev libasound2 libatk1.0-0 libatk-bridge2.0-0 libcups2 libx11-xcb1 \
      libxcomposite1 libxcursor1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libgtk-3-0 \
      libvpx-dev libevent-dev libopus0 libgstreamer1.0-0 unzip \
      libgstreamer-plugins-base1.0-0 libgstreamer-plugins-good1.0-0 libgstreamer-plugins-bad1.0-0 \
      libwebp-dev libharfbuzz-dev libsecret-1-dev libhyphen0 libflite1 libgles2-mesa-dev \
      libx264-dev gnupg curl)
  fi

  echo -e "\e[34m[INFO]\e[0m Installing system dependencies..."
  sudo apt-get install -y "${DEP_PACKAGES[@]}" || handle_error "Failed to install dependencies"
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

install_chrome_and_chromedriver() {
  echo -e "\e[34m[INFO]\e[0m Installing Chrome and ChromeDriver..."
  if [ ! -f /opt/chrome/chrome-linux64/chrome ]; then
    curl -SL https://storage.googleapis.com/chrome-for-testing-public/127.0.6533.72/linux64/chromedriver-linux64.zip -o /tmp/chromedriver.zip || handle_error "Failed downloading ChromeDriver"
    curl -SL https://storage.googleapis.com/chrome-for-testing-public/127.0.6533.72/linux64/chrome-linux64.zip -o /tmp/chrome.zip || handle_error "Failed downloading Chrome"
    
    sudo mkdir -p /opt/chrome /opt/chromedriver
    sudo unzip /tmp/chrome.zip -d /opt/chrome || handle_error "Failed unzipping Chrome"
    sudo unzip /tmp/chromedriver.zip -d /opt/chromedriver || handle_error "Failed unzipping ChromeDriver"
    rm /tmp/chrome.zip /tmp/chromedriver.zip

    sudo chmod +x /opt/chrome/chrome-linux64/chrome || handle_error "Failed setting Chrome permissions"
    sudo chmod +x /opt/chromedriver/chromedriver-linux64/chromedriver || handle_error "Failed setting ChromeDriver permissions"
    success_msg "Chrome and ChromeDriver installed successfully"
  else
    echo -e "\e[32m[INFO]\e[0m Chrome is already installed. Skipping."
  fi
}

main() {
  install_system_dependencies
  install_pm2
#  install_chrome_and_chromedriver
  success_msg "System dependencies installed successfully!"
}

main "$@"
