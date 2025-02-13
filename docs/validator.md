# Web Agents Subnet: _Validator Guide_

This guide explains how to set up and run your validator for Subnet 36.

**⚠️ IMPORTANT ⚠️**
This subnet requires **Docker**. For optimal performance, we strongly recommend using a bare metal GPU, as virtualized environments may lead to performance issues.

You can deploy the components on separate instances:

- **LLM**: GPU (check System Requirements) - Requires CUDA 12.1
- **Demo-Webs**: CPU only (deployed via Docker)
- **Validator.py**: CPU only

Detailed configuration instructions for each component are provided in the following sections.

---

## System Requirements

- **Hardware:**
  - **CPU:** Minimum 12 cores recommended
  - **RAM:** Minimum 32GB RAM required
  - **GPU:**
    - Recommended: NVIDIA A40
    - Optional: Higher memory GPUs like A6000, A100, or H100
  - **CUDA:** (Only required for LLM component)
    - Must be installed on the machine running the LLM service
- **Storage:**
  - Minimum 1TB disk space recommended
- **Operating System:**
  - Ubuntu 20.04 LTS or newer

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

### 1. Deploy LLM Generation Endpoint

Before proceeding with any installation steps, verify your CUDA version:

```bash
nvcc --version
```

⚠️ **CRITICAL**: The output should show a version of CUDA, we've tested on 11.5

Set up the local LLM generation endpoint:

```bash
chmod +x autoppia_iwa_module/modules/llm_local/setup.sh
./autoppia_iwa_module/modules/llm_local/setup.sh

source llm_env/bin/activate
pm2 start autoppia_iwa_module/modules/llm_local/run_local_llm.py --name llm_local -- --port 6000
```

To verify that the LLM service is running correctly, you can run the test script:

```bash
python3 autoppia_iwa_module/modules/llm_local/tests/test.py
```

This script will:

- Verify CUDA 12.1 installation
- Exit with an error if CUDA 12.1 is not found
- Launch a PM2 process that provides an API endpoint for LLM model interactions

Currently, we are using the **qwen2.5-coder-14b-instruct-q4_k_m** model, but we will be updating to better performing models in the near future.

For additional configuration options and advanced setup, refer to the detailed documentation in `modules/llm_local/setup.md`.

### 2. Deploy Demo Web Projects

Deploy the demo web projects by running:

```bash
chmod +x autoppia_iwa_module/modules/webs_demo/setup.sh
./autoppia_iwa_module/modules/webs_demo/setup.sh
```

This script will:

- Install **Docker** and **Docker Compose** if not already installed
- Deploy **multiple Docker containers**, each running a different demo web project
- Set up the necessary networking and configurations

### 3. Configure Environment

Copy .env template:

```bash
cp .env.example .env
```

Edit the `.env` file to configure your environment:

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
  - _Note: The server hosting the LLM must have CUDA 12.1 installed_
- **`DEMO_WEBS_ENDPOINT`**: The endpoint where your demo web projects are deployed
  - Default: `http://localhost`
  - You can modify this if running the demo webs on a different server
  - Example remote setup: `http://your-demo-webs-server-ip`

This configuration allows you to:

- Run the validator, LLM service, and demo webs on separate machines for better resource management

### 4. Set Up Validator

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
  --logging.debug \
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

---
