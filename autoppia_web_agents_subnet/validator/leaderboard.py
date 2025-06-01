import requests
from datetime import datetime, timezone
from typing import Optional, Union

LEADERBOARD_TASKS_ENDPOINT = "https://api-leaderboard.autoppia.com/tasks"


def log_task_to_leaderboard(
    *,
    validator_uid: int,
    miner_uid: int,
    miner_hotkey: str,
    task_id: str,
    success: bool,
    score: float,
    duration: float,
    website: str,
    created_at: Optional[Union[datetime, str]] = None,
    endpoint: str = LEADERBOARD_TASKS_ENDPOINT,
    timeout: int = 5,
) -> requests.Response:
    """
    POST a new task execution record to the leaderboard service.

    Args:
        validator_uid:   The unique ID of the validator (int).
        miner_uid:       The unique ID of the miner (int).
        miner_hotkey:    The on-chain hotkey of the miner (str).
        task_id:         The unique task identifier (str).
        success:         Whether the task succeeded (bool).
        score:           The score assigned (float).
        duration:        How long the run took, in seconds (float).
        website:         Which site you ran against (e.g. "autoppia.com") (str).
        created_at:      ISO timestamp or datetime; defaults to now UTC.
        endpoint:        Full URL of the `/tasks` endpoint.
        timeout:         HTTP timeout in seconds.

    Returns:
        The `requests.Response` from the leaderboard API.
    """
    # prepare timestamp
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    if isinstance(created_at, datetime):
        # DRF view reads .timestamp(), but it also accepts ISO-8601 strings
        created_at = created_at.isoformat()

    payload = {
        "validator_uid": validator_uid,
        "miner_uid": miner_uid,
        "miner_hotkey": miner_hotkey,
        "task_id": task_id,
        "success": success,
        "score": score,
        "duration": duration,
        "website": website,
        "created_at": created_at,
    }

    resp = requests.post(endpoint, json=payload, timeout=timeout)
    # will raise an HTTPError on 4xx/5xx
    resp.raise_for_status()
    return resp
