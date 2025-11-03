import os
from dotenv import load_dotenv

from autoppia_web_agents_subnet.utils.env import (
    _env_float,
    _env_int,
    _normalized,
    _str_to_bool,
)

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════
# ENVIRONMENT MODE
# ═══════════════════════════════════════════════════════════════════════════
TESTING = _str_to_bool(os.getenv("TESTING", "false"))

# ── Burn configuration ──────────────────────────────────────────────────────
BURN_UID = _env_int("BURN_UID", 5)
BURN_ALL = _str_to_bool(os.getenv("BURN_ALL", "false"))

# ═══════════════════════════════════════════════════════════════════════════
# TESTING CONFIGURATION (fast rounds)
# ═══════════════════════════════════════════════════════════════════════════
if TESTING:
    ROUND_SIZE_EPOCHS = _env_float("TEST_ROUND_SIZE_EPOCHS", 0.2)
    SAFETY_BUFFER_EPOCHS = _env_float("TEST_SAFETY_BUFFER_EPOCHS", 0.02)
    AVG_TASK_DURATION_SECONDS = _env_int("TEST_AVG_TASK_DURATION_SECONDS", 300)
    PRE_GENERATED_TASKS = _env_int("TEST_PRE_GENERATED_TASKS", 3)
    DZ_STARTING_BLOCK = _env_int("TEST_DZ_STARTING_BLOCK", 6726960)

    STOP_TASK_EVALUATION_AT_ROUND_FRACTION = _env_float("TEST_STOP_TASK_FRACTION", 0.65)
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION = _env_float("TEST_FETCH_TASK_FRACTION", 0.75)
    SKIP_ROUND_IF_STARTED_AFTER_FRACTION = _env_float("TEST_SKIP_ROUND_AFTER_FRACTION", 0.95)

    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = _env_float("TEST_MIN_STAKE_FOR_CONSENSUS", 0.0)
    IWAP_API_BASE_URL = os.getenv("IWAP_API_BASE_URL", "https://dev-api-leaderboard.autoppia.com")

    CONSENSUS_VERIFICATION_ENABLED = _str_to_bool(os.getenv("CONSENSUS_VERIFICATION_ENABLED", "true"))
    CONSENSUS_VERIFICATION_SAMPLE_FRACTION = _env_float("CONSENSUS_VERIFICATION_SAMPLE_FRACTION", 0.10)
    CONSENSUS_VERIFY_SAMPLE_MIN = _env_int("CONSENSUS_VERIFY_SAMPLE_MIN", 30)
    CONSENSUS_VERIFY_SAMPLE_TOLERANCE = _env_float("CONSENSUS_VERIFY_SAMPLE_TOLERANCE", 1e-6)
    CONSENSUS_VERIFY_SAMPLE_MAX_CONCURRENCY = _env_int("CONSENSUS_VERIFY_SAMPLE_MAX_CONCURRENCY", 2)
    CONSENSUS_DATASET_EMBED = _str_to_bool(os.getenv("CONSENSUS_DATASET_EMBED", "false"))

# ═══════════════════════════════════════════════════════════════════════════
# PRODUCTION CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
else:
    ROUND_SIZE_EPOCHS = _env_float("ROUND_SIZE_EPOCHS", 4.0)
    SAFETY_BUFFER_EPOCHS = _env_float("SAFETY_BUFFER_EPOCHS", 0.5)
    AVG_TASK_DURATION_SECONDS = _env_int("AVG_TASK_DURATION_SECONDS", 300)
    PRE_GENERATED_TASKS = _env_int("PRE_GENERATED_TASKS", 188)
    DZ_STARTING_BLOCK = _env_int("DZ_STARTING_BLOCK", 6726960)

    STOP_TASK_EVALUATION_AT_ROUND_FRACTION = _env_float("STOP_TASK_EVALUATION_AT_ROUND_FRACTION", 0.90)
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION = _env_float("FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION", 0.95)
    SKIP_ROUND_IF_STARTED_AFTER_FRACTION = _env_float("SKIP_ROUND_IF_STARTED_AFTER_FRACTION", 0.30)

    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = _env_float("MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO", 10000.0)
    IWAP_API_BASE_URL = os.getenv("IWAP_API_BASE_URL", "https://api-leaderboard.autoppia.com")

    CONSENSUS_VERIFICATION_ENABLED = _str_to_bool(os.getenv("CONSENSUS_VERIFICATION_ENABLED", "false"))
    CONSENSUS_VERIFICATION_SAMPLE_FRACTION = _env_float("CONSENSUS_VERIFICATION_SAMPLE_FRACTION", 0.10)
    CONSENSUS_VERIFY_SAMPLE_MIN = _env_int("CONSENSUS_VERIFY_SAMPLE_MIN", 100)
    CONSENSUS_VERIFY_SAMPLE_TOLERANCE = _env_float("CONSENSUS_VERIFY_SAMPLE_TOLERANCE", 1e-6)
    CONSENSUS_VERIFY_SAMPLE_MAX_CONCURRENCY = _env_int("CONSENSUS_VERIFY_SAMPLE_MAX_CONCURRENCY", 2)
    CONSENSUS_DATASET_EMBED = _str_to_bool(os.getenv("CONSENSUS_DATASET_EMBED", "false"))

# ═══════════════════════════════════════════════════════════════════════════
# SHARED CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
PROMPTS_PER_USECASE = _env_int("PROMPTS_PER_USECASE", 1)
MAX_ACTIONS_LENGTH = _env_int("MAX_ACTIONS_LENGTH", 60)
TIMEOUT = _env_int("TASK_TIMEOUT_SECONDS", 120)
FEEDBACK_TIMEOUT = _env_int("FEEDBACK_TIMEOUT_SECONDS", 60)

ENABLE_DYNAMIC_HTML = _str_to_bool(os.getenv("ENABLE_DYNAMIC_HTML", "true"))
SHOULD_RECORD_GIF = _str_to_bool(os.getenv("SHOULD_RECORD_GIF", "true"))

EVAL_SCORE_WEIGHT = _env_float("EVAL_SCORE_WEIGHT", 1.0)
TIME_WEIGHT = _env_float("TIME_WEIGHT", 0.0)

SAME_SOLUTION_PENALTY = _env_float("SAME_SOLUTION_PENALTY", 0.0)
SAME_SOLUTION_SIM_THRESHOLD = _env_float("SAME_SOLUTION_SIM_THRESHOLD", 0.90)

VALIDATOR_NAME = _normalized(os.getenv("VALIDATOR_NAME"))
VALIDATOR_IMAGE = _normalized(os.getenv("VALIDATOR_IMAGE"))
MAX_MINER_AGENT_NAME_LENGTH = _env_int("MAX_MINER_AGENT_NAME_LENGTH", 12)

IWAP_VALIDATOR_AUTH_MESSAGE = _normalized(os.getenv("IWAP_VALIDATOR_AUTH_MESSAGE", "I am a honest validator"))

ENABLE_CHECKPOINT_SYSTEM = _str_to_bool(os.getenv("ENABLE_CHECKPOINT_SYSTEM", "true"))
ENABLE_DISTRIBUTED_CONSENSUS = _str_to_bool(os.getenv("ENABLE_DISTRIBUTED_CONSENSUS", "true"))

IPFS_API_URL = os.getenv("IPFS_API_URL", "http://ipfs.metahash73.com:5001/api/v0")
IPFS_GATEWAYS = [
    g.strip()
    for g in (os.getenv("IPFS_GATEWAYS", "https://ipfs.io/ipfs,https://cloudflare-ipfs.com/ipfs,https://gateway.pinata.cloud/ipfs") or "").split(",")
    if g.strip()
]

# Screening / Final two-stage evaluation
SCREENING_TOP_S = _env_int("SCREENING_TOP_S", 4)
SCREENING_STOP_FRACTION = _env_float("SCREENING_STOP_FRACTION", 0.40 if not TESTING else 0.30)
FINAL_TIE_BONUS_PCT = _env_float("FINAL_TIE_BONUS_PCT", 5.0)
FINAL_TIE_EPSILON = _env_float("FINAL_TIE_EPSILON", 1e-6)
ENABLE_FINAL_LOCAL = _str_to_bool(os.getenv("ENABLE_FINAL_LOCAL", "true"))
CONSENSUS_PROPAGATION_DELAY_SEC = _env_int("CONSENSUS_PROPAGATION_DELAY_SEC", 12)
PROPAGATION_BLOCKS_SLEEP = _env_int("PROPAGATION_BLOCKS_SLEEP", 0)

# Misc helpers
IWAP_BACKUP_DIR = os.getenv("IWAP_BACKUP_DIR")
