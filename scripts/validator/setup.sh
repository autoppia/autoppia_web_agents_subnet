#!/bin/bash
# setup.sh - Setup environment dependencies for Validator

set -e  # Exit immediately on error

# Function to handle errors
function handle_error {
    echo -e "\e[31m[ERROR]\e[0m $1" >&2
    exit 1
}

# Function to print success messages
function success_msg {
    echo -e "\e[32m[SUCCESS]\e[0m $1"
}

# Variables
VENV_DIR="validator_env"  # Virtual environment directory

# ------------------------------------------------------------------
# Step 1: Install System Dependencies
echo -e "\e[34m[INFO]\e[0m Installing system dependencies..."
sudo apt update -y || handle_error "Failed to update package list"
sudo apt upgrade -y || handle_error "Failed to upgrade packages"
sudo apt install -y sudo || handle_error "Failed to install sudo"

# Install Python 3.11 and essential dependencies
echo -e "\e[34m[INFO]\e[0m Installing Python 3.11 and dependencies..."
sudo apt-get install -y \
  python3.11 python3.11-venv python3.11-dev build-essential cmake wget sqlite \
  libnss3 libnss3-dev libasound2 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libx11-xcb1 libxcomposite1 libxcursor1 libxdamage1 \
  libxrandr2 libgbm1 libpango-1.0-0 libatk-bridge2.0-0 libgtk-3-0 \
  libvpx-dev libevent-dev libopus0 libgstreamer1.0-0 unzip \
  libgstreamer-plugins-base1.0-0 libgstreamer-plugins-good1.0-0 \
  libgstreamer-plugins-bad1.0-0 libwebp-dev libharfbuzz-dev \
  libsecret-1-dev libhyphen0 libflite1 libgles2-mesa libx264-dev \
  gnupg curl || handle_error "Failed to install Python 3.11 and dependencies"

# ------------------------------------------------------------------
# Step 2: Install MongoDB (Optional - for web analysis caching)
echo -e "\e[34m[INFO]\e[0m Installing MongoDB for task caching..."
curl -fsSL https://pgp.mongodb.com/server-7.0.asc | \
   sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg \
   --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | \
    sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt-get update
sudo apt-get install -y mongodb-org
sudo systemctl start mongod
sudo systemctl enable mongod

# Create .env file with MongoDB URL
echo 'MONGODB_URL="mongodb://localhost:27017"' > .env

# ------------------------------------------------------------------
# Step 3: Install and Configure PM2
echo -e "\e[34m[INFO]\e[0m Installing and configuring PM2 service..."
sudo apt install -y npm || handle_error "Failed to install npm"
sudo npm install -g pm2 || handle_error "Failed to install PM2"
pm2 update || handle_error "Failed to update PM2"

# ------------------------------------------------------------------
# Step 4: Install uv (Python Virtual Environment Manager)
if ! command -v uv &> /dev/null; then
    echo -e "\e[34m[INFO]\e[0m Installing uv (Python package manager)..."
    curl -L https://astral.sh/uv/install.sh | sh || handle_error "Failed to install uv"
    export PATH="$HOME/.local/bin:$PATH"
    success_msg "uv installed successfully."
else
    echo -e "\e[32m[INFO]\e[0m uv is already installed. Skipping."
fi

# ------------------------------------------------------------------
# Step 5: Verify Python 3.11 Installation
echo -e "\e[34m[INFO]\e[0m Checking Python version..."
python3.11 --version || handle_error "Python 3.11 not found"

# ------------------------------------------------------------------
# Step 6: Create Virtual Environment using uv
echo -e "\e[34m[INFO]\e[0m Creating virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    uv venv --python=3.11 $VENV_DIR || handle_error "Failed to create virtual environment with uv"
    success_msg "Virtual environment created successfully."
else
    echo -e "\e[32m[INFO]\e[0m Virtual environment already exists. Skipping."
fi

# ------------------------------------------------------------------
# Step 7: Activate Virtual Environment
echo -e "\e[34m[INFO]\e[0m Activating virtual environment..."
source $VENV_DIR/bin/activate || handle_error "Failed to activate virtual environment"

# ------------------------------------------------------------------
# Step 8: Upgrade pip and setuptools
echo -e "\e[34m[INFO]\e[0m Upgrading pip and setuptools..."
python3.11 -m ensurepip
uv pip install --upgrade pip setuptools || handle_error "Failed to upgrade pip and setuptools"
success_msg "pip and setuptools upgraded successfully."

# ------------------------------------------------------------------
# Step 9: Install Python Dependencies
echo -e "\e[34m[INFO]\e[0m Installing Python dependencies..."
if ! uv pip install -r requirements.txt; then
    handle_error "Failed to install Python dependencies"
fi
success_msg "Python dependencies installed successfully."

# ------------------------------------------------------------------
# Step 10: Install autoppia_iwa Package
echo -e "\e[34m[INFO]\e[0m Installing autoppia_iwa package..."
if cd autoppia_iwa && uv pip install -e . && cd ..; then
    success_msg "autoppia_iwa package installed successfully."
else
    handle_error "Failed to install autoppia_iwa package"
fi
# Step 7: Install Google Chrome and ChromeDriver if not installed
echo "Checking for Chrome and ChromeDriver installation..."
if [ ! -f /opt/chrome/chrome-linux64/chrome ]; then
  echo "Installing Google Chrome and ChromeDriver..."

  # Download and install Chrome and ChromeDriver
  curl -SL https://storage.googleapis.com/chrome-for-testing-public/127.0.6533.72/linux64/chromedriver-linux64.zip > /tmp/chromedriver.zip || handle_error "Downloading ChromeDriver"
  curl -SL https://storage.googleapis.com/chrome-for-testing-public/127.0.6533.72/linux64/chrome-linux64.zip > /tmp/chrome.zip || handle_error "Downloading Chrome"
  unzip /tmp/chrome.zip -d /opt/chrome || handle_error "Unzipping Chrome"
  unzip /tmp/chromedriver.zip -d /opt/chromedriver || handle_error "Unzipping ChromeDriver"
  rm /tmp/chrome.zip /tmp/chromedriver.zip || handle_error "Cleaning up temporary files"

  # Set execute permissions for Chrome and ChromeDriver
  sudo chmod +x /opt/chrome/chrome-linux64/chrome || handle_error "Setting execute permission for Chrome"
  sudo chmod +x /opt/chromedriver/chromedriver-linux64/chromedriver || handle_error "Setting execute permission for ChromeDriver"
fi

# Step 8: Verify Chrome and ChromeDriver Installation
echo "Verifying Chrome installation..."
/opt/chrome/chrome-linux64/chrome --version || handle_error "Verifying Chrome installation"

echo "Verifying ChromeDriver installation..."
/opt/chromedriver/chromedriver-linux64/chromedriver --version || handle_error "Verifying ChromeDriver installation"

# ------------------------------------------------------------------
# Step 11: Install Bittensor
echo -e "\e[34m[INFO]\e[0m Installing Bittensor..."
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/opentensor/bittensor/v8.4.5/scripts/install.sh)" || handle_error "Failed to install Bittensor"
success_msg "Bittensor installed successfully."

echo -e "\e[32m[COMPLETE]\e[0m Setup completed successfully!"