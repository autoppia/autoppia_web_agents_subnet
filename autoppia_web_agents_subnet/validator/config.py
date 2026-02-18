from autoppia_web_agents_subnet.utils.env import (
    _env_str,
    _env_bool,
    _env_int,
    _env_float,
)

import os

TESTING = _env_bool("TESTING", False)


# ═══════════════════════════════════════════════════════════════════════════
# BURN CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
# BURN_AMOUNT_PERCENTAGE: 0.0-1.0 (qué fracción se quema, el resto premia a miners)
# 1.0 = quemar todo. 0.9 = 90% burn, 10% a winner. Igual que en main.
BURN_UID = _env_int("BURN_UID", 5)
BURN_AMOUNT_PERCENTAGE = _env_float("BURN_AMOUNT_PERCENTAGE", 0.9)


# ═══════════════════════════════════════════════════════════════════════════
# SHARED CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

SEASON_SIZE_EPOCHS = _env_float("SEASON_SIZE_EPOCHS", 280.0, test_default=2)
ROUND_SIZE_EPOCHS = _env_float("ROUND_SIZE_EPOCHS", 4.0, test_default=0.5)
MINIMUM_START_BLOCK = _env_int("MINIMUM_START_BLOCK", 7478200, test_default=1000)
ROUND_START_UNTIL_FRACTION = _env_float("ROUND_START_UNTIL_FRACTION", 0.3, test_default=0.6)
MAXIMUM_EVALUATION_TIME = _env_float("MAXIMUM_EVALUATION_TIME", 30.0, test_default=6.0)  # minutes
MAXIMUM_CONSENSUS_TIME = _env_float("MAXIMUM_CONSENSUS_TIME", 15.0, test_default=3.0)  # minutes
SAFETY_BUFFER_EPOCHS = _env_float("SAFETY_BUFFER_EPOCHS", 0.02, test_default=0.02)
AVG_TASK_DURATION_SECONDS = _env_float("AVG_TASK_DURATION_SECONDS", 600.0, test_default=600.0)
STOP_TASK_EVALUATION_AND_UPLOAD_IPFS_AT_ROUND_FRACTION = _env_float("STOP_TASK_EVALUATION_AND_UPLOAD_IPFS_AT_ROUND_FRACTION", 0.90, test_default=0.65)
FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION = _env_float("FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION", 0.95, test_default=0.75)
SKIP_ROUND_IF_STARTED_AFTER_FRACTION = _env_float("SKIP_ROUND_IF_STARTED_AFTER_FRACTION", 0.30, test_default=0.95)

# TASKS_PER_SEASON: Number of tasks to generate for each season (generated only in round 1)
# Tasks are distributed round-robin across all demo projects (1 task per project per cycle)
TASKS_PER_SEASON = _env_int("TASKS_PER_SEASON", 100, test_default=3)
PROMPTS_PER_USE_CASE = _env_int("PROMPTS_PER_USE_CASE", 1)
CONCURRENT_EVALUATION_NUM = _env_int("CONCURRENT_EVALUATION_NUM", 5)
SCREENING_TASKS_FOR_EARLY_STOP = _env_int("SCREENING_TASKS_FOR_EARLY_STOP", 10)
AGENT_MAX_STEPS = _env_int("AGENT_MAX_STEPS", 30, test_default=1)
AGENT_STEP_TIMEOUT = _env_int("AGENT_STEP_TIMEOUT", 180)  # seconds
MAX_ACTIONS_LENGTH = _env_int("MAX_ACTIONS_LENGTH", 30, test_default=30)
TIMEOUT = _env_float("TIMEOUT", 180.0, test_default=180.0)  # seconds
FEEDBACK_TIMEOUT = _env_float("FEEDBACK_TIMEOUT", 30.0, test_default=30.0)  # seconds
SHOULD_RECORD_GIF = _env_bool("SHOULD_RECORD_GIF", True)

COST_LIMIT_ENABLED = _env_bool("COST_LIMIT_ENABLED", True)
COST_LIMIT_VALUE = _env_float("COST_LIMIT_VALUE", 10.0)  # USD

MAXIMUM_EXECUTION_TIME = _env_float("MAXIMUM_EXECUTION_TIME", 300.0)  # seconds
MAXIMUM_TOKEN_COST = _env_float("MAXIMUM_TOKEN_COST", 0.1)  # USD

EVAL_SCORE_WEIGHT = _env_float("EVAL_SCORE_WEIGHT", 1.0)
TIME_WEIGHT = _env_float("TIME_WEIGHT", 0.0)
COST_WEIGHT = _env_float("COST_WEIGHT", 0.0)

SAME_SOLUTION_PENALTY = _env_float("SAME_SOLUTION_PENALTY", 0.0)
SAME_SOLUTION_SIM_THRESHOLD = _env_float("SAME_SOLUTION_SIM_THRESHOLD", 0.90)

# Miner submission policy:
# Require an explicit git ref (branch/tag) or a pinned commit URL, instead of
# accepting bare repo URLs (which implicitly track the default branch).
REQUIRE_MINER_GITHUB_REF = _env_bool("REQUIRE_MINER_GITHUB_REF", True)

# Evaluation resource controls:
# 1) Per-round stake window: only handshake/evaluate the top N miners by stake.
#    Set to 0 to disable.
MAX_MINERS_PER_ROUND_BY_STAKE = _env_int("MAX_MINERS_PER_ROUND_BY_STAKE", 10, test_default=0)
# 2) Cooldown: minimum number of rounds between evaluations for the same miner.
#    Set to 0 to disable.
EVALUATION_COOLDOWN_ROUNDS = _env_int("EVALUATION_COOLDOWN_ROUNDS", 2, test_default=0)

# Early stop: abort evaluating a miner when it can no longer beat the current best
# possible average reward (winner-takes-all settlement), saving time and cost.
EARLY_STOP_BEHIND_BEST = _env_bool("EARLY_STOP_BEHIND_BEST", False)

VALIDATOR_NAME = _env_str("VALIDATOR_NAME")
VALIDATOR_IMAGE = _env_str("VALIDATOR_IMAGE")
IWAP_VALIDATOR_AUTH_MESSAGE = _env_str("IWAP_VALIDATOR_AUTH_MESSAGE", "I am a honest validator")
MAX_MINER_AGENT_NAME_LENGTH = _env_int("MAX_MINER_AGENT_NAME_LENGTH", 12)
MIN_MINER_STAKE_TAO = _env_float("MIN_MINER_STAKE_TAO", 0.0, test_default=0.0)
IPFS_API_URL = _env_str("IPFS_API_URL", "http://ipfs.metahash73.com:5001/api/v0")
# Comma-separated gateways for fetch fallback
IPFS_GATEWAYS = [gw.strip() for gw in (_env_str("IPFS_GATEWAYS", "https://ipfs.io/ipfs,https://cloudflare-ipfs.com/ipfs") or "").split(",") if gw.strip()]


# ═══════════════════════════════════════════════════════════════════════════
# SETTLEMENT CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

SETTLEMENT_FRACTION = _env_float("SETTLEMENT_FRACTION", 0.95, test_default=0.8)
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
SANDBOX_AGENT_IMAGE = _env_str("SANDBOX_IMAGE", "autoppia-sandbox-agent-image")
SANDBOX_AGENT_PORT = _env_int("SANDBOX_AGENT_PORT", 8000)
SANDBOX_CLONE_TIMEOUT = _env_int("SANDBOX_CLONE_TIMEOUT", 90)
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
ENABLE_DISTRIBUTED_CONSENSUS = _env_bool(
    "ENABLE_DISTRIBUTED_CONSENSUS",
    True,
    test_default=True,
)
MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = _env_float(
    "MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO",
    10000.0,
    test_default=0.0,
)
UPLOAD_TASK_LOGS = _env_bool("UPLOAD_TASK_LOGS", False, test_default=True)
IWAP_API_BASE_URL = _env_str("IWAP_API_BASE_URL", "https://api-leaderboard.autoppia.com" if not TESTING else "https://dev-api-leaderboard.autoppia.com")


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
