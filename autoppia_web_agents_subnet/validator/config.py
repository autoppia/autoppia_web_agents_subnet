import os
from pathlib import Path
from typing import Optional
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

# ═══════════════════════════════════════════════════════════════════════════
# TESTING CONFIGURATION (Fast iterations for development)
# ═══════════════════════════════════════════════════════════════════════════
if TESTING:
    # ── Round Structure ──────────────────────────────────────────────────────
    # Short rounds for rapid testing (~14.4 minutes per round)
    ROUND_SIZE_EPOCHS = _env_float("TEST_ROUND_SIZE_EPOCHS", 0.2)
    SAFETY_BUFFER_EPOCHS = _env_float("TEST_SAFETY_BUFFER_EPOCHS", 0.02)
    AVG_TASK_DURATION_SECONDS = _env_int("TEST_AVG_TASK_DURATION_SECONDS", 300)
    PRE_GENERATED_TASKS = _env_int("TEST_PRE_GENERATED_TASKS", 3)
    DZ_STARTING_BLOCK = _env_int("TEST_DZ_STARTING_BLOCK", 6726960)

    # ── Round Phase Timing (all absolute % of total round) ──────────────────
    # Stop task evaluation at 50% of round to allow time for consensus
    STOP_TASK_EVALUATION_AT_ROUND_FRACTION = 0.65
    # Fetch IPFS payloads at 75% of round (gives 25% gap for propagation)
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION = 0.75

    # ── Late Start Protection ────────────────────────────────────────────────
    # Skip round only if started when >95% complete (very permissive for testing)
    SKIP_ROUND_IF_STARTED_AFTER_FRACTION = 0.95

    # ── Consensus Participation Requirements ─────────────────────────────────
    # Testing: No stake required (0 τ) - anyone can participate
    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = 0.0
    IWAP_API_BASE_URL = "https://dev-api-leaderboard.autoppia.com"
    # ── Consensus dataset verification (testing defaults) ─────────────────────
    CONSENSUS_VERIFICATION_ENABLED = _str_to_bool(os.getenv("CONSENSUS_VERIFICATION_ENABLED", "true"))
    CONSENSUS_VERIFICATION_SAMPLE_FRACTION = _env_float("CONSENSUS_VERIFICATION_SAMPLE_FRACTION", 0.10)
    CONSENSUS_VERIFY_SAMPLE_MIN = _env_int("CONSENSUS_VERIFY_SAMPLE_MIN", 30)
    CONSENSUS_VERIFY_SAMPLE_TOLERANCE = _env_float("CONSENSUS_VERIFY_SAMPLE_TOLERANCE", 1e-6)
    # Renamed for clarity: concurrency cap during verify sampling
    CONSENSUS_VERIFY_SAMPLE_MAX_CONCURRENCY = _env_int("CONSENSUS_VERIFY_SAMPLE_MAX_CONCURRENCY", 2)
    CONSENSUS_DATASET_EMBED = _str_to_bool(os.getenv("CONSENSUS_DATASET_EMBED", "false"))

# ═══════════════════════════════════════════════════════════════════════════
# PRODUCTION CONFIGURATION (4.8-hour rounds, conservative)
# ═══════════════════════════════════════════════════════════════════════════
else:
    # ── Round Structure ──────────────────────────────────────────────────────
    # Production rounds (~4.8 hours) - Changed from 20 epochs to 4 for faster iterations
    ROUND_SIZE_EPOCHS = _env_float("ROUND_SIZE_EPOCHS", 4.0)
    SAFETY_BUFFER_EPOCHS = _env_float("SAFETY_BUFFER_EPOCHS", 0.5)
    AVG_TASK_DURATION_SECONDS = _env_int("AVG_TASK_DURATION_SECONDS", 300)
    # Increased default tasks for production to extend execution closer to the
    # reserved consensus window. Previous default was 75; 2.5x -> ~188.
    # Environment variable PRE_GENERATED_TASKS still takes precedence.
    PRE_GENERATED_TASKS = _env_int("PRE_GENERATED_TASKS", 188)
    DZ_STARTING_BLOCK = _env_int("DZ_STARTING_BLOCK", 6726960)

    # ── Round Phase Timing (all absolute % of total round) ──────────────────
    # Stop task evaluation at 90% of round to reserve time for consensus
    STOP_TASK_EVALUATION_AT_ROUND_FRACTION = 0.90
    # Fetch IPFS payloads at 95% of round (gives 5% gap for propagation)
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION = 0.95

    # ── Late Start Protection ────────────────────────────────────────────────
    # Skip round if started when >30% complete (conservative for production)
    SKIP_ROUND_IF_STARTED_AFTER_FRACTION = 0.30

    # ── Consensus Participation Requirements ─────────────────────────────────
    # Production: Minimum 10k τ stake required to be included in consensus calculations
    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = 10000.0
    IWAP_API_BASE_URL = "https://api-leaderboard.autoppia.com"
    # ── Consensus dataset verification (production defaults) ──────────────────
    CONSENSUS_VERIFICATION_ENABLED = _str_to_bool(os.getenv("CONSENSUS_VERIFICATION_ENABLED", "false"))
    CONSENSUS_VERIFICATION_SAMPLE_FRACTION = _env_float("CONSENSUS_VERIFICATION_SAMPLE_FRACTION", 0.10)
    CONSENSUS_VERIFY_SAMPLE_MIN = _env_int("CONSENSUS_VERIFY_SAMPLE_MIN", 100)
    CONSENSUS_VERIFY_SAMPLE_TOLERANCE = _env_float("CONSENSUS_VERIFY_SAMPLE_TOLERANCE", 1e-6)
    # Renamed for clarity: concurrency cap during verify sampling
    CONSENSUS_VERIFY_SAMPLE_MAX_CONCURRENCY = _env_int("CONSENSUS_VERIFY_SAMPLE_MAX_CONCURRENCY", 2)
    CONSENSUS_DATASET_EMBED = _str_to_bool(os.getenv("CONSENSUS_DATASET_EMBED", "false"))
# ═══════════════════════════════════════════════════════════════════════════
# SHARED CONFIGURATION (same for all modes)
# ═══════════════════════════════════════════════════════════════════════════

# ── Task Execution Settings ──────────────────────────────────────────────────
PROMPTS_PER_USECASE = 1
MAX_ACTIONS_LENGTH = 60
TIMEOUT = 120
FEEDBACK_TIMEOUT = 60

# ── Dynamic HTML / Media ─────────────────────────────────────────────────────
ENABLE_DYNAMIC_HTML = _str_to_bool(os.getenv("ENABLE_DYNAMIC_HTML", "true"))
SHOULD_RECORD_GIF = _str_to_bool(os.getenv("SHOULD_RECORD_GIF", "true"))

# ── Scoring Weights ──────────────────────────────────────────────────────────
EVAL_SCORE_WEIGHT = 1.0
TIME_WEIGHT = 0.0

# ── Duplicate Solution Penalty ───────────────────────────────────────────────
# If 2+ miners submit the same or highly similar solutions for a task,
# multiply their evaluation score by this penalty. Default 0.0 to zero-out.
SAME_SOLUTION_PENALTY = _env_float("SAME_SOLUTION_PENALTY", 0.0)
# Similarity threshold in [0,1] to consider two solutions "the same".
# Keep this high to only catch near-identical solutions.
SAME_SOLUTION_SIM_THRESHOLD = _env_float("SAME_SOLUTION_SIM_THRESHOLD", 0.90)

# ── Validator Identity (IWAP) ────────────────────────────────────────────────
VALIDATOR_NAME = _normalized(os.getenv("VALIDATOR_NAME"))
VALIDATOR_IMAGE = _normalized(os.getenv("VALIDATOR_IMAGE"))
MAX_MINER_AGENT_NAME_LENGTH = _env_int("MAX_MINER_AGENT_NAME_LENGTH", 12)

# ── IWAP Leaderboard API ─────────────────────────────────────────────────────

IWAP_VALIDATOR_AUTH_MESSAGE = _normalized(os.getenv("IWAP_VALIDATOR_AUTH_MESSAGE", "I am a honest validator"))

# ── Checkpoint System & Recovery ─────────────────────────────────────────────
# Enable checkpoint system (save/load round state for crash recovery)
# Enabled by default, can be disabled via .env (works in both testing and production)
ENABLE_CHECKPOINT_SYSTEM = _str_to_bool(os.getenv("ENABLE_CHECKPOINT_SYSTEM", "true"))

# ── Distributed Consensus (IPFS + Blockchain) ────────────────────────────────
# Enabled by default, can be disabled via .env (works in both testing and production)
ENABLE_DISTRIBUTED_CONSENSUS = _str_to_bool(os.getenv("ENABLE_DISTRIBUTED_CONSENSUS", "true"))

# ── IPFS Storage ─────────────────────────────────────────────────────────────
IPFS_API_URL = os.getenv("IPFS_API_URL", "http://ipfs.metahash73.com:5001/api/v0")
IPFS_GATEWAYS = [g.strip() for g in (os.getenv("IPFS_GATEWAYS", "https://ipfs.io/ipfs,https://cloudflare-ipfs.com/ipfs,https://gateway.pinata.cloud/ipfs") or "").split(",") if g.strip()]

# ── Burn Mechanism ───────────────────────────────────────────────────────────
BURN_UID = _env_int("BURN_UID", 5)

# ═══════════════════════════════════════════════════════════════════════════
# Screening / Final phase (two-stage evaluation)
# ═══════════════════════════════════════════════════════════════════════════
# Number of miners to take to the final local phase
SCREENING_TOP_S = _env_int("SCREENING_TOP_S", 4)
# Fraction of the round time reserved for screening (0..1)
SCREENING_STOP_FRACTION = _env_float("SCREENING_STOP_FRACTION", 0.40 if not TESTING else 0.30)
# Final tie-break bonus percentage for last round's winner (only when tied)
FINAL_TIE_BONUS_PCT = _env_float("FINAL_TIE_BONUS_PCT", 5.0)
FINAL_TIE_EPSILON = _env_float("FINAL_TIE_EPSILON", 1e-6)
# Enable final stage local HTTP evaluation
ENABLE_FINAL_LOCAL = _str_to_bool(os.getenv("ENABLE_FINAL_LOCAL", "true"))

# Give the network time to propagate IPFS + on-chain commits before fetching
CONSENSUS_PROPAGATION_DELAY_SEC = _env_int("CONSENSUS_PROPAGATION_DELAY_SEC", 12)
