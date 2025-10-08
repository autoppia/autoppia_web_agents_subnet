# autoppia_web_agents_subnet/validator/leaderboard.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict
from typing import Any, Dict, List

import numpy as np
import requests

LEADERBOARD_TASKS_ENDPOINT = "https://api-leaderboard.autoppia.com/tasks"


# =============================== DATA MODEL =================================
@dataclass
class LeaderboardTaskRecord:
    validator_uid: int
    miner_uid: int
    miner_coldkey: str
    miner_hotkey: str
    task_id: str
    task_prompt: str
    website: str
    web_project: str
    use_case: str
    actions: List[Dict[str, Any]]  # listado serializado de acciones
    success: bool = False
    score: float = 0.0
    duration: float = 0.0  # segundos

    def to_dict(self) -> Dict[str, Any]:
        raw: Dict[str, Any] = asdict(self)
        cleaned: Dict[str, Any] = {}
        for k, v in raw.items():
            # Convertir tipos de numpy a tipos nativos de Python
            if isinstance(v, np.generic):
                cleaned[k] = v.item()
            else:
                cleaned[k] = v
        return cleaned


# =============================== SENDER =====================================
def send_many_tasks_to_leaderboard(
    records: List[LeaderboardTaskRecord],
    endpoint: str = LEADERBOARD_TASKS_ENDPOINT,
    timeout: int = 30,
) -> requests.Response:
    """
    Publica múltiples task-records en bloque al servicio de leaderboard.
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
    Wrapper asíncrono: ejecuta el POST en un thread para no bloquear el event loop.
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        send_many_tasks_to_leaderboard,
        records,
        endpoint,
        timeout,
    )
