#!/bin/bash

# **Purpose of the Script**
# This script sets up and runs the Django development environment in a controlled and automated way using PM2.

# Function to handle errors
function handle_error {
    echo "Error occurred at step: $1"
    exit 1
}

# 1. Install system dependencies
echo "Installing system dependencies..."
sudo apt update || handle_error "Updating package list"
sudo apt install -y \
  python3 python3-pip python3.8-venv python3-dev python3.10 python3.10-venv build-essential cmake wget sqlite3 npm || handle_error "Installing system dependencies"

# Install PM2 globally if not already installed
if ! command -v pm2 &> /dev/null; then
    echo "Installing PM2..."
    sudo npm install pm2 -g || handle_error "Installing PM2"
    pm2 update || handle_error "Updating PM2"
else
    echo "PM2 is already installed."
fi

# 2. Set up virtual environment
echo "Setting up the virtual environment..."
if [ ! -d "venv_django" ]; then
  python3.10 -m venv venv_django || handle_error "Creating virtual environment"
fi

# Activate the virtual environment
source venv_django/bin/activate || handle_error "Activating virtual environment"

# 3. Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip || handle_error "Upgrading pip"

# 4. Install Python dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt || handle_error "Installing Python dependencies"

# 5. Run database migrations
echo "Running database migrations..."
python3.10 manage.py migrate || handle_error "Running database migrations"

# 6. Start the Django development server with PM2
echo "Starting the Django development server using PM2..."

# Check if the PM2 process is already running
if pm2 list | grep -q "django-server"; then
    echo "PM2 process 'django-server' is already running. Restarting..."
    pm2 restart django-server || handle_error "Restarting Django server with PM2"
else
    # Start a new PM2 process for the Django server
    pm2 start python3.10 --name django-server -- manage.py runserver 0.0.0.0:8000 || handle_error "Starting Django server with PM2"
fi

# Save the PM2 process list to start on system boot
pm2 save || handle_error "Saving PM2 process list"

# Inform the user
echo "The Django server is running and managed by PM2."
echo "You can monitor it using: pm2 list"
echo "Logs can be viewed with: pm2 logs django-server"
echo "Access the server at: http://127.0.0.1:8000/"
