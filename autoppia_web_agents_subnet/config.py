import os
from distutils.util import strtobool
from pathlib import Path


# ╭─────────────────────────── Environment ─────────────────────────────╮

EPOCH_LENGTH_OVERRIDE = 0 
TESTING = False
ROUND_EPOCHS_DURATION = 20  # 1 day

# ╭─────────────────────────── Rounds ─────────────────────────────╮

ROUND_SIZE_EPOCHS = 20   # How much epcohs a round takes
CLOSEOUT_EPOCHS = 2  # How close we shopuld be to end epoch to stop sending tasks
PROMPTS_PER_USECASE = 1
NUMBER_OF_PROMPTS_PER_FORWARD = 24
MAX_ACTIONS_LENGTH = 30

# ╭─────────────────────────── Rewards ─────────────────────────────╮
EVAL_SCORE_WEIGHT = 0.85
TIME_WEIGHT = 0.15

# ╭─────────────────────────── Task Settings ─────────────────────────────╮

TIMEOUT = 60 * 2
FEEDBACK_TIMEOUT = 60
FORWARD_SLEEP_SECONDS = 60 * 1


# ╭─────────────────────────── Leaderboard ─────────────────────────────╮

LEADERBOARD_ENDPOINT = os.getenv("LEADERBOARD_ENDPOINT", "https://leaderboard-api.autoppia.com")
LEADERBOARD_TASKS_ENDPOINT = "https://api-leaderboard.autoppia.com/tasks"
LEADERBOARD_VALIDATOR_RUNS_ENDPOINT = "https://api-leaderboard.autoppia.com/validator-runs"

SAVE_SUCCESSFUL_TASK_IN_JSON = bool(strtobool(os.getenv("SAVE_SUCCESSFUL_TASK_IN_JSON", "false")))

# ╭─────────────────────────── Stats ─────────────────────────────╮
STATS_FILE = Path("coldkey_web_usecase_stats.json")  # snapshot
