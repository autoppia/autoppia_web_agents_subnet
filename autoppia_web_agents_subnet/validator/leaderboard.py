# autoppia_web_agents_subnet/validator/leaderboard.py
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import requests

try:
    import bittensor as bt
    _HAS_BT = True
except Exception:
    _HAS_BT = False


# =============================== CONFIG ======================================
LEADERBOARD_BASE_URL = "https://api-leaderboard.autoppia.com"
API_V1 = f"{LEADERBOARD_BASE_URL}/v1"

ENDPOINTS = {
    # v0 (legacy, still supported for archival)
    "events_v0": f"{LEADERBOARD_BASE_URL}/events/",
    "round_results_v0": f"{LEADERBOARD_BASE_URL}/round-results/",
    # v1 (streaming API)
    "round_start": f"{API_V1}/rounds/start",
    "round_events": f"{API_V1}/rounds/{{round_id}}/events",
    "task_runs_batch_upsert": f"{API_V1}/rounds/{{round_id}}/task-runs:batch-upsert",
    "agent_runs_upsert": f"{API_V1}/rounds/{{round_id}}/agent-runs:upsert",
    "progress": f"{API_V1}/rounds/{{round_id}}/progress",
    "weights": f"{API_V1}/rounds/{{round_id}}/weights",
    "finalize": f"{API_V1}/rounds/{{round_id}}/finalize",
    "round_results_v1": f"{API_V1}/rounds/{{round_id}}/round-results",
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


# --- RoundResults Hierarchy (archival) ---

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


# --- Streaming API data (v1) ---

@dataclass
class RoundHeader:
    validator_uid: int
    round_id: str
    version: str
    max_epochs: int
    max_blocks: int
    started_at: float
    start_block: int
    n_total_miners: int
    task_set: List[TaskInfo] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskRun:
    validator_uid: int
    round_id: str
    task_id: str
    miner_uid: int
    miner_hotkey: str
    miner_coldkey: str
    eval_score: float
    time_score: float
    execution_time: float
    reward: float
    solution: Dict[str, Any] = field(default_factory=dict)
    test_results: Dict[str, Any] = field(default_factory=dict)
    evaluation_result: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRun:
    validator_uid: int
    round_id: str
    miner_uid: int
    miner_hotkey: str
    miner_coldkey: str
    reward: float
    eval_score: float
    time_score: float
    execution_time: float
    tasks_count: Optional[int] = None


@dataclass
class RoundSummary:
    validator_uid: int
    round_id: str
    ended_at: float
    elapsed_sec: float
    n_active_miners: int
    n_total_miners: int
    stats: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)


# =============================== CLIENT ======================================
class LeaderboardAPI:
    """
    Two families:

    v1 (streaming):
      round_start(), log_event(), post_task_runs(), upsert_agent_runs(), post_progress(),
      put_weights(), finalize_round(), post_round_results_v1()

    v0 (legacy archival, optional):
      log_event_legacy(), post_round_results()
    """

    def __init__(self, base_url: str = LEADERBOARD_BASE_URL, timeout: int = DEFAULT_TIMEOUT, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key

    # ------------------------------- HTTP -------------------------------------
    def _headers(self, idempotency_key: Optional[str] = None) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        if idempotency_key:
            h["Idempotency-Key"] = idempotency_key
        return h

    def _post(self, url: str, json_payload: Any, idempotency_key: Optional[str] = None) -> Optional[requests.Response]:
        payload = _to_serializable(json_payload)
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout, headers=self._headers(idempotency_key))
            resp.raise_for_status()
            return resp
        except Exception as e:
            _log_error(f"POST {url} failed: {e}")
            return None

    def _put(self, url: str, json_payload: Any) -> Optional[requests.Response]:
        payload = _to_serializable(json_payload)
        try:
            resp = requests.put(url, json=payload, timeout=self.timeout, headers=self._headers())
            resp.raise_for_status()
            return resp
        except Exception as e:
            _log_error(f"PUT {url} failed: {e}")
            return None

    async def _post_async(self, url: str, json_payload: Any, idempotency_key: Optional[str] = None) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._post, url, json_payload, idempotency_key)

    async def _put_async(self, url: str, json_payload: Any) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._put, url, json_payload)

    def _post_bg(self, url: str, json_payload: Any, idempotency_key: Optional[str] = None) -> None:
        try:
            task = asyncio.create_task(self._post_async(url, json_payload, idempotency_key))
            task.add_done_callback(lambda fut: _log_error(f"Background POST error: {fut.exception()}") if fut.exception() else None)
        except RuntimeError:
            # not in an event loop -> sync
            self._post(url, json_payload, idempotency_key)

    def _put_bg(self, url: str, json_payload: Any) -> None:
        try:
            task = asyncio.create_task(self._put_async(url, json_payload))
            task.add_done_callback(lambda fut: _log_error(f"Background PUT error: {fut.exception()}") if fut.exception() else None)
        except RuntimeError:
            self._put(url, json_payload)

    # ----------------------------- v1 API -------------------------------------
    def start_round(self, header: RoundHeader, *, background: bool = True, idempotency_key: Optional[str] = None) -> None:
        url = ENDPOINTS["round_start"]
        (self._post_bg if background else self._post)(url, header, idempotency_key)

    def log_event(self, record: EventRecord, *, background: bool = True, idempotency_key: Optional[str] = None) -> None:
        url = ENDPOINTS["round_events"].format(round_id=record.round_id)
        (self._post_bg if background else self._post)(url, asdict(record), idempotency_key)

    def post_task_runs(self, *, round_id: str, validator_uid: int, task_runs: Sequence[TaskRun], background: bool = True) -> None:
        url = ENDPOINTS["task_runs_batch_upsert"].format(round_id=round_id)
        payload = {
            "validator_uid": int(validator_uid),
            "round_id": round_id,
            "task_runs": [asdict(tr) for tr in task_runs],
        }
        (self._post_bg if background else self._post)(url, payload, None)

    def upsert_agent_runs(self, *, round_id: str, validator_uid: int, agent_runs: Sequence[AgentRun], background: bool = True) -> None:
        url = ENDPOINTS["agent_runs_upsert"].format(round_id=round_id)
        payload = {
            "validator_uid": int(validator_uid),
            "round_id": round_id,
            "agent_runs": [asdict(ar) for ar in agent_runs],
        }
        (self._post_bg if background else self._post)(url, payload, None)

    def post_progress(self, *, round_id: str, validator_uid: int, tasks_total: int, tasks_completed: int, extra: Optional[Dict[str, Any]] = None, background: bool = True) -> None:
        url = ENDPOINTS["progress"].format(round_id=round_id)
        payload = {
            "validator_uid": int(validator_uid),
            "round_id": round_id,
            "tasks_total": int(tasks_total),
            "tasks_completed": int(tasks_completed),
            "extra": extra or {},
        }
        (self._post_bg if background else self._post)(url, payload, None)

    def put_weights(self, *, round_id: str, validator_uid: int, weights: WeightsSnapshot, background: bool = True) -> None:
        url = ENDPOINTS["weights"].format(round_id=round_id)
        payload = {
            "validator_uid": int(validator_uid),
            "round_id": round_id,
            "weights": asdict(weights),
        }
        (self._put_bg if background else self._put)(url, payload)

    def finalize_round(self, summary: RoundSummary, *, background: bool = True) -> None:
        url = ENDPOINTS["finalize"].format(round_id=summary.round_id)
        (self._post_bg if background else self._post)(url, summary, None)

    def post_round_results_v1(self, rr: RoundResults, *, background: bool = True) -> None:
        url = ENDPOINTS["round_results_v1"].format(round_id=rr.round_id)
        (self._post_bg if background else self._post)(url, rr, None)

    # --------------------------- Legacy (v0) -----------------------------------
    def log_event_legacy(self, record: EventRecord, background: bool = True) -> None:
        url = ENDPOINTS["events_v0"]
        (self._post_bg if background else self._post)(url, asdict(record))

    def post_round_results(self, rr: RoundResults, background: bool = True) -> None:
        url = ENDPOINTS["round_results_v0"]
        (self._post_bg if background else self._post)(url, rr)
