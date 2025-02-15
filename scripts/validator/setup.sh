#!/bin/bash
# setup.sh - Setup environment dependencies for Validator

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

  # Detect Ubuntu codename and set dependencies accordingly.
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
    # Replace libasound2 with libasound2t64 as recommended.
    DEP_PACKAGES=(python3.11 python3.11-venv python3.11-dev build-essential cmake wget sqlite3 \
      libnss3 libnss3-dev libasound2t64 libatk1.0-0 libatk-bridge2.0-0 libcups2 libx11-xcb1 \
      libxcomposite1 libxcursor1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libgtk-3-0 \
      libvpx-dev libevent-dev libopus0 libgstreamer1.0-0 unzip \
      libgstreamer-plugins-base1.0-0 libgstreamer-plugins-good1.0-0 libgstreamer-plugins-bad1.0-0 \
      libwebp-dev libharfbuzz-dev libsecret-1-dev libhyphen0 libflite1 libgles2-mesa-dev \
      libx264-dev gnupg curl)
  else
    # Default dependency list (adjust as necessary for other Ubuntu versions)
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

install_python311() {
  echo -e "\e[34m[INFO]\e[0m Verifying Python 3.11 installation..."
  python3.11 --version || handle_error "Python 3.11 not found"
}

install_pm2() {
  echo -e "\e[34m[INFO]\e[0m Installing PM2..."
  sudo apt install -y npm || handle_error "Failed to install npm"
  sudo npm install -g pm2 || handle_error "Failed to install PM2"
  pm2 update || handle_error "Failed to update PM2"
}

install_uv() {
  echo -e "\e[34m[INFO]\e[0m Installing uv (Python Venv Manager) if not present..."
  if ! command -v uv &> /dev/null; then
    curl -L https://astral.sh/uv/install.sh | sh || handle_error "Failed to install uv"
    export PATH="$HOME/.local/bin:$PATH"
    success_msg "uv installed successfully."
  else
    echo -e "\e[32m[INFO]\e[0m uv is already installed. Skipping."
  fi
}

install_mongodb() {
  echo -e "\e[34m[INFO]\e[0m Installing MongoDB for task caching..."
  curl -fsSL https://pgp.mongodb.com/server-7.0.asc | sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor || handle_error "Failed to import MongoDB GPG key"
  echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu $(lsb_release -cs)/mongodb-org/7.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list || handle_error "Failed to add MongoDB repository"
  sudo apt-get update -y || handle_error "Failed to update package list after adding MongoDB repo"
  sudo apt-get install -y mongodb-org || handle_error "Failed to install MongoDB"
  
  if command -v systemctl &> /dev/null && [ -d /run/systemd/system ]; then
    sudo systemctl start mongod || handle_error "Failed to start MongoDB via systemctl"
    sudo systemctl enable mongod || handle_error "Failed to enable MongoDB via systemctl"
  else
    echo -e "\e[34m[INFO]\e[0m Starting MongoDB manually..."
    sudo mkdir -p /var/lib/mongodb
    sudo chown -R mongodb:mongodb /var/lib/mongodb 2>/dev/null || true
    mongod --fork --logpath /var/log/mongod.log --dbpath /var/lib/mongodb || handle_error "Failed to start MongoDB manually"
  fi

  if [ ! -f .env ]; then
    echo 'MONGODB_URL="mongodb://localhost:27017"' > .env || handle_error "Failed to create .env file"
  fi
  success_msg "MongoDB installed and configured successfully"
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

create_and_activate_venv() {
  VENV_DIR="validator_env"
  echo -e "\e[34m[INFO]\e[0m Creating virtual environment..."
  if [ ! -d "$VENV_DIR" ]; then
    uv venv --python=3.11 "$VENV_DIR" || handle_error "Failed to create virtual environment with uv"
    success_msg "Virtual environment created successfully."
  else
    echo -e "\e[32m[INFO]\e[0m Virtual environment already exists. Skipping."
  fi

  echo -e "\e[34m[INFO]\e[0m Activating virtual environment..."
  source "$VENV_DIR/bin/activate" || handle_error "Failed to activate virtual environment"
}

upgrade_pip_setuptools() {
  echo -e "\e[34m[INFO]\e[0m Upgrading pip and setuptools..."
  python3.11 -m ensurepip
  uv pip install --upgrade pip setuptools || handle_error "Failed to upgrade pip and setuptools"
  success_msg "pip and setuptools upgraded successfully."
}

install_python_requirements() {
  echo -e "\e[34m[INFO]\e[0m Installing Python dependencies and Playwright..."
  uv pip install -r requirements.txt || handle_error "Failed to install Python dependencies"
  
  if ! python3.11 -m pip show playwright > /dev/null 2>&1; then
    echo -e "\e[34m[INFO]\e[0m Installing Playwright..."
    python3.11 -m pip install playwright || handle_error "Failed to install Playwright"
  fi
  
  python3.11 -m playwright install || handle_error "Failed to install Playwright"
  playwright install-deps || handle_error "Failed to install Playwright dependencies"
  success_msg "Python dependencies and Playwright installed successfully."
}

install_autoppia_iwa_module() {
  echo -e "\e[34m[INFO]\e[0m Installing autoppia_iwa module..."
  if cd autoppia_iwa_module && uv pip install -e . && cd ..; then
    success_msg "autoppia_iwa_module installed successfully."
  else
    handle_error "Failed to install autoppia_iwa module"
  fi
}

install_bittensor() {
  echo -e "\e[34m[INFO]\e[0m Installing Bittensor..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/opentensor/bittensor/v8.4.5/scripts/install.sh)" || handle_error "Failed to install Bittensor"
  success_msg "Bittensor installed successfully."
}

main() {
  install_system_dependencies
  install_python311
  install_pm2
  install_uv
  install_mongodb
  install_chrome_and_chromedriver

  echo -e "\e[34m[INFO]\e[0m Checking Python version..."
  python3.11 --version || handle_error "Python 3.11 not found"

  create_and_activate_venv
  upgrade_pip_setuptools
  install_python_requirements
  install_autoppia_iwa_module
  install_bittensor

  echo -e "\e[34m[INFO]\e[0m Verifying installations..."
  echo "Chrome version:"
  /opt/chrome/chrome-linux64/chrome --version || echo "Chrome not found"
  echo "ChromeDriver version:"
  /opt/chromedriver/chromedriver-linux64/chromedriver --version || echo "ChromeDriver not found"
  echo "MongoDB version:"
  mongod --version || echo "MongoDB not found"
  
  success_msg "Setup completed successfully!"
}

main "$@"
