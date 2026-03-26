import os

from autoppia_web_agents_subnet.utils.env import (
    _env_bool,
    _env_float,
    _env_int,
    _env_str,
)

TESTING = _env_bool("TESTING", False)

# ═══════════════════════════════════════════════════════════════════════════
# BURN CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
# BURN_AMOUNT_PERCENTAGE: 0.0-1.0 (qué fracción se quema, el resto premia a miners)
# 1.0 = quemar todo. 0.9 = 90% burn, 10% a winner. Igual que en main.
BURN_UID = _env_int("BURN_UID", 5)
BURN_AMOUNT_PERCENTAGE = _env_float("BURN_AMOUNT_PERCENTAGE", 0.925)


# ═══════════════════════════════════════════════════════════════════════════
# SHARED CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

# Season/round scheduling must always come from this file for the validator.
# Do not read these values from the process environment, otherwise PM2 can keep
# stale overrides after resets/restarts.
# Chain epoch size is 360 blocks. Round length is expressed in epochs.
BLOCKS_PER_EPOCH = 360
ROUND_SIZE_EPOCHS = 5
ROUNDS_PER_SEASON = 28
SEASON_SIZE_EPOCHS = 140
# IMPORTANT: season/round math uses MINIMUM_START_BLOCK always.
MINIMUM_START_BLOCK = 7802800
STOP_TASK_EVALUATION_AND_UPLOAD_IPFS_AT_ROUND_FRACTION = _env_float("STOP_TASK_EVALUATION_AND_UPLOAD_IPFS_AT_ROUND_FRACTION", 0.94, test_default=0.94)
FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION = _env_float("FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION", 0.97, test_default=0.97)
SKIP_ROUND_IF_STARTED_AFTER_FRACTION = _env_float("SKIP_ROUND_IF_STARTED_AFTER_FRACTION", 0.30, test_default=0.30)

# Source of truth: tasks per season.
TASKS_PER_SEASON = 50
CONCURRENT_EVALUATION_NUM = _env_int("CONCURRENT_EVALUATION_NUM", 5)
AGENT_MAX_STEPS = _env_int("AGENT_MAX_STEPS", 12, test_default=12)
AGENT_STEP_TIMEOUT_SECONDS = _env_int("AGENT_STEP_TIMEOUT_SECONDS", 25)
TASK_TIMEOUT_SECONDS = _env_float("TASK_TIMEOUT_SECONDS", 180.0, test_default=180.0)
SHOULD_RECORD_GIF = _env_bool("SHOULD_RECORD_GIF", True)
# Upload the per-round validator log to IWAP/S3 periodically during evaluation.
# This reduces observability gaps when round settlement is skipped/late.
ROUND_LOG_UPLOAD_INTERVAL_SECONDS = _env_int("ROUND_LOG_UPLOAD_INTERVAL_SECONDS", 120)

MAX_TASK_DOLLAR_COST_USD = _env_float("MAX_TASK_DOLLAR_COST_USD", 0.05)

# Stop evaluating a miner after this many tasks that exceed the per-task cost cap.
# 0 disables this guard.
MAX_OVER_COST_TASKS_BEFORE_FORCED_ZERO_SCORE = _env_int(
    "MAX_OVER_COST_TASKS_BEFORE_FORCED_ZERO_SCORE",
    10,
)

REWARD_TASK_DOLLAR_COST_NORMALIZATOR = _env_float(
    "REWARD_TASK_DOLLAR_COST_NORMALIZATOR",
    0.05,
)  # USD

EVAL_SCORE_WEIGHT = _env_float("EVAL_SCORE_WEIGHT", 0.7)
TIME_WEIGHT = _env_float("TIME_WEIGHT", 0.1)
COST_WEIGHT = _env_float("COST_WEIGHT", 0.2)

# Evaluation resource controls:
# 1) Per-round stake window: only handshake/evaluate the top N miners by stake.
#    Set to 0 to disable. In TESTING, default 0 so local/low-stake miners get handshake.
MAX_MINERS_PER_ROUND_BY_STAKE = _env_int("MAX_MINERS_PER_ROUND_BY_STAKE", 0 if TESTING else 30)
# 2) Anti-sybil controls during handshake: cap unique active miners sharing the same coldkey/repo.
#    REPO caps are applied per season (resets when a new season starts).
MAX_MINERS_PER_COLDKEY = _env_int("MAX_MINERS_PER_COLDKEY", 2)
MAX_MINERS_PER_REPO = _env_int("MAX_MINERS_PER_REPO", 2)
# Adaptive cooldown policy:
# - Better miners wait fewer rounds.
# - Worse/non-responding miners wait more rounds.
# - Max cooldown is capped to keep iteration speed.
# Disabled by default for now. When `false`, validators always evaluate changed submissions
# immediately and skip the adaptive round-based waiting logic entirely.
ENABLE_EVALUATION_COOLDOWN = _env_bool("ENABLE_EVALUATION_COOLDOWN", False)
EVALUATION_COOLDOWN_MIN_ROUNDS = _env_int("EVALUATION_COOLDOWN_MIN_ROUNDS", 1)
EVALUATION_COOLDOWN_MAX_ROUNDS = _env_int("EVALUATION_COOLDOWN_MAX_ROUNDS", 5)
EVALUATION_COOLDOWN_NO_RESPONSE_BADNESS = _env_float("EVALUATION_COOLDOWN_NO_RESPONSE_BADNESS", 0.2)
EVALUATION_COOLDOWN_ZERO_SCORE_BADNESS = _env_float("EVALUATION_COOLDOWN_ZERO_SCORE_BADNESS", 0.5)

VALIDATOR_NAME = _env_str("VALIDATOR_NAME")
VALIDATOR_IMAGE = _env_str("VALIDATOR_IMAGE")
IWAP_VALIDATOR_AUTH_MESSAGE = _env_str("IWAP_VALIDATOR_AUTH_MESSAGE", "I am a honest validator")
MAX_MINER_AGENT_NAME_LENGTH = _env_int("MAX_MINER_AGENT_NAME_LENGTH", 32)
MIN_MINER_STAKE_ALPHA = _env_float("MIN_MINER_STAKE_ALPHA", 100.0, test_default=0.0)
IPFS_API_URL = _env_str("IPFS_API_URL", "http://ipfs.metahash73.com:5001/api/v0")
# Comma-separated gateways for fetch fallback
IPFS_GATEWAYS = [gw.strip() for gw in (_env_str("IPFS_GATEWAYS", "https://ipfs.io/ipfs,https://cloudflare-ipfs.com/ipfs") or "").split(",") if gw.strip()]
# Retry policy for finish_round when backend blocks non-main validator writes.
# Optional via env:
# - FINISH_ROUND_MAX_RETRIES
# - FINISH_ROUND_RETRY_SECONDS
FINISH_ROUND_MAX_RETRIES = _env_int("FINISH_ROUND_MAX_RETRIES", 3, test_default=4)
FINISH_ROUND_RETRY_SECONDS = _env_int("FINISH_ROUND_RETRY_SECONDS", 180, test_default=30)
START_ROUND_MAX_RETRIES = _env_int("START_ROUND_MAX_RETRIES", 3, test_default=4)
START_ROUND_RETRY_SECONDS = _env_int("START_ROUND_RETRY_SECONDS", 15, test_default=5)


# ═══════════════════════════════════════════════════════════════════════════
# SETTLEMENT / WINNER PERSISTENCE CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
# Required % over the current season leader's best reward to dethrone it.
# Example: 0.05 => challenger must beat leader_best_reward * 1.05
LAST_WINNER_BONUS_PCT = _env_float("LAST_WINNER_BONUS_PCT", 0.05)


# ═══════════════════════════════════════════════════════════════════════════
# SANDBOX / DEPLOYMENT CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

SANDBOX_NETWORK_NAME = _env_str("SANDBOX_NETWORK_NAME", "sandbox-network")
SANDBOX_GATEWAY_IMAGE = _env_str("SANDBOX_GATEWAY_IMAGE", "autoppia-sandbox-gateway-image")

# Multi-validator support on the same machine:
# Each validator should run its own gateway container to avoid name/port/token conflicts.
#
# Recommended:
# - Set `SANDBOX_GATEWAY_INSTANCE` to a unique string per validator process.
# - Set `SANDBOX_GATEWAY_PORT_OFFSET` to a unique integer per validator process.
#
# You can always override `SANDBOX_GATEWAY_HOST` / `SANDBOX_GATEWAY_PORT` explicitly.
_SANDBOX_GATEWAY_INSTANCE = (_env_str("SANDBOX_GATEWAY_INSTANCE", "") or "").strip()

if (os.getenv("SANDBOX_GATEWAY_HOST") or "").strip():
    SANDBOX_GATEWAY_HOST = _env_str("SANDBOX_GATEWAY_HOST", "sandbox-gateway")
else:
    _base = "sandbox-gateway"
    SANDBOX_GATEWAY_HOST = f"{_base}-{_SANDBOX_GATEWAY_INSTANCE}" if _SANDBOX_GATEWAY_INSTANCE else _base

if (os.getenv("SANDBOX_GATEWAY_PORT") or "").strip():
    SANDBOX_GATEWAY_PORT = _env_int("SANDBOX_GATEWAY_PORT", 9000)
else:
    _offset = _env_int("SANDBOX_GATEWAY_PORT_OFFSET", 0)
    SANDBOX_GATEWAY_PORT = 9000 + int(_offset)
SANDBOX_AGENT_IMAGE = _env_str("SANDBOX_AGENT_IMAGE", "autoppia-sandbox-agent-image")
SANDBOX_AGENT_PORT = _env_int("SANDBOX_AGENT_PORT", 8000)
SANDBOX_CLONE_TIMEOUT_SECONDS = _env_int("SANDBOX_CLONE_TIMEOUT_SECONDS", 90)
# Debug/testing: keep agent containers (and clone dirs) after evaluation so you can inspect
# logs via `docker logs` and examine the cloned repo. Default is False for safety/cleanup.
SANDBOX_KEEP_AGENT_CONTAINERS = _env_bool("SANDBOX_KEEP_AGENT_CONTAINERS", False)
if TESTING:
    SANDBOX_KEEP_AGENT_CONTAINERS = _env_bool("TEST_SANDBOX_KEEP_AGENT_CONTAINERS", SANDBOX_KEEP_AGENT_CONTAINERS)

# Debug/testing: enable miner agent diagnostics (logged to container stdout).
# Keep this off by default to avoid noisy logs in production.
SANDBOX_AGENT_LOG_ERRORS = _env_bool("SANDBOX_AGENT_LOG_ERRORS", False)
SANDBOX_AGENT_LOG_DECISIONS = _env_bool("SANDBOX_AGENT_LOG_DECISIONS", False)
SANDBOX_AGENT_RETURN_METRICS = _env_bool("SANDBOX_AGENT_RETURN_METRICS", False)


# ═══════════════════════════════════════════════════════════════════════════
# CONSENSUS CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

CONSENSUS_VERSION = _env_int("CONSENSUS_VERSION", 1)
MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = _env_float(
    "MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO",
    10000.0,
    test_default=0.0,
)
IWAP_API_BASE_URL = _env_str(
    "IWAP_API_BASE_URL",
    "http://127.0.0.1:8080" if TESTING else "https://api-leaderboard.autoppia.com",
)


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


def validate_config():
    import sys

    import bittensor as bt

    if not VALIDATOR_NAME or not VALIDATOR_IMAGE:
        bt.logging.error("VALIDATOR_NAME and VALIDATOR_IMAGE must be set in the environment before starting the validator.")
        sys.exit(1)


validate_config()
