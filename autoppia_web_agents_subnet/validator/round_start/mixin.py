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
        wait_info = self.round_manager.get_wait_info(current_block)

        if current_fraction < SCREENING_START_UNTIL_FRACTION:
            starting_phase = RoundPhase.SCREENING
        elif current_fraction < FINAL_START_UNTIL_FRACTION:
            starting_phase = RoundPhase.FINAL
            if wait_info['minutes_to_final'] > 0:
                ColoredLogger.info(
                    f"   Waiting ~{wait_info['minutes_to_final']:.1f}m to final phase...",
                    ColoredLogger.YELLOW,
                )
                self.round_manager.enter_phase(
                    RoundPhase.WAITING,
                    block=current_block,
                    note="Late round start detected; deferring to final phase",
                )
                await self._wait_until_final_phase()
        else:
            starting_phase = RoundPhase.COMPLETE
            if wait_info['minutes_to_target'] > 0:
                ColoredLogger.info(
                    f"   Waiting ~{wait_info['minutes_to_target']:.1f}m to next boundary...",
                    ColoredLogger.YELLOW,
                )
                self.round_manager.enter_phase(
                    RoundPhase.WAITING,
                    block=current_block,
                    note="Late start detected; deferring to next boundary",
                )
                await self._wait_until_next_round_boundary()

        if starting_phase != RoundPhase.COMPLETE:
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


