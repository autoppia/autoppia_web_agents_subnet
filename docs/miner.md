# ⛏️ Miner Guide for Subnet 36 Web Agents

> **🎯 Key Innovation**: We've worked extensively to simplify miner deployment. **You don't need to run on testnet first!** Use our **Benchmark Framework** to develop and test your web agents locally before mining.

## 📋 Overview

This guide covers two distinct phases:

1. **🔬 LOCAL TESTING** - Develop and test your web agent using our benchmark framework
2. **⛏️ MINER DEPLOYMENT** - Deploy your tested agent as a miner on mainnet

---

# 🔬 PHASE 1: LOCAL TESTING & DEVELOPMENT

## 🎯 What is the Benchmark Framework?

The **Benchmark Framework** simulates the entire validator workflow locally. It:

- 🎯 **Tests your agents** without network registration
- 📊 **Provides performance metrics** identical to production
- 🔄 **Enables rapid iteration** with immediate feedback
- 💰 **Free development** without testnet costs
- ✅ **No registration needed** until you're ready to mine

### **How It Works**

1. **Task Generation**: Uses LLM APIs to generate realistic web tasks
2. **Agent Testing**: Sends tasks to your local agent endpoints
3. **Evaluation**: Scores solutions using the same logic as validators
4. **Reporting**: Provides detailed performance analytics

**The benchmark system exactly replicates what happens in production!**

---

## 🚀 Local Testing Setup

### **Step 1: Repository Setup**

```bash
# Clone repository
git clone https://github.com/autoppia/autoppia_web_agents_subnet
cd autoppia_web_agents_subnet

# Initialize submodules
git submodule update --init --recursive --remote
```

### **Step 2: Environment Configuration**

```bash
# Create environment file
cp .env.example .env
```

**Configure your `.env` file with LLM API key for task generation:**

**Option 1: OpenAI (Recommended)**

```bash
# Add your OpenAI API key for task generation
OPENAI_API_KEY="your_openai_api_key_here"
```

**Option 2: Chutes LLM**

```bash
# Chutes LLM configuration
LLM_PROVIDER=chutes
CHUTES_BASE_URL=https://your-username-your-chute.chutes.ai/v1
CHUTES_API_KEY=cpk_your_api_key_here
CHUTES_MODEL=meta-llama/Llama-3.1-8B-Instruct
CHUTES_MAX_TOKENS=2048
CHUTES_TEMPERATURE=0.7
CHUTES_USE_BEARER=False
```

⚠️ **Important**: You need an LLM API key (OpenAI or Chutes) to generate tasks in the benchmark system.

### **Step 3: Install Benchmark Dependencies**

For the benchmark (which simulates validator behavior), you need validator dependencies:

```bash
# Install validator dependencies for benchmark
cd autoppia_iwa_module
pip install -e .
```

**Or if you have specific validator setup scripts:**

```bash
# Check if there are validator setup scripts
ls scripts/validator/
# Run validator setup if available
```

### **Step 4: Deploy Demo Web Projects**

> **Required for Benchmark Testing**: You need demo web projects to generate and test tasks.

```bash
chmod +x autoppia_iwa_module/modules/webs_demo/scripts/setup.sh
./autoppia_iwa_module/modules/webs_demo/scripts/setup.sh
```

This script:

- 🐳 Installs Docker and Docker Compose (if needed)
- 🚀 Deploys multiple demo web project containers
- 🔗 Sets up networking and configurations

---

## 🧪 Testing Your Web Agent

### **Step 1: Test Task Generation**

First, verify tasks are being generated correctly:

```bash
cd autoppia_iwa_module
source ../miner_env/bin/activate
python -m autoppia_iwa.entrypoints.benchmark.run
```

**Expected Output:**

```
2025-01-XX XX:XX:XX | INFO | === Project: work ===
2025-01-XX XX:XX:XX | INFO | Generated 6 tasks for project 'work'
2025-01-XX XX:XX:XX | SUCCESS | Task generation completed ✔
```

✅ **Success**: If you see tasks being generated, your environment is ready!

❌ **Troubleshoot**: If you get errors, check:

- LLM API key is correctly set in `.env` (OpenAI or Chutes)
- Demo web projects are running (`docker ps`)
- Python environment is activated

### **Step 2: Create Your Web Agent**

Create your web agent that will receive tasks and return actions:

```bash
mkdir -p my_agent
cd my_agent
nano simple_agent.py
```

**Basic Agent Template:**

```python
from flask import Flask, request, jsonify
import json

app = Flask(__name__)

@app.route('/solve_task', methods=['POST'])
def solve_task():
    """
    Main endpoint that receives tasks from the benchmark system.
    This simulates what validators will send to your miner.
    """
    try:
        # Get the task data
        task_data = request.get_json()

        print(f"Received task: {task_data.get('id', 'unknown')}")
        print(f"Task prompt: {task_data.get('prompt', 'No prompt')}")

        # TODO: Implement your agent logic here
        # For now, return a simple response

        response = {
            "task_id": task_data.get('id'),
            "actions": [
                {
                    "action_type": "click",
                    "x": 100,
                    "y": 100
                }
            ],
            "success": True,
            "message": "Task processed successfully"
        }

        return jsonify(response)

    except Exception as e:
        return jsonify({
            "task_id": task_data.get('id') if 'task_data' in locals() else "unknown",
            "success": False,
            "error": str(e)
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "agent": "simple_agent"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
```

**Install Flask and Start Your Agent:**

```bash
pip install flask
python simple_agent.py
```

### **Step 3: Configure Benchmark to Test Your Agent**

Edit the benchmark configuration:

```bash
nano autoppia_iwa_module/autoppia_iwa/entrypoints/benchmark/run.py
```

**Update the AGENTS section:**

```python
# 1) Agents (ports where your agents are listening)
AGENTS = [
    ApifiedWebAgent(id="1", name="MySimpleAgent", host="127.0.0.1", port=5000, timeout=120),
]

# 2) Projects to evaluate (by id from demo_web_projects)
PROJECT_IDS = [
    "work",        # Start with one project
    # "cinema",    # Add more as needed
    # "connect",   # Available: autozone, cinema, books, connect, work, etc.
]
```

### **Step 4: Run Benchmark with Your Agent**

```bash
cd autoppia_iwa_module
python -m autoppia_iwa.entrypoints.benchmark.run
```

**Watch your agent logs** - you should see requests coming in:

```
Received task: task_123
Task prompt: Click on the login button
```

**Watch benchmark logs** - you should see:

```
2025-01-XX XX:XX:XX | INFO | MySimpleAgent | 100.00% (1/1) | avg 0.50s
```

✅ **Success**: Your agent is receiving tasks and responding!

---

## 🕷️ Web Agent Development

### **Understanding Tasks**

Tasks contain:

- `id`: Unique task identifier
- `prompt`: Human-readable instruction
- `specifications`: Screen dimensions, target URL, etc.
- `use_case`: Category of task (login, form_filling, etc.)

### **Available Actions**

Your web agents can use these actions:

| Action        | Description                | Example Use Case      |
| ------------- | -------------------------- | --------------------- |
| `click`       | Mouse click at coordinates | Button interactions   |
| `type`        | Text input                 | Form filling          |
| `navigate`    | URL navigation             | Page changes          |
| `screenshot`  | Screen capture             | State verification    |
| `wait`        | Pause execution            | Loading waits         |
| `assert`      | Condition verification     | Task validation       |
| `hover`       | Mouse hover                | Tooltip triggers      |
| `dragAndDrop` | Drag and drop              | File uploads, sorting |
| `submit`      | Form submission            | Data sending          |
| `doubleClick` | Double click               | File opening          |
| `scroll`      | Page scrolling             | Content viewing       |
| `select`      | Dropdown selection         | Option choosing       |

### **Agent Development Tips**

- 🧠 **Start Simple**: Begin with basic click/type actions
- 🎯 **Parse Prompts**: Extract intent from task descriptions
- 🌐 **Handle Errors**: Implement robust error handling
- ✅ **Test Thoroughly**: Use benchmark for continuous testing
- 📊 **Monitor Performance**: Track success rates and speed

### **Performance Targets**

Aim for:

- **Success Rate**: >80% task completion
- **Speed**: <5 seconds per task
- **Quality**: Complete and correct solutions

### **Iterative Development**

1. **Run benchmark** → See performance metrics
2. **Analyze failures** → Check task logs and solutions
3. **Improve agent logic** → Fix identified issues
4. **Repeat** → Continuous improvement cycle

---

# ⛏️ PHASE 2: MINER DEPLOYMENT

## 🚀 Deploy Your Miner to Mainnet

> **Prerequisites**: Only deploy to mainnet after thorough local testing with the benchmark!

### **Before Deploying**

Ensure your agent:

- ✅ **Passes benchmark tests** with >80% success rate
- ✅ **Handles all task types** you plan to support
- ✅ **Responds within time limits** (<30 seconds per task)
- ✅ **Has been tested** with multiple project types

### **Miner Setup & Deployment**

**First, setup the miner environment:**

```bash
# Install miner dependencies
chmod +x scripts/miner/install_dependencies.sh
./scripts/miner/install_dependencies.sh

# Setup miner environment
chmod +x scripts/miner/setup.sh
./scripts/miner/setup.sh
```

**Then deploy your miner:**

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

## 🏆 Understanding Mining & Rewards

### **What is a Miner?**

A **Miner** is your deployed web agent that:

- 📥 **Receives tasks** from validators on the network
- 🧠 **Processes** task requirements using your agent logic
- 📤 **Returns** action sequences to accomplish tasks
- 💰 **Earns rewards** based on performance

### **Reward Factors**

Miners are rewarded based on:

- **📊 Task Completion Rate**: Primary factor
- **🎯 Completion Quality**: Complete solutions required
- **⚡ Execution Speed**: Faster solutions get higher rewards
- **🏁 Competitive Performance**: Relative to other miners

### **Success Metrics**

| Metric            | Target | Description                   |
| ----------------- | ------ | ----------------------------- |
| **Success Rate**  | >80%   | Percentage of completed tasks |
| **Response Time** | <5s    | Average time per task         |
| **Quality Score** | >0.8   | Completeness and correctness  |
| **Uptime**        | >99%   | Agent availability            |

---

## 🎯 Quick Start Summary

### **Local Testing (30 minutes)**

1. **Setup** (10 min):

   ```bash
   git clone https://github.com/autoppia/autoppia_web_agents_subnet
   cd autoppia_web_agents_subnet
   cp .env.example .env  # Add OpenAI or Chutes API key
   cd autoppia_iwa_module && pip install -e .  # Install validator dependencies
   ```

2. **Deploy Demo Projects** (5 min):

   ```bash
   chmod +x autoppia_iwa_module/modules/webs_demo/scripts/setup.sh
   ./autoppia_iwa_module/modules/webs_demo/scripts/setup.sh
   ```

3. **Test Task Generation** (5 min):

   ```bash
   cd autoppia_iwa_module
   python -m autoppia_iwa.entrypoints.benchmark.run
   ```

4. **Create Your Agent** (10 min):
   - Create Flask app with `/solve_task` endpoint
   - Configure benchmark to use your agent
   - Run benchmark to test your agent

### **Miner Deployment (when ready)**

5. **Setup Miner Environment**:

   ```bash
   chmod +x scripts/miner/setup.sh && ./scripts/miner/setup.sh
   ```

6. **Deploy to Mainnet**:
   - Ensure agent passes benchmark tests
   - Deploy miner with PM2
   - Monitor performance and rewards

### **Key Benefits**

- ✅ **No testnet required** - develop locally first
- ✅ **Free development** - no network fees for testing
- ✅ **Instant feedback** - immediate performance metrics
- ✅ **Production-ready** - benchmark = production behavior
- ✅ **Risk-free iteration** - test before deploying

---

## 🆘 Support & Contact

Need assistance? Contact our team on Discord:

- **@Daryxx**
- **@Riiveer**

---

## 📚 Additional Resources

- **📖 Benchmark Documentation**: `autoppia_iwa_module/autoppia_iwa/entrypoints/benchmark/README.md`
- **🔧 Agent Examples**: Check the `examples/` directory
- **📊 Performance Monitoring**: Use benchmark results to track progress
- **🔄 Continuous Integration**: Set up automated benchmark testing
