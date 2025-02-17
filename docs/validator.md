# Web Agents Subnet: Validator Guide

Validator setup for Subnet 36.

## Requirements

- Ubuntu 22.04.5 LTS (Jammy)
- RAM: 32GB minimum
- GPU: NVIDIA A40/A6000/A100/H100 (or use OpenAI API)
- Storage: 200MB minimum

## Component Overview

You can deploy components separately:

- **LLM**: OpenAI API or Local LLM
- **Demo-Webs**: CPU only (Docker required)
- **Validator**: CPU only

## Quick Start

1. Clone and setup:

```bash
git clone https://github.com/autoppia/autoppia_web_agents_subnet
cd autoppia_web_agents_subnet
git submodule update --init --recursive --remote
```

2. Install dependencies:

```bash
chmod +x scripts/install_dependencies.sh
./scripts/install_dependencies.sh
```

3. Setup environment:

### Option A: Dockerized Environment (runpod or similar)

```bash
chmod +x scripts/validator/no_sudo_setup.sh
./scripts/validator/no_sudo_setup.sh
```

### Option B: Standard Environment

```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

4. Configure LLM:

```bash
cp .env.example .env
# Edit .env with your configuration
```

## LLM Setup Options

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
LLM_ENDPOINT="http://localhost:6000/generate"
```

2. Verify CUDA:

```bash
nvcc --version
```

⚠️ **CRITICAL**: Should show CUDA 12.6

3. Setup local LLM:

```bash
chmod +x autoppia_iwa_module/modules/llm_local/setup.sh
./autoppia_iwa_module/modules/llm_local/setup.sh
source llm_env/bin/activate
pm2 start autoppia_iwa_module/modules/llm_local/run_local_llm.py --name llm_local -- --port 6000
```

**To verify if your LLM is working correctly:**

```bash
python3 autoppia_iwa_module/modules/llm_local/test/test.py
```

The local setup uses **deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B** model.

## Demo Web Projects Setup

This script requires **Docker**. If **Docker** is not installed, the script will attempt to install it automatically.

1. Deploy demo webs:

```bash
CURRENT_DIR=$(pwd)
cd autoppia_iwa_module/modules/webs_demo
chmod +x setup.sh
./setup.sh
cd "$CURRENT_DIR"
```

2. Configure endpoints (optional):
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
  - _Note: The server hosting the LLM must have CUDA 12.6 installed_
- **`DEMO_WEBS_ENDPOINT`**: The endpoint where your demo web projects are deployed
  - Default: `http://localhost`
  - You can modify this if running the demo webs on a different server
  - Example remote setup: `http://your-demo-webs-server-ip`

This configuration allows you to run the validator, LLM service, and demo webs on separate machines for better resource management.

## Start Validator

```bash
source validator_env/bin/activate
pm2 start neurons/validator.py \
  --name "subnet-36-validator" \
  --interpreter python \
  -- \
  --netuid 36 \
  --subtensor.network finney \
  --wallet.name your_coldkey \
  --wallet.hotkey your_hotkey
```

## Installation Paths

- Python environment: **/validator_env**
- Chrome: **/opt/chrome**
- ChromeDriver: **/opt/chromedriver**
- LLM service: **localhost:6000**
- Demo webs: **localhost:8000**

## Support

Contact **@Daryxx**, **@Riiveer**, or **@Miguelik** on Discord

## Important Notes

- For optimal performance, use bare metal GPU
- Verify CUDA 12.6 installation for local LLM
- Demo webs require Docker and Docker Compose
- All components can be deployed on separate machines
