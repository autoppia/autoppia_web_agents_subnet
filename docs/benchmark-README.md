# 🔬 Benchmark Framework for Autoppia IWA

> **Note**: This is a copy of the benchmark README from the `autoppia_iwa_module` submodule for GitHub accessibility.
> **Original location**: `autoppia_iwa_module/autoppia_iwa/entrypoints/benchmark/README.md`

> **Purpose**: Test your web agents locally before deploying to mainnet. Simulates validator behavior without network requirements.

## 📋 Quick Overview

**What it does:**

- 🎯 **Generates tasks** for demo web projects
- 🚀 **Sends tasks** to your local agents
- 📊 **Evaluates solutions** using validator logic
- 📈 **Compares agents** side by side

**What you need:**

1. **Demo web projects** running (e.g., `autoconnect`, `autocinema`)
2. **Your agent(s)** deployed on local ports
3. **Configuration** in `run.py`

---

## 📂 Directory Structure

```
entrypoints/benchmark/
├─ __init__.py
├─ config.py              # BenchmarkConfig dataclass
├─ tasks_generation.py     # Task generation/loading
├─ benchmark.py           # Main benchmark orchestrator
└─ run.py                 # Configuration & entry point
```

## 🕷️ What is a Web Agent?

A **Web Agent** is an application that:

- 📥 **Receive tasks** from validators
- 🧠 **Process requirements** using your logic
- 🎯 **Interacts** with web interfaces

- ✅ **Return a list of actions** (see actions allowed)
- 💰 **Earn rewards** based on performance
  programmatically

### **Task Structure**

Your agent receives a **Task** which consists of:

- **url**: The target URL to interact with
- **prompt**: The task you need to perform
- **id**: Unique task identifier
- **specifications**: Additional task details (screen dimensions, etc.)

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

---

## 🚀 Setup & Configuration

### **Step 1: Environment Setup**

```bash
# Clone repository
git clone https://github.com/autoppia/autoppia_web_agents_subnet
cd autoppia_web_agents_subnet
git submodule update --init --recursive --remote
```

### **Step 2: Environment Configuration**

```bash
# Create environment file
cp .env.example .env
```

**Configure LLM for task generation:**

**Option 1: OpenAI (Recommended)**

```bash
OPENAI_API_KEY="your_openai_api_key_here"
```

**Option 2: Chutes LLM**

```bash
LLM_PROVIDER=chutes
CHUTES_BASE_URL=https://your-username-your-chute.chutes.ai/v1
CHUTES_API_KEY=cpk_your_api_key_here
CHUTES_MODEL=meta-llama/Llama-3.1-8B-Instruct
CHUTES_MAX_TOKENS=2048
CHUTES_TEMPERATURE=0.7
CHUTES_USE_BEARER=False
```

⚠️ **Required**: LLM API key for task generation

### **Step 3: Install Dependencies**

```bash
# Install validator dependencies for benchmark
cd autoppia_iwa_module
pip install -e .
```

### **Step 4: Deploy Demo Projects**

✅ **Important**: Deploy the demo web applications before running benchmarks. These are required to evaluate agent actions and verify task completion.

```bash
# Deploy demo web applications for testing
chmod +x autoppia_iwa_module/modules/webs_demo/scripts/setup.sh
./autoppia_iwa_module/modules/webs_demo/scripts/setup.sh
```

**What this does:**

- 🐳 Installs Docker/Docker Compose
- 🚀 Deploys demo web containers
- 🔗 Sets up networking

---

## 🧪 Testing Your Agent

### **Step 1: Test Task Generation**

```bash
# Verify tasks are generated correctly
cd autoppia_iwa_module
python -m autoppia_iwa.entrypoints.benchmark.run
```

**Expected Output:**

```
2025-01-XX XX:XX:XX | INFO | === Project: work ===
2025-01-XX XX:XX:XX | INFO | Generated 6 tasks for project 'work'
2025-01-XX XX:XX:XX | SUCCESS | Task generation completed ✔
```

**Troubleshooting:**

- ❌ LLM API key set correctly?
- ❌ Demo projects running? (`docker ps`)
- ❌ Python environment activated?

### **Step 2: Create Your Agent**

**Create agent:**

```bash
mkdir -p my_agent
cd my_agent
nano simple_agent.py
```

**Basic Template:**

Your agent must implement a `solve_task` method that returns a list of actions in the format described earlier. The evaluator will execute these actions to verify task completion.

**Allowed actions:** See the action types list mentioned previously in this document.

```python
from flask import Flask, request, jsonify
import json

app = Flask(__name__)

@app.route('/solve_task', methods=['POST'])
def solve_task():
    """Main endpoint - receives tasks from benchmark/validators"""
    try:
        task_data = request.get_json()

        print(f"Received task: {task_data.get('id', 'unknown')}")
        print(f"Task prompt: {task_data.get('prompt', 'No prompt')}")

        # TODO: Implement your agent logic here

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
    return jsonify({"status": "healthy", "agent": "simple_agent"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
```

**Start agent:**

```bash
pip install flask
python simple_agent.py
```

**Expected output:**

```
* Running on all addresses (0.0.0.0)
* Running on http://127.0.0.1:5000
```

### **Step 3: Configure Benchmark**

```bash
# Edit benchmark configuration
nano autoppia_iwa_module/autoppia_iwa/entrypoints/benchmark/run.py
```

**Update configuration:**

```python
# Agents
AGENTS = [
    ApifiedWebAgent(id="1", name="MySimpleAgent", host="127.0.0.1", port=5000, timeout=120),
]

# Projects to test
PROJECT_IDS = [
    "work",        # Start with one project
    # "cinema",    # Add more as needed
    # "connect",   # Available: autozone, cinema, books, connect, work, etc.
]
```

### **Step 4: Run Benchmark**

```bash
# Test your agent
cd autoppia_iwa_module
python -m autoppia_iwa.entrypoints.benchmark.run
```

**Watch logs:**

**Agent logs:**

```
Received task: task_123
Task prompt: Click on the login button
```

**Benchmark logs:**

```
2025-01-XX XX:XX:XX | INFO | MySimpleAgent | 100.00% (1/1) | avg 0.50s
```

✅ **Success**: Agent receiving tasks and responding!

---

## ⚙️ Configuration

**Everything configured in code** - edit `run.py`:

### **Basic Setup**

```python
# 1) Your agents
AGENTS = [
    ApifiedWebAgent(id="1", name="MyAgent", host="127.0.0.1", port=5000, timeout=120),
    # ApifiedWebAgent(id="2", name="MyAgent2", host="127.0.0.1", port=7000, timeout=120),
]

# 2) Projects to test
PROJECT_IDS = ["connect"]  # Available: connect, cinema, work, books, etc.

# 3) Benchmark settings
CFG = BenchmarkConfig(
    projects=get_projects_by_ids(demo_web_projects, PROJECT_IDS),
    agents=AGENTS,
    runs=3,                      # Number of test runs
    max_parallel_agent_calls=1,  # Concurrency control
    save_results_json=True,      # Save results to JSON
)
```

### **Configuration Options**

| Parameter                  | Default | Description                                    |
| -------------------------- | ------- | ---------------------------------------------- |
| `use_cached_tasks`         | `False` | Load tasks from cache instead of generating    |
| `prompts_per_use_case`     | `1`     | Tasks per use case                             |
| `num_use_cases`            | `0`     | Use cases to test (0 = all)                    |
| `runs`                     | `1`     | Number of test runs                            |
| `max_parallel_agent_calls` | `1`     | Concurrent agent calls                         |
| `use_cached_solutions`     | `False` | Use cached solutions instead of calling agents |
| `record_gif`               | `False` | Save evaluation GIFs                           |
| `save_results_json`        | `True`  | Save results to JSON                           |
| `plot_results`             | `False` | Generate performance plots                     |

---

## 📊 How It Works

### **Step-by-Step Process**

**For each project:**

1. **Generate/Load Tasks**

   - **Cache**: `data/tasks_cache/<project>_tasks.json`
   - **Generate**: Via LLM pipeline → save to cache

2. **Solve Tasks**

   - **Send** tasks to configured agents
   - **Cache**: `data/solutions_cache/solutions.json` (optional)

3. **Evaluate Solutions**

   - **Score** each solution using validator logic
   - **Record**: GIFs saved to `recordings/<agent>/` (optional)

4. **Save Results**

   - **JSON**: `results/benchmark_results_<timestamp>.json`
   - **Plots**: `results/stress_test_chart_<timestamp>.png` (optional)

5. **Print Statistics**
   - **Per agent**: Success rate, average time
   - **Global**: Overall performance metrics

---

## 📁 Output Files

| File Type           | Location                                     | Description               |
| ------------------- | -------------------------------------------- | ------------------------- |
| **Tasks Cache**     | `data/tasks_cache/<project>_tasks.json`      | Generated tasks for reuse |
| **Solutions Cache** | `data/solutions_cache/solutions.json`        | Agent responses for reuse |
| **Results**         | `results/benchmark_results_<timestamp>.json` | Performance metrics       |
| **GIF Recordings**  | `recordings/<agent>/<task_id>_run_<n>.gif`   | Task execution videos     |
| **Plots**           | `results/stress_test_chart_<timestamp>.png`  | Performance charts        |

---

## 🛠️ Customization

### **Change Projects**

```python
PROJECT_IDS = ["cinema", "work"]  # Test different projects
```

### **Add More Agents**

```python
AGENTS = [
    ApifiedWebAgent(id="1", name="Agent1", host="127.0.0.1", port=5000, timeout=120),
    ApifiedWebAgent(id="2", name="Agent2", host="127.0.0.1", port=7000, timeout=120),
    ApifiedWebAgent(id="3", name="Agent3", host="127.0.0.1", port=8000, timeout=120),
]
```

### **Adjust Test Parameters**

```python
CFG = BenchmarkConfig(
    runs=5,                      # More test runs
    max_parallel_agent_calls=3,  # Higher concurrency
    record_gif=True,             # Enable GIF recording
    plot_results=True,           # Generate charts
)
```

## ✅ Summary

**Key Features:**

- ✅ **Code-based configuration** - no CLI needed
- ✅ **Cache-aware** - reuse tasks and solutions
- ✅ **Multi-agent support** - compare agents side by side
- ✅ **Rich outputs** - JSON reports, GIFs, plots
- ✅ **Flexible testing** - adjust runs, concurrency, projects

**Main configuration file:** `run.py` - edit this to customize your benchmark runs.
