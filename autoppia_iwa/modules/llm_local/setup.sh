#!/bin/bash

echo "Creating and activating virtual environment..."
apt update -y && apt upgrade -y && apt install -y sudo
sudo apt-get update -y && sudo apt-get upgrade -y
sudo apt-get install -y python3 python3-pip python3-dev python3.10 python3.10-venv build-essential cmake wget
python3.10 -m venv llm_env && source llm_env/bin/activate
echo "Checking CUDA installation..."

echo "Installing project dependencies from local_llm_requirements.txt..."
pip install -r autoppia_iwa_module/modules/llm_local/requirements.txt

# NOTE - VERSION 12.6
pip3 install torch==2.4.1 

echo "Installing and configuring PM2 service..."
sudo apt install -y npm
sudo npm install pm2 -g
pm2 update -y
