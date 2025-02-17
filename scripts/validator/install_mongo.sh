#!/bin/bash
# install_mongodb.sh - MongoDB installation for Ubuntu/Debian systems

echo "🔵 Installing MongoDB..."

# Check if already installed
if command -v mongod &> /dev/null; then
    echo "✅ MongoDB already installed, starting service..."
    sudo systemctl start mongod
    sudo systemctl enable mongod
    exit 0
fi

# Install required packages
sudo apt-get update
sudo apt-get install -y gnupg curl

# Add MongoDB repo (works on Ubuntu 20.04, 22.04, and newer)
curl -fsSL https://pgp.mongodb.com/server-7.0.asc | \
    sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg \
    --dearmor

echo "deb [ arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu $(lsb_release -cs)/mongodb-org/7.0 multiverse" | \
    sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list

# Install MongoDB
sudo apt-get update
sudo apt-get install -y mongodb-org

# Start MongoDB
sudo systemctl start mongod
sudo systemctl enable mongod

echo "✅ MongoDB installed and running on port 27017"