#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPERATOR_ROOT="$(cd "$REPO_ROOT/.." && pwd)"
AUTOPPIA_IWA_ROOT="$OPERATOR_ROOT/autoppia_iwa"
cd "$REPO_ROOT"
PYTHONPATH_VALUE="$REPO_ROOT:$AUTOPPIA_IWA_ROOT"

usage() {
  cat <<'EOF'
Usage:
  tests/test_locally.sh [github_url] [options]

Runs a local smoke test with:
1. one miner on-chain commitment submitted via autoppia-miner-cli
2. one validator PM2 process with IWAP/Platform HTTP writes mocked
3. a unique consensus version to avoid mixing with production validator payloads
4. artifact checks for pre-consensus and post-consensus round outputs

Options:
  --agent-name NAME           Miner agent name (default: local-smoke-agent)
  --agent-image URL           Miner image URL (default: https://example.com/local-smoke-agent.png)
  --validator-wallet NAME     Validator wallet name (default: validator)
  --validator-hotkey NAME     Validator hotkey name (default: default)
  --miner-wallet NAME         Miner wallet name (default: miner)
  --miner-hotkey NAME         Miner hotkey name (default: default)
  --netuid N                  Netuid (default: 36)
  --subtensor-network NAME    Subtensor network (default: finney)
  --timeout-minutes N         How long to wait for artifacts (default: 45)
  --keep-pm2                  Keep PM2 processes alive after the test
  --allow-set-weights         Do not pass --neuron.disable_set_weights
  -h, --help                  Show this help

If github_url is omitted, the script falls back to GITHUB_URL from the repo .env.

Notes:
- This script requires the miner and validator hotkeys to already be registered on the target subnet.
- Validator Platform/IWAP writes are disabled via --iwap.mock-client.
- The validator uses an isolated env file via AUTOPPIA_VALIDATOR_ENV_FILE and does not overwrite repo .env.
EOF
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

DEFAULT_GITHUB_URL="$(python - <<'PY'
from pathlib import Path
import re
env_path = Path('.env')
value = ''
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^GITHUB_URL=(.*)$', line)
        if m:
            value = m.group(1).strip().strip('"').strip("'")
            break
print(value)
PY
)"

GITHUB_URL="${DEFAULT_GITHUB_URL}"
AGENT_NAME="local-smoke-agent"
AGENT_IMAGE="https://example.com/local-smoke-agent.png"
VALIDATOR_WALLET="validator"
VALIDATOR_HOTKEY="default"
MINER_WALLET="miner"
MINER_HOTKEY="default"
NETUID="36"
SUBTENSOR_NETWORK="finney"
TIMEOUT_MINUTES="20"
KEEP_PM2="false"
ALLOW_SET_WEIGHTS="false"

POSITIONAL_GITHUB_SET="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent-name)
      AGENT_NAME="$2"
      shift 2
      ;;
    --agent-image)
      AGENT_IMAGE="$2"
      shift 2
      ;;
    --validator-wallet)
      VALIDATOR_WALLET="$2"
      shift 2
      ;;
    --validator-hotkey)
      VALIDATOR_HOTKEY="$2"
      shift 2
      ;;
    --miner-wallet)
      MINER_WALLET="$2"
      shift 2
      ;;
    --miner-hotkey)
      MINER_HOTKEY="$2"
      shift 2
      ;;
    --netuid)
      NETUID="$2"
      shift 2
      ;;
    --subtensor-network)
      SUBTENSOR_NETWORK="$2"
      shift 2
      ;;
    --timeout-minutes)
      TIMEOUT_MINUTES="$2"
      shift 2
      ;;
    --keep-pm2)
      KEEP_PM2="true"
      shift
      ;;
    --allow-set-weights)
      ALLOW_SET_WEIGHTS="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      if [[ "$POSITIONAL_GITHUB_SET" == "true" ]]; then
        echo "Unexpected extra positional argument: $1" >&2
        usage >&2
        exit 1
      fi
      GITHUB_URL="$1"
      POSITIONAL_GITHUB_SET="true"
      shift
      ;;
  esac
done

if [[ -z "${GITHUB_URL}" ]]; then
  echo "Missing GitHub URL. Pass it as the first argument or set GITHUB_URL in .env." >&2
  exit 1
fi

require_cmd pm2
require_cmd python

if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

VALIDATOR_PY="$REPO_ROOT/validator_env/bin/python"
MINER_PY="$REPO_ROOT/miner_env/bin/python"
[[ -x "$VALIDATOR_PY" ]] || { echo "Missing validator python: $VALIDATOR_PY" >&2; exit 1; }
[[ -x "$MINER_PY" ]] || { echo "Missing miner python: $MINER_PY" >&2; exit 1; }

RUN_ID="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="$REPO_ROOT/tests/local_runs/$RUN_ID"
mkdir -p "$RUN_DIR"
mkdir -p "$RUN_DIR/bittensor_logs"
mkdir -p "$RUN_DIR/sandbox_logs"
mkdir -p "$RUN_DIR/data"

CONSENSUS_VERSION="$(date +%s)"
PORT_OFFSET="$(( (CONSENSUS_VERSION % 3000) + 100 ))"
VALIDATOR_PROCESS="local-validator-${RUN_ID}"
VALIDATOR_ENV_FILE="$RUN_DIR/validator.env"
MINER_CLI_CONFIG_FILE="$RUN_DIR/miner-cli.json"
CURRENT_BLOCK="$("$VALIDATOR_PY" - <<'PY'
import bittensor as bt
print(bt.subtensor(network='finney').get_current_block())
PY
)"

cleanup() {
  local exit_code=$?
  cleanup_localtest_containers
  if [[ "$KEEP_PM2" != "true" ]]; then
    pm2 delete "$VALIDATOR_PROCESS" >/dev/null 2>&1 || true
  fi
  if [[ $exit_code -ne 0 ]]; then
    echo
    echo "Smoke test failed. PM2 status:"
    pm2 status "$VALIDATOR_PROCESS" || true
    echo
    echo "Validator logs:"
    pm2 logs "$VALIDATOR_PROCESS" --lines 80 --nostream || true
    echo
    echo "Run directory: $RUN_DIR"
  fi
  exit $exit_code
}
trap cleanup EXIT

cleanup_localtest_containers() {
  local ids=""
  ids="$(
    {
      docker ps -aq --filter "name=sandbox-gateway-localtest-" 2>/dev/null || true
      docker ps -aq --filter "name=sandbox-agent-localtest-" 2>/dev/null || true
    } | awk 'NF && !seen[$0]++'
  )"
  [[ -n "$ids" ]] || return 0
  while IFS= read -r container_id; do
    [[ -n "$container_id" ]] || continue
    docker rm -f "$container_id" >/dev/null 2>&1 || true
  done <<< "$ids"
}

cleanup_localtest_containers

python - <<'PY' "$VALIDATOR_ENV_FILE" "$RUN_DIR" "$CONSENSUS_VERSION" "$PORT_OFFSET" "$CURRENT_BLOCK"
from pathlib import Path
import os
import sys

target = Path(sys.argv[1])
run_dir = Path(sys.argv[2])
consensus_version = sys.argv[3]
port_offset = sys.argv[4]
current_block = int(sys.argv[5])

with target.open("w", encoding="utf-8") as fh:
    overrides = {
        "TESTING": "true",
        "VALIDATOR_NAME": "local-smoke-validator",
        "VALIDATOR_IMAGE": "local-smoke-validator",
        "GATEWAY_ALLOWED_PROVIDERS": "openai",
        "MINER_DISCOVERY_MODE": "commitments",
        "CONSENSUS_VERSION": consensus_version,
        "IWAP_BACKUP_DIR": str(run_dir / "data"),
        "IWAP_API_BASE_URL": "http://127.0.0.1:8080",
        "SANDBOX_INSTANCE": f"localtest-{consensus_version}",
        "SANDBOX_GATEWAY_INSTANCE": f"localtest-{consensus_version}",
        "SANDBOX_GATEWAY_PORT_OFFSET": port_offset,
        "SANDBOX_LOG_DIR": str(run_dir / "sandbox_logs"),
        "MIN_MINER_STAKE_ALPHA": "0",
        "MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO": "0",
        "MAX_MINERS_PER_ROUND_BY_STAKE": "0",
        "ENABLE_EVALUATION_COOLDOWN": "false",
        "ROUND_LOG_UPLOAD_INTERVAL_SECONDS": "30",
        "SKIP_ROUND_MIN_BLOCKS_AFTER_HANDSHAKE": "1",
        "TEST_MINIMUM_START_BLOCK": str(current_block),
        "TEST_ROUND_SIZE_EPOCHS": "0.01",
        "TEST_SEASON_SIZE_EPOCHS": "0.04",
        "TEST_TASKS_PER_SEASON": "1",
        "KING_OVERFIT_LLM_JUDGE_ENABLED": os.getenv("KING_OVERFIT_LLM_JUDGE_ENABLED", "false"),
    }
    for key, value in overrides.items():
        fh.write(f"{key}={value}\n")
PY

python - <<'PY' "$RUN_DIR/data/season_1/tasks.json"
from pathlib import Path
import json
import sys

target = Path(sys.argv[1])
target.parent.mkdir(parents=True, exist_ok=True)
payload = {
    "season_number": 1,
    "generated_at": "2026-04-02T00:00:00Z",
    "validator_version": "31.0.0",
    "num_tasks": 1,
    "tasks": [
        {
            "project_name": "Autoppia AutoDelivery",
            "task": {
                "id": "60ff015b-cee3-423b-a830-51a3abbba1c2",
                "is_web_real": False,
                "web_project_id": "autodelivery",
                "url": "http://84.247.180.192:8006/?seed=210",
                "prompt": "Go back to the previous page of restaurants.",
                "specifications": {
                    "viewport_width": 1920,
                    "viewport_height": 1080,
                    "screen_width": 1920,
                    "screen_height": 1080,
                    "device_pixel_ratio": 1.0,
                    "scroll_x": 0,
                    "scroll_y": 0,
                    "browser_x": 0,
                    "browser_y": 0
                },
                "tests": [
                    {
                        "type": "CheckEventTest",
                        "event_name": "RESTAURANT_PREV_PAGE",
                        "event_criteria": {},
                        "description": "Check if specific event was triggered"
                    }
                ],
                "use_case": {
                    "name": "RESTAURANT_PREV_PAGE",
                    "description": "The user navigates back to the previous set of restaurants.",
                    "event": "RestaurantPrevPageEvent",
                    "event_source_code": True,
                    "examples": [
                        {
                            "prompt": "Go back to the previous page of restaurants.",
                            "prompt_for_task_generation": "Go back to the previous page of restaurants."
                        },
                        {
                            "prompt": "View restaurants that are on previous page.",
                            "prompt_for_task_generation": "View restaurants that are on previous page."
                        },
                        {
                            "prompt": "Move backward to view earlier restaurants.",
                            "prompt_for_task_generation": "Move backward to view earlier restaurants."
                        }
                    ],
                    "constraints": None,
                    "additional_prompt_info": "GENERATE PROMPT LIKE: Go back to the previous page of restaurants.\nView restaurants that are on previous page.\nMove backward to view earlier restaurants."
                },
                "should_record": False,
                "original_prompt": "Go back to the previous page of restaurants."
            }
        }
    ]
}
target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

echo "Run directory: $RUN_DIR"
echo "GitHub URL: $GITHUB_URL"
echo "Consensus version: $CONSENSUS_VERSION"
echo "Current block: $CURRENT_BLOCK"
echo "Validator env file: $VALIDATOR_ENV_FILE"

python - <<'PY' "$VALIDATOR_PY" "$NETUID" "$VALIDATOR_WALLET" "$VALIDATOR_HOTKEY" "$MINER_WALLET" "$MINER_HOTKEY" "$SUBTENSOR_NETWORK"
import sys
import bittensor as bt

python_bin, netuid, validator_wallet, validator_hotkey, miner_wallet, miner_hotkey, network = sys.argv[1:]
netuid = int(netuid)
subtensor = bt.subtensor(network=network)

checks = [
    ("validator", validator_wallet, validator_hotkey),
    ("miner", miner_wallet, miner_hotkey),
]

failed = False
for role, wallet_name, hotkey_name in checks:
    wallet = bt.wallet(name=wallet_name, hotkey=hotkey_name)
    hotkey = wallet.hotkey.ss58_address
    try:
        registered = subtensor.is_hotkey_registered(netuid=netuid, hotkey_ss58=hotkey)
    except TypeError:
        registered = subtensor.is_hotkey_registered(netuid, hotkey)
    print(f"{role}: wallet={wallet_name} hotkey={hotkey_name} ss58={hotkey} registered={registered}")
    if not registered:
        failed = True

if failed:
    raise SystemExit("Both validator and miner hotkeys must be registered on the target subnet before running this smoke test.")
PY

pm2 delete "$VALIDATOR_PROCESS" >/dev/null 2>&1 || true

python - <<'PY' | while IFS= read -r proc_name; do
import json
import subprocess

data = json.loads(subprocess.check_output(["pm2", "jlist"], text=True))
for proc in data:
    name = proc.get("name") or ""
    if name.startswith("local-validator-"):
        print(name)
PY
  [[ -n "$proc_name" ]] || continue
  [[ "$proc_name" == "$VALIDATOR_PROCESS" ]] || pm2 delete "$proc_name" >/dev/null 2>&1 || true
done

MINER_HOTKEY_SS58="$("$VALIDATOR_PY" - <<'PY' "$MINER_WALLET" "$MINER_HOTKEY"
import sys
import bittensor as bt
w = bt.wallet(name=sys.argv[1], hotkey=sys.argv[2])
print(w.hotkey.ss58_address)
PY
)"

echo "Miner hotkey allowlist: $MINER_HOTKEY_SS58"
echo "Configuring autoppia-miner-cli defaults"
AUTOPPIA_MINER_CLI_CONFIG="$MINER_CLI_CONFIG_FILE" PYTHONPATH="$PYTHONPATH_VALUE" "$MINER_PY" -m autoppia_web_agents_subnet.miner.cli config set \
  --wallet.name "$MINER_WALLET" \
  --wallet.hotkey "$MINER_HOTKEY" \
  --netuid "$NETUID" \
  --subtensor.network "$SUBTENSOR_NETWORK" \
  --github "$GITHUB_URL" \
  --agent.name "$AGENT_NAME" \
  --agent.image "$AGENT_IMAGE"
echo "Submitting miner commitment with autoppia-miner-cli"
AUTOPPIA_MINER_CLI_CONFIG="$MINER_CLI_CONFIG_FILE" PYTHONPATH="$PYTHONPATH_VALUE" "$MINER_PY" -m autoppia_web_agents_subnet.miner.cli trigger-eval

VALIDATOR_EXTRA_ARGS=()
if [[ "$ALLOW_SET_WEIGHTS" != "true" ]]; then
  VALIDATOR_EXTRA_ARGS+=(--neuron.disable_set_weights)
fi

echo "Starting validator PM2 process: $VALIDATOR_PROCESS"
env \
  AUTOPPIA_VALIDATOR_ENV_FILE="$VALIDATOR_ENV_FILE" \
  MINER_HOTKEY_ALLOWLIST="$MINER_HOTKEY_SS58" \
  PYTHONPATH="$PYTHONPATH_VALUE" \
  pm2 start "$VALIDATOR_PY" \
    --name "$VALIDATOR_PROCESS" \
    --cwd "$REPO_ROOT" \
    -- \
    "$REPO_ROOT/neurons/validator.py" \
    --netuid "$NETUID" \
    --subtensor.network "$SUBTENSOR_NETWORK" \
    --wallet.name "$VALIDATOR_WALLET" \
    --wallet.hotkey "$VALIDATOR_HOTKEY" \
    --iwap.mock-client \
    --logging.logging_dir "$RUN_DIR/bittensor_logs" \
    --logging.debug \
    "${VALIDATOR_EXTRA_ARGS[@]}"

wait_for_pm2_online() {
  local name="$1"
  local deadline="$(( $(date +%s) + 60 ))"
  while (( $(date +%s) < deadline )); do
    local status
    status="$(pm2 jlist | python -c 'import json, sys; name = sys.argv[1]; data = json.load(sys.stdin); print(next((proc.get("pm2_env", {}).get("status", "unknown") for proc in data if proc.get("name") == name), "missing"))' "$name")"
    if [[ "$status" == "online" ]]; then
      return 0
    fi
    if [[ "$status" == "errored" || "$status" == "stopped" ]]; then
      return 1
    fi
    sleep 2
  done
  return 1
}

wait_for_pm2_online "$VALIDATOR_PROCESS"

echo "Validator process is online. Waiting for consensus artifacts..."

DEADLINE="$(( $(date +%s) + TIMEOUT_MINUTES * 60 ))"
ROUND_DIR=""
while (( $(date +%s) < DEADLINE )); do
  ROUND_DIR="$(python - <<'PY' "$RUN_DIR/data"
from pathlib import Path
import sys

root = Path(sys.argv[1])
completed_round_dirs = []
for candidate in root.glob("season_*/round_*"):
    if not candidate.is_dir():
        continue
    pre = candidate / "ipfs_uploaded.json"
    post = candidate / "post_consensus.json"
    if pre.exists() and post.exists():
        completed_round_dirs.append(candidate)

if completed_round_dirs:
    latest = max(completed_round_dirs, key=lambda p: p.stat().st_mtime)
    print(latest)
PY
)"
  if [[ -n "$ROUND_DIR" ]]; then
    break
  fi
  sleep 20
done

if [[ -z "$ROUND_DIR" ]]; then
  echo "Timed out waiting for ipfs_uploaded.json and post_consensus.json under $RUN_DIR/data" >&2
  exit 1
fi

echo "Found round artifacts in: $ROUND_DIR"

python - <<'PY' "$ROUND_DIR" "$MINER_HOTKEY_SS58" "$CONSENSUS_VERSION"
from pathlib import Path
import json
import sys

round_dir = Path(sys.argv[1])
expected_miner_hotkey = sys.argv[2]
expected_consensus_version = int(sys.argv[3])
pre = json.loads((round_dir / "ipfs_uploaded.json").read_text(encoding="utf-8"))
post = json.loads((round_dir / "post_consensus.json").read_text(encoding="utf-8"))
checkpoint = json.loads((round_dir / "round_checkpoint.json").read_text(encoding="utf-8"))

def _miner_count(payload):
    miners = payload.get("miners")
    if isinstance(miners, list):
        return len(miners)
    rewards = payload.get("rewards") or payload.get("scores")
    if isinstance(rewards, dict):
        return len(rewards)
    return 0

pre_payload = pre.get("payload") if isinstance(pre.get("payload"), dict) else {}
pre_count = _miner_count(pre_payload)
post_count = _miner_count(post)
phase_names = [entry.get("phase") for entry in checkpoint.get("phase_history", []) if isinstance(entry, dict)]
eligibility = checkpoint.get("eligibility_status_by_uid")
pre_miners = pre_payload.get("miners") if isinstance(pre_payload.get("miners"), list) else []
post_miners = post.get("miners") if isinstance(post.get("miners"), list) else []
expected_round = checkpoint.get("round_number_in_season")
expected_season = checkpoint.get("season_number")

def _require(condition, message):
    if not condition:
        raise SystemExit(message)

_require(isinstance(pre.get("cid"), str) and pre["cid"], "ipfs_uploaded.json is missing cid")
_require(pre.get("commit_version") == 4, f"unexpected commit_version in ipfs_uploaded.json: {pre.get('commit_version')!r}")
_require(pre_count > 0, "ipfs_uploaded.json does not contain any miner entries")
_require(post_count > 0, "post_consensus.json does not contain any miner entries")
_require(checkpoint.get("status") == "completed", f"round_checkpoint.json status is not completed: {checkpoint.get('status')!r}")
_require(checkpoint.get("reason") == "finish_round_offline", f"unexpected checkpoint reason: {checkpoint.get('reason')!r}")
_require(phase_names == ["PREPARING", "EVALUATION", "CONSENSUS", "FINALIZING"], f"unexpected phase history: {phase_names!r}")
_require(isinstance(eligibility, dict) and eligibility, "round_checkpoint.json is missing eligibility_status_by_uid entries")
_require(pre_payload.get("r") == expected_round, f"ipfs_uploaded.json round mismatch: {pre_payload.get('r')!r} != {expected_round!r}")
_require(pre_payload.get("s") == expected_season, f"ipfs_uploaded.json season mismatch: {pre_payload.get('s')!r} != {expected_season!r}")
_require(post.get("round") == expected_round, f"post_consensus.json round mismatch: {post.get('round')!r} != {expected_round!r}")
_require(post.get("season") == expected_season, f"post_consensus.json season mismatch: {post.get('season')!r} != {expected_season!r}")
_require(pre_payload.get("v") == expected_consensus_version, f"ipfs_uploaded.json consensus version mismatch: {pre_payload.get('v')!r} != {expected_consensus_version!r}")
_require(pre_payload.get("validator_uid") == checkpoint.get("validator_uid"), "validator UID mismatch between ipfs_uploaded.json and round_checkpoint.json")
_require(pre_payload.get("validator_hotkey") == checkpoint.get("validator_hotkey"), "validator hotkey mismatch between ipfs_uploaded.json and round_checkpoint.json")
_require(pre_payload.get("validator_round_id") == checkpoint.get("validator_round_id"), "validator round id mismatch between ipfs_uploaded.json and round_checkpoint.json")
_require(any(m.get("hotkey") == expected_miner_hotkey for m in pre_miners if isinstance(m, dict)), "expected miner hotkey not found in ipfs_uploaded.json payload")
_require(any(m.get("hotkey") == expected_miner_hotkey for m in post_miners if isinstance(m, dict)), "expected miner hotkey not found in post_consensus.json")
_require(checkpoint.get("active_miner_uids"), "round_checkpoint.json has no active_miner_uids")
_require(any(value == "evaluated" for value in eligibility.values()), f"no evaluated miners in eligibility_status_by_uid: {eligibility!r}")
_require(post.get("consensus_type") == "stake_weighted", f"unexpected consensus_type in post_consensus.json: {post.get('consensus_type')!r}")
_require(isinstance(checkpoint.get("round_log_file"), str) and checkpoint.get("round_log_file"), "round_checkpoint.json missing round_log_file")
_require(Path(checkpoint["round_log_file"]).exists(), f"round log file missing on disk: {checkpoint['round_log_file']}")
_require(Path(checkpoint["round_log_file"]).stat().st_size > 0, f"round log file is empty: {checkpoint['round_log_file']}")

observed_pre_miner = next((m for m in pre_miners if isinstance(m, dict) and m.get("hotkey") == expected_miner_hotkey), None)
observed_post_miner = next((m for m in post_miners if isinstance(m, dict) and m.get("hotkey") == expected_miner_hotkey), None)
_require(observed_pre_miner is not None, "expected miner entry missing from ipfs_uploaded.json")
_require(observed_post_miner is not None, "expected miner entry missing from post_consensus.json")
best_run_consensus = observed_post_miner.get("best_run_consensus") if isinstance(observed_post_miner, dict) else None
_require(isinstance(best_run_consensus, dict), "post_consensus.json expected miner is missing best_run_consensus")
for key in ("rank", "score", "reward", "tasks_received", "tasks_success", "time", "cost", "penalty", "weight"):
    _require(key in best_run_consensus, f"post_consensus.json expected miner missing best_run_consensus.{key}")

print(f"pre_consensus_miners={pre_count}")
print(f"post_consensus_miners={post_count}")
print(f"checkpoint_status={checkpoint.get('status')}")
print(f"checkpoint_reason={checkpoint.get('reason')}")
print(f"phases={','.join(phase_names)}")
print(f"expected_miner_uid={observed_pre_miner.get('uid')}")
print(f"expected_miner_rank={best_run_consensus.get('rank')}")
PY

ROUND_LOG_FILE="$(python - <<'PY' "$ROUND_DIR"
from pathlib import Path
import json
import sys

round_dir = Path(sys.argv[1])
checkpoint = json.loads((round_dir / "round_checkpoint.json").read_text(encoding="utf-8"))
print(checkpoint["round_log_file"])
PY
)"

EXPECTED_ROUND="$(python - <<'PY' "$ROUND_DIR"
from pathlib import Path
import json
import sys

round_dir = Path(sys.argv[1])
checkpoint = json.loads((round_dir / "round_checkpoint.json").read_text(encoding="utf-8"))
print(checkpoint["round_number_in_season"])
PY
)"

EXPECTED_MINER_UID="$(python - <<'PY' "$ROUND_DIR" "$MINER_HOTKEY_SS58"
from pathlib import Path
import json
import sys

round_dir = Path(sys.argv[1])
expected_miner_hotkey = sys.argv[2]
pre = json.loads((round_dir / "ipfs_uploaded.json").read_text(encoding="utf-8"))
payload = pre.get("payload") if isinstance(pre.get("payload"), dict) else {}
miners = payload.get("miners") if isinstance(payload.get("miners"), list) else []
for miner in miners:
    if isinstance(miner, dict) and miner.get("hotkey") == expected_miner_hotkey:
        print(miner.get("uid"))
        raise SystemExit(0)
raise SystemExit("expected miner hotkey not found while deriving miner uid for log checks")
PY
)"

echo "Checking round.log markers in: $ROUND_LOG_FILE"

check_log_marker() {
  local pattern="$1"
  local message="$2"
  if ! rg -q "$pattern" "$ROUND_LOG_FILE"; then
    echo "$message" >&2
    exit 1
  fi
}

check_log_marker "\\[commitments\\] Miner discovery complete: 1/1 miners with valid commitments" "round.log missing successful commitment discovery marker"
check_log_marker "IWAP mock-client mode active" "round.log missing IWAP mock-client activation marker"
check_log_marker "OFFLINE MODE: Skipping miner registration" "round.log missing offline miner registration skip marker"
check_log_marker "Starting evaluation phase" "round.log missing evaluation phase start marker"
check_log_marker "Evaluation phase completed" "round.log missing evaluation phase completion marker"
check_log_marker "\\[MINER_TOOLS\\].*uid=${EXPECTED_MINER_UID}" "round.log missing MINER_TOOLS marker for expected miner"
check_log_marker "\\[EXEC_TOOLS\\].*uid=${EXPECTED_MINER_UID}" "round.log missing EXEC_TOOLS marker for expected miner"
check_log_marker "IWAP submission skipped for agent ${EXPECTED_MINER_UID}" "round.log missing offline IWAP submission skip marker"
check_log_marker "\\[IPFS\\] \\[UPLOAD\\].*Round ${EXPECTED_ROUND} \\| 1 miners" "round.log missing IPFS upload summary for expected round"
check_log_marker "\\[IPFS\\] \\[UPLOAD\\].*SUCCESS - CID:" "round.log missing successful IPFS upload marker"
check_log_marker "CONSENSUS COMMIT START \\| v=${CONSENSUS_VERSION} s=1 r=${EXPECTED_ROUND} \\| cid=" "round.log missing consensus commit start marker with expected identifiers"

if rg -q "Service unavailable at .*StartRoundSynapse|Timed out waiting for ipfs_uploaded.json and post_consensus.json|Failed to read on-chain commitments" "$ROUND_LOG_FILE"; then
  echo "round.log contains miner discovery failure markers" >&2
  exit 1
fi

if rg -q "\\[trajectory_eval\\].*/find_trayectory|Failed to find trayectory" "$ROUND_LOG_FILE"; then
  echo "round.log warning: trajectory validation failure observed during smoke test" >&2
fi

MINER_STATUS_OUT="$RUN_DIR/miner_status.txt"
echo "Checking autoppia-miner-cli status output..."
set -a
# shellcheck disable=SC1090
source "$VALIDATOR_ENV_FILE"
set +a
AUTOPPIA_MINER_CLI_CONFIG="$MINER_CLI_CONFIG_FILE" PYTHONPATH="$PYTHONPATH_VALUE" "$MINER_PY" -m autoppia_web_agents_subnet.miner.cli status >"$MINER_STATUS_OUT"
for expected_section in "Current Commitment" "Latest Consensus Snapshot" "Latest Consensus" "Top Consensus Ranking"; do
  if ! rg -q "$expected_section" "$MINER_STATUS_OUT"; then
    echo "miner status output is missing expected section: $expected_section" >&2
    exit 1
  fi
done
if rg -q "No compatible validator consensus snapshot found on-chain" "$MINER_STATUS_OUT"; then
  echo "miner status output did not resolve a latest consensus snapshot" >&2
  exit 1
fi

echo "Smoke test completed successfully."
echo "Validator process: $VALIDATOR_PROCESS"
echo "Miner commitment submitted for hotkey: $MINER_HOTKEY_SS58"
echo "Miner status output: $MINER_STATUS_OUT"
echo "Run directory: $RUN_DIR"
