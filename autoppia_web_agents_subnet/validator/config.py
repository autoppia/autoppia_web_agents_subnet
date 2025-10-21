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


# ╭─────────────────────────── Round System Configuration QUICK TEST─────────────────────────────╮

# Round-based system: Long-duration rounds with pre-generated tasks and dynamic execution
# All validators synchronize: start at epoch multiples of ROUND_SIZE_EPOCHS
# and set weights when reaching the target epoch...

ROUND_SIZE_EPOCHS = 0.1               # Round duration in epochs (~14.4 min para testing adecuado)
# 1 epoch = 360 blocks ≈ 72 minutes
# 0.2 epochs = 72 blocks ≈ 14.4 minutes

SAFETY_BUFFER_EPOCHS = 0.02          # Safety buffer in epochs before target epoch
# If less than 0.02 epochs remaining, stop sending tasks
# 0.02 epochs ≈ 1.4 minutes (sufficient for last task)

AVG_TASK_DURATION_SECONDS = 300     # ⚠️ CALIBRATE THIS VALUE based on real measurements
# Average time for: send + evaluate 1 task (excluding generation)
# Testing value: 300s (5 minutes)
# Measure in production and update
# This value is used to estimate if there's time for another task

PRE_GENERATED_TASKS = 1           # Number of tasks to pre-generate at round start
# Generate all at the beginning to avoid on-the-fly errors
# Testing: only 1 task

# Minimum chain block required before the validator begins orchestrating rounds.
# This gate keeps all validators aligned for the production launch window.
# Only used when TESTING=false
# 
# DZ_STARTING_BLOCK debe estar alineado con el inicio de una época para sincronización perfecta
# Época 18,639 = bloque 6,710,040 (inicio de época alineado)
TESTING = _str_to_bool(os.getenv("TESTING", "false"))
DZ_STARTING_BLOCK = int(os.getenv("DZ_STARTING_BLOCK", "6710040")) if not TESTING else 0


# ╭─────────────────────────── Round System Configuration ─────────────────────────────╮

# # Round-based system: Long-duration rounds with pre-generated tasks and dynamic execution
# # All validators synchronize: start at epoch multiples of ROUND_SIZE_EPOCHS
# # and set weights when reaching the target epoch

# ROUND_SIZE_EPOCHS = 20              # Round duration in epochs (~24h = 20 epochs)
# # 1 epoch = 360 blocks ≈ 72 minutes
# # 20 epochs = 7200 blocks ≈ 24 hours

# SAFETY_BUFFER_EPOCHS = 0.5          # Safety buffer in epochs before target epoch
# # If less than 0.5 epochs remaining, stop sending tasks
# # 0.5 epochs ≈ 36 minutes (sufficient for last task)

# AVG_TASK_DURATION_SECONDS = 600     # ⚠️ CALIBRATE THIS VALUE based on real measurements
# # Average time for: send + evaluate 1 task (excluding generation)
# # Default value: 600s (10 minutes)
# # Measure in production and update
# # This value is used to estimate if there's time for another task

# PRE_GENERATED_TASKS = 120           # Number of tasks to pre-generate at round start
# # Generate all at the beginning to avoid on-the-fly errors
# # Adjust based on estimation: (available_time / avg_duration) + margin

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
