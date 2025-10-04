# Test Forward Simple

## Overview

The `test_forward_simple.py` script is a **simplified simulation** that tests the validator's pre-generation and dynamic loop system **without bittensor dependencies**. This script accurately reproduces the validator's behavior locally for testing purposes.

## What It Does

### 1. **Pre-Generation Phase**

- Generates all tasks at the beginning of the round
- Creates mock tasks with different projects (movies, books, autozone, etc.)
- Avoids on-the-fly generation errors

### 2. **Dynamic Task Execution**

- Simulates the validator's dynamic loop
- Sends tasks to simulated miners
- Miners return actions (not scores directly)
- Evaluator scores the actions based on miner skill level
- Accumulates scores across all tasks

### 3. **Safety Buffer System**

- Calculates absolute limit: `start + round_size - safety_buffer`
- Stops task generation when approaching the limit
- Waits for target epoch to set weights

### 4. **Winner Takes All (WTA)**

- Calculates average scores per miner
- Applies WTA: only the best miner gets rewards
- Shows detailed statistics

## Key Components

### MockTask

```python
class MockTask:
    """Simulates a task"""
    def __init__(self, task_id: int, project: str):
        self.id = f"task_{task_id}"
        self.prompt = f"Task {task_id}: Perform action on {project}"
        self.project = project
        self.url = f"http://{project}.com"
```

### MockAction

```python
class MockAction:
    """Simulates a miner action"""
    def __init__(self, action_type: str, target: str, value: str = ""):
        self.action_type = action_type  # "click", "type", "scroll", etc.
        self.target = target           # selector, xpath, etc.
        self.value = value            # text to write, etc.
```

### MockMiner

- Each miner has a skill level (0.0 - 1.0)
- `solve_task()` returns a list of actions
- More skilled miners generate better actions

### MockEvaluator

- Takes miner actions and skill level
- Calculates realistic scores with noise
- Simulates execution time based on action count

## Configuration

```python
@dataclass
class SimulationConfig:
    """Simulation configuration"""
    num_tasks: int = 100            # Number of tasks to pre-generate
    num_miners: int = 4              # Number of simulated miners
    round_size_epochs: int = 2       # Round duration in epochs
    avg_task_duration: float = 120    # Average task duration in seconds
    safety_buffer_epochs: float = 0.2  # Safety buffer
    task_execution_time: float = 20   # Real execution time per task
```

## Usage

### Basic Usage

```bash
python3 scripts/test_forward_simple.py
```

### Custom Parameters

```bash
python3 scripts/test_forward_simple.py \
    --num-tasks 100 \
    --num-miners 4 \
    --round-epochs 2 \
    --avg-duration 120 \
    --task-time 20
```

### Parameters

- `--num-tasks`: Number of tasks to pre-generate (default: 100)
- `--num-miners`: Number of miners to simulate (default: 5)
- `--round-epochs`: Round duration in epochs (default: 2)
- `--avg-duration`: Average task duration in seconds (default: 30)
- `--task-time`: Real execution time per task (default: 5)

## Example Output

```
================================================================================
🎮 FORWARD SIMULATION INITIALIZED
================================================================================
   Miners: 4
   Pre-generated tasks: 100
   Round size: 2 epochs
   Avg task duration: 120.0s
   Safety buffer: 0.2 epochs

   Miner skills:
      Miner 0: skill=0.85
      Miner 1: skill=0.50
      Miner 2: skill=0.80
      Miner 3: skill=0.57
================================================================================

🔄 PRE-GENERATING TASKS
================================================================================
✅ Pre-generation complete: 100 tasks in 0.000s
================================================================================

🎯 STARTING DYNAMIC TASK EXECUTION
   Total pre-generated tasks: 100
================================================================================

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📍 TASK 1/100 | Epoch 0.00/2 | Time remaining: 144.0 min
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Task: Task 1: Perform action on movies
   Sending to 4 miners...
   🏆 Best miner: 2 (score: 0.990)
   📊 Task scores:
      Miner 0: 0.750 (exec_time: 0.9s, actions: 7)
      Miner 1: 0.570 (exec_time: 1.4s, actions: 6)
      Miner 2: 0.990 (exec_time: 0.9s, actions: 5)
      Miner 3: 0.600 (exec_time: 1.1s, actions: 6)
   🔍 Winner actions: ['type(div-0)', 'click(div-1)', 'wait(input-2)']...
✅ Completed task 1/100 in 2.0s
```

## Safety Buffer Behavior

The safety buffer ensures the validator stops generating tasks before the round ends:

```
🛑 STOPPING TASK EXECUTION - SAFETY BUFFER REACHED
   Reason: Insufficient time remaining for another task
   Current epoch: 1.75
   Time remaining: 1080s
   Safety buffer: 0.2 epochs
   Tasks completed: 64/100
   ⏳ Now waiting for target epoch to set weights...
```

## Final Results

```
================================================================================
📊 AVERAGE SCORES (before WTA)
================================================================================
   Miner 0: avg=0.849, tasks=64, skill=0.853
   Miner 1: avg=0.498, tasks=64, skill=0.498
   Miner 2: avg=0.819, tasks=64, skill=0.802
   Miner 3: avg=0.622, tasks=64, skill=0.570

================================================================================
🏆 WTA RESULTS
================================================================================
   🥇 WINNER: Miner 0
      Score: 1.000
      Skill: 0.853
      Tasks completed: 64

   All WTA scores:
      🥇 Miner 0: 1.000
         Miner 1: 0.000
         Miner 2: 0.000
         Miner 3: 0.000
================================================================================

================================================================================
✅ SIMULATION COMPLETE
================================================================================
   Total tasks pre-generated: 100
   Tasks completed: 64
   Completion rate: 64.0%
   Final epoch: 2.00
================================================================================
```

## Key Features

### ✅ **Working Features**

- Pre-generation of all tasks
- Dynamic task execution with time checking
- Realistic miner-evaluator interaction
- Safety buffer system
- WTA reward mechanism
- Detailed logging and statistics

### ❌ **Not Working**

- `test_forward_simulation.py` - Has dependency conflicts (NumPy/Pydantic)

## Differences from Real Validator

1. **No Network Communication**: Uses local mocks instead of real miners
2. **Simplified Task Generation**: Creates basic mock tasks
3. **Simulated Time**: Uses configurable execution times
4. **No Bittensor Dependencies**: Avoids dependency conflicts

## Testing Scenarios

### Test Safety Buffer

```bash
python3 scripts/test_forward_simple.py --num-tasks 100 --round-epochs 2 --avg-duration 120 --task-time 20
```

### Test Short Round

```bash
python3 scripts/test_forward_simple.py --num-tasks 50 --round-epochs 1 --avg-duration 60 --task-time 10
```

### Test Many Miners

```bash
python3 scripts/test_forward_simple.py --num-tasks 100 --num-miners 10 --round-epochs 2
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Make sure you're in the project root directory
2. **Permission Errors**: Use `python3` instead of `python`
3. **Parameter Errors**: Check parameter names and types

### Dependencies

- Python 3.8+
- numpy
- asyncio (built-in)
- argparse (built-in)
- dataclasses (built-in)

## Integration with Real Validator

This simulation script mirrors the real validator's behavior in:

- `autoppia_web_agents_subnet/validator/forward.py`
- `autoppia_web_agents_subnet/validator/round_calculator.py`
- `autoppia_web_agents_subnet/validator/rewards.py`

The logic is identical, but uses mocks instead of real components.
