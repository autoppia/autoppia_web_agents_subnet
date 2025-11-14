from dotenv import load_dotenv
load_dotenv()

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

ROUND_SIZE_EPOCHS = _env_float("ROUND_SIZE_EPOCHS", 4.0, test_default=0.2)
MINIMUM_START_BLOCK = _env_int("MINIMUM_START_BLOCK", 6726960)

PROMPTS_PER_USE_CASE = _env_int("PROMPTS_PER_USE_CASE", 1)
MAX_ACTIONS_LENGTH = _env_int("MAX_ACTIONS_LENGTH", 60)
TIMEOUT = _env_int("TASK_TIMEOUT_SECONDS", 120)
FEEDBACK_TIMEOUT = _env_int("FEEDBACK_TIMEOUT_SECONDS", 60)
ENABLE_DYNAMIC_HTML = _env_bool("ENABLE_DYNAMIC_HTML", True)
SHOULD_RECORD_GIF = _env_bool("SHOULD_RECORD_GIF", True)

EVAL_SCORE_WEIGHT = _env_float("EVAL_SCORE_WEIGHT", 1.0)
TIME_WEIGHT = _env_float("TIME_WEIGHT", 0.0)

SAME_SOLUTION_PENALTY = _env_float("SAME_SOLUTION_PENALTY", 0.0)
SAME_SOLUTION_SIM_THRESHOLD = _env_float("SAME_SOLUTION_SIM_THRESHOLD", 0.90)

VALIDATOR_NAME = _env_str("VALIDATOR_NAME")
VALIDATOR_IMAGE = _env_str("VALIDATOR_IMAGE")
IWAP_VALIDATOR_AUTH_MESSAGE = _env_str("IWAP_VALIDATOR_AUTH_MESSAGE", "I am a honest validator")
MAX_MINER_AGENT_NAME_LENGTH = _env_int("MAX_MINER_AGENT_NAME_LENGTH", 12)

# ═══════════════════════════════════════════════════════════════════════════
# SCREENING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

SCREENING_START_FRACTION = _env_float("SCREENING_START_FRACTION", 0.0)
SCREENING_START_UNTIL_FRACTION = _env_float("SCREENING_START_UNTIL_FRACTION", 0.2)
SCREENING_STOP_FRACTION = _env_float("SCREENING_STOP_FRACTION", 0.45)
SCREENING_PRE_GENERATED_TASKS = _env_int("SCREENING_PRE_GENERATED_TASKS", 10)

# ═══════════════════════════════════════════════════════════════════════════
# FINAL CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

FINAL_START_FRACTION = _env_float("FINAL_START_FRACTION", 0.5)
FINAL_START_UNTIL_FRACTION = _env_float("FINAL_START_UNTIL_FRACTION", 0.7)
FINAL_STOP_FRACTION = _env_float("FINAL_STOP_FRACTION", 0.9)
FINAL_PRE_GENERATED_TASKS = _env_int("FINAL_PRE_GENERATED_TASKS", 10)
FINAL_TOP_K = _env_int("FINAL_TOP_K", 3)

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

    if not (
        0 <= SCREENING_START_FRACTION < 
        SCREENING_START_UNTIL_FRACTION < 
        SCREENING_STOP_FRACTION < 
        FINAL_START_FRACTION < 
        FINAL_START_UNTIL_FRACTION < 
        FINAL_STOP_FRACTION <= 1.0
    ):
        bt.logging.error(
            "Fraction values must form a strictly increasing sequence "
            "from 0 to 1.0 in the order: screening_start, screening_start_until, "
            "screening_stop, final_start, final_start_until, final_stop. "
        )
        sys.exit(1)

validate_config()