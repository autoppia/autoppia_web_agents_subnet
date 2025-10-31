# autoppia_web_agents_subnet/validator/validator.py
from __future__ import annotations

import asyncio
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
    AVG_TASK_DURATION_SECONDS,
    SAFETY_BUFFER_EPOCHS,
    VALIDATOR_NAME,
    VALIDATOR_IMAGE,
    DZ_STARTING_BLOCK,
)
from autoppia_web_agents_subnet.protocol import StartRoundSynapse
from autoppia_web_agents_subnet.validator.round_manager import RoundManager, RoundPhase
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.platform.mixin import ValidatorPlatformMixin
from autoppia_web_agents_subnet.validator.round_state import (
    RoundStateValidatorMixin,
    RoundPhaseValidatorMixin,
)
from autoppia_web_agents_subnet.validator.round_start import RoundStartMixin
from autoppia_web_agents_subnet.validator.evaluation import EvaluationPhaseMixin
from autoppia_web_agents_subnet.validator.settlement import SettlementMixin
from autoppia_iwa.src.bootstrap import AppBootstrap


class Validator(
    RoundStateValidatorMixin,
    RoundPhaseValidatorMixin,
    RoundStartMixin,
    EvaluationPhaseMixin,
    SettlementMixin,
    ValidatorPlatformMixin,
    BaseValidatorNeuron,
):
    def __init__(self, config=None):
        if not VALIDATOR_NAME or not VALIDATOR_IMAGE:
            bt.logging.error("VALIDATOR_NAME and VALIDATOR_IMAGE must be set in the environment before starting the validator.")
            raise SystemExit(1)

        super().__init__(config=config)

        self.forward_count = 0
        self.last_rewards: np.ndarray | None = None
        self.last_round_responses: Dict[int, StartRoundSynapse] = {}
        self.version: str = __version__

        # Active miners (those who responded to StartRoundSynapse handshake)
        self.active_miner_uids: list[int] = []

        # Burn-on-round-1 guard to avoid repeated chain sets
        self._burn_applied: bool = False
        # Consensus sharing
        self._consensus_published: bool = False
        self._consensus_mid_fetched: bool = False
        self._agg_scores_cache: dict[int, float] | None = None
        # Track if final weights + IWAP finish_round were already sent this round
        self._finalized_this_round: bool = False

        # ⭐ Round system components
        self.round_manager = RoundManager(
            round_size_epochs=ROUND_SIZE_EPOCHS,
            avg_task_duration_seconds=AVG_TASK_DURATION_SECONDS,
            safety_buffer_epochs=SAFETY_BUFFER_EPOCHS,
            minimum_start_block=DZ_STARTING_BLOCK,
        )

        bt.logging.info("load_state()")
        self.load_state()

    async def forward(self) -> None:
        """High-level round orchestration stitched together from phase engines."""
        current_block = self.block
        self.round_manager.enter_phase(
            RoundPhase.PREPARING,
            block=current_block,
            note="Starting forward pass",
        )

        resume_status = getattr(self, "_last_resume_info", {}).get("status")
        stored_round_number = getattr(self, "_current_round_number", None)
        if resume_status == "loaded" and stored_round_number is not None:
            try:
                current_round_number = int(stored_round_number)
            except Exception:
                current_round_number = await self.round_manager.calculate_round(current_block)
        else:
            current_round_number = await self.round_manager.calculate_round(current_block)
            try:
                setattr(self, "_current_round_number", int(current_round_number))
            except Exception:
                pass
        bt.logging.info(f"🚀 Starting round-based forward (round {current_round_number})")
        ColoredLogger.info(f"🚦 Starting Round: {int(current_round_number)}", ColoredLogger.GREEN)

        if await self._wait_for_minimum_start_block(current_block):
            return

        self.round_manager.log_calculation_summary()

        start_result = await self._run_start_phase(current_block)
        if not start_result.continue_forward:
            return

        all_tasks = start_result.all_tasks
        task_result = await self._run_task_phase(all_tasks)

        await self._run_settlement_phase(
            tasks_completed=task_result.tasks_completed,
            total_tasks=len(all_tasks),
        )

    # ═══════════════════════════════════════════════════════════════════════════════
    # TASK EXECUTION HELPERS
    # ═══════════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    AppBootstrap()
    logger.remove()
    logger.add("logfile.log", level="INFO")
    logger.add(lambda msg: print(msg, end=""), level="WARNING")

    with Validator(config=config(role="validator")) as validator:
        while True:
            bt.logging.debug(f"Heartbeat — validator running... {time.time()}")
            time.sleep(120)
