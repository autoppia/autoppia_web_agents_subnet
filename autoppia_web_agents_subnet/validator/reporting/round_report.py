"""
RoundReport - Complete round statistics stored in memory during validator execution.

This class captures ALL relevant data during a round so we can generate
comprehensive reports without parsing logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class MinerReport:
    """Statistics for a single miner in a round."""

    uid: int
    hotkey: str
    coldkey: str = ""

    # Handshake
    responded_to_handshake: bool = False
    agent_name: Optional[str] = None
    agent_image: Optional[str] = None

    # Task execution
    tasks_attempted: int = 0
    tasks_success: int = 0
    tasks_failed: int = 0

    # Performance metrics
    execution_times: List[float] = field(default_factory=list)
    eval_scores: List[float] = field(default_factory=list)
    rewards: List[float] = field(default_factory=list)

    # Per-web statistics (NEW)
    # web_name -> {"attempted": int, "success": int, "failed": int}
    per_web_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)

    # Final results
    avg_time: float = 0.0
    avg_score: float = 0.0
    avg_reward: float = 0.0
    score_percentage: float = 0.0  # tasks_success / tasks_attempted * 100
    final_score_after_consensus: float = 0.0
    final_weight: float = 0.0
    is_winner: bool = False
    rank: int = 0

    def calculate_averages(self):
        """Calculate average metrics from collected data."""
        if self.execution_times:
            self.avg_time = sum(self.execution_times) / len(self.execution_times)

        if self.eval_scores:
            self.avg_score = sum(self.eval_scores) / len(self.eval_scores)

        if self.rewards:
            self.avg_reward = sum(self.rewards) / len(self.rewards)

        # Calculate score percentage
        if self.tasks_attempted > 0:
            self.score_percentage = (self.tasks_success / self.tasks_attempted) * 100.0


@dataclass
class ConsensusValidatorReport:
    """Information about a validator participating in consensus."""

    uid: Optional[int]
    hotkey: str
    stake_tao: float
    ipfs_cid: Optional[str] = None
    miners_reported: int = 0

    # Their scores for miners (for comparison)
    miner_scores: Dict[int, float] = field(default_factory=dict)


@dataclass
class RoundReport:
    """Complete round report with all statistics."""

    # Round identification
    round_number: int
    validator_round_id: str
    validator_uid: int
    validator_hotkey: str

    # Timing
    start_block: int
    end_block: Optional[int] = None
    start_epoch: float = 0.0
    end_epoch: Optional[float] = None
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None

    # Round configuration
    total_blocks: int = 72
    planned_tasks: int = 0
    tasks_completed: int = 0

    # Handshake phase
    handshake_sent_to: int = 0  # Total miners contacted
    handshake_responses: int = 0  # Miners that responded
    handshake_response_uids: List[int] = field(default_factory=list)
    handshake_response_hotkeys: List[str] = field(default_factory=list)

    # Miners data
    miners: Dict[int, MinerReport] = field(default_factory=dict)

    # Per-web global statistics (NEW)
    # web_name -> {"sent": int, "solved": int}
    per_web_global_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)

    # Consensus data
    consensus_enabled: bool = True
    consensus_published: bool = False
    consensus_ipfs_cid: Optional[str] = None
    consensus_validators: List[ConsensusValidatorReport] = field(default_factory=list)
    consensus_aggregated: bool = False

    # Winners
    local_winner_uid: Optional[int] = None
    final_winner_uid: Optional[int] = None  # After consensus

    # Status
    completed: bool = False
    error: Optional[str] = None

    # Errors and warnings during round (NEW)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Round progress checklist (NEW)
    checkpoint_tasks_generated: bool = False
    checkpoint_handshake_sent: bool = False
    checkpoint_tasks_evaluated: bool = False
    checkpoint_ipfs_published: bool = False
    checkpoint_ipfs_downloaded: bool = False
    checkpoint_winner_selected: bool = False

    def add_miner(self, uid: int, hotkey: str) -> MinerReport:
        """Add or get a miner report."""
        if uid not in self.miners:
            self.miners[uid] = MinerReport(uid=uid, hotkey=hotkey)
        return self.miners[uid]

    def add_error(self, error_message: str):
        """Record an error that occurred during the round."""
        if error_message and error_message not in self.errors:
            self.errors.append(error_message)

    def add_warning(self, warning_message: str):
        """Record a warning that occurred during the round."""
        if warning_message and warning_message not in self.warnings:
            self.warnings.append(warning_message)

    def record_handshake_response(self, uid: int, hotkey: str, agent_name: str = None, agent_image: str = None):
        """Record that a miner responded to handshake."""
        miner = self.add_miner(uid, hotkey)
        miner.responded_to_handshake = True
        miner.agent_name = agent_name
        miner.agent_image = agent_image

        if uid not in self.handshake_response_uids:
            self.handshake_response_uids.append(uid)
            self.handshake_response_hotkeys.append(hotkey)
            self.handshake_responses += 1

    def record_task_result(self, uid: int, success: bool, execution_time: float, eval_score: float, reward: float, web_name: Optional[str] = None):
        """Record a task execution result for a miner."""
        if uid not in self.miners:
            return

        miner = self.miners[uid]
        miner.tasks_attempted += 1

        if success:
            miner.tasks_success += 1
        else:
            miner.tasks_failed += 1

        miner.execution_times.append(execution_time)
        miner.eval_scores.append(eval_score)
        miner.rewards.append(reward)

        # Record per-web statistics
        if web_name:
            if web_name not in miner.per_web_stats:
                miner.per_web_stats[web_name] = {"attempted": 0, "success": 0, "failed": 0}

            miner.per_web_stats[web_name]["attempted"] += 1
            if success:
                miner.per_web_stats[web_name]["success"] += 1
            else:
                miner.per_web_stats[web_name]["failed"] += 1

            # Update global per-web stats
            if web_name not in self.per_web_global_stats:
                self.per_web_global_stats[web_name] = {"sent": 0, "solved": 0}

            self.per_web_global_stats[web_name]["sent"] += 1
            if success:
                self.per_web_global_stats[web_name]["solved"] += 1

    def finalize_round(self, end_block: int, end_epoch: float):
        """Finalize the round and calculate all averages."""
        self.end_block = end_block
        self.end_epoch = end_epoch
        self.end_time = datetime.utcnow()
        self.completed = True

        # Calculate averages for all miners
        for miner in self.miners.values():
            miner.calculate_averages()

        # Rank miners by final score
        sorted_miners = sorted(self.miners.values(), key=lambda m: m.final_score_after_consensus or m.avg_score, reverse=True)

        for rank, miner in enumerate(sorted_miners, start=1):
            miner.rank = rank

    def get_top_miners(self, n: int = 5) -> List[MinerReport]:
        """Get top N miners by final score."""
        sorted_miners = sorted(self.miners.values(), key=lambda m: m.final_score_after_consensus or m.avg_score, reverse=True)
        return sorted_miners[:n]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "round_number": self.round_number,
            "validator_round_id": self.validator_round_id,
            "validator_uid": self.validator_uid,
            "validator_hotkey": self.validator_hotkey,
            "start_block": self.start_block,
            "end_block": self.end_block,
            "start_epoch": self.start_epoch,
            "end_epoch": self.end_epoch,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "planned_tasks": self.planned_tasks,
            "tasks_completed": self.tasks_completed,
            "handshake_sent_to": self.handshake_sent_to,
            "handshake_responses": self.handshake_responses,
            "handshake_response_uids": self.handshake_response_uids,
            "handshake_response_hotkeys": self.handshake_response_hotkeys,
            "miners": {
                uid: {
                    "uid": m.uid,
                    "hotkey": m.hotkey,
                    "responded_to_handshake": m.responded_to_handshake,
                    "agent_name": m.agent_name,
                    "tasks_attempted": m.tasks_attempted,
                    "tasks_success": m.tasks_success,
                    "tasks_failed": m.tasks_failed,
                    "avg_time": m.avg_time,
                    "avg_score": m.avg_score,
                    "avg_reward": m.avg_reward,
                    "final_score": m.final_score_after_consensus,
                    "final_weight": m.final_weight,
                    "is_winner": m.is_winner,
                    "rank": m.rank,
                }
                for uid, m in self.miners.items()
            },
            "consensus_enabled": self.consensus_enabled,
            "consensus_published": self.consensus_published,
            "consensus_ipfs_cid": self.consensus_ipfs_cid,
            "consensus_validators": [
                {
                    "uid": v.uid,
                    "hotkey": v.hotkey,
                    "stake_tao": v.stake_tao,
                    "ipfs_cid": v.ipfs_cid,
                    "miners_reported": v.miners_reported,
                }
                for v in self.consensus_validators
            ],
            "local_winner_uid": self.local_winner_uid,
            "final_winner_uid": self.final_winner_uid,
            "completed": self.completed,
            "error": self.error,
        }
