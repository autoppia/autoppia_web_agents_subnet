#!/bin/bash

# Update repositories
git pull origin main
cd autoppia_iwa_module && git pull origin main
cd modules/webs_demo && git pull origin main
cd ../../../

# Deploy MongoDB with Docker
./scripts/mongo/deploy_mongo_docker.sh -y

# Stop running containers on ports 8000 or 5432
docker ps --format "{{.ID}} {{.Ports}}" | grep -E '0.0.0.0:8000|0.0.0.0:5432' | awk '{print $1}' | xargs -r docker stop

# Deploy the validator demo
./scripts/validator/deploy_demo_webs.sh

# Restart PM2 processes
pm2 restart auto_update_validator

# Restart llm_local if applicable
if pm2 list | grep -q "llm_local"; then
    pm2 restart llm_local
fi

# Activate virtual environment and install packages
source validator_env/bin/activate
pip install -e .
cd autoppia_iwa_module && pip install -e .
cd ..

# Restart subnet validator
pm2 restart subnet-36-validator
