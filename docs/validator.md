# 🚀 Validator Guide for Subnet 36

## 📋 System Requirements

### **Linux Distribution Support**

Our `install_dependencies.sh` script currently supports:

- **Ubuntu 22.04 LTS** (Jammy) ✅
- **Ubuntu 24.04 LTS** (Noble) ✅

⚠️ **Note**: For other Ubuntu versions, manually adjust dependencies in the installation script.

---

## 🏗️ Architecture Overview

The deployment uses a **modular architecture** - each component can be deployed separately:

| Component       | Requirements            | Notes                       |
| --------------- | ----------------------- | --------------------------- |
| **Validator**   | CPU only                | Lightweight setup           |
| **LLM Service** | OpenAI API or Local GPU | A40 GPU suggested for local |
| **Demo Webs**   | CPU only                | Docker required             |

💡 **Tip**: Components can run on different machines - configure `.env` with appropriate URLs.

---

## 🔧 1. Initial Setup

### **Repository Setup**

Clone the repositories as siblings:

```bash
git clone https://github.com/autoppia/autoppia_web_agents_subnet
git clone https://github.com/autoppia/autoppia_iwa.git          # IWA (main)
git clone https://github.com/autoppia/autoppia_webs_demo.git    # webs_demo (main)
```

Work inside `autoppia_web_agents_subnet`. The setup scripts will try to clone/pull `autoppia_iwa` and `autoppia_webs_demo` automatically into the default sibling paths (`../autoppia_iwa`, `../autoppia_webs_demo`). If you keep them elsewhere, export:

```bash
export IWA_PATH=/path/to/autoppia_iwa
export WEBS_DEMO_PATH=/path/to/autoppia_webs_demo
```

### **System Dependencies**

```bash
# Install system dependencies
chmod +x scripts/validator/main/install_dependencies.sh
./scripts/validator/main/install_dependencies.sh
```

### **Validator Setup**

```bash
# Setup Python environment and packages
chmod +x scripts/validator/main/setup.sh
./scripts/validator/main/setup.sh
```

### **Environment Configuration**

```bash
cp .env.validator-example .env
# Edit .env with your specific settings
```

> **Important:** Ensure `IWAP_VALIDATOR_AUTH_MESSAGE` in your `.env` matches the backend configuration so IWAP requests are signed with the correct challenge.

---

## 🤖 2. LLM Configuration

### **Recommended Specs for Local LLM**

- **Platform**: RunPod with A40 GPU
- **Requirements**: CUDA 12.4.1 + PyTorch 2.4.0
- **Template**: `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04`
- **Model**: Qwen/Qwen2.5-14B-Instruct (default)

### **Option A: OpenAI API** 🌐 (No GPU Required)

Edit your `.env` file:

```bash
LLM_PROVIDER="openai"
OPENAI_API_KEY="your-api-key-here"
```

### **Option B: Local LLM** 🖥️ (GPU Required)

**Step 1**: Configure environment

```bash
# Edit .env
LLM_PROVIDER="local"
LOCAL_MODEL_ENDPOINT="http://localhost:6000/generate"
```

**Step 2**: Setup local LLM

This step installs the dependencies and environment needed to run a local language model (e.g., Qwen/Qwen2.5-14B-Instruct) on your GPU. The setup script creates a virtual environment and installs PyTorch, transformers, and other required packages.

```bash
IWA_PATH=${IWA_PATH:-../autoppia_iwa}
chmod +x "$IWA_PATH/modules/llm_local/setup.sh"
"$IWA_PATH/modules/llm_local/setup.sh"
```

**What this does:**

- Creates a virtual environment (`llm_env`) for the LLM service
- Installs PyTorch with CUDA support for GPU acceleration
- Installs transformers and other model dependencies
- Downloads and configures the default model (Qwen2.5-14B-Instruct)

**Step 3**: Deploy with PM2

```bash
source llm_env/bin/activate
CUDA_VISIBLE_DEVICES=0 pm2 start "$IWA_PATH/modules/llm_local/run_local_llm.py" \
  --name llm_local -- --port 6000
```

**Step 4**: Test deployment

```bash
python3 "$IWA_PATH/modules/llm_local/test/test_one_request.py"
```

---

## 🌐 3. Demo Webs Setup

### **Docker Installation**

```bash
# Install Docker (if not already installed)
chmod +x scripts/validator/demo-webs/install_docker.sh
./scripts/validator/demo-webs/install_docker.sh
```

### **Deploy Demo Webs**

```bash
# Setup demo web applications (set WEBS_DEMO_PATH if distinto al default ../webs_demo)
chmod +x scripts/validator/demo-webs/deploy_demo_webs.sh
WEBS_DEMO_PATH=${WEBS_DEMO_PATH:-../autoppia_webs_demo} ./scripts/validator/demo-webs/deploy_demo_webs.sh
```

### **Configuration** (Optional)

Edit `.env` to customize endpoints:

```bash
DEMO_WEBS_ENDPOINT=http://localhost
DEMO_WEBS_STARTING_PORT=8000
```

#### **Configuration Options**

| Variable                  | Description            | Default            | Example                |
| ------------------------- | ---------------------- | ------------------ | ---------------------- |
| `DEMO_WEBS_ENDPOINT`      | Base URL for demo webs | `http://localhost` | `http://192.168.1.100` |
| `DEMO_WEBS_STARTING_PORT` | Starting port number   | `8000`             | `9000`                 |

🔧 **Remote Setup**: Change endpoint to your demo webs server IP for distributed deployment.

---

## ✅ 4. Validator Deployment

### **Starting the Validator**

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

---

## 🔄 5. Updates & Maintenance

### **Auto-Update Setup**

Enable automatic updates with safe rollback:

#### **Edit Script Configuration (Recommended)**

**Step 1**: Edit the auto-update script with your validator details:

```bash
nano scripts/validator/update/auto_update_deploy.sh
```

**Step 2**: Modify these configuration lines in the script:

```bash
# Change these lines to match your setup:
PROCESS_NAME="subnet-36-validator"      # Your PM2 process name
WALLET_NAME="your_coldkey"              # Your actual coldkey
WALLET_HOTKEY="your_hotkey"             # Your actual hotkey
SUBTENSOR_PARAM="--subtensor.network finney"  # Subtensor network
```

**Step 3**: Start the auto-update service:

```bash
chmod +x scripts/validator/update/auto_update_deploy.sh
pm2 start --name auto_update_validator \
  --interpreter /bin/bash \
  scripts/validator/update/auto_update_deploy.sh
```

**Auto-Update Features**:

- ✅ Automatic version checking (every 2 minutes by default)
- ✅ Safe deployment with rollback capability
- ✅ Zero-downtime updates
- ✅ Configurable check intervals

### **Manual Updates**

Update all components manually:

```bash
# Complete update
chmod +x scripts/validator/update/update_deploy.sh
./scripts/validator/update/update_deploy.sh

```

---

## 📊 6. Reports Module

We have added a reports module for both terminal and email reporting. To configure email report sending, modify the `.env` file:

### **Email Configuration**

```bash
# Validator EMAIL Report
SMTP_HOST=smtp.your-provider.com
SMTP_PORT=587
SMTP_USER=user@domain.com
SMTP_PASS=PASSWORD
SMTP_FROM=report@domain.com
SMTP_TO=test@domain.com
SMTP_STARTTLS=true

# reports folder (where the forward writes the jsonl)
REPORTS_DIR=forward_reports
```

### Setting up Automated Reports

Once configured, it's as simple as creating a PM2 process that executes the reports at regular intervals, for example every hour. Here's an example command so you can verify everything is working correctly:

```bash
python3 autoppia_web_agents_subnet/validator/send_reports.py
```

### PM2 Automated Reports Setup

```bash
pm2 start --name "validator-reports" \
  --interpreter python3 \
  --cron "0 * * * *" \
  --no-autorestart \
  autoppia_web_agents_subnet/validator/send_reports.py
```

## This will send reports every hour and help you monitor that everything is functioning correctly.

## 🆘 Support & Contact

Need help? Contact our team on Discord:

- **@Daryxx**
- **@Riiveer**

---

## ⚠️ Important Notes

- 🖥️ **Performance**: Use bare metal GPU for optimal local LLM performance
- 🐳 **Dependencies**: Demo webs require Docker and Docker Compose
- 🌍 **Scalability**: All components support distributed deployment across multiple machines
- 🔒 **Security**: Ensure proper firewall configuration for remote deployments
- 🔄 **Auto-Updates**: Option 1 (editing script) is recommended as it persists configuration across restarts

```

```
