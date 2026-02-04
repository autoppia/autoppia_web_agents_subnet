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

SEASON_SIZE_EPOCHS = _env_float("SEASON_SIZE_EPOCHS", 280.0, test_default=4.0)
ROUND_SIZE_EPOCHS = _env_float("ROUND_SIZE_EPOCHS", 4.0, test_default=1.0)
MINIMUM_START_BLOCK = _env_int("MINIMUM_START_BLOCK", 6726960)
ROUND_START_UNTIL_FRACTION = _env_float("ROUND_START_UNTIL_FRACTION", 0.3, test_default=0.6)
MAXIMUM_EVALUATION_TIME = _env_float("MAXIMUM_EVALUATION_TIME", 30.0, test_default=6.0) # minutes
MAXIMUM_CONSENSUS_TIME = _env_float("MAXIMUM_CONSENSUS_TIME", 15.0, test_default=3.0) # minutes

PROMPTS_PER_USE_CASE = _env_int("PROMPTS_PER_USE_CASE", 1)
PRE_GENERATED_TASKS = _env_int("PRE_GENERATED_TASKS", 1)
AGENT_MAX_STEPS = _env_int("AGENT_MAX_STEPS", 30, test_default=1)

EVAL_SCORE_WEIGHT = _env_float("EVAL_SCORE_WEIGHT", 1.0)
TIME_WEIGHT = _env_float("TIME_WEIGHT", 0.0)
COST_WEIGHT = _env_float("COST_WEIGHT", 0.0)

SAME_SOLUTION_PENALTY = _env_float("SAME_SOLUTION_PENALTY", 0.0)
SAME_SOLUTION_SIM_THRESHOLD = _env_float("SAME_SOLUTION_SIM_THRESHOLD", 0.90)

VALIDATOR_NAME = _env_str("VALIDATOR_NAME")
VALIDATOR_IMAGE = _env_str("VALIDATOR_IMAGE")
IWAP_VALIDATOR_AUTH_MESSAGE = _env_str("IWAP_VALIDATOR_AUTH_MESSAGE", "I am a honest validator")
MAX_MINER_AGENT_NAME_LENGTH = _env_int("MAX_MINER_AGENT_NAME_LENGTH", 12)
MIN_MINER_STAKE_TAO = _env_float("MIN_MINER_STAKE_TAO", 0.0, test_default=0.0)
IPFS_API_URL = _env_str("IPFS_API_URL", "http://ipfs.metahash73.com:5001/api/v0")
# Comma-separated gateways for fetch fallback
IPFS_GATEWAYS = [
    gw.strip()
    for gw in (_env_str("IPFS_GATEWAYS", "https://ipfs.io/ipfs,https://cloudflare-ipfs.com/ipfs") or "").split(",")
    if gw.strip()
]


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
SANDBOX_GATEWAY_HOST = _env_str("SANDBOX_GATEWAY_HOST", "sandbox-gateway")
SANDBOX_GATEWAY_PORT = _env_int("SANDBOX_GATEWAY_PORT", 9000)
SANDBOX_AGENT_IMAGE = _env_str("SANDBOX_IMAGE", "autoppia-sandbox-agent-image")
SANDBOX_AGENT_PORT = _env_int("SANDBOX_AGENT_PORT", 8000)
SANDBOX_CLONE_TIMEOUT = _env_int("SANDBOX_CLONE_TIMEOUT", 90)


# ═══════════════════════════════════════════════════════════════════════════
# CONSENSUS CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

CONSENSUS_VERSION = _env_int("CONSENSUS_VERSION", 1)
ENABLE_DISTRIBUTED_CONSENSUS = _env_bool("ENABLE_DISTRIBUTED_CONSENSUS", True)
MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = _env_float("MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO", 10000.0)
IWAP_API_BASE_URL = _env_str("IWAP_API_BASE_URL", "https://api-leaderboard.autoppia.com" if not TESTING else "https://dev-api-leaderboard.autoppia.com")


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
