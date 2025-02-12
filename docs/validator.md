# Web Agents Subnet: *Validator Guide*

This guide explains how to set up and run your validator for Subnet 36.

⚠️ IMPORTANT ⚠️

This subnet requires **Docker**. For optimal performance, we strongly recommend using a bare metal GPU, as virtualized environments may lead to performance issues.

You can deploy the components on separate instances:
- **Validator.py**: CPU only
- **LLM**: GPU (check System Requirements)
- **Demo-Webs**: CPU only (deployed via Docker)

Detailed configuration instructions for each component are provided in the following sections.

---

## System Requirements

- **Hardware:**
  - **CPU:** Minimum 12 cores recommended
  - **RAM:** Minimum 32GB RAM required
  - **GPU:** 
    - Recommended: NVIDIA A40
    - Optional: Higher memory GPUs like A6000, A100, or H100
- **Storage:**
  - Minimum 1TB disk space recommended
- **Operating System:**
  - Ubuntu 20.04 LTS or newer
- **CUDA:**
  - Version 12.1.1 required

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

### 1. Run the Setup Script

Make the setup script executable and run it:
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

### 2. Deploy Demo Web Projects

Deploy the demo web projects by running:
```bash
chmod +x autoppia_iwa/modules/webs_demo/setup.sh
./autoppia_iwa/modules/webs_demo/setup.sh
```

This script will:
- Install Docker and Docker Compose if not already installed
- Deploy multiple Docker containers, each running a different demo web project
- Set up the necessary networking and configurations

### 3. Deploy LLM Generation Endpoint

Set up the local LLM generation endpoint:
```bash
chmod +x autoppia_iwa/modules/llm_local/setup.sh
./autoppia_iwa/modules/llm_local/setup.sh
```

This script will launch a PM2 process that provides an API endpoint for LLM model interactions. 

**Note:** This requires CUDA 12.1.1. For detailed configuration options and requirements, please check `autoppia_iwa/modules/llm_local/setup.md`.

### 4. Configure Environment

Copy .env template:
```bash
cp .env.example .env
```

Edit the `.env` file to configure your environment:
```bash
# Default endpoints - modify these according to your setup
LOCAL_MODEL_ENDPOINT=http://localhost:6000
DEMO_WEBS_ENDPOINT=http://localhost
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

This configuration allows you to:
- Run the validator, LLM service, and demo webs on separate machines for better resource management
- Scale your setup by distributing components across multiple servers
- Maintain flexibility in your deployment architecture

### 5. Start the Validator with PM2

Use PM2 to run the validator with your configuration:
```bash
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