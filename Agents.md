# Autoppia Web Agents – Operator Guide

This document explains how the subnet validator, IWAP integration, consensus workflow, and reporting/alerting stack fit together. Use it as context when operating locally, wiring new automations, or giving external agents (Codex, etc.) the information they need.

---

## IMPORTANT – Fail Fast Over Defensive Code

- Treat core dependencies and invariants as non-negotiable. If we cannot import/initialize a required module, crash loudly instead of logging and re-raising.
- **Do NOT** wrap critical imports or setup in blanket `try/except` that simply logs and rethrows; it only adds noise and hides the root cause. Example to avoid:

```python
try:
    from autoppia_iwa.src.bootstrap import AppBootstrap
except ImportError as exc:  # pragma: no cover - bootstrap only in runtime
    bt.logging.warning("autoppia_iwa bootstrap import failed; validator will exit")
    raise exc
```

The import should be unconditional so the process fails immediately when the dependency is missing. Apply the same philosophy to round calculations, IWAP payload parsing, and any path that must succeed for the validator to operate.

---

## 1. Repository Layout

| Path | Purpose |
|------|---------|
| `neurons/validator.py` | Main validator loop: handshake, task execution, scoring, consensus publish, final weights. |
| `autoppia_web_agents_subnet/validator/` | Core utilities (config, round manager, consensus helpers, reward maths, models). |
| `autoppia_web_agents_subnet/platform/` | IWAP integration (round phases, HTTP client, logging helpers, finish-round orchestration). |
| `autoppia_web_agents_subnet/utils/` | Shared helpers (logging, commitments, env parsing, GIF handling, etc.). |
| `scripts/validator/reporting/` | Reporting, monitoring, Codex integration, and admin alert scripts. |
| `demo-webs` (Docker compose) | Local demo web applications used by miners during evaluation; start via docker-compose when needed. |

Environment defaults (round size, fractions, stake thresholds, endpoints) live in `autoppia_web_agents_subnet/validator/config.py` and are sourced from `.env`. Testing mode (`TESTING=true`) shortens rounds and disables stake requirements.

---

## 2. Validator Flow (Round Lifecycle)

Each round follows these steps (see `neurons/validator.py`):

1. **Initialization & Task Generation**
   - `RoundManager.start_new_round()` anchors the round start, using `ROUND_SIZE_EPOCHS` (0.2 epochs by default in testing: ~14.4 min).
   - Tasks are pre-generated (`PRE_GENERATED_TASKS`, 3 in testing) via `get_task_collection_interleaved`.
   - IWAP identities are registered (`IWAPClient.start_round`).

2. **Phase 1 – Handshake**
   - `send_start_round_synapse_to_miners` broadcasts the start signal; responders populate `active_miner_uids`.

3. **Phase 2 – Task Distribution**
   - Tasks are submitted through IWAP (`set_tasks`) and cached for local tracking.

4. **Phase 3 – Task Execution**
   - For each task, miners run agent simulations; validator waits for responses within `TIMEOUT`/`FEEDBACK_TIMEOUT`.
   - IWAP `start_agent_run` is called per miner to record progress.

5. **Phase 4 – Evaluation**
   - `evaluate_task_solutions` scores outputs (functional tests + heuristics).
   - Rewards combine evaluation scores and execution time (`validator/evaluation/rewards.calculate_rewards_for_task`).
   - GIFs and metadata upload through IWAP (Phase 4 logging: see `platform/utils/iwa_core.py`).
   - Results are stored in `RoundManager` accumulators and IWAP via `add_evaluation`.

6. **Phase 5 – Settlement & Boundary Wait**
   - Consensus snapshot publishes (when enabled), shared scores fetched, and final weights set (`validator/settlement/mixin.py`).
   - IWAP `finish_round` posts burn/weights summary to the Autoppia backend.
   - Validator idles in `WAITING` until the next round boundary before the loop restarts.

---

## 3. IWAP Integration (Phases & Contracts)

IWAP phases (see `platform/utils/iwa_core.py`):

| Phase | API Call | Purpose |
|-------|----------|---------|
| Phase 0 | `start_round` | Announce validator identity, round metadata, and snapshot. |
| Phase 2 | `set_tasks` | Submit the full list of prompts/tests to Autoppia. |
| Phase 3 | `start_agent_run` | Signal miners’ execution sessions with identity snapshots. |
| Phase 4 | `add_evaluation`, GIF logging | Upload evaluation payloads and optional GIF captures. |
| Phase 5 | `finish_round` | Post final weights, winners, burn summary, and round settlement metadata. |

All IWAP requests include validator-hotkey signature headers (set in `platform/client.IWAPClient` via `iwap_core.build_iwap_auth_headers`). GIF capture, uploads, and error logging happen per evaluation—stripe with `[Phase 4] [GIF]` entries in logs.

---

## 4. Distributed Consensus & Commitments

**Fractions & Timing (Testing defaults):**

| Setting | Value | Description |
|---------|-------|-------------|
| `STOP_TASK_EVALUATION_AND_UPLOAD_IPFS_AT_ROUND_FRACTION` | 0.65 | Stop task evaluation and upload to IPFS at 65% of round. |
| `FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION` | 0.75 | Fetch IPFS payloads and calculate consensus weights at 75% of round. |
| `SKIP_ROUND_IF_STARTED_AFTER_FRACTION` | 0.95 | Skip if starting too late (looser in testing). |
| `SAFETY_BUFFER_EPOCHS` | 0.02 | Buffer before the round boundary when we park and wait. |

**Publish Flow** (`validator/consensus.publish_round_snapshot`):
1. Aggregate task rewards → average scores per miner (`RoundManager.round_rewards`).
2. Build JSON payload with block window, epoch window, validator metadata.
3. Upload to IPFS via `aadd_json` → receives CID + SHA-256.
4. Commit the CID on-chain via `AsyncSubtensor.commit` (v4 payload).
5. On success, record `validator._consensus_commit_block` & `_consensus_commit_cid`.
6. On failure, warn and continue with local data (monitor + Codex highlight this as `ERROR`).

**Aggregation & Settlement**:
- At `FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION`, the validator fetches peer CIDs (`aggregate_scores_from_commitments`) and averages scores if stake thresholds are met (`MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO`). A final re-fetch is performed just before calculating weights to ensure all commits are included, and an immutable snapshot of consensus data is used for both weight calculation and IWAP submission to guarantee consistency.
- If all scores ≤ 0, or no miners responded, on-chain weights burn to `BURN_UID` with explanatory logs.

---

## 5. Evaluation & Scoring

Evaluation pipeline (`neurons/validator.py`, `validator/rewards.py`):

1. **Grouping**: Miners with identical action traces evaluated together (helps surface seed mismatches).
2. **Tests**: Functional checks per task (see log tables for pass/fail counts).
3. **Reward calculation**: `final = eval_weight × eval_score + time_weight × time_score`.
4. **Accumulation**: `RoundManager` stores per-miner reward history for the round, enabling incremental average.
5. **Winner selection**: WTA picks top average; scoreboard renders via `round_table.render_round_summary_table`.
6. **Weights**: On-chain update sets WTA winner to 1.0, others 0.0 (burn fallback when necessary).

Logs use rich tables and emoji-coded severity (✅ / ⚠️ / ❌) to make CLI scanning easy.

---

## 6. Reporting & Monitoring Stack

### `report.sh`
Standalone CLI to summarize rounds:
```bash
scripts/validator/reporting/report.sh --pm2 validator            # auto-detect latest completed round
scripts/validator/reporting/report.sh --pm2 validator --round 598 # explicit round
scripts/validator/reporting/report.sh --path /tmp/validator.log   # log file instead of pm2
```
It scrapes the canonical start/end markers (`🚦 Starting Round`, `✅ Round completed`) and renders health checks, task stats, consensus events, winners, and any failures.

### `monitor_rounds.py`
1. Tails pm2 log (default `~/.pm2/logs/validator-out.log`).
2. Detects round start and completion markers.
3. Waits `block_delay × seconds_per_block` (default 2 × 12s = 24s).
4. Runs `report.sh` for the round; renders HTML + text email (SMTP config uses `.env` or `REPORT_MONITOR_*` variables).
5. Optional LLM command (`REPORT_MONITOR_LLM_COMMAND`) enriches the email.
6. **Codex integration**: after emailing, it streams the report to `run_codex.sh` (see below) and waits for Codex to finish before clearing the round.

### Alerts
`python scripts/validator/utils/alert_admins.py` lets Codex or humans dispatch additional notifications if a round requires attention beyond the automated email.

---

## 7. Automation Scripts

### `scripts/validator/reporting/run_codex.sh`
Launches Codex with full context:

```bash
# Provide round + report via stdin (env from .env is loaded automatically)
scripts/validator/reporting/run_codex.sh --round 598 <<'EOF'
…report output…
EOF
```

Behaviour:
1. Loads `.env` if present (ensures API keys are available).
2. Builds a prompt instructing Codex to:
   - Re-run `scripts/validator/reporting/report.sh` if necessary.
   - Analyse the supplied report.
   - Call `python scripts/validator/utils/alert_admins.py` when escalation is needed.
3. Provides `Agents.md` as the primary context file.
4. Uses `codex --sandbox danger-full-access` to avoid sandbox limitations (Codex may interact with the repo or run CLI tools).
5. Appends the full `.env` contents to the prompt so Codex sees every exported variable (ports, API keys, demo-web endpoints).
6. Waits for Codex to finish before returning (so monitor “closes” the round only after Codex assessment).

Codex output prints to stdout; pipe or capture as required.

### `scripts/validator/reporting/start_monitoring.sh`
Starts (or restarts) the pm2 monitor with one command:

```bash
scripts/validator/reporting/start_monitoring.sh
```

It loads `.env`, exports the variables for Codex, checks for `pm2`/`codex`, and launches `monitor_rounds.py` under pm2 (default process name `validator_monitor`, targeting pm2 id `validator`).
Override behaviour with `PM2_MONITOR_PM2`, `PM2_MONITOR_NAME`, `PM2_MONITOR_BLOCK_DELAY`, `PM2_MONITOR_SECONDS_PER_BLOCK`, `PM2_MONITOR_POLL_INTERVAL`.

### `scripts/validator/utils/alert_admins.py`
Python helper Codex and operators can call directly:
```bash
python scripts/validator/utils/alert_admins.py "Subject" "Body text"
```
It loads `.env`, infers SMTP (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`, `SMTP_TO`) and sends an HTML + plain-text message. Missing SMTP configuration falls back to printing the message (mirrors monitor behaviour).

---

## 8. Putting It Together (Round Close Pipeline)

1. Validator finishes tasks → logs `✅ Round completed`.
2. `monitor_rounds.py`:
   - Streams log lines in real time and tracks fraction elapsed (from `Round status` entries).
   - At each configured checkpoint (`CODEX_CHECK_FRACTIONS`, default `0.25,0.5,0.75,1.0`) it captures a fresh `report.sh --round <n>` snapshot, appends the recent log tail, and sends everything to Codex with a status label like `CHECKPOINT@25pct`.
   - On round completion it waits a couple of blocks, runs `report.sh`, emails admins (HTML + text, optional LLM comment), and invokes `run_codex.sh` one more time with the final report.
   - Codex can re-run the report, inspect `~/.pm2/logs/validator-out.log`, or escalate via `python scripts/validator/utils/alert_admins.py`.
   - The monitor blocks until Codex exits for each invocation, ensuring the round is “closed” only after automated review.
3. Checkpoints and IWAP finalize the round; the validator idles until the next boundary.

---

## 9. Operational Tips

- **Testing vs Production**: `TESTING=true` shrinks rounds and removes stake gates, but expect more on-chain `TimeoutError: Max retries exceeded` because the validator lacks weight. Monitor emails will flag these as `ERROR`.
- **Handling Commitment Failures**: When consensus commits time out, `_close_async_subtensor()` can be called (see `platform/mixin`) before the next attempt to reset the websocket connection.
- **Codex IAM**: Ensure `codex` CLI has the necessary credentials (API key, etc.) before launching pm2 processes. Restart with `pm2 restart … --update-env` after changing `.env`.
- **Log housekeeping**: `pm2 flush validator_monitor` trims old notifications if the log history gets noisy.

This document is the canonical context for automation agents. Keep it current when you change report formats, adjust phases, or add new scripts so Codex and other operators stay in sync.
