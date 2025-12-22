import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Shared env helpers
from autoppia_web_agents_subnet.utils.env import (  # noqa: E402
    _str_to_bool,
    _normalized,
    _env_int,
    _env_float,
)

# ═══════════════════════════════════════════════════════════════════════════
# ENVIRONMENT MODE
# ═══════════════════════════════════════════════════════════════════════════

TESTING = _str_to_bool(os.getenv("TESTING", "false"))

# ── Burn Mechanism ───────────────────────────────────────────────────────────
BURN_UID = _env_int("BURN_UID", 5)
# Default 0.925 = 92.5% burn, 7.5% to winner
BURN_AMOUNT_PERCENTAGE = _env_float("BURN_AMOUNT_PERCENTAGE", 0.925)


# ═══════════════════════════════════════════════════════════════════════════
# TESTING CONFIGURATION (Fast iterations for development)
# ═══════════════════════════════════════════════════════════════════════════
if TESTING:
    # ── Round Structure ──────────────────────────────────────────────────────
    # Short rounds for rapid testing (~25 minutes per round)
    ROUND_SIZE_EPOCHS = _env_float("TEST_ROUND_SIZE_EPOCHS", 0.347)
    SAFETY_BUFFER_EPOCHS = _env_float("TEST_SAFETY_BUFFER_EPOCHS", 0.02)
    AVG_TASK_DURATION_SECONDS = _env_int("TEST_AVG_TASK_DURATION_SECONDS", 300)
    PRE_GENERATED_TASKS = _env_int("TEST_PRE_GENERATED_TASKS", 3)
    DZ_STARTING_BLOCK = _env_int("TEST_DZ_STARTING_BLOCK", 6949035)  # Synced with PROD

    # ── Round Phase Timing (all absolute % of total round) ──────────────────
    # Stop task evaluation at 50% of round to allow time for consensus
    STOP_TASK_EVALUATION_AT_ROUND_FRACTION = 0.65
    # Fetch IPFS payloads at 75% of round (gives 25% gap for propagation)
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION = 0.75

    # ── Late Start Protection ────────────────────────────────────────────────
    # Skip round only if started when >95% complete (very permissive for testing)
    # Allow overriding via env var for local tuning.
    SKIP_ROUND_IF_STARTED_AFTER_FRACTION = _env_float("SKIP_ROUND_IF_STARTED_AFTER_FRACTION", 0.95)

    # ── Consensus Participation Requirements ─────────────────────────────────
    # Testing: No stake required (0 τ) - anyone can participate
    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = 0.0
    IWAP_API_BASE_URL = os.getenv("IWAP_API_BASE_URL", "https://dev-api-leaderboard.autoppia.com")

# ═══════════════════════════════════════════════════════════════════════════
# PRODUCTION CONFIGURATION (4.8-hour rounds, conservative)
# ═══════════════════════════════════════════════════════════════════════════
else:
    # ── Round Structure ──────────────────────────────────────────────────────
    # Production rounds (~3.6 hours) - 3 epochs for optimal balance
    ROUND_SIZE_EPOCHS = _env_float("ROUND_SIZE_EPOCHS", 3.0)
    SAFETY_BUFFER_EPOCHS = _env_float("SAFETY_BUFFER_EPOCHS", 0.5)
    AVG_TASK_DURATION_SECONDS = _env_int("AVG_TASK_DURATION_SECONDS", 150)
    # Increased default tasks for production to extend execution closer to the
    # reserved consensus window. Previous default was 75; 2.5x -> ~188.
    # Environment variable PRE_GENERATED_TASKS still takes precedence.
    PRE_GENERATED_TASKS = _env_int("PRE_GENERATED_TASKS", 75)
    DZ_STARTING_BLOCK = _env_int("DZ_STARTING_BLOCK", 7084250)

    # ── Round Phase Timing (all absolute % of total round) ──────────────────
    # Stop task evaluation at 90% of round to reserve time for consensus
    STOP_TASK_EVALUATION_AT_ROUND_FRACTION = 0.90
    # Fetch IPFS payloads at 95% of round (gives 5% gap for propagation)
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION = 0.95

    # ── Late Start Protection ────────────────────────────────────────────────
    # Skip round if started when >30% complete (conservative for production)
    # Allow overriding via env var for operators who want to be more permissive.
    SKIP_ROUND_IF_STARTED_AFTER_FRACTION = _env_float("SKIP_ROUND_IF_STARTED_AFTER_FRACTION", 0.30)

    # ── Consensus Participation Requirements ─────────────────────────────────
    # Production: Minimum 10k τ stake required to be included in consensus calculations
    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = 10000.0
    IWAP_API_BASE_URL = os.getenv("IWAP_API_BASE_URL", "https://api-leaderboard.autoppia.com")
# ═══════════════════════════════════════════════════════════════════════════
# SHARED CONFIGURATION (same for all modes)
# ═══════════════════════════════════════════════════════════════════════════

# ── Task Execution Settings ──────────────────────────────────────────────────
PROMPTS_PER_USECASE = 1
MAX_ACTIONS_LENGTH = 60
TIMEOUT = 120
FEEDBACK_TIMEOUT = 60

# ── Dynamic Task Generation (v1, v2, v3 features) ──────────────────────────────
# Controls whether tasks are generated with dynamic features (v1: seed, v2: DB selection, v3: structure)
# Note: Seeds are ALWAYS sent in task URLs regardless of this setting
ENABLE_DYNAMIC = _str_to_bool(os.getenv("ENABLE_DYNAMIC", "true"))
SHOULD_RECORD_GIF = _str_to_bool(os.getenv("SHOULD_RECORD_GIF", "true"))

# ── Scoring Weights ──────────────────────────────────────────────────────────
EVAL_SCORE_WEIGHT = float(os.getenv("EVAL_SCORE_WEIGHT", "0.995")) 
# TIME_WEIGHT: Small weight to incorporate execution time as tiebreaker in score calculation
TIME_WEIGHT = float(os.getenv("TIME_WEIGHT", "0.005")) 

# ── Validator Identity (IWAP) ────────────────────────────────────────────────
VALIDATOR_NAME = _normalized(os.getenv("VALIDATOR_NAME"))
VALIDATOR_IMAGE = _normalized(os.getenv("VALIDATOR_IMAGE"))
MAX_MINER_AGENT_NAME_LENGTH = _env_int("MAX_MINER_AGENT_NAME_LENGTH", 12)

# ── IWAP Leaderboard API ─────────────────────────────────────────────────────

IWAP_VALIDATOR_AUTH_MESSAGE = _normalized(os.getenv("IWAP_VALIDATOR_AUTH_MESSAGE", "I am a honest validator"))


# ── Distributed Consensus (IPFS + Blockchain) ────────────────────────────────
# Enabled by default, can be disabled via .env (works in both testing and production)
ENABLE_DISTRIBUTED_CONSENSUS = _str_to_bool(os.getenv("ENABLE_DISTRIBUTED_CONSENSUS", "true"))

# ── IPFS Storage ─────────────────────────────────────────────────────────────
IPFS_API_URL = os.getenv("IPFS_API_URL", "http://ipfs.metahash73.com:5001/api/v0")
IPFS_GATEWAYS = [g.strip() for g in (os.getenv("IPFS_GATEWAYS", "https://ipfs.io/ipfs,https://cloudflare-ipfs.com/ipfs,https://gateway.pinata.cloud/ipfs") or "").split(",") if g.strip()]
