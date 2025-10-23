import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env filee
load_dotenv()


def _str_to_bool(value: str) -> bool:
    """
    Minimal replacement for distutils.util.strtobool that keeps behaviour consistent
    while remaining compatible with Python 3.12+ where distutils is deprecated.
    """
    normalized = value.strip().lower()
    if normalized in {"y", "yes", "t", "true", "on", "1"}:
        return True
    if normalized in {"n", "no", "f", "false", "off", "0"}:
        return False
    raise ValueError(f"Invalid truth value {value!r}")


def _normalized(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _env_int(name: str, default: int) -> int:
    """
    Retrieve an integer environment variable, falling back to default for invalid values.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw.strip())
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


# ════════════════════════════════════════════════════════════════════════════════
# 🎯 PRODUCTION CONFIGURATION - Round System (24 HOURS)
# ════════════════════════════════════════════════════════════════════════════════
# Launch: Epoch 18,640 (Block 6,710,400) - ~21:00 Oct 21, 2025
# Round duration: 24 hours = 20 epochs = 7,200 blocks
# All validators synchronize at epoch multiples of 20 (GLOBAL SYNC)
# ════════════════════════════════════════════════════════════════════════════════

# ROUND_SIZE_EPOCHS = 6                # ~7.2 hours per round
# 1 epoch = 360 blocks = 72 minutes = 1.2 hours
# 6 epochs = 2,160 blocks = 25,920 seconds ≈ 432 minutes ≈ 7.2 hours
# Round boundaries still align to global multiples of ROUND_SIZE_EPOCHS
# ⚠️ If validator starts late, it still ends at the same target epoch as others!

# SAFETY_BUFFER_EPOCHS = 0.5           # 0.5 epoch = 36 minutes buffer before round ends
# Stop sending tasks when less than 0.5 epochs remains
# Ensures last task completes + weights are set before round deadline

# AVG_TASK_DURATION_SECONDS = 300      # 5 minutes average per task
# Includes: send task + miner execution + evaluation + API submission
# 300 tasks × 5 min = 1,500 min = 25 hours
# Distributed over ~23.4 hours (24h - 36min buffer) = ~13 tasks/hour
#
# PRE_GENERATED_TASKS = 75             # Generate fewer tasks (≈ 1/4)
# All tasks generated upfront; dynamic loop truncates based on time
# With 6-epoch rounds and ~5 min/task, ~75 tasks fits comfortably

# ════════════════════════════════════════════════════════════════════════════════
# 🚀 LAUNCH BLOCK (Epoch-Aligned) - FIXED VALUE
# ════════════════════════════════════════════════════════════════════════════════
# ⚠️  WARNING: This value MUST be identical across ALL validators
# ⚠️  DO NOT CHANGE without coordinating with all validator operators
# ════════════════════════════════════════════════════════════════════════════════
# Epoch-aligned start gate: choose a block strictly greater than 6,712,258 and a multiple of 300
# Selected: Block 6,712,500 (multiple of 300, +242 blocks over 6,712,258)
# 
# 🌐 GLOBAL SYNCHRONIZATION (using modulo):
# Round boundaries are calculated as: (current_epoch // 20) × 20
# This creates ABSOLUTE synchronization points every 20 epochs
# 
# Example (ROUND_SIZE_EPOCHS = 20):
#   Epoch 18,640-18,659 → Round 1 (ALL validators, regardless of start time)
#   Epoch 18,660-18,679 → Round 2 (ALL validators)
#   
#   - Validator A starts at epoch 18,640.0 → ends at 18,660 (24h duration)
#   - Validator B starts at epoch 18,645.0 (5h late) → STILL ends at 18,660 (19h duration)
#   - Validator C crashes and restarts at epoch 18,655.0 → STILL ends at 18,660 (5h duration)
#
# All validators set weights at epoch 18,660 simultaneously (FAIR & SYNCHRONIZED)
# ════════════════════════════════════════════════════════════════════════════════

TESTING = _str_to_bool(os.getenv("TESTING", "false"))

# ════════════════════════════════════════════════════════════════════════════════
# 🎯 Round System Configuration (Production defaults + Testing overrides)
# ════════════════════════════════════════════════════════════════════════════════
# 1 epoch = 360 blocks = 72 minutes

# ── Production defaults (24h rounds) ─
ROUND_SIZE_EPOCHS_PROD = 20.0             # 24 hours per round (20 epochs)
SAFETY_BUFFER_EPOCHS_PROD = 0.5           # 36 minutes buffer
AVG_TASK_DURATION_SECONDS_PROD = 300      # 5 minutes average per task
PRE_GENERATED_TASKS_PROD = 75             # Generate tasks upfront; loop truncates by time
# Epoch-aligned start gate: strictly > 6,712,258 and multiple of 300
DZ_STARTING_BLOCK_PROD = 6_716_460

# ── Testing defaults (quick dev cycles) ─
ROUND_SIZE_EPOCHS_TEST = 0.2               # 0.2 epochs per round in testing (~14.4 min)
SAFETY_BUFFER_EPOCHS_TEST = 0.02           # ~1.44 minutes buffer (kept minimal for tests)
AVG_TASK_DURATION_SECONDS_TEST = 300
PRE_GENERATED_TASKS_TEST = 5               # Only a few tasks for quick iteration
DZ_STARTING_BLOCK_TEST = 6_717_750         # Fixed testing gate as requested

# ── Final values selected by TESTING flag ─
ROUND_SIZE_EPOCHS = ROUND_SIZE_EPOCHS_TEST if TESTING else ROUND_SIZE_EPOCHS_PROD
SAFETY_BUFFER_EPOCHS = SAFETY_BUFFER_EPOCHS_TEST if TESTING else SAFETY_BUFFER_EPOCHS_PROD
AVG_TASK_DURATION_SECONDS = (
    AVG_TASK_DURATION_SECONDS_TEST if TESTING else AVG_TASK_DURATION_SECONDS_PROD
)
PRE_GENERATED_TASKS = PRE_GENERATED_TASKS_TEST if TESTING else PRE_GENERATED_TASKS_PROD
DZ_STARTING_BLOCK = DZ_STARTING_BLOCK_TEST if TESTING else DZ_STARTING_BLOCK_PROD

# ╭─────────────────────────── Task Settings ─────────────────────────────╮

PROMPTS_PER_USECASE = 1             # Number of prompts to generate per use case
MAX_ACTIONS_LENGTH = 60             # Maximum number of actions per solution

TIMEOUT = 60 * 2                    # 2 min: timeout for receiving miner responses
FEEDBACK_TIMEOUT = 60               # 1 min: timeout for sending feedback to miners

# Dynamic HTML - Enable seed assignment to task URLs for HTML variation
ENABLE_DYNAMIC_HTML = _str_to_bool(os.getenv("ENABLE_DYNAMIC_HTML", "true"))

# GIF Recording - Enable recording of browser execution as animated GIF for leaderboard
SHOULD_RECORD_GIF = _str_to_bool(os.getenv("SHOULD_RECORD_GIF", "true"))

# ╭─────────────────────────── Rewards ─────────────────────────────╮

EVAL_SCORE_WEIGHT = 1.0             # Weight of evaluation score (0-1) - Only quality matters
TIME_WEIGHT = 0.0                   # Weight of execution time (0-1) - Time doesn't affect score


# ╭─────────────────────────── Leaderboard ─────────────────────────────╮

VALIDATOR_NAME = _normalized(os.getenv("VALIDATOR_NAME"))
VALIDATOR_IMAGE = _normalized(os.getenv("VALIDATOR_IMAGE"))
MAX_AGENT_NAME_LENGTH = _env_int("MAX_AGENT_NAME_LENGTH", 12)

LEADERBOARD_ENDPOINT = os.getenv("LEADERBOARD_ENDPOINT", "https://leaderboard-api.autoppia.com")
IWAP_API_BASE_URL = os.getenv("IWAP_API_BASE_URL", "https://api-leaderboard.autoppia.com")
VALIDATOR_AUTH_MESSAGE = _normalized(os.getenv("VALIDATOR_AUTH_MESSAGE", "I am a honest validator"))
LEADERBOARD_TASKS_ENDPOINT = "https://api-leaderboard.autoppia.com/tasks"
LEADERBOARD_VALIDATOR_RUNS_ENDPOINT = "https://api-leaderboard.autoppia.com/validator-runs"

SAVE_SUCCESSFUL_TASK_IN_JSON = _str_to_bool(os.getenv("SAVE_SUCCESSFUL_TASK_IN_JSON", "false"))

# ╭─────────────────────────── Stats ─────────────────────────────╮
STATS_FILE = Path("coldkey_web_usecase_stats.json")  # snapshot

# ╭─────────────────────────── Consensus Sharing ─────────────────────────────╮
# Share mid-round scoring snapshots (IPFS + on-chain commitment), then aggregate
# across validators by stake to choose a single winner.

SHARE_SCORING = _str_to_bool(os.getenv("SHARE_SCORING", "false"))

# Fraction of the round when we stop sending tasks to reserve time for
# commitments and settlement (start of the reserved window). Example: 0.75 = stop at 75%.
STOP_TASKS_AT_FRACTION = float(os.getenv("STOP_TASKS_AT_FRACTION", os.getenv("SHARE_STOP_EVAL_AT_FRACTION", "0.75")))

# Fraction (0–1) of the settlement period after which we perform a mid-fetch
# of commitments/IPFS to cache aggregated scores. Example: 0.5 = halfway point
# between STOP_TASKS_AT_FRACTION and the end of the round.
SETTLEMENT_FETCH_FRACTION = float(os.getenv("SETTLEMENT_FETCH_FRACTION", "0.5"))

# Backward-compatible alias (deprecated in code use):
SHARE_STOP_EVAL_AT_FRACTION = STOP_TASKS_AT_FRACTION

# Minimum validator stake (in TAO) required to publish/participate in aggregation.
# Use sensible defaults; operators can tune via env.
MIN_VALIDATOR_STAKE_TO_SHARE_SCORES = float(os.getenv("MIN_VALIDATOR_STAKE_TO_SHARE_SCORES", "10000"))
MIN_VALIDATOR_STAKE_TO_AGGREGATE = float(os.getenv("MIN_VALIDATOR_STAKE_TO_AGGREGATE", "10000"))

# Number of blocks to wait (best-effort) after publishing before we consider
# reading others' commitments. This is a soft guideline; we still aggregate
# at finalize even if we haven't waited the full amount.
CONSENSUS_SPREAD_BLOCKS = int(os.getenv("CONSENSUS_SPREAD_BLOCKS", "60"))

# IPFS configuration (API and gateways). API is required for adding JSON; reads
# will try API, then CLI, then public gateways as fallback.
IPFS_API_URL = os.getenv("IPFS_API_URL", "http://ipfs.metahash73.com:5001/api/v0")
IPFS_GATEWAYS = [
    g.strip() for g in (
        os.getenv(
            "IPFS_GATEWAYS",
            "https://ipfs.io/ipfs,https://cloudflare-ipfs.com/ipfs,https://gateway.pinata.cloud/ipfs",
        )
        or ""
    ).split(",") if g.strip()
]

# In TESTING, allow separate stop fraction via TEST_* env, falling back to prod fraction
if TESTING:
    # In testing, start the commitments window at 50% of the round by default
    STOP_TASKS_AT_FRACTION = float(os.getenv("TEST_STOP_TASKS_AT_FRACTION", "0.5"))
    SETTLEMENT_FETCH_FRACTION = float(os.getenv("TEST_SETTLEMENT_FETCH_FRACTION", str(SETTLEMENT_FETCH_FRACTION)))
    # Point IWAP/leaderboard API to the dev environment by default
    IWAP_API_BASE_URL = os.getenv("IWAP_API_BASE_URL", "https://dev-api-leaderboard.autoppia.com")
    # Allow overriding test endpoints explicitly; otherwise derive from IWAP base
    _base = IWAP_API_BASE_URL.rstrip("/")
    LEADERBOARD_TASKS_ENDPOINT = os.getenv("TEST_LEADERBOARD_TASKS_ENDPOINT", f"{_base}/tasks")
    LEADERBOARD_VALIDATOR_RUNS_ENDPOINT = os.getenv("TEST_LEADERBOARD_VALIDATOR_RUNS_ENDPOINT", f"{_base}/validator-runs")
