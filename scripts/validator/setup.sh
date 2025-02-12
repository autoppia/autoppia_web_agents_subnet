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
  libsecret-1-dev libhyphen0 libflite1 libgles2-mesa libx264-dev || handle_error "Failed to install Python 3.11 and dependencies"

# ------------------------------------------------------------------
# Step 2: Install and Configure PM2
echo -e "\e[34m[INFO]\e[0m Installing and configuring PM2 service..."
sudo apt install -y npm || handle_error "Failed to install npm"
sudo npm install -g pm2 || handle_error "Failed to install PM2"
pm2 update || handle_error "Failed to update PM2"

# ------------------------------------------------------------------
# Step 3: Install uv (Python Virtual Environment Manager)
if ! command -v uv &> /dev/null; then
    echo -e "\e[34m[INFO]\e[0m Installing uv (Python package manager)..."
    curl -L https://astral.sh/uv/install.sh | sh || handle_error "Failed to install uv"
    export PATH="$HOME/.local/bin:$PATH"
    success_msg "uv installed successfully."
else
    echo -e "\e[32m[INFO]\e[0m uv is already installed. Skipping."
fi

# ------------------------------------------------------------------
# Step 4: Verify Python 3.11 Installation
echo -e "\e[34m[INFO]\e[0m Checking Python version..."
python3.11 --version || handle_error "Python 3.11 not found"

# ------------------------------------------------------------------
# Step 5: Create Virtual Environment using uv
echo -e "\e[34m[INFO]\e[0m Creating virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    uv venv --python=3.11 $VENV_DIR || handle_error "Failed to create virtual environment with uv"
    success_msg "Virtual environment created successfully."
else
    echo -e "\e[32m[INFO]\e[0m Virtual environment already exists. Skipping."
fi

# ------------------------------------------------------------------
# Step 6: Activate Virtual Environment
echo -e "\e[34m[INFO]\e[0m Activating virtual environment..."
source $VENV_DIR/bin/activate || handle_error "Failed to activate virtual environment"

# ------------------------------------------------------------------
# Step 7: Upgrade pip and setuptools
echo -e "\e[34m[INFO]\e[0m Upgrading pip and setuptools..."
python3.11 -m ensurepip
uv pip install --upgrade pip setuptools || handle_error "Failed to upgrade pip and setuptools"
success_msg "pip and setuptools upgraded successfully."

# ------------------------------------------------------------------
# Step 8: Install Python Dependencies
echo -e "\e[34m[INFO]\e[0m Installing Python dependencies..."
if ! uv pip install -r requirements.txt; then
    handle_error "Failed to install Python dependencies"
fi
success_msg "Python dependencies installed successfully."

# ------------------------------------------------------------------
# Step 9: Install autoppia_iwa Package
echo -e "\e[34m[INFO]\e[0m Installing autoppia_iwa package..."
if cd autoppia_iwa && uv pip install -e . && cd ..; then
    success_msg "autoppia_iwa package installed successfully."
else
    handle_error "Failed to install autoppia_iwa package"
fi

# ------------------------------------------------------------------
# Step 10: Install Bittensor
echo -e "\e[34m[INFO]\e[0m Installing Bittensor..."
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/opentensor/bittensor/v8.4.5/scripts/install.sh)" || handle_error "Failed to install Bittensor"
success_msg "Bittensor installed successfully."
