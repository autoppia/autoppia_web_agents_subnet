#!/bin/bash
# setup.sh - Deploy web demo projects

set -e

echo "🚀 Setting up web demos..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Please run install_docker.sh first"
    exit 1
fi

# Check if Docker is running
if ! systemctl is-active --quiet docker; then
    echo "🔄 Starting Docker service..."
    sudo systemctl start docker
fi

# Deploy projects
deploy_project() {
    local project_dir="$1"
    if [ -d "$project_dir" ]; then
        echo "📂 Deploying $project_dir..."
        cd "$project_dir"
        sudo docker compose up -d --build
        cd ..
    else
        echo "⚠️ Project directory $project_dir not found."
    fi
}

# Deploy each web demo project
echo "🔄 Deploying web demos..."
cd ..
deploy_project "web_1_demo_django_jobs"
# Add more projects as needed with:
# deploy_project "web_2_demo_..."

echo "✨ Web demos deployment complete!"