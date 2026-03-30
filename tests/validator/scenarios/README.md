## Scenario Tests

This folder is for validator regression scenarios.

These are not meant to be tiny unit tests. They are deterministic business-rule tests for the exact cases that have already hurt us in real rounds.

### What Is Covered Right Now

#### 1. Post-consensus scenarios
File: `test_post_consensus_scenarios.py`

Covered now:

- stake-weighted aggregation of `best_run` reward, score, time, and cost
- version compatibility by `major.minor`
- two compatible validators plus one higher-stake incompatible validator across two miners
- an all-zero validator is excluded from consensus when other validators have positive signal
- if every validator is all-zero, nobody is auto-excluded
- the snapshot summary exposes `validator_all_best_runs_zero` explicitly
- `best_run` still counts when `current_run` is `null`
- `best_run` metrics and `current_run` metrics stay separated in post-consensus output
- `best_run = null` contributes zero
- `tasks_received` and `tasks_success` are summed in current implementation
- mixed `20 vs 100` semantics are made explicit with fixed expected numbers

#### 2. Evaluation and round regression scenarios
File: `test_round_regressions.py`

Covered now:

- over-cost early stop keeps reward normalized by total season tasks
- post-consensus still works when only `best_run` exists
- patch versions are accepted while minor and major mismatches are skipped

#### 3. Round phase scenarios
File: `test_round_phases_scenarios.py`

Covered now:

- if the validator joins a round too late, the round is skipped cleanly
- if the evaluation stop fraction is already reached, queued miners are zeroed with `round_window_exceeded`
- if the stop fraction is reached between miners, the current miner finishes and only the remaining queued miners are zeroed

#### 4. Best-run selection scenarios
File: `test_best_run_scenarios.py`

Covered now:

- if `current_run` is better than historical `best_run`, then exported `best_run` must become the current one
- if `current_run` is worse than historical `best_run`, the historical best must remain

#### 5. Reuse, hash, and IPFS snapshot scenarios
File: `test_reuse_and_payload_scenarios.py`

Covered now:

- same repo + same commit + same evaluation conditions reuses the previous run
- changing validator conditions changes the evaluation-context hash
- if the evaluation-context hash changes, reuse is blocked and the commit must be re-evaluated
- if a validator finishes a suspicious all-zero round, reuse is disabled for the next round
- the published snapshot sets `summary.validator_all_current_runs_zero` and `summary.validator_all_best_runs_zero` from local runs
- a round that only ended with `round_window_exceeded` does not trigger the all-zero reuse guard
- if the next round keeps the same commit and there is no new current run yet, the previous `best_run` still persists
- the IPFS round snapshot matches the validator's local `best_run` and `current_run`
- a partial `current_run` that stopped early still exports `reward/score` normalized by full season tasks, never by only attempted tasks
- the IPFS snapshot cannot regress to `7/20` semantics when the season total is still `100`

#### 6. IWAP finish-round scenarios
File: `test_iwap_finish_round_scenarios.py`

Covered now:

- a partial miner run with `zero_reason=round_window_exceeded` is preserved into the IWAP finish payload
- a zeroed pending miner is still included in finish payloads and round totals
- main-validator grace errors trigger retries and then exit cleanly without crashing the validator
- `leader_before/candidate/leader_after` snapshots are canonicalized from the final post-consensus miner payloads

#### 6.1 IWAP start-round scenarios
Folder: `iwap_start_rounds/`

Covered now:

- main validator happy path for `start_round` + `set_tasks`
- authority/grace denial switches the validator to shadow mode instead of full offline mode
- duplicate `start_round` is treated as idempotent
- `round_number mismatch` forces IWAP offline for that round
- `round window not active` forces IWAP offline for that round
- backend `shadow_mode` responses update the local round id and still continue with `set_tasks`
- duplicate `set_tasks` does not block the round from becoming IWAP-ready

#### 6.2 IWAP finish-round control scenarios
Folder: `iwap_finish_rounds/`

Covered now:

- offline-mode finish skips backend writes but still closes local state cleanly
- normal finish persists a completed checkpoint
- main-validator grace/authority errors retry and can still succeed later
- generic primary finish failures fall back to a degraded payload instead of dropping the round

#### 7. Version bump and artifact invalidation scenarios
File: `test_version_bump_artifact_scenarios.py`

Covered now:

- a major version bump clears the entire validator state root, including season tasks, round artifacts, reusable-commit history, stale post-consensus files, and stray root files
- after a major bump, stale state cannot be rehydrated from disk; only the fresh `evaluation_context.json` is recreated
- a minor version bump preserves season task inventories but clears round artifacts, root metadata/state files, and local reuse history
- a patch version bump follows the same non-major cleanup policy and also preserves season task inventories
- a non-version evaluation-context change preserves season tasks but clears round artifacts and reuse history
- if neither version nor evaluation context changes, local artifacts stay intact and the same commit remains reusable

#### 8. Leader and weight scenarios
File: `test_leader_and_weight_scenarios.py`

Covered now:

- in round 1, the top post-consensus miner becomes leader and `candidate_this_round` stays null
- the reigning leader stays leader when the challenger is worse
- the reigning leader stays leader when the challenger improves but does not beat the required dethrone percentage
- the challenger dethrones only when it beats the required threshold
- `candidate_this_round` is not duplicated as the reigning leader
- final weights split correctly between winner and burn wallet

### What Is Not Covered Yet

Still missing:

- runtime healthcheck scenarios for demo-webs missing containers and closed ports
- mismatch between backend DB materialization and the consensus/IPFS payloads
- full finish-round materialization into backend DB tables
- round-log upload limits such as `413 Payload Too Large`
- a real multi-validator end-to-end test with shared payload exchange
- finish_round scenarios where the main validator writes season/round config into backend tables and backup validators are blocked
- post-consensus summary propagated through `finish_round` with canonicalized leader/candidate snapshots

### Rules For New Scenarios

1. Reproduce the prod bug with the smallest deterministic payload possible.
2. Assert the business contract, not incidental implementation details.
3. Use exact numbers so failures are readable from CI output.
4. Keep one failure mode per test.
