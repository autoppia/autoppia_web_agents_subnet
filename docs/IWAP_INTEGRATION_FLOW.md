# IWAP Integration Flow (Current Subnet Implementation)

This document reflects the current integration used by `autoppia_web_agents_subnet` with IWAP.

## Overview

Current validator ↔ IWAP flow:

1. `auth-check` (health / auth gate)
2. `start_round`
3. `set_tasks`
4. `start_agent_run` for each active miner
5. Local evaluation
6. Submit evaluations in batch
7. Upload task logs and evaluation GIFs
8. `finish_round`

If `auth-check` fails, the validator runs in **offline mode** (continues scoring/weights, but skips IWAP writes).

---

## 1) Auth + Session Start

### 1.1 `POST /api/v1/validator-rounds/auth-check`

- Executed at round start.
- Used to validate that IWAP is reachable and authentication works.
- On success → `ctx._iwap_offline_mode = False`.
- On failure → `ctx._iwap_offline_mode = True` and validator continues without dashboard sync.

### 1.2 `POST /api/v1/validator-rounds/start`

Called from `platform.utils.round_flow._iwap_start_round`.

Body includes:

- `validator_identity`
- `validator_round` (`validator_round_id`, season, round_in_season, blocks/epochs, start values)
- `validator_snapshot` (stake, vtrust, etc.)

`force=true` is added automatically when `TESTING` mode is enabled.

---

## 2) Task Registration

### 2.1 `POST /api/v1/validator-rounds/{validator_round_id}/tasks`

Called with:

- `tasks: TaskIWAP[]` where each task includes:
  - `task_id`
  - prompt / instructions
  - `url`
  - tests/validation criteria
  - metadata

This is how the backend receives the exact round tasks used by miners for evaluation.

---

## 3) Miner Registration

### 3.1 `POST /api/v1/validator-rounds/{validator_round_id}/agent-runs/start`

Called once per active miner during handshake flow.

Payload:

- `miner_identity` (uid, hotkeys)
- `miner_snapshot` (agent name / github / image / metadata)
- `agent_run` (agent_run_id, round link, started_at, etc.)

If backend returns an existing run id (idempotent case), the client updates local `agent_run_id`.

---

## 4) Evaluation Submission

### 4.1 Current path: `POST /api/v1/validator-rounds/{validator_round_id}/agent-runs/{agent_run_id}/evaluations/batch`

The current validator path submits evaluations grouped by miner (`agent_run_id`) in batch for performance.

Each item in the batch payload is an object with:

- `task` (round task payload)
- `task_solution` (action list / recording)
- `evaluation` (score, reward, time, IDs, etc.)
- `evaluation_result` (extended payload, backend compatibility shape)

This endpoint is called after all evaluator tasks for the miner are prepared and logged.

### 4.2 Note on non-batch path

There is still a single-evaluation client method in code (`add_evaluation`) that targets
`/evaluations`, but the active batch evaluator flow uses `evaluations/batch` and posts per miner.

---

## 5) Artifact Uploads (Task logs + GIFs)

### 5.1 Task logs

`POST /api/v1/task-logs`

- Executed for each `(task, miner)` when `UPLOAD_TASK_LOGS=true`.
- Contains structured execution metadata, actions, timings, and test outcomes used by IWAP/S3 storage.

### 5.2 Evaluation GIF

`POST /api/v1/evaluations/{evaluation_id}/gif`

- Called once per completed evaluation when a GIF is available.
- Uses multipart upload with binary GIF payload.

---

## 6) Round Finish

### 6.1 `POST /api/v1/validator-rounds/{validator_round_id}/finish`

Called in `platform.utils.round_flow.finish_round_flow` after:

- local rewards and local consensus data are computed
- pre-consensus and post-consensus miner summaries are assembled
- round metadata is generated

Payload shape includes:

- `status`
- `ended_at`
- `summary`
- `agent_runs` (per run ranking/avg reward/time and task counters)
- `round_metadata`
- `local_evaluation`
- `post_consensus_evaluation`
- `ipfs_uploaded`
- `ipfs_downloaded`

---

## 7) Offline Mode

If auth-check fails:

- handshake and evaluation still run normally
- ranking / on-chain weight update still happens
- IWAP sync calls are skipped:
  - start/set/agent-run
  - batch eval submission
  - task logs + gifs
  - finish_round

You can detect this in logs by:

- `ctx._iwap_offline_mode = True`
- messages containing `OFFLINE MODE`

---

## 8) Notes on current task generation

- Task generation itself is independent from IWAP endpoint calls.
- IWAP receives exactly `n_tasks` that exist in round flow (`ctx.current_round_tasks` built from season tasks + `build_iwap_tasks`).
- The validator logs round start details and task ids to correlate against IWAP records.

---

## 9) Quick reference: key flow order

```text
auth-check
  -> start_round
     -> set_tasks
        -> start_agent_run (per active miner)
            -> evaluate tasks locally
               -> upload_task_log (optional)
               -> upload_evaluation_gif (optional)
            -> add_evaluations_batch (per miner)
  -> finish_round
```

---

## 10) Endpoints matrix (current)

| Step | Endpoint | Purpose |
|---|---|---|
| 1 | `POST /api/v1/validator-rounds/auth-check` | Validate IWAP auth/reachability |
| 2 | `POST /api/v1/validator-rounds/start` | Register round metadata |
| 3 | `POST /api/v1/validator-rounds/{validator_round_id}/tasks` | Register round tasks |
| 4 | `POST /api/v1/validator-rounds/{validator_round_id}/agent-runs/start` | Register miner run |
| 5 | `POST /api/v1/validator-rounds/{validator_round_id}/agent-runs/{agent_run_id}/evaluations/batch` | Persist evaluation results |
| 6 | `POST /api/v1/task-logs` | Persist structured task logs |
| 7 | `POST /api/v1/evaluations/{evaluation_id}/gif` | Upload GIF |
| 8 | `POST /api/v1/validator-rounds/{validator_round_id}/finish` | Persist round summary |

---

## 11) Related code locations

- `autoppia_web_agents_subnet/platform/client.py` (all IWAP client calls)
- `autoppia_web_agents_subnet/platform/utils/round_flow.py` (start/set/finish orchestration)
- `autoppia_web_agents_subnet/platform/utils/task_flow.py` (evaluation payload construction helpers)
- `autoppia_web_agents_subnet/validator/evaluation/mixin.py` (batch assembly + submit + logs/gif upload hooks)
- `autoppia_web_agents_subnet/platform/models.py` (IWAP payload models)
