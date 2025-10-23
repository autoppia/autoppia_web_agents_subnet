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
    PRE_GENERATED_TASKS = _env_int("TEST_PRE_GENERATED_TASKS", 5)
    DZ_STARTING_BLOCK = _env_int("TEST_DZ_STARTING_BLOCK", 6_717_750)

    # ── Round Phase Timing (all absolute % of total round) ──────────────────
    # Stop task evaluation at 50% of round to allow time for consensus
    STOP_TASK_EVALUATION_AT_ROUND_FRACTION = 0.50
    # Fetch IPFS payloads at 75% of round (gives 25% gap for propagation)
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION = 0.75

    # ── Checkpoint System & Late Start ───────────────────────────────────────
    # Enable checkpoint system (save/load round state for crash recovery)
    ENABLE_CHECKPOINT_SYSTEM = True
    # Skip round only if started when >95% complete (very permissive for testing)
    SKIP_ROUND_IF_STARTED_AFTER_FRACTION = 0.95

    # ── Consensus Participation Requirements ─────────────────────────────────
    # Testing: No stake required (0 τ) - anyone can participate
    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = 0.0
    IWAP_API_BASE_URL = "https://dev-api-leaderboard.autoppia.com"

# ═══════════════════════════════════════════════════════════════════════════
# PRODUCTION CONFIGURATION (4.8-hour rounds, conservative)
# ═══════════════════════════════════════════════════════════════════════════
else:
    # ── Round Structure ──────────────────────────────────────────────────────
    # Production rounds (~4.8 hours) - Changed from 20 epochs to 4 for faster iterations
    ROUND_SIZE_EPOCHS = _env_float("ROUND_SIZE_EPOCHS", 4.0)
    SAFETY_BUFFER_EPOCHS = _env_float("SAFETY_BUFFER_EPOCHS", 0.5)
    AVG_TASK_DURATION_SECONDS = _env_int("AVG_TASK_DURATION_SECONDS", 300)
    PRE_GENERATED_TASKS = _env_int("PRE_GENERATED_TASKS", 75)
    DZ_STARTING_BLOCK = _env_int("DZ_STARTING_BLOCK", 6_720_366)

    # ── Round Phase Timing (all absolute % of total round) ──────────────────
    # Stop task evaluation at 75% of round to reserve time for consensus
    STOP_TASK_EVALUATION_AT_ROUND_FRACTION = 0.75
    # Fetch IPFS payloads at 87.5% of round (gives 12.5% gap for propagation)
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION = 0.875

    # ── Checkpoint System & Late Start ───────────────────────────────────────
    # Enable checkpoint system (save/load round state for crash recovery)
    ENABLE_CHECKPOINT_SYSTEM = True
    # Skip round if started when >30% complete (conservative for production)
    SKIP_ROUND_IF_STARTED_AFTER_FRACTION = 0.30

    # ── Consensus Participation Requirements ─────────────────────────────────
    # Production: Minimum 10k τ stake required to be included in consensus calculations
    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = 10000.0
    IWAP_API_BASE_URL = "https://api-leaderboard.autoppia.com"
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

# ── Validator Identity (IWAP) ────────────────────────────────────────────────
VALIDATOR_NAME = _normalized(os.getenv("VALIDATOR_NAME"))
VALIDATOR_IMAGE = _normalized(os.getenv("VALIDATOR_IMAGE"))
MAX_MINER_AGENT_NAME_LENGTH = _env_int("MAX_MINER_AGENT_NAME_LENGTH", 12)

# ── IWAP Leaderboard API ─────────────────────────────────────────────────────

IWAP_VALIDATOR_AUTH_MESSAGE = _normalized(os.getenv("IWAP_VALIDATOR_AUTH_MESSAGE", "I am a honest validator"))

# ── Burn Mechanism ───────────────────────────────────────────────────────────
BURN_UID = _env_int("BURN_UID", 5)

# ── Distributed Consensus (IPFS + Blockchain) ────────────────────────────────
ENABLE_DISTRIBUTED_CONSENSUS = _str_to_bool(os.getenv("ENABLE_DISTRIBUTED_CONSENSUS", "true"))

# ── IPFS Storage ─────────────────────────────────────────────────────────────
IPFS_API_URL = os.getenv("IPFS_API_URL", "http://ipfs.metahash73.com:5001/api/v0")
IPFS_GATEWAYS = [
    g.strip() for g in 
    (os.getenv("IPFS_GATEWAYS", "https://ipfs.io/ipfs,https://cloudflare-ipfs.com/ipfs,https://gateway.pinata.cloud/ipfs") or "")
    .split(",") if g.strip()
]
