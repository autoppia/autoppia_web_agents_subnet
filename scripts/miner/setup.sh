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

# ------------------------------------------------------------------
# Step 0: Helper function to try installing a package or fallback
function try_install {
    local PKG="$1"
    local ALT="$2"  # alternative name if the primary is not found
    echo -e "\e[34m[INFO]\e[0m Attempting to install '$PKG'..."

    if apt-cache show "$PKG" &> /dev/null; then
        sudo apt-get install -y "$PKG" && return 0
    fi

    # If we have an alternative, try it if the primary fails
    if [ -n "$ALT" ]; then
        echo -e "\e[33m[WARN]\e[0m '$PKG' not found, trying alternative '$ALT'..."
        if apt-cache show "$ALT" &> /dev/null; then
            sudo apt-get install -y "$ALT" && return 0
        fi
    fi

    echo -e "\e[33m[WARN]\e[0m Neither '$PKG' nor '$ALT' could be installed on this system."
    return 1
}

# Variables
VENV_DIR="miner_env"  # Virtual environment directory

# ------------------------------------------------------------------
# Step 1: Install System Dependencies
echo -e "\e[34m[INFO]\e[0m Installing system dependencies..."
sudo apt update -y || handle_error "Failed to update package list"
sudo apt upgrade -y || handle_error "Failed to upgrade packages"
sudo apt install -y sudo || handle_error "Failed to install sudo"

# ------------------------------------------------------------------
# Step 2: Install Python 3.11 and essential dependencies
echo -e "\e[34m[INFO]\e[0m Installing Python 3.11 and dependencies..."

# We'll install each package with 'try_install' to handle variations:
# For example, on some systems 'sqlite3' is used instead of 'sqlite',
# 'libasound2t64' instead of 'libasound2', etc.

# Required base packages
try_install python3.11
try_install python3.11-venv
try_install python3.11-dev
try_install build-essential
try_install cmake
try_install wget

# SQLite fallback
try_install sqlite sqlite3

# Attempt libasound2 with fallback
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

# libgles2-mesa fallback
try_install libgles2-mesa libgl1-mesa-dev

# libx264-dev (video encoding)
try_install libx264-dev

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
    uv venv --python=3.11 "$VENV_DIR" || handle_error "Failed to create virtual environment with uv"
    success_msg "Virtual environment created successfully."
else
    echo -e "\e[32m[INFO]\e[0m Virtual environment already exists. Skipping."
fi

# ------------------------------------------------------------------
# Step 7: Activate Virtual Environment
echo -e "\e[34m[INFO]\e[0m Activating virtual environment..."
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate" || handle_error "Failed to activate virtual environment"

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
# Step 10: Install autoppia_iwa_module Package
echo -e "\e[34m[INFO]\e[0m Installing autoppia_iwa_module package..."
if cd autoppia_iwa_module && uv pip install -e . && cd ..; then
    success_msg "autoppia_iwa_module package installed successfully."
else
    handle_error "Failed to install autoppia_iwa_module package"
fi

# Also install the local package
uv pip install -e .

# ------------------------------------------------------------------
# Step 11: Install Bittensor
echo -e "\e[34m[INFO]\e[0m Installing Bittensor..."
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/opentensor/bittensor/v8.4.5/scripts/install.sh)" \
    || handle_error "Failed to install Bittensor"
success_msg "Bittensor installed successfully."
