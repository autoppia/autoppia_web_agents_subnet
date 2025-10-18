from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


def _drop_nones(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Remove keys with None values to keep payloads compact."""
    return {key: value for key, value in payload.items() if value is not None}


@dataclass
class ValidatorIdentityIWAP:
    uid: int
    hotkey: str
    coldkey: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        return _drop_nones(asdict(self))


@dataclass
class ValidatorSnapshotIWAP:
    validator_round_id: str
    validator_uid: int
    validator_hotkey: str
    name: Optional[str] = None
    stake: Optional[float] = None
    vtrust: Optional[float] = None
    image_url: Optional[str] = None
    version: Optional[str] = None
    role: str = "primary"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        data = asdict(self)
        data["metadata"] = self.metadata or {}
        return _drop_nones(data)


@dataclass
class ValidatorRoundIWAP:
    validator_round_id: str
    round_number: int
    validator_uid: int
    validator_hotkey: str
    validator_coldkey: Optional[str]
    start_block: int
    start_epoch: float
    max_epochs: int
    max_blocks: int
    n_tasks: int
    n_miners: int
    n_winners: int
    status: str = "active"
    started_at: float = field(default_factory=float)
    end_block: Optional[int] = None
    end_epoch: Optional[float] = None
    ended_at: Optional[float] = None
    elapsed_sec: Optional[float] = None
    average_score: Optional[float] = None
    top_score: Optional[float] = None
    summary: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        data = asdict(self)
        data["summary"] = self.summary or {}
        data["metadata"] = self.metadata or {}
        return _drop_nones(data)


@dataclass
class MinerIdentityIWAP:
    uid: Optional[int]
    hotkey: Optional[str]
    coldkey: Optional[str] = None
    agent_key: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        return _drop_nones(asdict(self))


@dataclass
class MinerSnapshotIWAP:
    validator_round_id: str
    miner_uid: Optional[int]
    miner_hotkey: Optional[str]
    miner_coldkey: Optional[str]
    agent_key: Optional[str]
    agent_name: str
    image_url: Optional[str] = None
    github_url: Optional[str] = None
    provider: Optional[str] = None
    description: Optional[str] = None
    is_sota: bool = False
    first_seen_at: Optional[float] = None
    last_seen_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        data = asdict(self)
        data["metadata"] = self.metadata or {}
        return _drop_nones(data)


@dataclass
class TaskIWAP:
    task_id: str
    validator_round_id: str
    scope: str
    is_web_real: bool
    url: str
    prompt: str
    html: str
    clean_html: str
    specifications: Dict[str, Any]
    tests: List[Dict[str, Any]]
    relevant_data: Dict[str, Any]
    use_case: Dict[str, Any]
    should_record: bool = False
    sequence: Optional[int] = None
    web_project_id: Optional[str] = None
    interactive_elements: Optional[str] = None
    screenshot: Optional[str] = None
    screenshot_description: Optional[str] = None
    milestones: Optional[List[Dict[str, Any]]] = None
    success_criteria: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        data = asdict(self)
        data["specifications"] = self.specifications or {}
        data["tests"] = self.tests or []
        data["relevant_data"] = self.relevant_data or {}
        data["use_case"] = self.use_case or {}
        if self.milestones is None:
            data["milestones"] = None
        return _drop_nones(data)


@dataclass
class AgentRunIWAP:
    agent_run_id: str
    validator_round_id: str
    validator_uid: int
    validator_hotkey: str
    miner_uid: Optional[int]
    miner_hotkey: Optional[str]
    miner_agent_key: Optional[str]
    is_sota: bool
    version: Optional[str]
    started_at: float
    ended_at: Optional[float] = None
    elapsed_sec: Optional[float] = None
    average_score: Optional[float] = None
    average_execution_time: Optional[float] = None
    average_reward: Optional[float] = None
    total_reward: Optional[float] = None
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    rank: Optional[int] = None
    weight: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        data = asdict(self)
        data["metadata"] = self.metadata or {}
        return _drop_nones(data)


@dataclass
class TaskSolutionIWAP:
    solution_id: str
    task_id: str
    agent_run_id: str
    validator_round_id: str
    validator_uid: int
    validator_hotkey: str
    miner_uid: Optional[int]
    miner_hotkey: Optional[str]
    miner_agent_key: Optional[str]
    actions: List[Dict[str, Any]]
    web_agent_id: Optional[str] = None
    recording: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        data = asdict(self)
        data["metadata"] = self.metadata or {}
        return _drop_nones(data)


@dataclass
class EvaluationResultIWAP:
    evaluation_id: str
    validator_round_id: str
    agent_run_id: str
    task_id: str
    task_solution_id: str
    validator_uid: int
    miner_uid: Optional[int]
    final_score: float
    test_results_matrix: List[List[Dict[str, Any]]] = field(default_factory=list)
    execution_history: List[Dict[str, Any]] = field(default_factory=list)
    feedback: Optional[Dict[str, Any]] = None
    web_agent_id: Optional[str] = None
    raw_score: Optional[float] = None
    evaluation_time: Optional[float] = None
    stats: Optional[Dict[str, Any]] = None
    gif_recording: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        data = asdict(self)
        data["metadata"] = self.metadata or {}
        return _drop_nones(data)


@dataclass
class RoundWinnerIWAP:
    miner_uid: Optional[int]
    miner_hotkey: Optional[str]
    rank: int
    score: float

    def to_payload(self) -> Dict[str, Any]:
        return _drop_nones(asdict(self))


@dataclass
class FinishRoundAgentRunIWAP:
    agent_run_id: str
    rank: Optional[int] = None
    weight: Optional[float] = None

    def to_payload(self) -> Dict[str, Any]:
        return _drop_nones(asdict(self))


@dataclass
class FinishRoundIWAP:
    status: str
    winners: List[RoundWinnerIWAP]
    winner_scores: List[float]
    weights: Dict[str, float]
    ended_at: float
    summary: Optional[Dict[str, int]] = None
    agent_runs: List[FinishRoundAgentRunIWAP] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "winners": [winner.to_payload() for winner in self.winners],
            "winner_scores": self.winner_scores,
            "weights": self.weights,
            "ended_at": self.ended_at,
            "summary": self.summary or {},
            "agent_runs": [run.to_payload() for run in self.agent_runs],
        }
