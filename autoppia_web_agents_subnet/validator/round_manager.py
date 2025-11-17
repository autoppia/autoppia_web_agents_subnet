from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.config import (
    ROUND_SIZE_EPOCHS,
    MINIMUM_START_BLOCK,
    SCREENING_START_FRACTION,
    SCREENING_STOP_FRACTION,
    FINAL_START_FRACTION,
    FINAL_STOP_FRACTION,
    SETTLEMENT_FRACTION,
)


class RoundPhase(Enum):
    """Named phases in the validator round lifecycle."""

    IDLE = "idle"
    START = "start"
    SCREENING_HANDSHAKE = "screening_handshake"
    SCREENING_TASK_EXECUTION = "screening_task_execution"
    SCREENING_CONSENSUS = "screening_consensus"
    FINAL_DEPLOY = "final_deploy"
    FINAL_TASK_EXECUTION = "final_task_execution"
    FINAL_CONSENSUS = "final_consensus"
    COMPLETE = "complete"
    WAITING = "waiting"
    ERROR = "error"


@dataclass
class PhaseTransition:
    """Record of a phase transition within a round."""

    phase: RoundPhase
    started_at_block: Optional[int] = None
    started_at_epoch: Optional[float] = None
    note: Optional[str] = None
    started_at_time: float = field(default_factory=time.time)


@dataclass
class RoundStatus:
    """Lightweight snapshot of the current round status."""

    phase: RoundPhase
    round_start_block: Optional[int]
    target_block: Optional[int]
    current_block: Optional[int]
    blocks_remaining: Optional[int]
    minutes_remaining: Optional[float]
    note: Optional[str] = None


class RoundManager:
    """
    Manages complete round lifecycle: timing, boundaries, and score accumulation.

    Combines:
    - Round timing and boundaries
    - Score accumulation (screening + final)
    - Phase tracking for observability
    """

    BLOCKS_PER_EPOCH = 360
    SECONDS_PER_BLOCK = 12

    def __init__(self):
        self.round_size_epochs = ROUND_SIZE_EPOCHS
        self.minimum_start_block = MINIMUM_START_BLOCK
        self.screening_stop_fraction = SCREENING_STOP_FRACTION
        self.final_start_fraction = FINAL_START_FRACTION
        self.final_stop_fraction = FINAL_STOP_FRACTION
        self.settlement_fraction = SETTLEMENT_FRACTION

        self.round_block_length = int(self.BLOCKS_PER_EPOCH * max(self.round_size_epochs, 0.01))

        # Round boundaries
        self.round_number: int | None = None

        self.start_block: int | None = None
        self.final_block: int | None = None
        self.settlement_block: int | None = None
        self.target_block: int | None = None

        self.start_epoch: float | None = None
        self.final_epoch: float | None = None
        self.settlement_epoch: float | None = None
        self.target_epoch: float | None = None

        # Screening statistics
        self.screening_rewards: Dict[int, List[float]] = {}
        self.screening_eval_scores: Dict[int, List[float]] = {}
        self.screening_times: Dict[int, List[float]] = {}
        self.screening_aggregated_rewards: Dict[int, float] = {}

        # Final-phase statistics
        self.final_rewards: Dict[int, List[float]] = {}
        self.final_eval_scores: Dict[int, List[float]] = {}
        self.final_times: Dict[int, List[float]] = {}
        self.final_aggregated_rewards: Dict[int, float] = {}
        
        # Duplicate-solution bookkeeping
        self.round_duplicate_counts: Dict[int, int] = {}

        # Phase tracking
        self.current_phase: RoundPhase = RoundPhase.IDLE
        self.phase_history: List[PhaseTransition] = []

    # ──────────────────────────────────────────────────────────────────────────
    # Round timing helpers
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def block_to_epoch(cls, block: int) -> float:
        return block / cls.BLOCKS_PER_EPOCH

    @classmethod
    def epoch_to_block(cls, epoch: float) -> int:
        return int(epoch * cls.BLOCKS_PER_EPOCH)

    def sync_boundaries(self, current_block: int) -> None:
        base_block = int(self.minimum_start_block)
        effective_block = max(current_block, base_block)
        
        blocks_since_base = effective_block - base_block
        round_index = blocks_since_base // self.round_block_length

        start_block = int(base_block + round_index * self.round_block_length)
        final_block = int(start_block + int(self.round_block_length * self.final_start_fraction))
        settlement_block = int(start_block + int(self.round_block_length * self.settlement_fraction))
        target_block = int(start_block + self.round_block_length)

        start_epoch = self.block_to_epoch(start_block)
        final_epoch = self.block_to_epoch(final_block)
        settlement_epoch = self.block_to_epoch(settlement_block)
        target_epoch = self.block_to_epoch(target_block)

        self.round_number = round_index + 1
        self.start_block = start_block
        self.final_block = final_block
        self.settlement_block = settlement_block
        self.target_block = target_block
        self.start_epoch = start_epoch
        self.final_epoch = final_epoch
        self.settlement_epoch = settlement_epoch
        self.target_epoch = target_epoch

    def start_new_round(self, current_block: int):
        if self.round_number is None:
            self.sync_boundaries(current_block)

        self.reset_round()
        self.enter_phase(
            RoundPhase.START,
            block=current_block,
            note="Starting new round",
        )

    def get_round_boundaries(self, current_block: int) -> Dict[str, Any]:
        if self.round_number is None:
            self.sync_boundaries(current_block)

        return {
            "round_start_block": self.start_block,
            "round_final_block": self.final_block,
            "round_target_block": self.target_block,
            "round_start_epoch": self.start_epoch,
            "round_final_epoch": self.final_epoch,
            "round_target_epoch": self.target_epoch,
        }

    def get_wait_info(self, current_block: int) -> Dict[str, Any]:
        if self.round_number is None:
            self.sync_boundaries(current_block)

        blocks_to_final = max(self.final_block - current_block, 0)
        minutes_to_final = blocks_to_final * self.SECONDS_PER_BLOCK / 60
        blocks_to_settlement = max(self.settlement_block - current_block, 0)
        minutes_to_settlement = blocks_to_settlement * self.SECONDS_PER_BLOCK / 60
        blocks_to_target = max(self.target_block - current_block, 0)
        minutes_to_target = blocks_to_target * self.SECONDS_PER_BLOCK / 60

        return {
            "blocks_to_final": blocks_to_final,
            "minutes_to_final": minutes_to_final,
            "blocks_to_settlement": blocks_to_settlement,
            "minutes_to_settlement": minutes_to_settlement,
            "blocks_to_target": blocks_to_target,
            "minutes_to_target": minutes_to_target,
        }

    def fraction_elapsed(self, current_block: int) -> float:
        if self.round_number is None:
            self.sync_boundaries(current_block)
        return float((current_block - self.start_block) / self.round_block_length)

    def should_send_next_task(self, current_block: int) -> bool:
        if self.current_phase == RoundPhase.SCREENING_TASK_EXECUTION:
            return self.fraction_elapsed(current_block) < self.screening_stop_fraction
        elif self.current_phase == RoundPhase.FINAL_TASK_EXECUTION:
            return self.fraction_elapsed(current_block) < self.final_stop_fraction
        else:
            return False

    def blocks_until_allowed(self, current_block: int) -> int:
        return max(self.minimum_start_block - current_block, 0)

    # ──────────────────────────────────────────────────────────────────────────
    # Score accumulation
    # ──────────────────────────────────────────────────────────────────────────
    def accumulate_screening_rewards(
        self,
        miner_uids: List[int],
        rewards: List[float],
        eval_scores: List[float],
        execution_times: List[float],
    ) -> None:
        for i, uid in enumerate(miner_uids):
            uid = int(uid)
            self.screening_rewards.setdefault(uid, []).append(rewards[i])
            self.screening_eval_scores.setdefault(uid, []).append(eval_scores[i])
            self.screening_times.setdefault(uid, []).append(execution_times[i])

    def accumulate_final_rewards(
        self,
        miner_uids: List[int],
        rewards: List[float],
        eval_scores: List[float],
        execution_times: List[float],
    ) -> None:
        for i, uid in enumerate(miner_uids):
            uid = int(uid)
            self.final_rewards.setdefault(uid, []).append(rewards[i])
            self.final_eval_scores.setdefault(uid, []).append(eval_scores[i])
            self.final_times.setdefault(uid, []).append(execution_times[i])

    def record_duplicate_penalties(self, miner_uids: List[int], groups: List[List[int]]):
        try:
            for group in groups or []:
                for idx in group:
                    if 0 <= idx < len(miner_uids):
                        uid = int(miner_uids[idx])
                        self.round_duplicate_counts[uid] = int(self.round_duplicate_counts.get(uid, 0)) + 1
        except Exception:
            pass

    def get_screening_average_rewards(self) -> Dict[int, float]:
        self.screening_aggregated_rewards = {
            uid: (sum(rewards) / len(rewards)) if rewards else 0.0
            for uid, rewards in self.screening_rewards.items()
        }
        return self.screening_aggregated_rewards

    def get_final_average_rewards(self) -> Dict[int, float]:
        self.final_aggregated_rewards = {
            uid: (sum(rewards) / len(rewards)) if rewards else 0.0
            for uid, rewards in self.final_rewards.items()
        }
        return self.final_aggregated_rewards

    def reset_round(self) -> None:
        self.round_rewards = {}
        self.round_eval_scores = {}
        self.round_times = {}
        self.round_task_attempts = {}
        self.final_round_rewards = {}
        self.final_round_eval_scores = {}
        self.final_round_times = {}
        self.round_duplicate_counts = {}
        self.reset_phase_tracking()

    # ──────────────────────────────────────────────────────────────────────────
    # Phase tracking utilities
    # ──────────────────────────────────────────────────────────────────────────
    def enter_phase(
        self,
        phase: RoundPhase,
        *,
        block: Optional[int] = None,
        note: Optional[str] = None,
        force: bool = False,
    ) -> PhaseTransition:
        if not force and self.current_phase == phase and self.phase_history:
            transition = self.phase_history[-1]
            if note:
                transition.note = note
            if block is not None and transition.started_at_block is None:
                transition.started_at_block = block
                transition.started_at_epoch = self.block_to_epoch(block)
            return transition

        transition = PhaseTransition(
            phase=phase,
            started_at_block=block,
            started_at_epoch=self.block_to_epoch(block) if block is not None else None,
            note=note,
        )
        self.current_phase = phase
        self.phase_history.append(transition)
        self._log_phase_transition(transition)
        return transition

    def current_phase_state(self) -> PhaseTransition:
        if self.phase_history:
            return self.phase_history[-1]
        return PhaseTransition(phase=self.current_phase)

    def log_phase_history(self) -> None:
        if not self.phase_history:
            return

        lines = []
        for item in self.phase_history:
            block_info = f"block={item.started_at_block}" if item.started_at_block is not None else ""
            note_info = f"note={item.note}" if item.note else ""
            epoch_info = (
                f"epoch={item.started_at_epoch:.2f}"
                if item.started_at_epoch is not None
                else ""
            )
            parts = [part for part in (block_info, epoch_info, note_info) if part]
            suffix = " | ".join(parts)
            lines.append(f"{item.phase.value}: {suffix}" if suffix else item.phase.value)

        ColoredLogger.info("Round phase timeline ➜ " + " → ".join(lines), ColoredLogger.ORANGE)

    def get_status(self, current_block: Optional[int] = None) -> RoundStatus:
        boundaries: Dict[str, Any] = {}
        if self.start_block is not None:
            boundaries = self.get_round_boundaries(self.start_block, log_debug=False)

        target_block = boundaries.get("target_block")
        blocks_remaining: Optional[int] = None
        minutes_remaining: Optional[float] = None
        if current_block is not None and target_block is not None:
            blocks_remaining = max(target_block - current_block, 0)
            minutes_remaining = (blocks_remaining * self.SECONDS_PER_BLOCK) / 60

        transition = self.current_phase_state()
        return RoundStatus(
            phase=self.current_phase,
            round_start_block=self.start_block,
            target_block=target_block,
            current_block=current_block,
            blocks_remaining=blocks_remaining,
            minutes_remaining=minutes_remaining,
            note=transition.note,
        )

    def reset_phase_tracking(self) -> None:
        self.current_phase = RoundPhase.IDLE
        self.phase_history = []

    def _log_phase_transition(self, transition: PhaseTransition) -> None:
        color_map = {
            RoundPhase.PREPARING: ColoredLogger.CYAN,
            RoundPhase.HANDSHAKE: ColoredLogger.MAGENTA,
            RoundPhase.TASK_EXECUTION: ColoredLogger.BLUE,
            RoundPhase.CONSENSUS: ColoredLogger.PURPLE,
            RoundPhase.WAITING: ColoredLogger.GRAY,
            RoundPhase.FINALIZING: ColoredLogger.GOLD,
            RoundPhase.COMPLETE: ColoredLogger.GREEN,
            RoundPhase.ERROR: ColoredLogger.RED,
        }
        color = color_map.get(transition.phase, ColoredLogger.WHITE)

        message = f"🧭 Phase → {transition.phase.value}"
        if transition.started_at_block is not None:
            message += f" | block={transition.started_at_block}"
        if transition.started_at_epoch is not None:
            message += f" | epoch={transition.started_at_epoch:.2f}"
        if transition.note:
            message += f" | {transition.note}"

        ColoredLogger.info(message, color)
