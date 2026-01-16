from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.config import (
    ROUND_SIZE_EPOCHS,
    MINIMUM_START_BLOCK,
    SETTLEMENT_FRACTION,
)


class RoundPhase(Enum):
    """Named phases in the validator round lifecycle."""

    IDLE = "idle"
    START = "start"
    PREPARING = "preparing"
    HANDSHAKE = "handshake"
    EVALUATION = "evaluation"
    CONSENSUS = "consensus"
    FINALIZING = "finalizing"
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
    - Phase tracking for observability
    """

    BLOCKS_PER_EPOCH = 360
    SECONDS_PER_BLOCK = 12

    def __init__(
        self,
        round_size_epochs: float | None = None,
        minimum_start_block: int | None = None,
        settlement_fraction: float | None = None,
        **_: Any,
    ):
        self.round_size_epochs = round_size_epochs or ROUND_SIZE_EPOCHS
        self.minimum_start_block = (
            MINIMUM_START_BLOCK if minimum_start_block is None else int(minimum_start_block)
        )
        self.settlement_fraction = (
            SETTLEMENT_FRACTION if settlement_fraction is None else float(settlement_fraction)
        )

        self.round_block_length = int(self.BLOCKS_PER_EPOCH * max(self.round_size_epochs, 0.01))

        # Round boundaries
        self.round_number: int | None = None

        self.start_block: int | None = None
        self.settlement_block: int | None = None
        self.target_block: int | None = None

        self.start_epoch: float | None = None
        self.settlement_epoch: float | None = None
        self.target_epoch: float | None = None

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
        settlement_block = int(start_block + int(self.round_block_length * self.settlement_fraction))
        target_block = int(start_block + self.round_block_length)

        start_epoch = self.block_to_epoch(start_block)
        settlement_epoch = self.block_to_epoch(settlement_block)
        target_epoch = self.block_to_epoch(target_block)

        self.round_number = round_index + 1
        self.start_block = start_block
        self.settlement_block = settlement_block
        self.target_block = target_block
        self.start_epoch = start_epoch
        self.settlement_epoch = settlement_epoch
        self.target_epoch = target_epoch

    def start_new_round(self, current_block: int):
        if self.round_number is None:
            self.sync_boundaries(current_block)

        self.reset_round()
        self.enter_phase(
            RoundPhase.PREPARING,
            block=current_block,
            note="Starting new round",
        )

    def get_round_boundaries(self, current_block: int, *, log_debug: bool = True) -> Dict[str, Any]:
        if self.round_number is None:
            self.sync_boundaries(current_block)

        return {
            "round_start_block": self.start_block,
            "round_target_block": self.target_block,
            "target_block": self.target_block,  # Alias for compatibility
            "round_start_epoch": self.start_epoch,
            "round_target_epoch": self.target_epoch,
            "fraction_elapsed": self.fraction_elapsed(current_block),
        }

    def get_current_boundaries(self) -> Dict[str, Any]:
        if self.start_block is None:
            raise RuntimeError("Round boundaries not initialized")
        return self.get_round_boundaries(self.start_block, log_debug=False)

    def get_wait_info(self, current_block: int) -> Dict[str, Any]:
        if self.round_number is None:
            self.sync_boundaries(current_block)

        blocks_to_settlement = max(self.settlement_block - current_block, 0)
        minutes_to_settlement = blocks_to_settlement * self.SECONDS_PER_BLOCK / 60
        blocks_to_target = max(self.target_block - current_block, 0)
        minutes_to_target = blocks_to_target * self.SECONDS_PER_BLOCK / 60

        return {
            "blocks_to_settlement": blocks_to_settlement,
            "minutes_to_settlement": minutes_to_settlement,
            "blocks_to_target": blocks_to_target,
            "minutes_to_target": minutes_to_target,
        }

    def fraction_elapsed(self, current_block: int) -> float:
        if self.round_number is None:
            self.sync_boundaries(current_block)
        return float((current_block - self.start_block) / self.round_block_length)

    async def calculate_round(self, current_block: int) -> int:
        self.sync_boundaries(current_block)
        return int(self.round_number or 0)

    def blocks_until_allowed(self, current_block: int) -> int:
        return max(self.minimum_start_block - current_block, 0)

    def can_start_round(self, current_block: int) -> bool:
        return current_block >= self.minimum_start_block

    def reset_round(self) -> None:
        """Reset all per-round statistics/state."""
        # Phase tracking
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

        target_block = boundaries.get("round_target_block")  # Fixed: was "target_block"
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
            RoundPhase.START: ColoredLogger.CYAN,
            RoundPhase.HANDSHAKE: ColoredLogger.MAGENTA,
            RoundPhase.EVALUATION: ColoredLogger.BLUE,
            RoundPhase.CONSENSUS: ColoredLogger.GOLD,
            RoundPhase.WAITING: ColoredLogger.GRAY,
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
