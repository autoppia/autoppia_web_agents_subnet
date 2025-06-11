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
    success: bool = False,
    score: float = 0.0,
    duration: float = 0.0,
    website: str,
    endpoint: str = LEADERBOARD_TASKS_ENDPOINT,
    timeout: int = 5,
) -> requests.Response:
    """
    POST a new task execution record to the leaderboard service,
    optionally incluyendo un token Bearer para autenticación.
    """

    payload = {
        "validator_uid": validator_uid,
        "miner_uid": miner_uid,
        "miner_hotkey": miner_hotkey,
        "task_id": task_id,
        "success": success,
        "score": score,
        "duration": duration,
        "website": website,
    }

    headers = {"Content-Type": "application/json"}

    resp = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp
