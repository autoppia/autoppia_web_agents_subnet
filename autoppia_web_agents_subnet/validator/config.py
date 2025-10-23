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
    ROUND_SIZE_EPOCHS = 0.2                    # 14.4 min = 72 blocks
    SAFETY_BUFFER_EPOCHS = 0.02                # 1.44 min = 7 blocks
    PRE_GENERATED_TASKS = 5                    # Fewer tasks for speed
    DZ_STARTING_BLOCK = 6_717_750              # Test mode starting block

    # ── Task Execution Phase Timing ──────────────────────────────────────────
    # Stop task evaluation at 50% of round (absolute) to allow 50% for consensus
    STOP_TASK_EVALUATION_AT_ROUND_FRACTION = 0.50

    # ── Consensus Settlement Phase Timing ────────────────────────────────────
    # After stopping tasks at 50%, fetch IPFS payloads at 50% of settlement window
    # Effective time: 50% + (50% × 0.5) = 75% of total round
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_SETTLEMENT_FRACTION = 0.50

    # ── Late Start & Crash Recovery ──────────────────────────────────────────
    # Resume from checkpoint if validator crashes/restarts mid-round
    RESUME_ROUND_AFTER_CRASH = _str_to_bool(os.getenv("RESUME_ROUND_AFTER_CRASH", "true"))
    # Skip round only if started when >95% complete (very permissive for testing)
    SKIP_ROUND_IF_STARTED_AFTER_FRACTION = 0.95

    # ── Consensus Participation Requirements ─────────────────────────────────
    # Testing: No stake required (0 τ) - anyone can participate
    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = 0.0

# ═══════════════════════════════════════════════════════════════════════════
# PRODUCTION CONFIGURATION (24-hour rounds, conservative)
# ═══════════════════════════════════════════════════════════════════════════
else:
    # ── Round Structure ──────────────────────────────────────────────────────
    # Standard production rounds (~24 hours per round)
    ROUND_SIZE_EPOCHS = 20.0                   # 24h = 7200 blocks
    SAFETY_BUFFER_EPOCHS = 0.5                 # 36 min = 180 blocks
    PRE_GENERATED_TASKS = 75                   # More tasks for thorough evaluation
    DZ_STARTING_BLOCK = 6_720_066              # Production mode starting block

    # ── Task Execution Phase Timing ──────────────────────────────────────────
    # Stop task evaluation at 75% of round (absolute) to reserve 25% for consensus
    STOP_TASK_EVALUATION_AT_ROUND_FRACTION = 0.75

    # ── Consensus Settlement Phase Timing ────────────────────────────────────
    # After stopping tasks at 75%, fetch IPFS payloads at 50% of settlement window
    # Effective time: 75% + (25% × 0.5) = 87.5% of total round
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_SETTLEMENT_FRACTION = 0.50

    # ── Late Start & Crash Recovery ──────────────────────────────────────────
    # Resume from checkpoint if validator crashes/restarts mid-round
    RESUME_ROUND_AFTER_CRASH = _str_to_bool(os.getenv("RESUME_ROUND_AFTER_CRASH", "true"))
    # Skip round if started when >30% complete (conservative for production)
    SKIP_ROUND_IF_STARTED_AFTER_FRACTION = 0.30

    # ── Consensus Participation Requirements ─────────────────────────────────
    # Production: Minimum 10k τ stake required to be included in consensus calculations
    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO = 10000.0

# ═══════════════════════════════════════════════════════════════════════════
# SHARED CONFIGURATION (same for all modes)
# ═══════════════════════════════════════════════════════════════════════════

# ── Task Execution Settings ──────────────────────────────────────────────────
PROMPTS_PER_USECASE = 1
MAX_ACTIONS_LENGTH = 60
TIMEOUT = 120
FEEDBACK_TIMEOUT = 60
AVG_TASK_DURATION_SECONDS = 300  # Used for round time calculations

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
IWAP_API_BASE_URL = os.getenv(
    "IWAP_API_BASE_URL",
    "https://dev-api-leaderboard.autoppia.com" if TESTING else "https://api-leaderboard.autoppia.com"
)
IWAP_VALIDATOR_AUTH_MESSAGE = _normalized(os.getenv("IWAP_VALIDATOR_AUTH_MESSAGE", "I am a honest validator"))

# ── Burn Mechanism ───────────────────────────────────────────────────────────
BURN_UID = _env_int("BURN_UID", 5)
STATS_FILE = Path("coldkey_web_usecase_stats.json")

# ── Distributed Consensus (IPFS + Blockchain) ────────────────────────────────
ENABLE_DISTRIBUTED_CONSENSUS = _str_to_bool(os.getenv("ENABLE_DISTRIBUTED_CONSENSUS", "true"))
# Wait N blocks after committing to IPFS before fetching (ensures blockchain propagation)
IPFS_COMMIT_PROPAGATION_WAIT_BLOCKS = _env_int("IPFS_COMMIT_PROPAGATION_WAIT_BLOCKS", 10)

# ── IPFS Storage ─────────────────────────────────────────────────────────────
IPFS_API_URL = os.getenv("IPFS_API_URL", "http://ipfs.metahash73.com:5001/api/v0")
IPFS_GATEWAYS = [
    g.strip() for g in 
    (os.getenv("IPFS_GATEWAYS", "https://ipfs.io/ipfs,https://cloudflare-ipfs.com/ipfs,https://gateway.pinata.cloud/ipfs") or "")
    .split(",") if g.strip()
]
