# Round-Based System for AutoPPIA Web Agents Subnet

## Overview

This document explains the round-based system implemented in the AutoPPIA Web Agents subnet. The system is designed to run long-duration rounds (e.g., 24 hours) with pre-generated tasks and dynamic task execution based on time remaining.

## Key Concepts

### Round

- **Duration**: Configurable in epochs (default: 20 epochs ≈ 24 hours)
- **Purpose**: Accumulate scores from multiple tasks and set weights once at the end
- **Synchronization**: All validators start rounds at the same epoch boundaries

### Epoch

- **Definition**: 360 blocks in Bittensor
- **Duration**: ~72 minutes per epoch
- **Calculation**: `epoch = block_number / 360`

### Forward

- **Definition**: A single execution cycle that spans an entire round
- **Process**: Pre-generate tasks → Execute dynamically → Accumulate scores → Set weights

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    ROUND EXECUTION                          │
├─────────────────────────────────────────────────────────────┤
│ 1. Pre-generate all tasks (120 tasks by default)           │
│ 2. Dynamic task execution loop:                            │
│    - Send task to miners                                   │
│    - Evaluate responses                                    │
│    - Accumulate scores                                     │
│    - Check if time remaining for next task                 │
│ 3. Wait for target epoch                                   │
│ 4. Apply WTA and set weights                               │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

### Core Parameters

```python
# Round Configuration
ROUND_SIZE_EPOCHS = 20              # Round duration in epochs (~24h)
SAFETY_BUFFER_EPOCHS = 0.5          # Safety buffer before target epoch
AVG_TASK_DURATION_SECONDS = 600     # Average task execution time
PRE_GENERATED_TASKS = 120           # Tasks to pre-generate

# Task Configuration
PROMPTS_PER_USECASE = 1             # Prompts per use case
MAX_ACTIONS_LENGTH = 30             # Maximum actions per solution
```

### Time Calculations

- **Total Round Time**: `ROUND_SIZE_EPOCHS × 360 blocks × 12 seconds/block`
- **Available Time**: `(ROUND_SIZE_EPOCHS - SAFETY_BUFFER_EPOCHS) × 360 × 12`
- **Estimated Tasks**: `Available Time / AVG_TASK_DURATION_SECONDS`

## Dynamic Task Execution

### Safety Buffer Logic

The system stops sending new tasks when:

```
current_block >= start_block + total_round_blocks - safety_buffer_blocks
```

This ensures all tasks complete before the target epoch.

### Task Flow

1. **Pre-generation**: Generate all tasks at round start
2. **Execution Loop**:
   - Send task to all active miners
   - Collect responses (actions)
   - Evaluate actions and calculate scores
   - Accumulate scores for each miner
   - Check if time remaining for next task
3. **Completion**: Stop when safety buffer reached
4. **Waiting**: Wait until target epoch
5. **Finalization**: Apply WTA and set weights

## Winner Takes All (WTA)

### Scoring Process

1. **Accumulation**: Each miner's scores are averaged across all completed tasks
2. **Comparison**: Compare average scores across all miners
3. **Selection**: Miner with highest average score wins
4. **Reward**: Winner gets 1.0, others get 0.0

### Example

```
Miner 0: [0.85, 0.90, 0.88] → Average: 0.877
Miner 1: [0.92, 0.89, 0.91] → Average: 0.907 ← WINNER
Miner 2: [0.78, 0.82, 0.80] → Average: 0.800

WTA Result: [0.0, 1.0, 0.0]
```

## Implementation Files

### Core Files

- **`config.py`**: Round system configuration
- **`forward.py`**: Main round execution logic
- **`round_calculator.py`**: Time and epoch calculations
- **`rewards.py`**: WTA reward calculation

### Key Classes

- **`RoundCalculator`**: Handles epoch/block conversions and time calculations
- **`ForwardSimulator`**: Orchestrates the entire round execution

## Usage

### Running a Round

```python
# The validator automatically starts rounds at epoch boundaries
# No manual intervention required
```

### Configuration

```python
# Adjust these parameters in config.py
ROUND_SIZE_EPOCHS = 20              # Longer/shorter rounds
SAFETY_BUFFER_EPOCHS = 0.5          # More/less safety margin
PRE_GENERATED_TASKS = 120           # More/fewer tasks
```

## Testing

### Simulation Script

Use `scripts/test_forward_simple.py` to test the round system locally:

```bash
python3 scripts/test_forward_simple.py --num-tasks 100 --num-miners 4 --round-epochs 2
```

### Key Test Scenarios

1. **Normal Execution**: All tasks completed before safety buffer
2. **Safety Buffer Activation**: Tasks stop early due to time constraints
3. **WTA Verification**: Correct winner selection and reward distribution

## Monitoring

### Key Metrics

- **Task Completion Rate**: `completed_tasks / pre_generated_tasks`
- **Round Duration**: Actual time vs. configured time
- **Safety Buffer Activation**: How often early stopping occurs
- **WTA Accuracy**: Verification of winner selection

### Logging

The system provides detailed logging for:

- Round configuration and calculations
- Task execution progress
- Safety buffer activation
- Final WTA results

## Troubleshooting

### Common Issues

1. **Tasks Running Out**: Increase `PRE_GENERATED_TASKS`
2. **Safety Buffer Too Early**: Adjust `SAFETY_BUFFER_EPOCHS`
3. **Inaccurate Time Estimates**: Calibrate `AVG_TASK_DURATION_SECONDS`

### Calibration

1. Measure actual task execution times in production
2. Adjust `AVG_TASK_DURATION_SECONDS` accordingly
3. Monitor safety buffer activation frequency
4. Fine-tune `PRE_GENERATED_TASKS` based on completion rates

## Future Improvements

1. **Dynamic Task Generation**: Generate tasks on-demand instead of pre-generation
2. **Adaptive Safety Buffer**: Adjust buffer based on network conditions
3. **Multi-Round Optimization**: Learn from previous rounds to optimize parameters
4. **Real-time Monitoring**: Dashboard for round progress and metrics
