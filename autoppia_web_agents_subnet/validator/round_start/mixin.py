from __future__ import annotations

import asyncio
import bittensor as bt

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.utils.log_colors import round_details_tag

from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.round_start.types import RoundStartResult
from autoppia_web_agents_subnet.validator.config import (
    MINIMUM_START_BLOCK,
    SCREENING_START_UNTIL_FRACTION,
    FINAL_START_UNTIL_FRACTION,
)


class ValidatorRoundStartMixin:
    """Round preparation: pre-generate tasks, and perform handshake."""

    async def _start_round(self) -> RoundStartResult:
        current_block = self.block

        self.round_manager.sync_boundaries(current_block)
        current_fraction = float(self.round_manager.fraction_elapsed(current_block))

        if current_fraction < SCREENING_START_UNTIL_FRACTION:
            starting_phase = RoundPhase.SCREENING
        elif current_fraction < FINAL_START_UNTIL_FRACTION:
            starting_phase = RoundPhase.FINAL
            self._wait_until_specific_block(
                target_block=self.round_manager.final_block,
                target_discription="final start block",
            )
        else:
            self._wait_until_specific_block(
                target_block=self.round_manager.target_block,
                target_discription="round boundary block",
            )

        if starting_phase != RoundPhase.COMPLETE:  
            current_block = self.block
            self.round_manager.start_new_round(current_block)

            round_number = self.round_manager.round_number
            start_epoch = self.round_manager.start_epoch
            target_epoch = self.round_manager.target_epoch
            total_blocks = self.round_manager.target_block - current_block

            wait_info = self.round_manager.get_wait_info(current_block)

            bt.logging.info("=" * 100)
            bt.logging.info(round_details_tag("🚀 ROUND START"))
            bt.logging.info(round_details_tag(f"Round Number: {round_number}"))
            bt.logging.info(round_details_tag(f"Round Start Epoch: {start_epoch:.2f}"))
            bt.logging.info(round_details_tag(f"Round Target Epoch: {target_epoch:.2f}"))
            bt.logging.info(round_details_tag(f"Validator Round ID: {self.current_round_id}"))
            bt.logging.info(round_details_tag(f"Current Block: {current_block:,}"))
            bt.logging.info(round_details_tag(f"Starting Phase: {starting_phase.name}"))
            bt.logging.info(round_details_tag(f"Duration: ~{wait_info['minutes_to_target']:.1f} minutes"))
            bt.logging.info(round_details_tag(f"Total Blocks: {total_blocks}"))
            bt.logging.info("=" * 100)

        return RoundStartResult(
            starting_phase=starting_phase,
        ) 

    async def _wait_for_minimum_start_block(self) -> bool:
        """
        Block until the chain height reaches the configured launch gate.

        Returns True when a wait occurred so callers can short-circuit their flow.
        """
        rm = getattr(self, "round_manager", None)
        if rm is None:
            raise RuntimeError("Round manager not initialized; cannot enforce minimum start block")

        current_block = self.block
        if rm.can_start_round(current_block):
            return False
        
        blocks_remaining = rm.blocks_until_allowed(current_block)
        seconds_remaining = blocks_remaining * rm.SECONDS_PER_BLOCK
        minutes_remaining = seconds_remaining / 60
        hours_remaining = minutes_remaining / 60

        current_epoch = rm.block_to_epoch(current_block)
        target_epoch = rm.block_to_epoch(MINIMUM_START_BLOCK)

        eta = f"~{hours_remaining:.1f}h" if hours_remaining >= 1 else f"~{minutes_remaining:.0f}m"
        bt.logging.warning(
            f"🔒 Locked until block {MINIMUM_START_BLOCK:,} (epoch {target_epoch:.2f}) | "
            f"now {current_block:,} (epoch {current_epoch:.2f}) | ETA {eta}"
        )

        wait_seconds = min(max(seconds_remaining, 30), 600)
        rm.enter_phase(
            RoundPhase.WAITING,
            block=current_block,
            note=f"Waiting for minimum start block {MINIMUM_START_BLOCK}",
        )
        bt.logging.warning(f"💤 Rechecking in {wait_seconds:.0f}s...")

        await asyncio.sleep(wait_seconds)
        return True 


