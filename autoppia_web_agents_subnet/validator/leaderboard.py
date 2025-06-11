from dataclasses import dataclass, asdict
from typing import Any, Dict, List
import requests
import numpy as np

LEADERBOARD_TASKS_ENDPOINT = "https://api-leaderboard.autoppia.com/tasks"


@dataclass
class LeaderboardTaskRecord:
    validator_uid: int
    miner_uid: int
    miner_hotkey: str
    task_id: str
    task_prompt: str
    website: str
    success: bool = False
    score: float = 0.0
    duration: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        raw = asdict(self)
        cleaned: Dict[str, Any] = {}
        for k, v in raw.items():
            # Convierte numpy.int64, numpy.float64, etc. a tipos nativos
            if isinstance(v, np.generic):
                cleaned[k] = v.item()
            else:
                cleaned[k] = v
        return cleaned


def send_task_to_leaderboard(
    record: LeaderboardTaskRecord,
    endpoint: str = LEADERBOARD_TASKS_ENDPOINT,
    timeout: int = 5,
) -> requests.Response:
    """
    POST a new task execution record to the leaderboard service (single).
    """
    payload = record.to_dict()
    headers = {"Content-Type": "application/json"}
    resp = requests.post(f"{endpoint}/", json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp


def send_many_tasks_to_leaderboard(
    records: List[LeaderboardTaskRecord],
    endpoint: str = LEADERBOARD_TASKS_ENDPOINT,
    timeout: int = 10,
) -> requests.Response:
    """
    POST multiple task records in one go to the leaderboard service.
    Hits the /tasks/bulk/ endpoint with {"tasks": [...]}
    """
    # endpoint siempre acaba en /tasks
    bulk_url = f"{endpoint}/bulk/"
    payload = {"tasks": [r.to_dict() for r in records]}
    headers = {"Content-Type": "application/json"}
    resp = requests.post(bulk_url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp
