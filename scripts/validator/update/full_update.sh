#!/bin/bash
# full_update.sh - Complete update of all components with error handling
set -e

handle_error() {
    echo -e "\e[31m[ERROR]\e[0m $1" >&2
    exit 1
}

success_msg() {
    echo -e "\e[32m[SUCCESS]\e[0m $1"
}

info_msg() {
    echo -e "\e[34m[INFO]\e[0m $1"
}

# Get repo root directory
REPO_ROOT="$(pwd)"

update_repositories() {
    info_msg "Updating repositories..."
    
    # Update main repo
    git pull origin main || handle_error "Failed to pull main repo"
    
    # Update autoppia_iwa_module
    if [ -d "autoppia_iwa_module" ]; then
        cd autoppia_iwa_module || handle_error "Failed to enter autoppia_iwa_module"
        git pull origin main || handle_error "Failed to pull autoppia_iwa_module"
        
        # Update webs_demo submodule if it exists
        if [ -d "modules/webs_demo" ]; then
            cd modules/webs_demo || handle_error "Failed to enter webs_demo"
            git pull origin main || handle_error "Failed to pull webs_demo"
            cd ../.. || handle_error "Failed to return from webs_demo"
        fi
        
        cd "$REPO_ROOT" || handle_error "Failed to return to repo root"
    fi
    
    success_msg "Repositories updated successfully"
}

stop_conflicting_containers() {
    info_msg "Stopping containers on ports 8000 and 5432..."
    
    # Stop containers using specific ports (ignore errors if no containers found)
    docker ps --format "{{.ID}} {{.Ports}}" | grep -E '0.0.0.0:8000|0.0.0.0:5432' | awk '{print $1}' | xargs -r docker stop 2>/dev/null || true
    
    success_msg "Conflicting containers stopped"
}

deploy_demo_webs() {
    info_msg "Deploying demo webs..."
    
    # Use new script location
    if [ -f "scripts/demo-webs/deploy_demo_webs.sh" ]; then
        chmod +x scripts/demo-webs/deploy_demo_webs.sh
        ./scripts/demo-webs/deploy_demo_webs.sh || handle_error "Failed to deploy demo webs"
        success_msg "Demo webs deployed successfully"
    else
        info_msg "Demo webs script not found, skipping deployment"
    fi
}

restart_pm2_processes() {
    info_msg "Restarting PM2 processes..."
    
    # Restart auto update validator if exists
    if pm2 list | grep -q "auto_update_validator"; then
        pm2 restart auto_update_validator || info_msg "Warning: Failed to restart auto_update_validator"
    else
        info_msg "auto_update_validator not found in PM2"
    fi
    
    # Restart llm_local if exists
    if pm2 list | grep -q "llm_local"; then
        pm2 restart llm_local || info_msg "Warning: Failed to restart llm_local"
    else
        info_msg "llm_local not found in PM2"
    fi
    
    success_msg "PM2 processes restarted"
}

reinstall_packages() {
    info_msg "Reinstalling Python packages..."
    
    # Activate virtual environment
    if [ -f "validator_env/bin/activate" ]; then
        source validator_env/bin/activate || handle_error "Failed to activate virtual environment"
    else
        handle_error "Virtual environment not found. Run setup.sh first."
    fi
    
    # Install main package
    pip install -e . || handle_error "Failed to install main package"
    
    # Install autoppia_iwa_module
    if [ -d "autoppia_iwa_module" ]; then
        cd autoppia_iwa_module || handle_error "Failed to enter autoppia_iwa_module"
        pip install -e . || handle_error "Failed to install autoppia_iwa_module"
        cd "$REPO_ROOT" || handle_error "Failed to return to repo root"
    fi
    
    success_msg "Python packages reinstalled successfully"
}

restart_validator() {
    info_msg "Restarting subnet validator..."
    
    if pm2 list | grep -q "subnet-36-validator"; then
        pm2 restart subnet-36-validator || handle_error "Failed to restart subnet-36-validator"
        success_msg "Subnet validator restarted successfully"
    else
        info_msg "subnet-36-validator not found in PM2, skipping restart"
    fi
}

main() {
    info_msg "Starting full update process..."
    info_msg "Working directory: $REPO_ROOT"
    
    update_repositories
    stop_conflicting_containers
    docker system prune -a --volumes --force
    deploy_demo_webs
    restart_pm2_processes
    reinstall_packages
    restart_validator
    
    success_msg "Full update completed successfully!"
    echo
    info_msg "All components have been updated and restarted"
}

main "$@"