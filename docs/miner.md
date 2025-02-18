# Miner Guide

This guide explains how to set up and run your miner for Subnet 36 Web Agents.

---

## System Requirements

The **basic miner code** can run on virtually any system with Python support, including **CPU-only machines**. However, **competitive mining** in this subnet typically requires more robust hardware depending on your Web Agent implementation.

Your actual hardware requirements will be determined by:

- The **complexity** of your Web Agent solution
- Whether you're using **LLMs** for task understanding
- The type of **web automation** you're implementing
- The competitive landscape of the subnet

While you can start with **minimal hardware**, successful miners typically invest in better hardware (**GPUs**, more **RAM**, etc.) as they develop more sophisticated Web Agent solutions.

---

## Installation Steps

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

### 3. Run the Setup Script

This setup has been tested on ubuntu "jammy" and "noble" distributions.
Make the setup script executable and run it:

```bash
chmod +x scripts/miner/setup.sh
./scripts/miner/setup.sh
```

This script will:

- Install system dependencies
- Set up Python 3.11 environment
- Install and configure PM2
- Create and activate a virtual environment
- Install required Python packages including the autoppia_iwa package
- Set up Bittensor and other dependencies

If you are on runpod or other dockerized env:

```bash
chmod +x scripts/miner/runpod_setup.sh
./scripts/miner/runpod_setup.sh
```

Beware that this script has not being tested exhaustively.


### 4. Start the Miner with PM2

Use PM2 to run the miner with your configuration:

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

#### Common Configuration Options

- `--name`: PM2 process name (can be any name you choose)
- `--netuid`: Network UID (36 for this subnet)
- `--wallet.name`: Your coldkey name
- `--wallet.hotkey`: Your hotkey name
- `--axon.port`: Port for miner communication (default: 8091)
- `--logging.debug`: Enable debug logging
- `--subtensor.network`: Network to connect to (e.g., finney, local)

---

## Optional Components

If you want to develop competitive web agents you will surely need to deploy demo-webs

### 1. Deploy LLM Generation Endpoint

Before proceeding with any installation steps, verify your CUDA version:

```bash
nvcc --version
```

⚠️ **CRITICAL**: The output should show version 12.1. If you have a different version or CUDA is not installed, please install CUDA 12.1 before continuing.

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

These components are suggestions that may help with development and testing but are not required for mining.

---

## Understanding Web Agents

### What is a Web Agent?

A Web Agent is an application that receives web tasks and returns a list of actions to accomplish those tasks. Web Agents are designed to understand and interact with web interfaces programmatically.

### Available Actions

Web Agents can perform various actions defined in the `ACTION_CLASS_MAP`. These include:

- `click`: Performs a mouse click at specified coordinates
- `type`: Types text into form fields
- `hover`: Moves mouse over an element
- `navigate`: Navigates to a URL
- `dragAndDrop`: Performs drag and drop operations
- `submit`: Submits forms
- `doubleClick`: Performs a double click
- `scroll`: Scrolls the page
- `screenshot`: Takes a screenshot
- `wait`: Waits for a specified duration
- `assert`: Verifies conditions
- `select`: Selects options from dropdowns

For detailed information about action parameters and usage, refer to `/autoppia_iwa/src/execution/actions/actions.py`.

### Default Web Agent: RandomClicker

The repository includes a basic RandomClicker Web Agent that demonstrates the structure of a Web Agent:

```python
class RandomClickerWebAgent(IWebAgent):
    """
    Web Agent that executes random actions within the screen dimensions.
    """
    def __init__(self):
        pass

    def generate_actions(self, task: Task) -> TaskSolution:
        """
        Generates a list of random click actions within the screen dimensions.
        """
        actions = []
        for _ in range(1):  # Generate random click action
            x = random.randint(0, task.specifications.screen_width - 1)
            y = random.randint(0, task.specifications.screen_height - 1)
            actions.append(ClickAction(x=x, y=y))
        return TaskSolution(task=task, actions=actions)
```

While this RandomClicker doesn't meaningfully solve tasks, it serves as a useful example of:

- The basic Web Agent interface
- How to receive and process tasks
- How to generate and return actions
- The expected structure of a Web Agent implementation

To be competitive in this subnet, miners need to develop sophisticated Web Agents that can:

- Understand complex web tasks
- Generate appropriate sequences of actions
- Navigate and interact with web interfaces effectively
- Verify task completion successfully

---

## Reward Mechanism

Miners in Subnet 36 are rewarded based on their Web Agents' performance across multiple factors:

1. **Task Completion Rate**: The primary factor is the number of web tasks your agent can successfully complete.
2. **Completion Quality**: Tasks must be solved completely and correctly - partial solutions receive proportionally lower rewards.
3. **Execution Time**: The speed at which your agent completes tasks affects rewards - faster solutions are rewarded more highly.

The reward function is designed to incentivize the development of efficient, reliable Web Agents that can handle a wide variety of web tasks. For detailed implementation of the reward calculations, you can examine `src/validator/reward.py`.

**Note**: The competitive nature of the subnet means that rewards are relative to other miners' performance. Continuous improvement of your Web Agent is key to maintaining competitive rewards.

---

## Support

For additional help:

- Contact **@Daryxx**, **@Riiveer**, or **@Miguelik** on Discord channel if there is any problem
