#!/bin/bash
# setup.sh - Setup environment dependencies for Validator

set -e  # Exit immediately on error

handle_error() {
  echo -e "\e[31m[ERROR]\e[0m $1" >&2
  exit 1
}

success_msg() {
  echo -e "\e[32m[SUCCESS]\e[0m $1"
}

VENV_DIR="validator_env"  # Virtual environment directory

# ------------------------------------------------------------------
# Step 1: Install System Dependencies
echo -e "\e[34m[INFO]\e[0m Installing system dependencies..."
apt update -y || handle_error "Failed to update package list"
apt upgrade -y || handle_error "Failed to upgrade packages"
apt install -y software-properties-common || handle_error "Failed to install software-properties-common"

echo -e "\e[34m[INFO]\e[0m Adding Python 3.11 repository..."
add-apt-repository ppa:deadsnakes/ppa -y || handle_error "Failed to add Python repository"
apt update || handle_error "Failed to update package list after adding Python repo"

echo -e "\e[34m[INFO]\e[0m Installing Python 3.11 and browser dependencies..."
apt-get install -y \
  python3.11 python3.11-venv python3.11-dev build-essential cmake wget sqlite3 \
  libnss3 libnss3-dev libasound2 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libx11-xcb1 libxcomposite1 libxcursor1 libxdamage1 \
  libxrandr2 libgbm1 libpango-1.0-0 libatk-bridge2.0-0 libgtk-3-0 \
  libvpx-dev libevent-dev libopus0 libgstreamer1.0-0 unzip \
  libgstreamer-plugins-base1.0-0 libgstreamer-plugins-good1.0-0 \
  libgstreamer-plugins-bad1.0-0 libwebp-dev libharfbuzz-dev \
  libsecret-1-dev libhyphen0 libflite1 libgles2-mesa libx264-dev \
  gnupg curl || handle_error "Failed to install dependencies"

# ------------------------------------------------------------------
# Step 2: Install MongoDB (Optional - for task caching)
echo -e "\e[34m[INFO]\e[0m Installing MongoDB for task caching..."
curl -fsSL https://pgp.mongodb.com/server-7.0.asc | \
   gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor || handle_error "Failed to import MongoDB GPG key"

echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | \
    tee /etc/apt/sources.list.d/mongodb-org-7.0.list || handle_error "Failed to add MongoDB repository"

apt-get update || handle_error "Failed to update package list after adding MongoDB repo"
apt-get install -y mongodb-org || handle_error "Failed to install MongoDB"

mkdir -p /var/lib/mongodb
chown -R mongodb:mongodb /var/lib/mongodb 2>/dev/null || true

# Start MongoDB - if systemd exists use systemctl, otherwise start manually.
if command -v systemctl &> /dev/null && [ -d /run/systemd/system ]; then
    systemctl start mongod || handle_error "Failed to start MongoDB via systemctl"
    systemctl enable mongod || handle_error "Failed to enable MongoDB via systemctl"
else
    echo -e "\e[34m[INFO]\e[0m Starting MongoDB manually..."
    # Ensure log file exists and is writable.
    touch /var/log/mongod.log || handle_error "Failed to create MongoDB log file"
    chown mongodb:mongodb /var/log/mongod.log 2>/dev/null || true
    # Start with additional options.
    mongod --fork --logpath /var/log/mongod.log --dbpath /var/lib/mongodb --bind_ip 127.0.0.1 || handle_error "Failed to start MongoDB manually"
fi

if [ ! -f .env ]; then
    echo 'MONGODB_URL="mongodb://localhost:27017"' > .env || handle_error "Failed to create .env file"
fi

success_msg "MongoDB installed and configured successfully"

# ------------------------------------------------------------------
# Step 3: Install Chrome and ChromeDriver
echo -e "\e[34m[INFO]\e[0m Installing Chrome and ChromeDriver..."
if [ ! -f /opt/chrome/chrome-linux64/chrome ]; then
    curl -SL https://storage.googleapis.com/chrome-for-testing-public/127.0.6533.72/linux64/chromedriver-linux64.zip > /tmp/chromedriver.zip || handle_error "Failed downloading ChromeDriver"
    curl -SL https://storage.googleapis.com/chrome-for-testing-public/127.0.6533.72/linux64/chrome-linux64.zip > /tmp/chrome.zip || handle_error "Failed downloading Chrome"
    
    mkdir -p /opt/chrome /opt/chromedriver
    unzip /tmp/chrome.zip -d /opt/chrome || handle_error "Failed unzipping Chrome"
    unzip /tmp/chromedriver.zip -d /opt/chromedriver || handle_error "Failed unzipping ChromeDriver"
    rm /tmp/chrome.zip /tmp/chromedriver.zip

    chmod +x /opt/chrome/chrome-linux64/chrome || handle_error "Failed setting Chrome permissions"
    chmod +x /opt/chromedriver/chromedriver-linux64/chromedriver || handle_error "Failed setting ChromeDriver permissions"
    
    success_msg "Chrome and ChromeDriver installed successfully"
fi

# ------------------------------------------------------------------
# Step 4: Install and Configure PM2
echo -e "\e[34m[INFO]\e[0m Installing and configuring PM2 service..."
apt install -y npm || handle_error "Failed to install npm"
npm install -g pm2 || handle_error "Failed to install PM2"
pm2 update || handle_error "Failed to update PM2"

# ------------------------------------------------------------------
# Step 5: Install uv (Python Virtual Environment Manager)
if ! command -v uv &> /dev/null; then
    echo -e "\e[34m[INFO]\e[0m Installing uv (Python package manager)..."
    curl -L https://astral.sh/uv/install.sh | sh || handle_error "Failed to install uv"
    export PATH="$HOME/.local/bin:$PATH"
    success_msg "uv installed successfully."
else
    echo -e "\e[32m[INFO]\e[0m uv is already installed. Skipping."
fi

# ------------------------------------------------------------------
# Step 6: Verify Python 3.11 Installation
echo -e "\e[34m[INFO]\e[0m Checking Python version..."
python3.11 --version || handle_error "Python 3.11 not found"

# ------------------------------------------------------------------
# Step 7: Create Virtual Environment using uv
echo -e "\e[34m[INFO]\e[0m Creating virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    uv venv --python=3.11 $VENV_DIR || handle_error "Failed to create virtual environment with uv"
    success_msg "Virtual environment created successfully."
else
    echo -e "\e[32m[INFO]\e[0m Virtual environment already exists. Skipping."
fi

# ------------------------------------------------------------------
# Step 8: Activate Virtual Environment
echo -e "\e[34m[INFO]\e[0m Activating virtual environment..."
source $VENV_DIR/bin/activate || handle_error "Failed to activate virtual environment"

# ------------------------------------------------------------------
# Step 9: Upgrade pip and setuptools
echo -e "\e[34m[INFO]\e[0m Upgrading pip and setuptools..."
python3.11 -m ensurepip
uv pip install --upgrade pip setuptools || handle_error "Failed to upgrade pip and setuptools"
success_msg "pip and setuptools upgraded successfully."

# ------------------------------------------------------------------
# Step 10: Install Python Dependencies and Playwright
echo -e "\e[34m[INFO]\e[0m Installing Python dependencies and Playwright..."
uv pip install -r requirements.txt || handle_error "Failed to install Python dependencies"

if ! python3.11 -m pip show playwright > /dev/null 2>&1; then
    echo -e "\e[34m[INFO]\e[0m Installing Playwright..."
    python3.11 -m pip install playwright || handle_error "Failed to install Playwright"
fi

python3.11 -m playwright install || handle_error "Failed to install Playwright"
playwright install-deps || handle_error "Failed to install Playwright dependencies"

success_msg "Python dependencies and Playwright installed successfully."

# ------------------------------------------------------------------
# Step 11: Install autoppia_iwa Package
echo -e "\e[34m[INFO]\e[0m Installing autoppia_iwa package..."
if cd autoppia_iwa_module && uv pip install -e . && cd ..; then
    success_msg "autoppia_iwa_module package installed successfully."
else
    handle_error "Failed to install autoppia_iwa package"
fi

# ------------------------------------------------------------------
# Step 12: Install Bittensor
echo -e "\e[34m[INFO]\e[0m Installing Bittensor..."
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/opentensor/bittensor/v8.4.5/scripts/install.sh)" || handle_error "Failed to install Bittensor"
success_msg "Bittensor installed successfully."

# ------------------------------------------------------------------
# Final Verification
echo -e "\e[34m[INFO]\e[0m Verifying installations..."
echo "Chrome version:"
/opt/chrome/chrome-linux64/chrome --version || echo "Chrome not found"
echo "ChromeDriver version:"
/opt/chrome/chrome-linux64/chrome --version || echo "ChromeDriver not found"
echo "MongoDB version:"
mongod --version || echo "MongoDB not found"

success_msg "Setup completed successfully!"
