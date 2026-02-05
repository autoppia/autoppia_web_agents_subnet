# IWAP Integration Flow

Complete documentation of the integration flow between the Validator and the IWAP backend (Dashboard).

## Table of Contents

1. [General Overview](#general-overview)
2. [Phase 1: Handshake and Initialization](#phase-1-handshake-and-initialization)
3. [Phase 2: Task Evaluation](#phase-2-task-evaluation)
4. [Phase 3: Round Finalization](#phase-3-round-finalization)
5. [Offline Mode](#offline-mode)
6. [Database Tables](#database-tables)
7. [Flow Diagram](#flow-diagram)

---

## General Overview

The validator executes 3 main phases that synchronize with the IWAP backend:

```
Handshake → Evaluation → Finalization
    ↓           ↓            ↓
  IWAP        IWAP         IWAP
```

**Objective**: Keep the dashboard updated with real-time information about:
- Active rounds (season/round)
- Participating miners
- Executed tasks
- Detailed evaluations
- Final rankings and weights

---

## Phase 1: Handshake and Initialization

### 📍 Code Location
`validator.py` lines 80-90

### 🔄 Execution Flow

```python
# 1. Handshake with miners
await self._perform_handshake()
# Result: self.active_miner_uids = [42, 55, 78, ...]

# 2. Initialize round in IWAP
await self._iwap_start_round(current_block=current_block, n_tasks=n_tasks)

# 3. Register participating miners
await self._iwap_register_miners()
```

### 📡 Endpoints Called

#### 1.1. Start Round
**Endpoint**: `POST /api/v1/validator-rounds/start`

**Payload**:
```json
{
  "validator_identity": {
    "validator_uid": 1,
    "hotkey": "5FValidator...",
    "coldkey": "5CValidator..."
  },
  "validator_round": {
    "validator_round_id": "1/1",
    "season_number": 1,
    "round_number_in_season": 1,
    "start_block": 1000,
    "start_epoch": 100,
    "n_tasks": 5,
    "n_miners": 3,
    "started_at": 1234567890.0
  },
  "validator_snapshot": {
    "stake": 1000.5,
    "vtrust": 0.95,
    "incentive": 0.8,
    "dividends": 0.7
  }
}
```

**Tables Created**:
- ✅ `validator_rounds`
- ✅ `validator_round_validators`

---

#### 1.2. Set Tasks
**Endpoint**: `POST /api/v1/validator-rounds/{validator_round_id}/tasks`

**Payload**:
```json
{
  "tasks": [
    {
      "task_id": "task-001",
      "validator_round_id": "1/1",
      "url": "http://autocinema.com",
      "prompt": "Find and book a movie ticket",
      "tests": [
        {"type": "url_contains", "value": "/booking"},
        {"type": "element_exists", "selector": "#confirmation"}
      ],
      "metadata": {
        "project_name": "autocinema",
        "difficulty": "medium"
      }
    }
  ]
}
```

**Tables Created**:
- ✅ `tasks`

---

#### 1.3. Register Miners
**Endpoint**: `POST /api/v1/validator-rounds/{validator_round_id}/agent-runs/start`

**Called**: Once per active miner

**Payload** (example for miner_uid=42):
```json
{
  "miner_identity": {
    "miner_uid": 42,
    "miner_hotkey": "5F3sa...",
    "miner_coldkey": "5CMiner1..."
  },
  "miner_snapshot": {
    "agent_name": "AutoAgent-v1",
    "github_url": "https://github.com/user/agent",
    "image_url": "https://avatars.githubusercontent.com/...",
    "description": null
  },
  "agent_run": {
    "agent_run_id": "1/1_UID42",
    "validator_round_id": "1/1",
    "validator_uid": 1,
    "validator_hotkey": "5FValidator...",
    "miner_uid": 42,
    "miner_hotkey": "5F3sa...",
    "is_sota": false,
    "version": null,
    "started_at": 1234567890.0,
    "metadata": {
      "handshake_note": "Ready to evaluate"
    }
  }
}
```

**Tables Created**:
- ✅ `validator_round_miners`
- ✅ `miner_evaluation_runs` (also called `agent_evaluation_runs`)

---

## Phase 2: Task Evaluation

### 📍 Code Location
`validator/evaluation/mixin.py` lines 18-169

### 🔄 Execution Flow

```python
# 1. Deploy all agents
deployed_agents = {}  # {uid: (agent_info, agent_instance)}

# 2. For each task:
for task_item in season_tasks:
    # Evaluate all agents for this task
    for uid, (agent, agent_instance) in deployed_agents.items():
        score, exec_time, task_solution = await evaluate_with_stateful_cua(...)
    
    # Send results to IWAP
    await self._iwap_submit_task_results(
        task_item=task_item,
        task_solutions=[...],
        eval_scores=[...],
        execution_times=[...],
        rewards=[...]
    )
```

### 📡 Endpoint Called

#### 2.1. Add Evaluation
**Endpoint**: `POST /api/v1/validator-rounds/{validator_round_id}/agent-runs/{agent_run_id}/evaluations`

**Called**: Once per (miner, task) combination

**Payload** (example for miner_uid=42, task_id="task-001"):
```json
{
  "task": {
    "task_id": "task-001",
    "validator_round_id": "1/1",
    "url": "http://autocinema.com",
    "prompt": "Find and book a movie ticket",
    "tests": [...]
  },
  "task_solution": {
    "solution_id": "1/1_UID42_task-001",
    "task_id": "task-001",
    "agent_run_id": "1/1_UID42",
    "validator_round_id": "1/1",
    "validator_uid": 1,
    "validator_hotkey": "5FValidator...",
    "miner_uid": 42,
    "miner_hotkey": "5F3sa...",
    "actions": [
      {
        "type": "click",
        "selector": "#movie-123",
        "timestamp": 1234567891.5
      },
      {
        "type": "fill",
        "selector": "#seats",
        "value": "2",
        "timestamp": 1234567892.0
      }
    ],
    "recording": null,
    "metadata": {}
  },
  "evaluation": {
    "evaluation_id": "eval-1/1_UID42_task-001",
    "validator_round_id": "1/1",
    "agent_run_id": "1/1_UID42",
    "task_id": "task-001",
    "task_solution_id": "1/1_UID42_task-001",
    "validator_uid": 1,
    "miner_uid": 42,
    "eval_score": 0.85,
    "final_score": 0.85,
    "reward": 0.82,
    "evaluation_time": 5.3,
    "test_results": [
      {"success": true, "extra_data": null},
      {"success": true, "extra_data": null}
    ],
    "execution_history": [
      {"action": "click", "result": "success"},
      {"action": "fill", "result": "success"}
    ],
    "feedback": {
      "task_prompt": "Find and book a movie ticket",
      "final_score": 0.85,
      "executed_actions": 2,
      "failed_actions": 0,
      "passed_tests": 2,
      "failed_tests": 0,
      "total_execution_time": 5.3,
      "time_penalty": 0.0,
      "critical_test_penalty": 0
    },
    "stats": {
      "actions_count": 2,
      "avg_action_time": 2.65
    },
    "metadata": {}
  }
}
```

**Tables Created/Updated**:
- ✅ `task_solutions` (created)
- ✅ `evaluations` (created)
- ✅ `evaluations_execution_history` (created)
- ✅ `miner_evaluation_runs` (updated: `average_score`, `total_tasks`, `success_tasks`, `failed_tasks`)

---

## Phase 3: Round Finalization

### 📍 Code Location
`validator/settlement/mixin.py` lines 246-275

### 🔄 Execution Flow

```python
# 1. Calculate scores and weights
avg_rewards_array = np.zeros(self.metagraph.n)
for uid, score in valid_scores.items():
    avg_rewards_array[uid] = score

# 2. Apply WTA (Winner Takes All)
final_rewards_array = wta_rewards(avg_rewards_array)

# 3. Set weights on-chain
self.update_scores(rewards=final_rewards_array, uids=list(range(self.metagraph.n)))
self.set_weights()

# 4. Finalize in IWAP
await self._finish_iwap_round(
    avg_rewards=valid_scores,
    final_weights=final_weights_dict,
    tasks_completed=tasks_completed
)
```

### 📡 Endpoint Called

#### 3.1. Finish Round
**Endpoint**: `POST /api/v1/validator-rounds/{validator_round_id}/finish`

**Payload**:
```json
{
  "status": "finished",
  "ended_at": 1234568000.0,
  "summary": {
    "tasks": 5,
    "miners": 3,
    "completed": 3
  },
  "agent_runs": [
    {
      "agent_run_id": "1/1_UID42",
      "rank": 1,
      "weight": 0.7,
      "average_score": 0.85
    },
    {
      "agent_run_id": "1/1_UID55",
      "rank": 2,
      "weight": 0.3,
      "average_score": 0.72
    },
    {
      "agent_run_id": "1/1_UID78",
      "rank": 3,
      "weight": 0.0,
      "average_score": 0.45
    }
  ],
  "round": {
    "round_start_epoch_raw": 100.5,
    "target_epoch": 110,
    "miners_active": 3,
    "emission": {
      "total_emission": 1000.0,
      "validator_emission": 200.0,
      "miner_emission": 800.0
    }
  },
  "local_evaluation": {
    "42": 0.85,
    "55": 0.72,
    "78": 0.45
  },
  "post_consensus_evaluation": {
    "42": 0.85,
    "55": 0.72,
    "78": 0.45
  }
}
```

**Tables Updated/Created**:
- ✅ `validator_rounds` (updated: `status='finished'`, `ended_at`, `end_epoch`, `meta`)
- ✅ `miner_evaluation_runs` (updated: `ended_at`, `elapsed_sec`)
- ✅ `validator_round_summary_miners` (created: final summary with rank, weight, avg_reward)

---

## Offline Mode

### What is it?

**Offline mode** is a safety mechanism that allows the validator to continue functioning **even if the IWAP backend is down**.

### When is it activated?

In `start_round_flow()` line 127-146:

```python
try:
    await ctx.iwap_client.auth_check()
    ctx._iwap_offline_mode = False
except Exception as exc:
    ctx._iwap_offline_mode = True
    bt.logging.critical("🔴 CRITICAL: IWAP authentication FAILED - Continuing in OFFLINE mode")
```

### What does the validator do in offline mode?

| Action | Executed? | Notes |
|--------|-----------|-------|
| Handshake with miners | ✅ Yes | Continues normally |
| Task evaluation | ✅ Yes | Continues normally |
| Reward calculation | ✅ Yes | Continues normally |
| **Set weights on-chain** | ✅ **Yes** | **CRITICAL: Miners receive rewards** |
| IWAP API calls | ❌ No | All backend calls are skipped |
| Dashboard updates | ❌ No | Dashboard is not updated |

### Checks in each phase

All IWAP functions check for offline mode:

```python
# In register_participating_miners_in_iwap()
if getattr(ctx, "_iwap_offline_mode", False):
    log_iwap_phase("Register Miners", "⚠️ OFFLINE MODE: Skipping miner registration")
    return

# In submit_task_results()
if getattr(ctx, "_iwap_offline_mode", False):
    return

# In finish_round_flow()
if getattr(ctx, "_iwap_offline_mode", False):
    return
```

### Why is it important?

**Problem**: If the IWAP dashboard is down, the validator CANNOT stop because:
- Other validators are evaluating
- On-chain consensus is needed
- Miners are waiting to be evaluated and receive rewards

**Solution**: Offline mode allows:
- ✅ The validator to continue functioning
- ✅ Miners to be evaluated
- ✅ Weights to be set on-chain (BLOCKCHAIN)
- ✅ Consensus to be reached normally
- ❌ Only the dashboard is not updated (temporary)

---

## Database Tables

### Phase 1: Initialization

#### `validator_rounds`
Validator round information.

| Field | Type | Description |
|-------|------|-------------|
| `validator_round_id` | String | Unique ID (e.g., "1/1") |
| `season_number` | Integer | Season number (e.g., 1) |
| `round_number_in_season` | Integer | Round number within season (e.g., 1) |
| `validator_uid` | Integer | Validator UID |
| `validator_hotkey` | String | Validator hotkey |
| `start_block` | Integer | Start block |
| `start_epoch` | Integer | Start epoch |
| `n_tasks` | Integer | Number of tasks |
| `n_miners` | Integer | Number of participating miners |
| `status` | String | Status: 'active', 'finished', etc. |
| `started_at` | Float | Start timestamp |
| `ended_at` | Float | End timestamp (null if active) |

#### `validator_round_validators`
Validator snapshot at round start.

| Field | Type | Description |
|-------|------|-------------|
| `validator_uid` | Integer | Validator UID |
| `validator_hotkey` | String | Validator hotkey |
| `validator_coldkey` | String | Validator coldkey |
| `stake` | Float | Validator stake |
| `vtrust` | Float | Validator trust |
| `incentive` | Float | Validator incentive |
| `dividends` | Float | Validator dividends |

#### `tasks`
Round tasks.

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | String | Unique task ID |
| `validator_round_id` | String | Round ID |
| `url` | String | Website URL |
| `prompt` | String | Task prompt |
| `tests` | JSON | Validation tests |
| `metadata` | JSON | Additional metadata |

#### `validator_round_miners`
Participating miners information.

| Field | Type | Description |
|-------|------|-------------|
| `miner_uid` | Integer | Miner UID |
| `miner_hotkey` | String | Miner hotkey |
| `miner_coldkey` | String | Miner coldkey |
| `agent_name` | String | Agent name (e.g., "AutoAgent-v1") |
| `github_url` | String | GitHub repository URL |
| `image_url` | String | Avatar URL |

#### `miner_evaluation_runs`
Miner evaluation runs (also called `agent_evaluation_runs`).

| Field | Type | Description |
|-------|------|-------------|
| `agent_run_id` | String | Unique run ID (e.g., "1/1_UID42") |
| `validator_round_id` | String | Round ID |
| `miner_uid` | Integer | Miner UID |
| `started_at` | Float | Start timestamp |
| `ended_at` | Float | End timestamp (null if active) |
| `average_score` | Float | Average score (updated in Phase 2 and 3) |
| `total_tasks` | Integer | Total evaluated tasks |
| `success_tasks` | Integer | Successful tasks |
| `failed_tasks` | Integer | Failed tasks |

---

### Phase 2: Evaluation

#### `task_solutions`
Miner task solutions.

| Field | Type | Description |
|-------|------|-------------|
| `solution_id` | String | Unique solution ID |
| `task_id` | String | Task ID |
| `agent_run_id` | String | Agent run ID |
| `validator_round_id` | String | Round ID |
| `miner_uid` | Integer | Miner UID |
| `actions` | JSON | List of executed actions |
| `recording` | String | Session recording (optional) |
| `metadata` | JSON | Additional metadata |

#### `evaluations`
Solution evaluations.

| Field | Type | Description |
|-------|------|-------------|
| `evaluation_id` | String | Unique evaluation ID |
| `task_id` | String | Task ID |
| `task_solution_id` | String | Solution ID |
| `agent_run_id` | String | Agent run ID |
| `validator_round_id` | String | Round ID |
| `miner_uid` | Integer | Miner UID |
| `eval_score` | Float | Evaluation score (0-1) |
| `reward` | Float | Calculated reward |
| `evaluation_time` | Float | Evaluation time (seconds) |
| `test_results` | JSON | Test results |
| `feedback` | JSON | Detailed feedback |
| `stats` | JSON | Additional statistics |
| `metadata` | JSON | Additional metadata |

#### `evaluations_execution_history`
Evaluation execution history (separate table for performance).

| Field | Type | Description |
|-------|------|-------------|
| `evaluations_id` | Integer | Evaluation ID (FK) |
| `execution_history` | JSON | Complete action history |

---

### Phase 3: Finalization

#### `validator_round_summary_miners`
Final round summary per miner.

| Field | Type | Description |
|-------|------|-------------|
| `validator_round_id` | String | Round ID |
| `miner_uid` | Integer | Miner UID |
| `rank` | Integer | Final position (1, 2, 3, ...) |
| `weight` | Float | Assigned weight (0-1) |
| `avg_reward` | Float | Average reward |
| `total_tasks` | Integer | Total tasks |
| `success_tasks` | Integer | Successful tasks |
| `failed_tasks` | Integer | Failed tasks |

---

## Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    VALIDATOR FORWARD()                      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 1: HANDSHAKE AND INITIALIZATION                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. _perform_handshake()                                    │
│     └─► active_miner_uids = [42, 55, 78]                   │
│                                                             │
│  2. _iwap_start_round()                                     │
│     ├─► POST /api/v1/validator-rounds/start                │
│     │   └─► Creates: validator_rounds, validator_round_validators│
│     └─► POST /api/v1/validator-rounds/{id}/tasks           │
│         └─► Creates: tasks                                  │
│                                                             │
│  3. _iwap_register_miners()                                 │
│     └─► For each miner:                                     │
│         └─► POST /api/v1/validator-rounds/{id}/agent-runs/start│
│             └─► Creates: validator_round_miners,             │
│                       miner_evaluation_runs                 │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2: TASK EVALUATION                                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Deploy agents                                           │
│     └─► deployed_agents = {42: agent1, 55: agent2, ...}    │
│                                                             │
│  2. For each task:                                          │
│     ├─► Evaluate all agents                                │
│     │   └─► score, exec_time, task_solution = evaluate()    │
│     │                                                       │
│     └─► _iwap_submit_task_results()                         │
│         └─► For each miner:                                │
│             └─► POST /api/v1/validator-rounds/{id}/agent-runs/{agent_run_id}/evaluations│
│                 └─► Creates: task_solutions, evaluations,   │
│                           evaluations_execution_history    │
│                 └─► Updates: miner_evaluation_runs          │
│                                (average_score, total_tasks) │
│                                                             │
│  3. Cleanup agents                                          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 3: ROUND FINALIZATION                                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Calculate scores and weights                            │
│     ├─► avg_rewards_array                                   │
│     └─► final_rewards_array (WTA)                           │
│                                                             │
│  2. Set weights on-chain                                    │
│     ├─► update_scores()                                     │
│     └─► set_weights() ← CRITICAL: Blockchain                │
│                                                             │
│  3. _finish_iwap_round()                                    │
│     └─► POST /api/v1/validator-rounds/{id}/finish          │
│         └─► Updates: validator_rounds (status='finished')  │
│         └─► Updates: miner_evaluation_runs (ended_at)      │
│         └─► Creates: validator_round_summary_miners         │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
                    ✅ ROUND COMPLETE
```

---

## Offline Mode - Alternative Flow

```
┌─────────────────────────────────────────────────────────────┐
│ IWAP OFFLINE MODE                                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Detection:                                                 │
│  └─► await ctx.iwap_client.auth_check()                     │
│      └─► Exception: Connection refused                      │
│          └─► ctx._iwap_offline_mode = True                  │
│                                                             │
│  Behavior:                                                  │
│  ├─► ✅ Handshake with miners                              │
│  ├─► ✅ Task evaluation                                    │
│  ├─► ✅ Reward calculation                                  │
│  ├─► ✅ SET WEIGHTS ON-CHAIN ← CRITICAL                     │
│  │                                                          │
│  └─► ❌ NO IWAP calls:                                     │
│      ├─► register_participating_miners_in_iwap() → return  │
│      ├─► submit_task_results() → return                    │
│      └─► finish_round_flow() → return                      │
│                                                             │
│  Result:                                                    │
│  ├─► ✅ Validator functions normally                        │
│  ├─► ✅ Miners receive rewards on-chain                     │
│  └─► ❌ Dashboard not updated (temporary)                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Testing

Unit tests are located at: `tests/validator/unit/test_iwap_integration.py`

### Run tests

```bash
cd autoppia_web_agents_subnet
pytest tests/validator/unit/test_iwap_integration.py -v
```

### Included Tests

1. ✅ `test_register_participating_miners_success` - Successful miner registration
2. ✅ `test_register_miners_offline_mode` - Offline mode skips registration
3. ✅ `test_register_miners_no_active_miners` - Handles empty list
4. ✅ `test_register_miners_handles_duplicate` - Handles 409 conflict
5. ✅ `test_register_miners_missing_handshake_data` - Handles missing data
6. ✅ `test_submit_task_results_success` - Successful result submission
7. ✅ `test_submit_task_results_offline_mode` - Offline mode skips submission
8. ✅ `test_offline_mode_detection` - Detects IWAP downtime
9. ✅ `test_full_integration_flow` - Complete integration flow

---

## Quick Summary

| Phase | Endpoint | Tables Created/Updated |
|-------|----------|----------------------|
| **1. Handshake** | `POST /validator-rounds/start` | `validator_rounds`, `validator_round_validators` |
| | `POST /validator-rounds/{id}/tasks` | `tasks` |
| | `POST /validator-rounds/{id}/agent-runs/start` | `validator_round_miners`, `miner_evaluation_runs` |
| **2. Evaluation** | `POST /validator-rounds/{id}/agent-runs/{agent_run_id}/evaluations` | `task_solutions`, `evaluations`, `evaluations_execution_history` |
| | | Updates: `miner_evaluation_runs` |
| **3. Finalization** | `POST /validator-rounds/{id}/finish` | `validator_round_summary_miners` |
| | | Updates: `validator_rounds`, `miner_evaluation_runs` |

---

## Contact and Support

For questions or issues related to IWAP integration:
- Check validator logs: `logs/app.log`
- Verify IWAP status: `curl -X GET http://iwap-backend/health`
- Check offline mode: Search for "OFFLINE MODE" in logs

---

**Last updated**: 2026-02-04
