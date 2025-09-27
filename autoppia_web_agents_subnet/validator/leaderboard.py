# autoppia_web_agents_subnet/validator/leaderboard.py
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import requests

try:
    import bittensor as bt
    _HAS_BT = True
except Exception:
    _HAS_BT = False


# =============================== CONFIG ======================================
LEADERBOARD_BASE_URL = "https://api-leaderboard.autoppia.com"

ENDPOINTS = {
    "events": f"{LEADERBOARD_BASE_URL}/events/",
    "round_results": f"{LEADERBOARD_BASE_URL}/round-results/",
}

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
        print(f"[ERROR] {msg}")


def _now_ts() -> float:
    return time.time()


def _np_to_native(v: Any) -> Any:
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, np.ndarray):
        return v.tolist()
    return v


def _to_serializable(payload: Any) -> Any:
    """
    Recursively convert numpy scalars/arrays and dataclass payloads to JSON-safe types.
    """
    if dataclass_isinstance(payload):
        payload = asdict(payload)

    if isinstance(payload, dict):
        return {k: _to_serializable(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_to_serializable(x) for x in payload]
    if isinstance(payload, tuple):
        return [_to_serializable(x) for x in payload]
    return _np_to_native(payload)


def dataclass_isinstance(obj: Any) -> bool:
    return hasattr(obj, "__dataclass_fields__")


# ================================ ENUMS ======================================
class Phase(str, Enum):
    INITIALIZING = "initializing"
    GENERATING_TASKS = "generating_tasks"
    SENDING_TASKS = "sending_tasks"
    EVALUATING_TASKS = "evaluating_tasks"
    CALCULATING_METRICS = "calculating_metrics"
    SENDING_FEEDBACK = "sending_feedback"
    UPDATING_WEIGHTS = "updating_weights"
    ROUND_START = "round_start"
    ROUND_END = "round_end"
    DONE = "done"
    ERROR = "error"


# ============================== DATA MODELS ==================================
@dataclass
class EventRecord:
    validator_uid: int
    round_id: str
    phase: Phase
    message: str = ""
    ts: float = field(default_factory=_now_ts)
    extra: Dict[str, Any] = field(default_factory=dict)


# --- RoundResults Hierarchy ---

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
    solution: Dict[str, Any] = field(default_factory=dict)
    test_results: Dict[str, Any] = field(default_factory=dict)
    evaluation_result: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentEvaluationRun:
    miner_uid: int
    miner_hotkey: str
    miner_coldkey: str
    # aggregates over all tasks in the round
    reward: float
    eval_score: float
    time_score: float
    execution_time: float
    # per-task breakdown
    task_results: List[TaskResult] = field(default_factory=list)


@dataclass
class WeightsSnapshot:
    full_uids: List[int]
    rewards_full_avg: List[float]
    rewards_full_wta: List[float]
    winner_uid: Optional[int] = None


@dataclass
class RoundResults:
    # who/when
    validator_uid: int
    round_id: str
    version: str
    started_at: float
    ended_at: float
    elapsed_sec: float
    # miners
    n_active_miners: int
    n_total_miners: int
    # tasks and agents
    tasks: List[TaskInfo]
    agent_runs: List[AgentEvaluationRun]
    # optional on-chain snapshot
    weights: Optional[WeightsSnapshot] = None
    # any extras
    meta: Dict[str, Any] = field(default_factory=dict)


# =============================== CLIENT ======================================
class LeaderboardAPI:
    """
    Only two write paths:
      1) log_event(EventRecord)
      2) post_round_results(RoundResults)
    """

    def __init__(self, base_url: str = LEADERBOARD_BASE_URL, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, url: str, json_payload: Any) -> Optional[requests.Response]:
        payload = _to_serializable(json_payload)
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            _log_error(f"POST {url} failed: {e}")
            return None

    async def _post_async(self, url: str, json_payload: Any) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._post, url, json_payload)

    def _post_bg(self, url: str, json_payload: Any) -> None:
        try:
            task = asyncio.create_task(self._post_async(url, json_payload))
            task.add_done_callback(lambda fut: _log_error(f"Background POST error: {fut.exception()}") if fut.exception() else None)
        except RuntimeError:
            # not in an event loop -> sync
            self._post(url, json_payload)

    # ----------------------------- High-level API -----------------------------
    def log_event(self, record: EventRecord, background: bool = True) -> None:
        url = ENDPOINTS["events"]
        (self._post_bg if background else self._post)(url, asdict(record))

    def log_event_simple(
        self,
        *,
        validator_uid: int,
        round_id: str,
        phase: Phase,
        message: str = "",
        extra: Optional[Dict[str, Any]] = None,
        background: bool = True,
    ) -> None:
        self.log_event(
            EventRecord(
                validator_uid=int(validator_uid),
                round_id=round_id,
                phase=phase,
                message=message,
                extra=extra or {},
            ),
            background=background,
        )

    def post_round_results(self, rr: RoundResults, background: bool = True) -> None:
        url = ENDPOINTS["round_results"]
        (self._post_bg if background else self._post)(url, rr)
