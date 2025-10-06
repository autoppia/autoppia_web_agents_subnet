# ⛏️ Miner Guide for Subnet 36 Web Agents

> **🎯 Key Innovation**: We've worked extensively to simplify miner deployment. **You don't need to run on testnet first!** Use our **Benchmark Framework** to develop and test your web agents locally before mining.

## 📋 Overview

## 🎯 How It Works: Two Simple Steps

### Step 1: Build & Test Your Agent Locally

First, you'll create a web agent that can solve tasks. Test it thoroughly using our Benchmark Framework - no blockchain required!

### **Benefits of Local Testing**

| Benefit                   | Description                             |
| ------------------------- | --------------------------------------- |
| 💰 **Save Money**         | No network fees during development      |
| 🚀 **Faster Iteration**   | Instant feedback vs network cycles      |
| 🛡️ **Risk-Free**          | Test without risking rewards/reputation |
| 🎯 **Better Performance** | Optimize before competing               |
| 📊 **Detailed Analytics** | Comprehensive performance metrics       |
| 🔧 **Easy Debugging**     | Full logs and error tracking            |
| ⚡ **Quick Setup**        | Start testing in minutes                |

### Step 2: Deploy as a Miner

Once your agent performs well locally, deploy it to the network to start earning rewards.

**Your deployed miner will:**

- 📥 **Receive tasks** from validators
- 🧠 **Process requirements** using your logic
- ✅ **Return a list of actions** (see actions allowed)
- 💰 **Earn rewards** based on performance

---

## 🏆 **Steps to Be the Best Miner**

**Local Testing (Do this first!):**

1. **Configure .env** → Generate tasks as validator does
2. **Deploy demo projects** → Test target websites
3. **Install requirements** → Setup validator dependencies
4. **Create agent** → Build `/solve_task` endpoint
5. **Check endpoint** → Verify task reception
6. **Implement logic** → Return action sequences
7. **See results** → Get performance scores
8. **Deploy miner** → Go live when ready!

---

# 🔬 PHASE 1: LOCAL TESTING

## ⚠️ IMPORTANT: Test Locally First!

> **Before deploying your miner, you MUST test your agent locally using our Benchmark Framework.**

**Why local testing is crucial:**

- ✅ **Free development** - no network fees for testing
- ✅ **Instant feedback** - immediate performance metrics
- ✅ **Risk-free iteration** - test before deploying
- ✅ **Production-ready** - benchmark = production behavior

## 📚 Local Testing Guide

**Complete guide for local testing and agent development:**

📖 **👉 Go to**: `autoppia_iwa_module/autoppia_iwa/entrypoints/benchmark/README.md`

**What the benchmark does:**
The benchmark **generates tasks the same way a validator would** and sends them to your deployed agent, then **evaluates the results exactly like a validator would**. This gives you production-identical testing without any blockchain interaction.

**This guide covers:**

- 🕷️ **What is a Web Agent** and how it works
- 🎯 **Available Actions** your agent can use
- 🚀 **Setup & Configuration** for local testing
- 🧪 **Creating Your Agent** with code examples
- ⚙️ **Benchmark Configuration** and customization
- 📊 **Performance Testing** and optimization

**Quick start for local testing:**

```bash
# From the main repository root
cd autoppia_iwa_module
python -m autoppia_iwa.entrypoints.benchmark.run
```

---

# ⛏️ PHASE 2: MINER DEPLOYMENT

## 🚀 Deploy Your Miner to Mainnet

> **Prerequisites**: Only deploy to mainnet after thorough local testing with the benchmark!

### **Before Deploying**

Ensure your agent:

- ✅ **Thoroughly tested** with benchmark framework
- ✅ **Good performance results** in local testing
- ✅ **Ready for production** deployment

### **Miner Deployment**

**A miner is like the benchmark** - configure `.env` with your agent's port and run it.

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
# Configure your deployed agent
AGENT_HOST="localhost"  # or your agent's host
AGENT_PORT="5000"       # port where your agent is running
AGENT_NAME="your_agent_name"
```

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

| Phase                | Time  | Action               | Guide                                                              |
| -------------------- | ----- | -------------------- | ------------------------------------------------------------------ |
| **Local Testing**    | 30min | Develop & test agent | `autoppia_iwa_module/autoppia_iwa/entrypoints/benchmark/README.md` |
| **Miner Deployment** | 10min | Deploy to mainnet    | This guide (Phase 2)                                               |

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
