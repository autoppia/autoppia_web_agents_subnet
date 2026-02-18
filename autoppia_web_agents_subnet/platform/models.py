from __future__ import annotations

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
    validator_coldkey: Optional[str] = None
    name: Optional[str] = None
    stake: Optional[float] = None
    vtrust: Optional[float] = None
    image_url: Optional[str] = None
    version: Optional[str] = None
    role: str = "primary"
    validator_config: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        data = asdict(self)
        # Ensure validator_config is included even if empty
        data["validator_config"] = self.validator_config or {}
        return _drop_nones(data)


@dataclass
class ValidatorRoundIWAP:
    validator_round_id: str
    season_number: int
    round_number_in_season: int
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
    is_web_real: bool
    url: str
    prompt: str
    specifications: Dict[str, Any]
    tests: List[Dict[str, Any]]
    use_case: Dict[str, Any]
    web_project_id: Optional[str] = None
    web_version: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        from datetime import datetime, date, time as datetime_time

        def make_json_serializable(obj):
            """Convert non-JSON-serializable objects to JSON-compatible types"""
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()
            if isinstance(obj, datetime_time):
                return obj.isoformat()
            if isinstance(obj, dict):
                return {k: make_json_serializable(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [make_json_serializable(item) for item in obj]
            return obj

        data = asdict(self)
        data["specifications"] = make_json_serializable(self.specifications or {})
        data["tests"] = make_json_serializable(self.tests or [])
        data["use_case"] = make_json_serializable(self.use_case or {})
        # All fields are now clean, just serialize and return
        return _drop_nones(data)


@dataclass
class AgentRunIWAP:
    agent_run_id: str
    validator_round_id: str
    validator_uid: int
    validator_hotkey: str
    miner_uid: Optional[int]
    miner_hotkey: Optional[str]
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
    actions: List[Dict[str, Any]]
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
    validator_hotkey: str  # Required field for Evaluation model
    miner_uid: Optional[int]
    eval_score: float  # Evaluation score (tests/actions only, 0-1)
    reward: float  # Reward value (eval_score + time_score, used for consensus)
    test_results: List[Dict[str, Any]] = field(default_factory=list)  # Simplified from matrix to list
    execution_history: List[Dict[str, Any]] = field(default_factory=list)
    feedback: Optional[Dict[str, Any]] = None
    evaluation_time: Optional[float] = None
    stats: Optional[Dict[str, Any]] = None
    gif_recording: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    # LLM usage tracking (single source of truth)
    llm_usage: Optional[List[Dict[str, Any]]] = None  # Per-call usage [{provider, model?, tokens?, cost?}]

    def to_payload(self) -> Dict[str, Any]:
        data = asdict(self)
        # Only include metadata if it has useful information (not empty)
        if self.metadata:
            data["metadata"] = self.metadata
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
    # weight removed - now only in post_consensus_evaluation
    # FASE 1: Nuevos campos
    miner_name: Optional[str] = None
    avg_reward: Optional[float] = None  # Average reward (eval_score + time_score)
    avg_evaluation_time: Optional[float] = None
    tasks_attempted: Optional[int] = None
    tasks_completed: Optional[int] = None
    tasks_failed: Optional[int] = None

    def to_payload(self) -> Dict[str, Any]:
        return _drop_nones(asdict(self))


@dataclass
class RoundMetadataIWAP:
    """Round timing and metadata."""

    round_number: int
    started_at: float
    ended_at: float
    start_block: int
    end_block: int
    start_epoch: float
    end_epoch: float
    tasks_total: int
    tasks_completed: int
    miners_responded_handshake: int
    miners_active: int
    emission: Optional[Dict[str, Any]] = None

    def to_payload(self) -> Dict[str, Any]:
        return _drop_nones(asdict(self))


@dataclass
class FinishRoundIWAP:
    status: str
    ended_at: float
    summary: Optional[Dict[str, int]] = None
    agent_runs: List[FinishRoundAgentRunIWAP] = field(default_factory=list)
    # FASE 1: Nuevos campos opcionales
    round_metadata: Optional[RoundMetadataIWAP] = None
    local_evaluation: Optional[Dict[str, Any]] = None
    post_consensus_evaluation: Optional[Dict[str, Any]] = None
    # FASE 2: IPFS data
    ipfs_uploaded: Optional[Dict[str, Any]] = None
    ipfs_downloaded: Optional[Dict[str, Any]] = None
    # Deprecated fields (kept for backward compatibility but no longer populated)
    winners: List[RoundWinnerIWAP] = field(default_factory=list)
    winner_scores: List[float] = field(default_factory=list)
    weights: Dict[str, float] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "status": self.status,
            "ended_at": self.ended_at,
            "summary": self.summary or {},
            "agent_runs": [run.to_payload() for run in self.agent_runs],
        }

        # Add new fields if present
        if self.round_metadata:
            payload["round"] = self.round_metadata.to_payload()
        if self.local_evaluation:
            payload["local_evaluation"] = self.local_evaluation
        if self.post_consensus_evaluation:
            payload["post_consensus_evaluation"] = self.post_consensus_evaluation
        if self.ipfs_uploaded:
            payload["ipfs_uploaded"] = self.ipfs_uploaded
        if self.ipfs_downloaded:
            payload["ipfs_downloaded"] = self.ipfs_downloaded

        # Deprecated fields (only included if populated for backward compatibility)
        if self.winners:
            payload["winners"] = [winner.to_payload() for winner in self.winners]
        if self.winner_scores:
            payload["winner_scores"] = self.winner_scores
        if self.weights:
            payload["weights"] = self.weights

        return payload
