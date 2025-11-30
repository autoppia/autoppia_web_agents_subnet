from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import bittensor as bt

from autoppia_web_agents_subnet.validator.config import DZ_STARTING_BLOCK
from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase


class RoundStateValidatorMixin:
    """Stubbed checkpoint/resume helpers (state persistence disabled)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_resume_info: Dict[str, Any] = {"status": "disabled", "reason": "checkpoint system removed"}

    async def _wait_for_minimum_start_block(self, current_block: int) -> bool:
        """
        Block until the chain height reaches the configured launch gate.

        Returns True when a wait occurred so callers can short-circuit their flow.
        """
        rm = getattr(self, "round_manager", None)
        if rm is None:
            raise RuntimeError("Round manager not initialized; cannot enforce minimum start block")

        if rm.can_start_round(current_block):
            return False

        blocks_remaining = rm.blocks_until_allowed(current_block)
        seconds_remaining = blocks_remaining * rm.SECONDS_PER_BLOCK
        minutes_remaining = seconds_remaining / 60
        hours_remaining = minutes_remaining / 60

        current_epoch = rm.block_to_epoch(current_block)
        target_epoch = rm.block_to_epoch(DZ_STARTING_BLOCK)

        eta = f"~{hours_remaining:.1f}h" if hours_remaining >= 1 else f"~{minutes_remaining:.0f}m"
        bt.logging.warning(
            f"🔒 Locked until block {DZ_STARTING_BLOCK:,} (epoch {target_epoch:.2f}) | "
            f"now {current_block:,} (epoch {current_epoch:.2f}) | ETA {eta}"
        )

        wait_seconds = min(max(seconds_remaining, 30), 600)
        rm.enter_phase(
            RoundPhase.WAITING,
            block=current_block,
            note=f"Waiting for minimum start block {DZ_STARTING_BLOCK}",
        )
        bt.logging.warning(f"💤 Rechecking in {wait_seconds:.0f}s...")

        await asyncio.sleep(wait_seconds)
        return True

    def _save_round_state(self, *, tasks: Optional[List[TaskWithProject]] = None) -> None:
        bt.logging.debug("Checkpoint save skipped: state persistence removed")

    def _load_round_state(self, *, current_block: Optional[int] = None) -> Optional[Dict[str, Any]]:
        self._last_resume_info = {"status": "disabled", "reason": "checkpoint system removed"}
        return None

    def _remove_round_state(self) -> None:
        bt.logging.debug("Checkpoint cleanup skipped: state persistence removed")


class RoundPhaseValidatorMixin:
    """Stub mixin (checkpoint resume removed)."""

    def _rebuild_from_saved_evaluations(self) -> None:
        bt.logging.debug("Rebuild from saved evaluations skipped: state persistence removed")
