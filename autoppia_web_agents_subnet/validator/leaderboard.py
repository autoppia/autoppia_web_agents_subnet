import asyncio
from dataclasses import dataclass, asdict
from typing import Any, Dict, List

import numpy as np
import requests

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
        raw: Dict[str, Any] = asdict(self)
        cleaned: Dict[str, Any] = {}
        for k, v in raw.items():
            # Convert numpy types to native
            if isinstance(v, np.generic):
                cleaned[k] = v.item()
            else:
                cleaned[k] = v
        return cleaned


def send_many_tasks_to_leaderboard(
    records: List[LeaderboardTaskRecord],
    endpoint: str = LEADERBOARD_TASKS_ENDPOINT,
    timeout: int = 30,
) -> requests.Response:
    """
    POST multiple task records in one go to the leaderboard service.
    Hits the /tasks/bulk/ endpoint with a JSON array.
    """
    bulk_url = f"{endpoint}/bulk/"
    payload = [r.to_dict() for r in records]
    headers = {"Content-Type": "application/json"}
    resp = requests.post(bulk_url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp


async def send_many_tasks_to_leaderboard_async(
    records: List[LeaderboardTaskRecord],
    endpoint: str = LEADERBOARD_TASKS_ENDPOINT,
    timeout: int = 30,
) -> None:
    """
    Async wrapper: dispatch send_many_tasks_to_leaderboard in a thread so it
    doesn’t block your event loop.
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None, send_many_tasks_to_leaderboard, records, endpoint, timeout
    )
