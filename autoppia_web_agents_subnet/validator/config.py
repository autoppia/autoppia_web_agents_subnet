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
# 🎯 PRODUCTION CONFIGURATION - Round System (21 HOURS)
# ════════════════════════════════════════════════════════════════════════════════
# Launch: Epoch 18,639 (Block 6,710,040) - ~21:04 Oct 21, 2025
# Round duration: 21 hours = 17.5 epochs = 6,300 blocks
# All validators synchronize at epoch multiples of 17.5
# ════════════════════════════════════════════════════════════════════════════════

ROUND_SIZE_EPOCHS = 17.5             # 21 hours per round
# 1 epoch = 360 blocks = 72 minutes = 1.2 hours
# 17.5 epochs = 6,300 blocks = 75,600 seconds = 1,260 minutes = 21 hours
# Round 1: epochs 18,639.0 - 18,656.5 (21 hours)
# Round 2: epochs 18,656.5 - 18,674.0 (next 21 hours)

SAFETY_BUFFER_EPOCHS = 0.5           # 0.5 epoch = 36 minutes buffer before round ends
# Stop sending tasks when less than 0.5 epochs remains
# Ensures last task completes + weights are set before round deadline

AVG_TASK_DURATION_SECONDS = 300      # 5 minutes average per task
# Includes: send task + miner execution + evaluation + API submission
# 250 tasks × 5 min = 1,250 min = 20.83 hours
# Fits perfectly in 21 hours with 36-min buffer

PRE_GENERATED_TASKS = 250            # Generate 250 tasks at round start
# All tasks generated upfront to avoid runtime errors
# Distribution: ~12 tasks/hour over 21 hours
# Tasks sent dynamically based on time remaining

# ════════════════════════════════════════════════════════════════════════════════
# 🚀 LAUNCH BLOCK (Epoch-Aligned)
# ════════════════════════════════════════════════════════════════════════════════
# Epoch 18,639 = Block 6,710,040 (perfectly aligned with epoch start)
# Estimated launch: ~21:04 PM, October 21, 2025
# All validators MUST use this exact block for synchronization
# ════════════════════════════════════════════════════════════════════════════════

TESTING = _str_to_bool(os.getenv("TESTING", "false"))
DZ_STARTING_BLOCK = int(os.getenv("DZ_STARTING_BLOCK", "6710040")) if not TESTING else 0


# ╭────────────────────── TESTING Configuration (Commented) ──────────────────────╮
# Uncomment for quick testing (rounds every ~14 minutes):
#
# ROUND_SIZE_EPOCHS = 0.1               # 14.4 minutes per round
# SAFETY_BUFFER_EPOCHS = 0.02           # 1.4 minutes buffer
# AVG_TASK_DURATION_SECONDS = 300       # 5 minutes per task
# PRE_GENERATED_TASKS = 1               # Only 1 task
# DZ_STARTING_BLOCK = 0                 # Start immediately
# ╰───────────────────────────────────────────────────────────────────────────────╯

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
