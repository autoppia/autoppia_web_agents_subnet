# autoppia_web_agents_subnet/validator/leaderboard/api_client.py
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import requests

try:
    import bittensor as bt
    _HAS_BT = True
except Exception:
    _HAS_BT = False


# =============================== CONFIG ======================================
LEADERBOARD_BASE_URL = "https://api-leaderboard.autoppia.com"
API_V0_ROUND_RESULTS_URL = f"{LEADERBOARD_BASE_URL}/round-results/"
API_V1_ROUND_RESULTS_URL = f"{LEADERBOARD_BASE_URL}/v1/rounds/{{round_id}}/round-results"
DEFAULT_TIMEOUT = 30


# =============================== HELPERS =====================================
def _log_info(msg: str) -> None:
    if _HAS_BT:
        bt.logging.info(msg)
    else:
        print(msg)


def _log_error(msg: str) -> None:
    if _HAS_BT:
        bt.logging.error(msg)
    else:
        print(f"ERROR: {msg}")


def _to_serializable(obj: Any) -> Any:
    """Convert objects to JSON-serializable format"""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif hasattr(obj, "model_dump"):
        return obj.model_dump()
    elif hasattr(obj, "__dict__"):
        return {k: _to_serializable(v) for k, v in obj.__dict__.items()}
    elif isinstance(obj, (list, tuple)):
        return [_to_serializable(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: _to_serializable(value) for key, value in obj.items()}
    return obj


# =============================== DATACLASSES =================================
@dataclass
class TaskInfo:
    task_id: str
    prompt: str
    website: str
    web_project: str
    use_case: str


@dataclass
class TaskResult:
    task_id: str
    eval_score: float
    execution_time: float
    time_score: float
    reward: float
    solution: Dict[str, Any]
    test_results: Dict[str, Any]
    evaluation_result: Dict[str, Any]


@dataclass
class AgentEvaluationRun:
    miner_uid: int
    miner_hotkey: str
    miner_coldkey: str
    reward: float
    eval_score: float
    time_score: float
    execution_time: float
    task_results: List[TaskResult]


@dataclass
class WeightsSnapshot:
    full_uids: List[int]
    rewards_full_avg: List[float]
    rewards_full_wta: List[float]
    winner_uid: Optional[int] = None


@dataclass
class RoundResults:
    validator_uid: int
    round_id: str
    version: str
    started_at: float
    ended_at: float
    elapsed_sec: float
    n_active_miners: int
    n_total_miners: int
    tasks: List[TaskInfo]
    agent_runs: List[AgentEvaluationRun]
    weights: WeightsSnapshot
    meta: Dict[str, Any] = field(default_factory=dict)


# =============================== CLIENT ======================================
class LeaderboardAPI:
    """
    HTTP client for the Autoppia Leaderboard API.
    Handles all communication with the leaderboard endpoints.
    """

    def __init__(self, base_url: str = LEADERBOARD_BASE_URL, timeout: int = DEFAULT_TIMEOUT, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key

    def _headers(self, idempotency_key: Optional[str] = None) -> Dict[str, str]:
        """Get HTTP headers for API requests"""
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        if idempotency_key:
            h["Idempotency-Key"] = idempotency_key
        return h

    def _post(self, url: str, json_payload: Any, idempotency_key: Optional[str] = None) -> Optional[requests.Response]:
        """Send POST request to API"""
        payload = _to_serializable(json_payload)
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout, headers=self._headers(idempotency_key))
            resp.raise_for_status()
            return resp
        except Exception as e:
            _log_error(f"POST {url} failed: {e}")
            return None

    async def _post_async(self, url: str, json_payload: Any, idempotency_key: Optional[str] = None) -> None:
        """Send POST request asynchronously"""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._post, url, json_payload, idempotency_key)

    def _post_bg(self, url: str, json_payload: Any, idempotency_key: Optional[str] = None) -> None:
        """Send POST request in background"""
        asyncio.create_task(self._post_async(url, json_payload, idempotency_key))

    # ------------------------------- API Methods -------------------------------------
    def post_round_results(self, rr: RoundResults, background: bool = True) -> None:
        """Posts round results to the legacy v0 API endpoint"""
        url = API_V0_ROUND_RESULTS_URL
        (self._post_bg if background else self._post)(url, rr)
        _log_info(f"Posted round results to leaderboard: {rr.round_id}")

    def post_round_results_v1(self, round_id: str, rr: RoundResults, background: bool = True) -> None:
        """Posts round results to the v1 API endpoint"""
        url = API_V1_ROUND_RESULTS_URL.format(round_id=round_id)
        (self._post_bg if background else self._post)(url, rr)
        _log_info(f"Posted round results to leaderboard v1: {round_id}")
