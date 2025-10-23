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

# ── Environment ───────────────────────────────────────────────────────────
TESTING = _str_to_bool(os.getenv("TESTING", "false"))
ENABLE_STATE_RECOVERY = _str_to_bool(os.getenv("ENABLE_STATE_RECOVERY", "false" if TESTING else "true"))
USE_BACKEND_ROUND_FOR_TESTING = _str_to_bool(os.getenv("USE_BACKEND_ROUND_FOR_TESTING", "false"))

# ── Round Timing (epochs/blocks) ──────────────────────────────────────────
# 1 epoch = 360 blocks (≈72 min)
ROUND_SIZE_EPOCHS_PROD = 20.0
SAFETY_BUFFER_EPOCHS_PROD = 0.5
AVG_TASK_DURATION_SECONDS_PROD = 300
PRE_GENERATED_TASKS_PROD = 75
DZ_STARTING_BLOCK_PROD = 6_720_066

ROUND_SIZE_EPOCHS_TEST = 0.2
SAFETY_BUFFER_EPOCHS_TEST = 0.02
AVG_TASK_DURATION_SECONDS_TEST = 300
PRE_GENERATED_TASKS_TEST = 5
DZ_STARTING_BLOCK_TEST = 6_717_750

ROUND_SIZE_EPOCHS = ROUND_SIZE_EPOCHS_TEST if TESTING else ROUND_SIZE_EPOCHS_PROD
SAFETY_BUFFER_EPOCHS = SAFETY_BUFFER_EPOCHS_TEST if TESTING else SAFETY_BUFFER_EPOCHS_PROD
AVG_TASK_DURATION_SECONDS = AVG_TASK_DURATION_SECONDS_TEST if TESTING else AVG_TASK_DURATION_SECONDS_PROD
PRE_GENERATED_TASKS = PRE_GENERATED_TASKS_TEST if TESTING else PRE_GENERATED_TASKS_PROD
DZ_STARTING_BLOCK = DZ_STARTING_BLOCK_TEST if TESTING else DZ_STARTING_BLOCK_PROD

# ── Task / IWA Timeouts ──────────────────────────────────────────────────
PROMPTS_PER_USECASE = 1
MAX_ACTIONS_LENGTH = 60
TIMEOUT = 120
FEEDBACK_TIMEOUT = 60

# ── HTML / Media ─────────────────────────────────────────────────────────
ENABLE_DYNAMIC_HTML = _str_to_bool(os.getenv("ENABLE_DYNAMIC_HTML", "true"))
SHOULD_RECORD_GIF = _str_to_bool(os.getenv("SHOULD_RECORD_GIF", "true"))

# ── Scoring Weights ──────────────────────────────────────────────────────
EVAL_SCORE_WEIGHT = 1.0
TIME_WEIGHT = 0.0

# ── Identity / IWAP ──────────────────────────────────────────────────────
VALIDATOR_NAME = _normalized(os.getenv("VALIDATOR_NAME"))
VALIDATOR_IMAGE = _normalized(os.getenv("VALIDATOR_IMAGE"))
MAX_AGENT_NAME_LENGTH = _env_int("MAX_AGENT_NAME_LENGTH", 12)

LEADERBOARD_ENDPOINT = os.getenv("LEADERBOARD_ENDPOINT", "https://leaderboard-api.autoppia.com")
IWAP_API_BASE_URL = os.getenv("IWAP_API_BASE_URL", "https://dev-api-leaderboard.autoppia.com" if TESTING else "https://api-leaderboard.autoppia.com")
VALIDATOR_AUTH_MESSAGE = _normalized(os.getenv("VALIDATOR_AUTH_MESSAGE", "I am a honest validator"))
_base = (IWAP_API_BASE_URL or "").rstrip("/")
LEADERBOARD_TASKS_ENDPOINT = os.getenv("TEST_LEADERBOARD_TASKS_ENDPOINT" if TESTING else "LEADERBOARD_TASKS_ENDPOINT", f"{_base}/tasks")
LEADERBOARD_VALIDATOR_RUNS_ENDPOINT = os.getenv("TEST_LEADERBOARD_VALIDATOR_RUNS_ENDPOINT" if TESTING else "LEADERBOARD_VALIDATOR_RUNS_ENDPOINT", f"{_base}/validator-runs")
SAVE_SUCCESSFUL_TASK_IN_JSON = _str_to_bool(os.getenv("SAVE_SUCCESSFUL_TASK_IN_JSON", "false"))

# ── Burn / Stats ─────────────────────────────────────────────────────────
BURN_UID = _env_int("BURN_UID", 5)
STATS_FILE = Path("coldkey_web_usecase_stats.json")

# ── Consensus / Sharing ──────────────────────────────────────────────────
_DEFAULT_SHARE_SCORING = "true"
SHARE_SCORING = _str_to_bool(os.getenv("SHARE_SCORING", _DEFAULT_SHARE_SCORING))
STOP_TASKS_AT_FRACTION = _env_float("STOP_TASKS_AT_FRACTION", 0.75, alias="SHARE_STOP_EVAL_AT_FRACTION", test_default=0.50)
CONSENSUS_COMMIT_AT_FRACTION = _env_float("CONSENSUS_COMMIT_AT_FRACTION", 0.66)
SETTLEMENT_FETCH_FRACTION = _env_float("SETTLEMENT_FETCH_FRACTION", 0.5)
SHARE_STOP_EVAL_AT_FRACTION = STOP_TASKS_AT_FRACTION  # alias for compatibility

MIN_VALIDATOR_STAKE_TO_SHARE_SCORES = float(os.getenv("MIN_VALIDATOR_STAKE_TO_SHARE_SCORES", "0" if TESTING else "10000"))
MIN_VALIDATOR_STAKE_TO_AGGREGATE = float(os.getenv("MIN_VALIDATOR_STAKE_TO_AGGREGATE", "0" if TESTING else "10000"))
CONSENSUS_SPREAD_BLOCKS = _env_int("CONSENSUS_SPREAD_BLOCKS", 10)

# ── IPFS ────────────────────────────────────────────────────────────────
IPFS_API_URL = os.getenv("IPFS_API_URL", "http://ipfs.metahash73.com:5001/api/v0")
IPFS_GATEWAYS = [g.strip() for g in (os.getenv("IPFS_GATEWAYS", "https://ipfs.io/ipfs,https://cloudflare-ipfs.com/ipfs,https://gateway.pinata.cloud/ipfs") or "").split(",") if g.strip()]

# ── Late Start Skip ──────────────────────────────────────────────────────
SKIP_ROUND_IF_LATE_FRACTION = _env_float("SKIP_ROUND_IF_LATE_FRACTION", 0.30)
