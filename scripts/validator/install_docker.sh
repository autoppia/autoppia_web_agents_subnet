#!/bin/bash
# install_docker.sh - Docker Installation Script
# This script automates:
# - Docker installation
# - Docker Compose v2 setup (via apt or manual install)
# - User Docker group configuration
# - Verification of Docker and Docker Compose installations

set -e

install_docker() {
    if ! command -v docker &> /dev/null; then
        echo "🔧 Installing Docker..."
        sudo apt-get update -y
        sudo apt-get install -y docker.io
        sudo systemctl enable docker
        sudo systemctl start docker
    else
        echo "✅ Docker is already installed."
    fi
}

configure_docker_permissions() {
    if ! groups "$USER" | grep -q "docker"; then
        echo "🔒 Adding user to Docker group..."
        sudo usermod -aG docker "$USER"
        echo "⚠️ Please log out and log back in or run: newgrp docker"
    else
        echo "✅ User already has Docker group permissions."
    fi
}

remove_docker_compose_v1() {
    if command -v docker-compose &> /dev/null; then
        echo "🗑️ Removing Docker Compose v1..."
        sudo apt-get remove -y docker-compose
    else
        echo "✅ Docker Compose v1 already removed."
    fi
}

install_docker_compose_v2() {
    echo "🔍 Attempting to install Docker Compose v2 via apt-get..."
    sudo apt-get update -y
    set +e
    sudo apt-get install -y docker-compose-plugin
    install_status=$?
    set -e

    if [ $install_status -ne 0 ]; then
        echo "⚠️ Docker Compose v2 package not found in apt repository. Installing manually..."
        local compose_version="v2.20.2"
        local binary_dir="/usr/local/lib/docker/cli-plugins"
        local binary_path="${binary_dir}/docker-compose"
        sudo mkdir -p "$binary_dir"
        sudo curl -SL "https://github.com/docker/compose/releases/download/${compose_version}/docker-compose-$(uname -s)-$(uname -m)" -o "$binary_path"
        sudo chmod +x "$binary_path"
    else
        echo "✅ Docker Compose v2 installed via apt-get."
    fi

    echo "🔍 Installed Docker Compose version:"
    docker compose version || true
}

verify_installation() {
    echo "🔍 Verifying Docker installation..."
    docker --version || { echo "❌ Docker not found!"; exit 1; }
    echo "🔍 Verifying Docker Compose installation..."
    docker compose version || { echo "❌ Docker Compose not found!"; exit 1; }
    echo "✅ Docker and Docker Compose are installed and working."
}

main() {
    install_docker
    configure_docker_permissions
    remove_docker_compose_v1
    install_docker_compose_v2
    verify_installation
}

main "$@"
