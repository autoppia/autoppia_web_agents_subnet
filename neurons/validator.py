from __future__ import annotations

import time
from typing import Dict

import bittensor as bt
import numpy as np
from loguru import logger

from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.base.validator import BaseValidatorNeuron
from autoppia_web_agents_subnet.bittensor_config import config
from autoppia_web_agents_subnet.validator.config import (
    ROUND_SIZE_EPOCHS,
    MINIMUM_START_BLOCK,
    SCREENING_START_FRACTION,
    SCREENING_STOP_FRACTION,
    FINAL_START_FRACTION,
    FINAL_STOP_FRACTION,
)
from autoppia_web_agents_subnet.protocol import StartRoundSynapse
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.round_manager import RoundManager, RoundPhase
from autoppia_web_agents_subnet.validator.dataset import RoundDatasetCollector

from autoppia_web_agents_subnet.platform.validator_mixin import ValidatorPlatformMixin
from autoppia_web_agents_subnet.validator.round_start.mixin import ValidatorRoundStartMixin

from autoppia_iwa.src.bootstrap import AppBootstrap


class Validator(
    ValidatorRoundStartMixin,
    BaseValidatorNeuron,
):
    def __init__(self, config=None):
        super().__init__(config=config)

        # Configure IWA (loguru) logging level based on CLI flag
        try:
            iwa_debug = False
            if (
                hasattr(self.config, "iwa")
                and hasattr(self.config.iwa, "logging")
                and hasattr(self.config.iwa.logging, "debug")
            ):
                iwa_debug = bool(self.config.iwa.logging.debug)
            AppBootstrap(debug=iwa_debug)
        except Exception:
            pass

        self.version: str = __version__
        
        # Active miners and final top K UIDs
        self.active_miner_uids: list[int] = []
        self.final_top_k_uids: list[int] = [] 
        self.final_endpoints: list[str] = []
        
        # Burn-on-round-1 guard to avoid repeated chain sets
        self._burn_applied: bool = False

        # Dataset collector for consensus
        self.dataset_collector: RoundDatasetCollector | None = None

        # ⭐ Round system components
        self.round_manager = RoundManager(
            round_size_epochs=ROUND_SIZE_EPOCHS,
            minimum_start_block=MINIMUM_START_BLOCK,
            screening_stop_fraction=SCREENING_STOP_FRACTION,
            final_start_fraction=FINAL_START_FRACTION,
            final_stop_fraction=FINAL_STOP_FRACTION,
        )

        bt.logging.info("load_state()")
        self.load_state()

    async def forward(self) -> None:
        """
        Forward pass for the validator.
        """
        bt.logging.info(f"🚀 Starting round-based forward (epochs per round: {ROUND_SIZE_EPOCHS:.1f})")
        if await self._wait_for_minimum_start_block():
            return

        start_result = await self._start_round()

        try:
            self._log_phase_plan()
        except Exception as exc:
            bt.logging.debug(f"Phase plan logging failed: {exc}")

        if start_result.starting_phase == RoundPhase.SCREENING:
            await self._run_screening_phase()
            await self._run_final_phase()
        elif start_result.starting_phase == RoundPhase.FINAL:
            await self._run_final_phase()
        else:
            return

    def _log_phase_plan(self) -> None:
        """
        Print a concise Phase Plan:
          Phase name — fraction — target block — ETA minutes
        """
        current_block = self.block
        bounds = self.round_manager.get_round_boundaries(current_block)
        start_block = int(bounds["round_start_block"])
        target_block = int(bounds["round_target_block"])
        total_blocks = max(target_block - start_block, 1)
        spb = self.round_manager.SECONDS_PER_BLOCK

        def _line(name: str, frac: float) -> str:
            frac = max(0.0, min(1.0, float(frac)))
            blk = start_block + int(total_blocks * frac)
            remain_blocks = max(blk - current_block, 0)
            eta_min = (remain_blocks * spb) / 60.0
            return f"• {name}: {frac:.0%} — block {blk} — ~{eta_min:.1f}m"

        bt.logging.info("Phase Plan (targets)")
        try:
            now_frac = min(max((current_block - start_block) / total_blocks, 0.0), 1.0)
            end_eta_min = max((target_block - current_block), 0) * spb / 60.0
            bt.logging.info(f"• Now: {now_frac:.0%} — block {current_block} — ~{end_eta_min:.1f}m to end")
        except Exception:
            pass
        bt.logging.info(_line("Round start", 0.0))
        bt.logging.info(_line("Screening start", SCREENING_START_FRACTION))
        bt.logging.info(_line("Screening end", SCREENING_STOP_FRACTION))
        bt.logging.info(_line("Final start", FINAL_START_FRACTION))
        bt.logging.info(_line("Final end", FINAL_STOP_FRACTION))
        bt.logging.info(_line("Round end", 1.0))


if __name__ == "__main__":
    AppBootstrap()
    logger.remove()
    logger.add("logfile.log", level="INFO")
    logger.add(lambda msg: print(msg, end=""), level="WARNING")

    with Validator(config=config(role="validator")) as validator:
        while True:
            bt.logging.debug(f"Heartbeat — validator running... {time.time()}")
            time.sleep(120)
