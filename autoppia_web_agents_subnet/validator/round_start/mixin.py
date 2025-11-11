from __future__ import annotations

import bittensor as bt

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.utils.log_colors import round_details_tag

from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.round_start.types import RoundStartResult
from autoppia_web_agents_subnet.validator.config import (
    SCREENING_START_UNTIL_FRACTION,
    FINAL_START_UNTIL_FRACTION,
)


class ValidatorRoundStartMixin:
    """Round preparation: pre-generate tasks, and perform handshake."""

    async def _start_round(self) -> RoundStartResult:
        current_block = self.block

        current_fraction = float(self.round_manager.fraction_elapsed(current_block))
        boundaries = self.round_manager.get_round_boundaries(current_block, log_debug=False)

        if current_fraction < SCREENING_START_UNTIL_FRACTION:
            next_phase = RoundPhase.SCREENING
        elif current_fraction < FINAL_START_UNTIL_FRACTION:
            next_phase = RoundPhase.FINAL
            blocks_to_target = max(boundaries["final_start_block"] - current_block, 0)
            minutes_remaining = (blocks_to_target * self.round_manager.SECONDS_PER_BLOCK) / 60
            ColoredLogger.info(
                f"   Waiting ~{minutes_remaining:.1f}m to final phase...",
                ColoredLogger.YELLOW,
            )
            self.round_manager.enter_phase(
                RoundPhase.WAITING,
                block=current_block,
                note="Late round start detected; deferring to final phase",
            )
            await self._wait_until_final_phase()
        else:
            next_phase = RoundPhase.COMPLETE
            blocks_to_target = max(boundaries["target_block"] - current_block, 0)
            minutes_remaining = (blocks_to_target * self.round_manager.SECONDS_PER_BLOCK) / 60
            ColoredLogger.info(
                f"   Waiting ~{minutes_remaining:.1f}m to next boundary...",
                ColoredLogger.YELLOW,
            )
            self.round_manager.enter_phase(
                RoundPhase.WAITING,
                block=current_block,
                note="Late start detected; deferring to next boundary",
            )
            await self._wait_until_next_round_boundary()

        if next_phase != RoundPhase.COMPLETE:
            self.round_manager.start_new_round(current_block)
            
            round_number = await self.round_manager.calculate_round(current_block)
            start_epoch = boundaries["round_start_epoch"]
            target_epoch = boundaries["target_epoch"]
            total_blocks = boundaries["target_block"] - boundaries["round_start_block"]
            blocks_remaining = boundaries["target_block"] - current_block
            minutes_remaining = (blocks_remaining * self.round_manager.SECONDS_PER_BLOCK) / 60

            bt.logging.info("=" * 100)
            bt.logging.info(round_details_tag("🚀 ROUND START"))
            bt.logging.info(round_details_tag(f"Round Number: {round_number}"))
            bt.logging.info(round_details_tag(f"Validator Round ID: {self.current_round_id}"))
            bt.logging.info(round_details_tag(f"Start Block: {current_block:,}"))
            bt.logging.info(round_details_tag(f"Start Epoch: {start_epoch:.2f}"))
            bt.logging.info(round_details_tag(f"Target Epoch: {target_epoch:.2f}"))
            bt.logging.info(round_details_tag(f"Duration: ~{minutes_remaining:.1f} minutes"))
            bt.logging.info(round_details_tag(f"Total Blocks: {total_blocks}"))
            bt.logging.info("=" * 100)

        return RoundStartResult(
            next_phase=next_phase,
        )  

