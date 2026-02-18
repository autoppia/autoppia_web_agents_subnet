# ⛏️ Miner Guide for Subnet 36 Web Agents

> **🎯 Key Innovation**: We've worked extensively to simplify miner deployment. **You don't need to run on testnet first!** Use our **Benchmark Framework** to develop and test your web agents locally before mining.

## 📋 Overview

A miner only announces **metadata** (name, image, GitHub URL). Validators then clone your repo at that URL and run your agent in a sandbox. The miner itself does not receive tasks or execute them.

## 🎯 How It Works (Simple)

1. You publish your agent code in a GitHub repo (commit or branch).
2. Your miner advertises `MINER_AGENT_NAME`, `MINER_GITHUB_URL`, and `MINER_AGENT_IMAGE`.
3. Validators clone your repo and run it locally in a sandbox for evaluation.

---

## 🧪 Test Locally First

Use the benchmark to validate your agent **before** advertising it to validators.

```bash
IWA_PATH=${IWA_PATH:-../autoppia_iwa}
cd "$IWA_PATH"
python -m autoppia_iwa.entrypoints.benchmark.run
```

---

# ⛏️ Miner Deployment

## 🚀 Deploy Your Miner to Mainnet

> **Prerequisites**: Only deploy to mainnet after thorough local testing with the benchmark!

### **Before Deploying**

Make sure your agent repo runs locally and passes the benchmark.

### **Configure .env**

**Step 1: Setup Miner Environment**

```bash
# Install miner dependencies
chmod +x scripts/miner/install_dependencies.sh
./scripts/miner/install_dependencies.sh

# Setup miner environment
chmod +x scripts/miner/setup.sh
./scripts/miner/setup.sh
```

**Step 2: Configure Agent in .env**

```bash
# Copy the miner environment template
cp .env.miner-example .env

# Edit .env with your agent configuration
```

Minimum fields to set:

- `MINER_AGENT_NAME` (public name shown to validators)
- `MINER_GITHUB_URL` (repo URL or commit URL that validators clone in the sandbox)
- `MINER_AGENT_IMAGE` (public image URL shown in UI, optional but recommended)

Note: demo webs are only required for local benchmarking. A miner does not need demo webs running in production.

**Step 3: Deploy Miner**

```bash
source miner_env/bin/activate

pm2 start neurons/miner.py \
  --name "subnet_36_miner" \
  --interpreter python3.11 \
  -- \
  --netuid 36 \
  --subtensor.network finney \
  --wallet.name your_coldkey \
  --wallet.hotkey your_hotkey \
  --logging.debug \
  --axon.port 8091
```

### **Validator Compatibility**

Validators only read your metadata, then clone your repo and run it locally in a sandbox. If the repo cannot be cloned or run, you will score 0.

Your agent repo must expose the HTTP **`/act`** endpoint expected by the validator's sandbox runner (used by `ApifiedWebAgent` in IWA). If your agent does not implement `/act`, the validator will fail every step.

### **Configuration Options**

| Parameter             | Description              | Default | Example           |
| --------------------- | ------------------------ | ------- | ----------------- |
| `--name`              | PM2 process name         | -       | `subnet_36_miner` |
| `--netuid`            | Network UID              | -       | `36`              |
| `--wallet.name`       | Coldkey name             | -       | `my_coldkey`      |
| `--wallet.hotkey`     | Hotkey name              | -       | `my_hotkey`       |
| `--axon.port`         | Miner communication port | `8091`  | `8091`            |
| `--subtensor.network` | Network type             | -       | `finney`          |

---

## 💪 Mining & Rewards

### **Reward Structure**

| Factor                           | Weight  | Description                               |
| -------------------------------- | ------- | ----------------------------------------- |
| **🎯 Task Completion Precision** | **85%** | How accurately your agent completes tasks |
| **⚡ Execution Speed**           | **15%** | How quickly your agent responds           |

---

## 🎯 Quick Start Summary

### **Complete Workflow**

| Phase                | Time  | Action               | Guide                                    |
| -------------------- | ----- | -------------------- | ---------------------------------------- |
| **Local Testing**    | 30min | Develop & test agent | [Benchmark Guide](./benchmark-README.md) |
| **Miner Deployment** | 10min | Deploy to mainnet    | This guide (Phase 2)                     |

### **Key Benefits**

- ✅ **No testnet required** - develop locally first
- ✅ **Free development** - no network fees for testing
- ✅ **Instant feedback** - immediate performance metrics
- ✅ **Production-ready** - benchmark = production behavior
- ✅ **Risk-free iteration** - test before deploying

---

## 🆘 Support & Contact

**Need help?** Contact our team on Discord:

- **@Daryxx**
- **@Riiveer**

---
