import os
from distutils.util import strtobool
from pathlib import Path


# ╭─────────────────────────── Task Settings ─────────────────────────────╮

TIMEOUT = 60 * 2
CHECK_VERSION_SYNAPSE = 30
CHECK_VERSION_PROBABILITY = 0.25
FEEDBACK_TIMEOUT = 60
FORWARD_SLEEP_SECONDS = 60 * 1
TASK_SLEEP = 60 * 1

# ╭─────────────────────────── Scoring Weights ─────────────────────────────╮

TIME_WEIGHT = 0.15
EFFICIENCY_WEIGHT = 0.10
MIN_SCORE_FOR_CORRECT_FORMAT = 0.0
MIN_RESPONSE_REWARD = 0
APPLY_WEIGHTS_VERSION_CHECK_PENALTY = False
# ╭─────────────────────────── Sampling & Limits ─────────────────────────────╮

SAMPLE_SIZE = 256
MAX_ACTIONS_LENGTH = 15
NUM_URLS = 1
PROMPTS_PER_USECASE = 1
NUMBER_OF_PROMPTS_PER_FORWARD = 24
SET_OPERATOR_ENDPOINT_FORWARDS_INTERVAL = 10

# ╭─────────────────────────── Leaderboard ─────────────────────────────╮

LEADERBOARD_ENDPOINT = os.getenv("LEADERBOARD_ENDPOINT", "https://leaderboard-api.autoppia.com")
LEADERBOARD_TASKS_ENDPOINT = "https://api-leaderboard.autoppia.com/tasks"
LEADERBOARD_VALIDATOR_RUNS_ENDPOINT = "https://api-leaderboard.autoppia.com/validator-runs"

SAVE_SUCCESSFUL_TASK_IN_JSON = bool(strtobool(os.getenv("SAVE_SUCCESSFUL_TASK_IN_JSON", "false")))

# ╭─────────────────────────── Stats ─────────────────────────────╮
STATS_FILE = Path("coldkey_web_usecase_stats.json")  # snapshot
