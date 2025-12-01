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

| Component       | Requirements         | Notes             |
| --------------- | -------------------- | ----------------- |
| **Validator**   | CPU only             | Lightweight setup |
| **LLM Service** | OpenAI API or Chutes | No GPU required   |
| **Demo Webs**   | CPU only             | Docker required   |

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

**Important:** All following commands must be run from inside the `autoppia_web_agents_subnet` directory.

The setup scripts will try to clone/pull `autoppia_iwa` and `autoppia_webs_demo` automatically into the default sibling paths (`../autoppia_iwa`, `../autoppia_webs_demo`). If you keep them elsewhere, export:

```bash
export IWA_PATH=/path/to/autoppia_iwa
export WEBS_DEMO_PATH=/path/to/autoppia_webs_demo
```

### **System Dependencies**

```bash
# Navigate to the subnet repository
cd autoppia_web_agents_subnet

# Install system dependencies
chmod +x scripts/validator/main/install_dependencies.sh
./scripts/validator/main/install_dependencies.sh
```

### **Validator Setup**

```bash
# Make sure you're in the subnet repository directory
cd autoppia_web_agents_subnet

# Setup Python environment and packages
chmod +x scripts/validator/main/setup.sh
./scripts/validator/main/setup.sh
```

### **Environment Configuration**

```bash
# Make sure you're in the subnet repository directory
cd autoppia_web_agents_subnet

cp .env.validator-example .env
# Edit .env with your specific settings
```

---

## 🤖 2. LLM Configuration

The validator uses IWA to generate tasks, which requires an LLM provider. Choose one:

### **Option A: OpenAI API** 🌐 (No GPU Required)

Edit your `.env` file:

```bash
LLM_PROVIDER="openai"
OPENAI_API_KEY="your-api-key-here"
OPENAI_MODEL="gpt-4o-mini"
OPENAI_MAX_TOKENS="10000"
OPENAI_TEMPERATURE="0.7"
```

### **Option B: Chutes LLM** 🌐 (No GPU Required)

Edit your `.env` file:

```bash
LLM_PROVIDER="chutes"
CHUTES_BASE_URL="https://your-username-your-chute.chutes.ai/v1"
CHUTES_API_KEY="cpk_your_api_key_here"
CHUTES_MODEL="meta-llama/Llama-3.1-8B-Instruct"
CHUTES_MAX_TOKENS=2048
CHUTES_TEMPERATURE=0.7
CHUTES_USE_BEARER=False
```

---

## 🌐 3. Demo Webs Setup

### **Docker Installation**

```bash
# Navigate to the subnet repository
cd autoppia_web_agents_subnet

# Install Docker (if not already installed)
chmod +x scripts/validator/demo-webs/install_docker.sh
./scripts/validator/demo-webs/install_docker.sh
```

### **Deploy Demo Webs**

```bash
# Make sure you're in the subnet repository directory
cd autoppia_web_agents_subnet

# Setup demo web applications (set WEBS_DEMO_PATH if different from default ../autoppia_webs_demo)
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
# Navigate to the subnet repository
cd autoppia_web_agents_subnet

# Activate virtual environment
source validator_env/bin/activate

# Start the validator with PM2
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

**Step 1**: Navigate to the subnet repository and edit the auto-update script:

```bash
cd autoppia_web_agents_subnet
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
cd autoppia_web_agents_subnet
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
# Navigate to the subnet repository
cd autoppia_web_agents_subnet

# Complete update
chmod +x scripts/validator/update/update_deploy.sh
./scripts/validator/update/update_deploy.sh
```

---

## 📊 6. Reports Module

The validator automatically generates and sends detailed round reports via email at the end of each round. Reports include round statistics, miner performance, consensus data, and any errors or warnings.

### **Email Configuration**

Configure email settings in your `.env` file using `REPORT_MONITOR_*` variables:

```bash
# Validator Email Report Configuration
REPORT_MONITOR_SMTP_HOST=smtp.your-provider.com
REPORT_MONITOR_SMTP_PORT=587
REPORT_MONITOR_SMTP_USERNAME=user@domain.com
REPORT_MONITOR_SMTP_PASSWORD=your-password
REPORT_MONITOR_EMAIL_FROM=report@domain.com
REPORT_MONITOR_EMAIL_TO=recipient1@domain.com,recipient2@domain.com
REPORT_MONITOR_SMTP_TLS=true
REPORT_MONITOR_SMTP_SSL=false
```

**Note:** Reports are sent automatically at the end of each round. No additional PM2 process is needed.

### **Log Splitting by Round (Optional)**

To organize validator logs by round for easier analysis, you can use the log splitter script. This monitors your PM2 validator log file and automatically creates separate log files for each round:

```bash
pm2 start scripts/validator/utils/simple_log_splitter_v2.py \
  --name "validator-log-splitter" \
  --interpreter python3 \
  -- \
  --log-file ~/.pm2/logs/validator-out.log \
  --output-dir data/logs/rounds
```

**Replace:**

- `--log-file` with your actual PM2 validator log file path (e.g., `~/.pm2/logs/validator-6am-out.log`)
- `--output-dir` with your desired output directory path

This will automatically split the validator logs into separate files per round (e.g., `round_598.log`, `round_599.log`) in the specified output directory.

## 🆘 Support & Contact

Need help? Contact our team on Discord:

- **@Daryxx**
- **@Riiveer**

---

## ⚠️ Important Notes

- 🐳 **Dependencies**: Demo webs require Docker and Docker Compose
- 🌍 **Scalability**: All components support distributed deployment across multiple machines
- 🔒 **Security**: Ensure proper firewall configuration for remote deployments
- 🔄 **Auto-Updates**: Option 1 (editing script) is recommended as it persists configuration across restarts

```

```
