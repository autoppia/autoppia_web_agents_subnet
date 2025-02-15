# Web Agents Subnet: Validator Guide

This guide explains how to set up and run your validator for Subnet 36.

**⚠️ IMPORTANT ⚠️**

This subnet requires **Docker**. For optimal performance, we strongly recommend using a bare metal GPU, as virtualized environments may lead to performance issues.

## Component Deployment

You can deploy the components on separate instances:

- **LLM**: Two options available:
  - **Option A:** Use OpenAI API (No GPU required, API key needed)
  - **Option B:** Use our Local LLM (Requires GPU with CUDA 12.1)
- **Demo-Webs**: CPU only (deployed via Docker)
- **Validator.py**: CPU only

Detailed configuration instructions for each component are provided in the following sections.

## Validator Information

If you wish to ChildKey (CHK) our validator, please note our hotkey ss58 address on subnet 36 is:
```
5DUmbxsTWuMxefEk36BYX8qNsF18BbUeTgBPuefBN6gSDe8j
```

---
## System Requirements

- **Hardware:**
  <!-- - **CPU:** Minimum 12 cores recommended -->
  - **RAM:** Minimum 32GB RAM required for the local llm
  - **GPU:**
    - Recommended: NVIDIA A40
    - Others: A6000, 6000Ada, A100, H100
    - Or no GPU and use OpenAI. 
  - **CUDA:** (Only required for LLM component)
    - Must be installed on the machine running the LLM service
- **Storage:**
  - Minimum 200MBs disk space recommended
- **Operating System:**
  - Ubuntu 22.04.5 LTS (Jammy Jellyfish)

---

## Pre-Installation Setup

### 1. Clone the Repository

First, clone the repository and navigate to the project directory:

```bash
git clone https://github.com/autoppia/autoppia_web_agents_subnet
cd autoppia_web_agents_subnet
```

### 2. Initialize and Update Submodules

Initialize and update the Autoppia IWA submodule:

```bash
git submodule update --init --recursive --remote
```

---

## Installation Steps

### 1. Configure LLM Provider

First, copy the environment template and configure your LLM provider:

```bash
cp .env.example .env
```

You have two options for the LLM provider:

#### Option A: Use OpenAI API (No GPU Required)

If you prefer to use OpenAI's API, edit your `.env` file with:

```bash
LLM_PROVIDER="openai"
OPENAI_API_KEY="your-api-key-here"
```

With this configuration, you can skip the local LLM setup and proceed to step 2.

#### Option B: Deploy Local LLM (GPU Required)

If you want to use our local LLM solution:

1. Edit your `.env` file:

```bash
LLM_PROVIDER="local"
LLM_ENDPOINT="http://localhost:6000/generate"
```

2. Verify your CUDA version:

```bash
nvcc --version
```

⚠️ **CRITICAL**: The output should show a version of CUDA, the code is prepared to install automatically for CUDA 12.6 (as shown by nvcc --version)

3. Set up the local LLM generation endpoint:

```bash
chmod +x autoppia_iwa_module/modules/llm_local/setup.sh
./autoppia_iwa_module/modules/llm_local/setup.sh

source llm_env/bin/activate
pm2 start autoppia_iwa_module/modules/llm_local/run_local_llm.py --name llm_local -- --port 6000
```

4. Verify the LLM service:

```bash
python3 autoppia_iwa_module/modules/llm_local/test/test.py
```

The local setup uses the **deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B** model and requires:

- CUDA 12.6 installation
- GPU with sufficient memory (see System Requirements)
- PM2 process running on port 6000

For additional configuration options and advanced setup of the local LLM, refer to the detailed documentation in `modules/llm_local/setup.md`.

### 2. Deploy Demo Web Projects

Deploy the demo web projects by running:

```bash
CURRENT_DIR=$(pwd)
cd autoppia_iwa_module/modules/webs_demo
chmod +x setup.sh
./setup.sh
cd "$CURRENT_DIR"
```

This script will:

- Install **Docker** and **Docker Compose** if not already installed
- Deploy **multiple Docker containers**, each running a different demo web project
- Set up the necessary networking and configurations

### 3. (Optional) Configure Demo Webs Endpoint

If want another port, or has deployed the Demo-Webs on another server => Edit the `.env` file to configure your environment with the following parameters:

```bash
# Default endpoints - modify these according to your setup
LOCAL_MODEL_ENDPOINT=http://localhost:6000
DEMO_WEBS_ENDPOINT=http://localhost
DEMO_WEBS_STARTING_PORT=8000
```

#### Configuration Options:

- **`LOCAL_MODEL_ENDPOINT`**: The endpoint where your LLM service is running
  - Default: `http://localhost:6000`
  - You can modify this if running the LLM on a different server
  - Example remote setup: `http://your-llm-server_ip:port`
  - _Note: The server hosting the LLM must have CUDA 12.1+ installed_
- **`DEMO_WEBS_ENDPOINT`**: The endpoint where your demo web projects are deployed
  - Default: `http://localhost`
  - You can modify this if running the demo webs on a different server
  - Example remote setup: `http://your-demo-webs-server-ip`

This configuration allows you to:

- Run the validator, LLM service, and demo webs on separate machines for better resource management

### 4. Set Up Validator

This setup has been tested on ubuntu "jammy" distribution. "noble" distribution DOES NOT work. 

Run the setup script:

```bash
chmod +x scripts/validator/setup.sh
./scripts/validator/setup.sh
```

This script will:

- Install system dependencies
- Set up Python 3.11 environment
- Install and configure PM2
- Create and activate a virtual environment
- Install required Python packages including the autoppia_iwa package
- Set up Bittensor and other dependencies

If you are on runpod or other dockerized env:

```bash
chmod +x scripts/validator/no_sudo_setup.sh
./scripts/validator/no_sudo_setup.sh
```

### 5. Deploy Validator

Activate the virtual environment and start the validator with PM2:

```bash
source validator_env/bin/activate

pm2 start neurons/validator.py \
  --name "subnet-36-validator" \
  --interpreter python \
  -- \
  --netuid 36 \
  --subtensor.network finney \
  --wallet.name your_coldkey \
  --wallet.hotkey your_hotkey \
  --logging.debug
```

#### Common Configuration Options

- `--name`: PM2 process name (can be any name you choose)
- `--netuid`: Network UID (36 for this subnet)
- `--wallet.name`: Your coldkey name
- `--wallet.hotkey`: Your hotkey name
- `--logging.debug`: Enable debug logging
- `--subtensor.network`: Network to connect to (e.g., finney, local)

---

## Support

For additional help:

- Contact **@Daryxx**, **@Riiveer**, or **@Miguelik** on Discord if you encounter any issues
