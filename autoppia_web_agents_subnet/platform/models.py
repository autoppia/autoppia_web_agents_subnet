from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _drop_nones(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove keys with None values to keep payloads compact."""
    return {key: value for key, value in payload.items() if value is not None}


@dataclass
class ValidatorIdentityIWAP:
    uid: int
    hotkey: str
    coldkey: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return _drop_nones(asdict(self))


@dataclass
class ValidatorSnapshotIWAP:
    validator_round_id: str
    validator_uid: int
    validator_hotkey: str
    validator_coldkey: str | None = None
    name: str | None = None
    stake: float | None = None
    vtrust: float | None = None
    image_url: str | None = None
    version: str | None = None
    role: str = "primary"
    validator_config: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
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
    validator_coldkey: str | None
    start_block: int
    start_epoch: float
    max_epochs: int
    max_blocks: int
    n_tasks: int
    n_miners: int
    n_winners: int
    status: str = "active"
    started_at: float = field(default_factory=float)
    end_block: int | None = None
    end_epoch: float | None = None
    ended_at: float | None = None
    elapsed_sec: float | None = None
    average_score: float | None = None
    top_score: float | None = None
    summary: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["summary"] = self.summary or {}
        data["metadata"] = self.metadata or {}
        return _drop_nones(data)


@dataclass
class MinerIdentityIWAP:
    uid: int | None
    hotkey: str | None
    coldkey: str | None = None
    agent_key: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return _drop_nones(asdict(self))


@dataclass
class MinerSnapshotIWAP:
    validator_round_id: str
    miner_uid: int | None
    miner_hotkey: str | None
    miner_coldkey: str | None
    agent_key: str | None
    agent_name: str
    image_url: str | None = None
    github_url: str | None = None
    provider: str | None = None
    description: str | None = None
    is_sota: bool = False
    first_seen_at: float | None = None
    last_seen_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
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
    specifications: dict[str, Any]
    tests: list[dict[str, Any]]
    use_case: dict[str, Any]
    web_project_id: str | None = None
    web_version: str | None = None

    def to_payload(self) -> dict[str, Any]:
        from datetime import date, datetime, time as datetime_time

        def make_json_serializable(obj):
            """Convert non-JSON-serializable objects to JSON-compatible types"""
            if isinstance(obj, datetime | date):
                return obj.isoformat()
            if isinstance(obj, datetime_time):
                return obj.isoformat()
            if isinstance(obj, dict):
                return {k: make_json_serializable(v) for k, v in obj.items()}
            if isinstance(obj, list | tuple):
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
    miner_uid: int | None
    miner_hotkey: str | None
    is_sota: bool
    version: str | None
    started_at: float
    ended_at: float | None = None
    elapsed_sec: float | None = None
    average_score: float | None = None
    average_execution_time: float | None = None
    average_reward: float | None = None
    total_reward: float | None = None
    total_tasks: int = 0
    tasks_attempted: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    rank: int | None = None
    weight: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Reason for score 0 when applicable (e.g. task_timeout, over_cost_limit); copied from source when reused
    zero_reason: str | None = None
    early_stop_reason: str | None = None
    early_stop_message: str | None = None

    def to_payload(self) -> dict[str, Any]:
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
    miner_uid: int | None
    miner_hotkey: str | None
    actions: list[dict[str, Any]]
    recording: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
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
    miner_uid: int | None
    eval_score: float  # Pure evaluation quality score (tests/actions only, 0-1)
    reward: float  # Final task reward used by consensus (eval_score + time/cost shaping + penalties)
    test_results: list[dict[str, Any]] = field(default_factory=list)  # Simplified from matrix to list
    execution_history: list[dict[str, Any]] = field(default_factory=list)
    feedback: dict[str, Any] | None = None
    evaluation_time: float | None = None
    stats: dict[str, Any] | None = None
    gif_recording: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # LLM usage tracking (single source of truth)
    llm_usage: list[dict[str, Any]] | None = None  # Per-call usage [{provider, model?, tokens?, cost?}]
    # Reason for score 0 at evaluation level (e.g. task_timeout, tests_failed)
    zero_reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        data = asdict(self)
        # Emit evaluation_score (canonical); drop eval_score from payload
        if "eval_score" in data:
            data["evaluation_score"] = data.pop("eval_score")
        # Only include metadata if it has useful information (not empty)
        if self.metadata:
            data["metadata"] = self.metadata
        return _drop_nones(data)


@dataclass
class RoundWinnerIWAP:
    miner_uid: int | None
    miner_hotkey: str | None
    rank: int
    reward: float  # Winner reward for the round/season decision; this is not raw eval_score

    def to_payload(self) -> dict[str, Any]:
        return _drop_nones(asdict(self))


@dataclass
class FinishRoundAgentRunIWAP:
    agent_run_id: str
    rank: int | None = None
    # weight removed - now only in post_consensus_evaluation
    # FASE 1: Nuevos campos
    miner_name: str | None = None
    avg_reward: float | None = None  # Local per-validator average reward used as consensus input
    avg_evaluation_time: float | None = None
    tasks_attempted: int | None = None
    tasks_completed: int | None = None
    tasks_failed: int | None = None
    # Reason for score 0 when applicable (e.g. over_cost_limit, deploy_failed, task_failed)
    zero_reason: str | None = None
    early_stop_reason: str | None = None
    early_stop_message: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return _drop_nones(asdict(self))


@dataclass
class RoundMetadataIWAP:
    """Round timing and metadata. Backend uses round_size_epochs/season_size_epochs/minimum_start_block to persist config_season_round (main validator only)."""

    round_number: int
    started_at: float
    ended_at: float
    start_block: int
    end_block: int
    start_epoch: float
    end_epoch: float
    tasks_total: int
    tasks_completed: int
    miners_responded_handshake: int  # miners that answered the round handshake
    miners_evaluated: int  # miners that had at least one task evaluated (appear in rewards)
    emission: dict[str, Any] | None = None
    # Round/season config: backend persists to config_season_round table (main validator only) so dashboard uses validator timing
    round_size_epochs: float | None = None
    season_size_epochs: float | None = None
    minimum_start_block: int | None = None
    blocks_per_epoch: int | None = None

    def to_payload(self) -> dict[str, Any]:
        return _drop_nones(asdict(self))


@dataclass
class FinishRoundIWAP:
    status: str
    ended_at: float
    summary: dict[str, Any] | None = None
    agent_runs: list[FinishRoundAgentRunIWAP] = field(default_factory=list)
    # FASE 1: Nuevos campos opcionales
    round_metadata: RoundMetadataIWAP | None = None
    local_evaluation: dict[str, Any] | None = None
    post_consensus_evaluation: dict[str, Any] | None = None  # Stake-weighted consensus metrics across included validators
    validator_summary: dict[str, Any] | None = None
    # FASE 2: IPFS data
    ipfs_uploaded: dict[str, Any] | None = None
    ipfs_downloaded: dict[str, Any] | None = None
    s3_logs_url: str | None = None
    validator_state: dict[str, Any] | None = None
    # Compatibility fields kept in the payload shape even though current consumers use the richer summaries
    winners: list[RoundWinnerIWAP] = field(default_factory=list)
    winner_rewards: list[float] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "ended_at": self.ended_at,
            "summary": self.summary or {},
            "agent_runs": [run.to_payload() for run in self.agent_runs],
        }

        # Add new fields if present
        if self.round_metadata:
            payload["round"] = self.round_metadata.to_payload()
        if self.local_evaluation is not None:
            payload["local_evaluation"] = self.local_evaluation
        if self.post_consensus_evaluation is not None:
            payload["post_consensus_evaluation"] = self.post_consensus_evaluation
        if self.validator_summary is not None:
            payload["validator_summary"] = self.validator_summary
        if self.ipfs_uploaded is not None:
            payload["ipfs_uploaded"] = self.ipfs_uploaded
        if self.ipfs_downloaded is not None:
            payload["ipfs_downloaded"] = self.ipfs_downloaded
        if self.s3_logs_url is not None:
            payload["s3_logs_url"] = self.s3_logs_url
        if self.validator_state is not None:
            payload["validator_state"] = self.validator_state

        # Compatibility fields included only when populated
        if self.winners:
            payload["winners"] = [winner.to_payload() for winner in self.winners]
        if self.winner_rewards:
            payload["winner_rewards"] = self.winner_rewards
        if self.weights:
            payload["weights"] = self.weights

        return payload
