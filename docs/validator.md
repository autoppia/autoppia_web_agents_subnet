# Validator Guide

Validator setup for Subnet 36.

## Requirements

**Important Linux Distribution Note**:

- Our **install_dependencies.sh** script currently supports:
  1. Ubuntu 22.04 LTS (Jammy)
  2. Ubuntu 24.04 LTS (Noble)
- If using a different Ubuntu version, you may need to manually adjust the dependencies in the **install_dependencies.sh** script

## Component Overview

The deployment is compartmentalized, allowing each component to be deployed separately:

- **Validator**: CPU only (MongoDB Recommended)
- **LLM**: OpenAI API or Local LLM
- **Demo-Webs**: CPU only (Docker required)

## Global Setup

1. Clone and setup:

```bash
git clone https://github.com/autoppia/autoppia_web_agents_subnet
cd autoppia_web_agents_subnet
git submodule update --init --recursive --remote
```

2. Install system dependencies:

```bash
chmod +x scripts/validator/install_dependencies.sh
./scripts/validator/install_dependencies.sh
playwright install
```

3. Install Docker:

```bash
chmod +x scripts/validator/install_docker.sh
./scripts/validator/install_docker.sh
```

4. Set up .env

```bash
# Edit .env with your configuration
cp .env.example .env
```

5. Install **MongoDB**

A) with Docker for caching web analysis results:

```bash
chmod +x scripts/mongo/deploy_mongo_docker.sh 
./scripts/mongo/deploy_mongo_docker.sh -y
```

Change mongo url in .env if you have deployed it in another IP or Port.

```bash
MONGODB_URL="mongodb://adminUser:password@localhost:27017/admin?authSource=admin"
```

# VALIDATOR SETUP

Setup the validator:

```bash
chmod +x scripts/validator/setup.sh
./scripts/validator/setup.sh
```

# LLM SETUP

- **POD TYPE**: We suggest using A40 in RunPod
- **Requirements**: CUDA 12.4.1 and PyTorch 2.4.0
- **Tested on RunPod template**: `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04`
- **Model**: Using Qwen/Qwen2.5-14B-Instruct by default in `run_local_llm.py`

### Option A: OpenAI API (No GPU Required)

Edit `.env`:

```bash
LLM_PROVIDER="openai"
OPENAI_API_KEY="your-api-key-here"
```

### Option B: Local LLM (GPU Required)

1. Edit `.env`:

```bash
LLM_PROVIDER="local"
LOCAL_MODEL_ENDPOINT="http://localhost:6000/generate"
```

2. Setup local LLM:

```bash
chmod +x autoppia_iwa_module/modules/llm_local/setup.sh
./autoppia_iwa_module/modules/llm_local/setup.sh
```

3. Setup in PM2:

```bash
source llm_env/bin/activate
CUDA_VISIBLE_DEVICES=0 pm2 start autoppia_iwa_module/modules/llm_local/run_local_llm.py --name llm_local -- --port 6000
```

To verify if your LLM is working correctly:

```bash
python3 autoppia_iwa_module/modules/llm_local/test/test_one_request.py
```

# DEMO WEBS SETUP

This script requires **Docker**. The following commands will install Docker and initialize the demo webs:

```bash
CURRENT_DIR=$(pwd)
cd autoppia_iwa_module/modules/webs_demo/scripts
chmod +x install_docker.sh
./install_docker.sh
chmod +x setup.sh
./setup.sh
cd "$CURRENT_DIR"
```

### Configure endpoints (optional):

Edit `.env`:

```bash
LOCAL_MODEL_ENDPOINT=http://localhost:6000
DEMO_WEBS_ENDPOINT=http://localhost
DEMO_WEBS_STARTING_PORT=8000
```

#### Configuration Options:

- **`LOCAL_MODEL_ENDPOINT`**: The endpoint where your LLM service is running

  - Default: `http://localhost:6000`
  - You can modify this if running the LLM on a different server
  - Example remote setup: `http://your-llm-server_ip:port`

- **`DEMO_WEBS_ENDPOINT`**: The endpoint where your demo web projects are deployed
  - Default: `http://localhost`
  - You can modify this if running the demo webs on a different server
  - Example remote setup: `http://your-demo-webs-server-ip`

This configuration allows you to run the validator, LLM service, and demo webs on separate machines for better resource management.

## Start Validator

```bash
deactivate
source validator_env/bin/activate
pm2 start neurons/validator.py \
  --name "subnet-36-validator" \
  --interpreter python \
  -- \
  --netuid 36 \
  --subtensor.network finney \
  --wallet.name your_coldkey \
  --wallet.hotkey your_hotkey \
  -logging.debug
  
```

## Auto Update for Validator

Script for _automatic version control_ and _safe updates_ of your validator:

```bash
chmod +x scripts/validator/auto_update_validator.sh
pm2 start --name auto_update_validator --interpreter /bin/bash ./scripts/validator/auto_update_validator.sh -- subnet-36-validator your_actual_coldkey your_actual_hotkey
```

_Note_: If you change something edit the script to match your PM2 configuration (process name, wallet keys) before running it.

The script automatically checks for updates, deploys new versions, and includes _automatic rollback_ if the update fails. Runs every _5 minutes_ to ensure your validator stays up to date.

## Support

Contact **@Daryxx**, **@Riiveer**, or **@Miguelik** on Discord

## Important Notes

- For optimal performance, use bare metal GPU
- Demo webs require Docker and Docker Compose
- All components can be deployed on separate machines
