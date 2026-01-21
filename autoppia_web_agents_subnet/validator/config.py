import os

from autoppia_web_agents_subnet.utils.env import (
    _env_str, 
    _env_bool,
    _env_int, 
    _env_float,
)

TESTING = _env_bool("TESTING", False)

# ═══════════════════════════════════════════════════════════════════════════
# BURN CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

BURN_UID = _env_int("BURN_UID", 5)
BURN_ALL = _env_bool("BURN_ALL", False)

# ═══════════════════════════════════════════════════════════════════════════
# SHARED CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

SEASON_SIZE_EPOCHS = _env_float("SEASON_SIZE_EPOCHS", 280.0, test_default=2.0)
ROUND_SIZE_EPOCHS = _env_float("ROUND_SIZE_EPOCHS", 4.0, test_default=0.2)
MINIMUM_START_BLOCK = _env_int("MINIMUM_START_BLOCK", 6726960)
ROUND_START_UNTIL_FRACTION = _env_float("ROUND_START_UNTIL_FRACTION", 0.3)
MAXIMUM_EVALUATION_TIME = _env_int("MAXIMUM_EVALUATION_TIME", 30) # minutes

PROMPTS_PER_USE_CASE = _env_int("PROMPTS_PER_USE_CASE", 1)
MAX_ACTIONS_LENGTH = _env_int("MAX_ACTIONS_LENGTH", 60)
TIMEOUT = _env_int("TASK_TIMEOUT_SECONDS", 120)
FEEDBACK_TIMEOUT = _env_int("FEEDBACK_TIMEOUT_SECONDS", 60)
ENABLE_DYNAMIC_HTML = _env_bool("ENABLE_DYNAMIC_HTML", True)
SHOULD_RECORD_GIF = _env_bool("SHOULD_RECORD_GIF", True)
PRE_GENERATED_TASKS = _env_int("PRE_GENERATED_TASKS", 1)

EVAL_SCORE_WEIGHT = _env_float("EVAL_SCORE_WEIGHT", 1.0)
TIME_WEIGHT = _env_float("TIME_WEIGHT", 0.0)

SAME_SOLUTION_PENALTY = _env_float("SAME_SOLUTION_PENALTY", 0.0)
SAME_SOLUTION_SIM_THRESHOLD = _env_float("SAME_SOLUTION_SIM_THRESHOLD", 0.90)

VALIDATOR_NAME = _env_str("VALIDATOR_NAME")
VALIDATOR_IMAGE = _env_str("VALIDATOR_IMAGE")
IWAP_VALIDATOR_AUTH_MESSAGE = _env_str("IWAP_VALIDATOR_AUTH_MESSAGE", "I am a honest validator")
MAX_MINER_AGENT_NAME_LENGTH = _env_int("MAX_MINER_AGENT_NAME_LENGTH", 12)
MIN_MINER_STAKE_TAO = _env_float("MIN_MINER_STAKE_TAO", 0.0)
ENABLE_CHECKPOINT_SYSTEM = _env_bool("ENABLE_CHECKPOINT_SYSTEM", True)
IPFS_API_URL = _env_str("IPFS_API_URL", "")
# Comma-separated gateways for fetch fallback
IPFS_GATEWAYS = [
    gw.strip()
    for gw in (_env_str("IPFS_GATEWAYS", "https://ipfs.io/ipfs,https://cloudflare-ipfs.com/ipfs") or "").split(",")
    if gw.strip()
]
FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION = _env_float("FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION", 0.95)
STOP_TASK_EVALUATION_AT_ROUND_FRACTION = _env_float("STOP_TASK_EVALUATION_AT_ROUND_FRACTION", 0.90)
SKIP_ROUND_IF_STARTED_AFTER_FRACTION = _env_float("SKIP_ROUND_IF_STARTED_AFTER_FRACTION", 1.0)

# Testing overrides
if TESTING:
    test_frac = os.getenv("TEST_FETCH_TASK_FRACTION")
    if test_frac:
        try:
            FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION = float(test_frac)
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════════
# SETTLEMENT CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

SETTLEMENT_FRACTION = _env_float("SETTLEMENT_FRACTION", 0.95)
LAST_WINNER_BONUS_PCT = _env_float("LAST_WINNER_BONUS_PCT", 0.05)

# ═══════════════════════════════════════════════════════════════════════════
# SANDBOX / DEPLOYMENT CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

SANDBOX_NETWORK_NAME = _env_str("SANDBOX_NETWORK_NAME", "sandbox-network")
SANDBOX_IMAGE = _env_str("SANDBOX_IMAGE", "autoppia-sandbox-image")
SANDBOX_GATEWAY_IMAGE = _env_str("SANDBOX_GATEWAY_IMAGE", "autoppia-sandbox-gateway-image")
SANDBOX_GATEWAY_HOST = _env_str("SANDBOX_GATEWAY_HOST", "sandbox-gateway")
SANDBOX_GATEWAY_PORT = _env_int("SANDBOX_GATEWAY_PORT", 8080)
SANDBOX_AGENT_PORT = _env_int("SANDBOX_AGENT_PORT", 9000)
SANDBOX_AGENT_START_CMD = _env_str(
    "SANDBOX_AGENT_START_CMD",
    # Miner code is expected to run against a predefined runtime image. We
    # deliberately do NOT install miner-provided requirements.txt at runtime
    # to avoid arbitrary dependency execution and supply-chain risk.
    "cd /sandbox/repo && uvicorn api:app --host 0.0.0.0 --port {port}",
)
SANDBOX_CLONE_TIMEOUT = _env_int("SANDBOX_CLONE_TIMEOUT", 90)

# Require miners to pin their GitHub URL to a specific commit/ref (production safety).
REQUIRE_PINNED_GITHUB_COMMIT = _env_bool("REQUIRE_PINNED_GITHUB_COMMIT", False)

# ═══════════════════════════════════════════════════════════════════════════
# CONSENSUS CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

ENABLE_DISTRIBUTED_CONSENSUS = _env_bool("ENABLE_DISTRIBUTED_CONSENSUS", True)
MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = _env_float("MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO", 10000.0)
IWAP_API_BASE_URL = _env_str("IWAP_API_BASE_URL", "https://api-leaderboard.autoppia.com" if not TESTING else "https://dev-api-leaderboard.autoppia.com")

CONSENSUS_VERIFY_ENABLED = _env_bool("CONSENSUS_VERIFY_ENABLED", False)
CONSENSUS_VERIFY_SAMPLE_SIZE = _env_int("CONSENSUS_VERIFY_SAMPLE_SIZE", 1)
CONSENSUS_VERIFY_SAMPLE_TOLERANCE = _env_float("CONSENSUS_VERIFY_SAMPLE_TOLERANCE", 1e-6)


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def validate_config():
    import sys
    import bittensor as bt

    if not VALIDATOR_NAME or not VALIDATOR_IMAGE:
        bt.logging.error(
            "VALIDATOR_NAME and VALIDATOR_IMAGE must be set in the environment before starting the validator."
        )
        sys.exit(1)
        
validate_config()
