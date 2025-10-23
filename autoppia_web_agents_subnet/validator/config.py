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


def _env_float(name: str, default: float, *, alias: Optional[str] = None,
               test_default: Optional[float] = None) -> float:
    """
    Retrieve a float environment variable with optional:
    - alias: fallback env var name (for backward compatibility)
    - test_default: default used when TESTING is true and TEST_* variable is not set

    Resolution order:
      1) If TESTING and TEST_<name> is set → parse and return
      2) If <name> is set → parse and return
      3) If alias is set and alias is set → parse and return
      4) If TESTING and test_default is provided → return test_default
      5) Otherwise → return default
    """
    # 1) Explicit testing override
    if TESTING:
        tval = os.getenv(f"TEST_{name}")
        if tval is not None:
            try:
                return float(tval.strip())
            except (TypeError, ValueError):
                pass

    # 2) Primary name
    raw = os.getenv(name)
    if raw is not None:
        try:
            return float(raw.strip())
        except (TypeError, ValueError):
            pass

    # 3) Backward-compatible alias
    if alias is not None:
        ar = os.getenv(alias)
        if ar is not None:
            try:
                return float(ar.strip())
            except (TypeError, ValueError):
                pass

    # 4) Testing default
    if TESTING and test_default is not None:
        return float(test_default)

    # 5) Production/default
    return float(default)


# Round synchronization notes: validators align on 20-epoch boundaries; late starts
# still end at the same target boundary. See ROUND_SIZE_EPOCHS_* and DZ_STARTING_BLOCK_*
# below for prod/test defaults.

TESTING = _str_to_bool(os.getenv("TESTING", "false"))

# Enable/disable local state recovery (resume of validator rounds)
# Default: disabled in TESTING for clean local cycles, enabled in prod.
ENABLE_STATE_RECOVERY = _str_to_bool(
    os.getenv("ENABLE_STATE_RECOVERY", "false" if TESTING else "true")
)

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
# In testing, default IWAP to the dev environment; allow explicit override via env
IWAP_API_BASE_URL = os.getenv(
    "IWAP_API_BASE_URL",
    "https://dev-api-leaderboard.autoppia.com" if TESTING else "https://api-leaderboard.autoppia.com",
)
VALIDATOR_AUTH_MESSAGE = _normalized(os.getenv("VALIDATOR_AUTH_MESSAGE", "I am a honest validator"))
_base = (IWAP_API_BASE_URL or "").rstrip("/")
# Derive endpoints from IWAP base, but allow override; in testing prefer TEST_* names
LEADERBOARD_TASKS_ENDPOINT = os.getenv(
    "TEST_LEADERBOARD_TASKS_ENDPOINT" if TESTING else "LEADERBOARD_TASKS_ENDPOINT",
    f"{_base}/tasks",
)
LEADERBOARD_VALIDATOR_RUNS_ENDPOINT = os.getenv(
    "TEST_LEADERBOARD_VALIDATOR_RUNS_ENDPOINT" if TESTING else "LEADERBOARD_VALIDATOR_RUNS_ENDPOINT",
    f"{_base}/validator-runs",
)

SAVE_SUCCESSFUL_TASK_IN_JSON = _str_to_bool(os.getenv("SAVE_SUCCESSFUL_TASK_IN_JSON", "false"))

# ╭─────────────────────────── Burn Settings ─────────────────────────────╮
# UID that receives full weight when burning (no valid winners)
BURN_UID = _env_int("BURN_UID", 5)

# ╭─────────────────────────── Stats ─────────────────────────────╮
STATS_FILE = Path("coldkey_web_usecase_stats.json")  # snapshot

# ╭─────────────────────────── Consensus Sharing ─────────────────────────────╮
# Share mid-round scoring snapshots (IPFS + on-chain commitment), then aggregate
# across validators by stake to choose a single winner.
#
# Defaults:
# - Testing (TESTING=true): default ON
# - Production (TESTING=false): default ON (opt-out via SHARE_SCORING=false)
_DEFAULT_SHARE_SCORING = "true"
SHARE_SCORING = _str_to_bool(os.getenv("SHARE_SCORING", _DEFAULT_SHARE_SCORING))

# Fraction of the round when we stop sending tasks to reserve time for
# commitments and settlement (start of the reserved window).
# Example defaults: prod=0.75, test=0.50
STOP_TASKS_AT_FRACTION = _env_float(
    "STOP_TASKS_AT_FRACTION",
    0.75,
    alias="SHARE_STOP_EVAL_AT_FRACTION",
    test_default=0.50,
)

# Fraction of the round at which to commit consensus snapshot (publish to IPFS + on-chain).
# Should happen before STOP_TASKS_AT_FRACTION to ensure snapshot is available for aggregation.
# Example: 0.66 = commit at 66% of round duration.
CONSENSUS_COMMIT_AT_FRACTION = _env_float("CONSENSUS_COMMIT_AT_FRACTION", 0.66)

# Fraction (0–1) of the settlement period after which we perform a mid-fetch
# of commitments/IPFS to cache aggregated scores. Example: 0.5 = halfway point
# between STOP_TASKS_AT_FRACTION and the end of the round.
SETTLEMENT_FETCH_FRACTION = _env_float("SETTLEMENT_FETCH_FRACTION", 0.5)

# Backward-compatible alias (deprecated in code use):
SHARE_STOP_EVAL_AT_FRACTION = STOP_TASKS_AT_FRACTION

# Minimum validator stake (in TAO) required to publish/participate in aggregation.
# Use sensible defaults; operators can tune via env.
MIN_VALIDATOR_STAKE_TO_SHARE_SCORES = float(
    os.getenv("MIN_VALIDATOR_STAKE_TO_SHARE_SCORES", "0" if TESTING else "10000")
)
MIN_VALIDATOR_STAKE_TO_AGGREGATE = float(
    os.getenv("MIN_VALIDATOR_STAKE_TO_AGGREGATE", "0" if TESTING else "10000")
)

# Number of blocks to wait (best-effort) after publishing before we consider
# reading others' commitments. This is a soft guideline; we still aggregate
# at finalize even if we haven't waited the full amount.
CONSENSUS_SPREAD_BLOCKS = _env_int("CONSENSUS_SPREAD_BLOCKS", 60)

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

# Testing overrides are handled inline via _env_float and default IWAP base above.

# ╭─────────────────────────── Late Start Skip ─────────────────────────────╮
# If a validator starts FRESH (no resume state) and the current round has
# progressed beyond this fraction (0.0–1.0), skip starting and wait for the
# next round boundary. Default: 0.30 (30%).
SKIP_ROUND_IF_LATE_FRACTION = _env_float("SKIP_ROUND_IF_LATE_FRACTION", 0.30)
