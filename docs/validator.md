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

```bash
# Clone and initialize
git clone https://github.com/autoppia/autoppia_web_agents_subnet
cd autoppia_web_agents_subnet
git submodule update --init --recursive --remote
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
cp .env.example .env
# Edit .env with your specific settings
```

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

```bash
chmod +x autoppia_iwa_module/modules/llm_local/setup.sh
./autoppia_iwa_module/modules/llm_local/setup.sh
```

**Step 3**: Deploy with PM2

```bash
source llm_env/bin/activate
CUDA_VISIBLE_DEVICES=0 pm2 start autoppia_iwa_module/modules/llm_local/run_local_llm.py \
  --name llm_local -- --port 6000
```

**Step 4**: Test deployment

```bash
python3 autoppia_iwa_module/modules/llm_local/test/test_one_request.py
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
# Setup demo web applications
chmod +x scripts/validator/demo-webs/deploy_demo_webs.sh
./scripts/validator/demo-webs/deploy_demo_webs.sh
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

```bash
chmod +x scripts/validator/update/auto_update_validator.sh
pm2 start --name auto_update_validator \
  --interpreter /bin/bash \
  ./scripts/validator/update/auto_update_validator.sh \
  -- subnet-36-validator your_actual_coldkey your_actual_hotkey
```

⚠️ **Important**: Edit the script with your actual PM2 process name and wallet keys before running.

**Features**:

- ✅ Automatic version checking (every 5 minutes)
- ✅ Safe deployment with rollback
- ✅ Zero-downtime updates

### **Manual Updates**

Update all components manually:

```bash
# Complete update
chmod +x scripts/validator/update/full_update.sh
./scripts/validator/update/full_update.sh

# Or forced update with rollback
chmod +x scripts/validator/update/update.sh
./scripts/validator/update/update.sh
```

---

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
