# ⛏️ Miner Guide for Subnet 36 Web Agents

> **🎯 Key Innovation**: We've worked extensively to simplify miner deployment. **You don't need to run on testnet first!** Use our **Benchmark Framework** to develop and test your web agents locally before mining.

## 📋 Overview

A miner only announces **metadata** (name, image, GitHub URL). Validators then clone your repo at that URL and run your agent in a sandbox. The miner itself does not receive tasks or execute them.

## 🎯 How It Works (Simple)

1. You publish your agent code in a GitHub repo (commit or branch).
2. Your miner advertises `AGENT_NAME`, `GITHUB_URL`, and `AGENT_IMAGE`.

**Important:** your agent repo must expose the HTTP **`/act`** endpoint expected by the validator's sandbox runner (used by `ApifiedWebAgent` in IWA). If your agent does not implement `/act`, the validator will fail every step.

3. Validators clone your repo and run it locally in a sandbox for evaluation.

## Just a reminder miners

To avoid spam, you need:

- Have enough stake: minimum `100` alpha staked (`>= 100.0`).
- Only `2` hotkeys are allowed per coldkey.
- `AGENT_NAME` and `GITHUB_URL` must be valid.
- `GITHUB_URL` must point to a specific ref/commit (recommended: exact commit URL). Example:
  `https://github.com/autoppia/autoppia_operator/commit/b4d967f5266b82b36db02f286e9ada48708aa47f`

## 🗓️ Seasons, Rounds, and Re-evaluation

- Each **season** contains multiple **rounds**.
- At the start of every round, miners respond with their GitHub URL (plus name/image).
- If the validator has already evaluated the **same repo + same commit** during the **current season**, it will skip re-evaluation.
- To be evaluated again in the same season, publish a **new commit** and update your `GITHUB_URL` to that commit URL.

---

## 🧪 Test Locally First

Use the benchmark to validate your agent **before** advertising it to validators. See the [Benchmark Guide](./advanced/benchmark_readme.md).

```bash
IWA_PATH=${IWA_PATH:-../autoppia_iwa}
cd "$IWA_PATH"
python -m autoppia_iwa.entrypoints.benchmark.run
```

You can also run a validator-like sandbox evaluation against your exact `GITHUB_URL` submission:

```bash
python -m scripts.miner.eval_github \
  --github "https://github.com/<owner>/<repo>/commit/<sha>" \
  --tasks 1
```

Options:
- `--tasks-json /path/to/season_tasks.json`: evaluate tasks from a JSON file instead of generating new tasks.
- `--output-json /tmp/miner_eval_report.json`: save a structured report.
- `--env-file .env`: load API keys/settings from an env file before running.
- `--keep-containers`: preserve sandbox containers for debugging.

Scoring parity with validator:
- Uses the same reward function as validator (`score` + time/cost shaping via `calculate_reward_for_task`).
- Applies the same over-cost safety rule:
  - Task is counted as over-cost when `cost_usd >= MAX_TASK_DOLLAR_COST_USD`.
  - If over-cost hits reach `MAX_OVER_COST_TASKS_BEFORE_FORCED_ZERO_SCORE` (default `10`), remaining tasks stop and final validator-equivalent score is forced to `0`.
- Report includes `summary.validator_final_score` (the score miners should expect for that run) plus cost-limit counters.

---

# ⛏️ Miner Deployment

## 🚀 Deploy Your Miner to Mainnet

> **Prerequisites**: Only deploy to mainnet after local testing with the benchmark!

### **Configure .env**

**Step 1: Setup Miner Environment (minimal runtime)**

```bash
# Install miner dependencies
chmod +x scripts/miner/install_dependencies.sh
./scripts/miner/install_dependencies.sh

# Setup miner environment
chmod +x scripts/miner/setup.sh
./scripts/miner/setup.sh
```

These scripts install only what the miner needs to answer handshake metadata (Python, PM2, bittensor). They do **not** install Playwright/IWA.

**Step 2: Configure Agent in .env**

```bash
# Copy the miner environment template
cp .env.miner-example .env

# Edit .env with your agent configuration
```

Minimum fields to set:

- `AGENT_NAME` (public name shown to validators)
- `GITHUB_URL` (repo URL or commit URL that validators clone in the sandbox)
- `AGENT_IMAGE` (public image URL shown in UI, optional but recommended)

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
| **Local Testing**    | 30min | Develop & test agent | [Benchmark Guide](./advanced/benchmark_readme.md) |
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
