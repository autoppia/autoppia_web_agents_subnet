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
from autoppia_web_agents_subnet.validator.start import StartPhaseMixin
from autoppia_web_agents_subnet.validator.evaluation import EvaluationPhaseMixin
from autoppia_web_agents_subnet.validator.settlement import SettlementMixin


class Validator(
    RoundStateValidatorMixin,
    RoundPhaseValidatorMixin,
    StartPhaseMixin,
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

        current_round_number: int | None = None
        try:
            current_round_number = await self.round_manager.calculate_round(current_block)
            if current_round_number is not None:
                setattr(self, "_current_round_number", int(current_round_number))
        except Exception as exc:
            bt.logging.debug(f"Unable to calculate current round number: {exc}")
            current_round_number = None

        if current_round_number is not None:
            bt.logging.info(f"🚀 Starting round-based forward (round {current_round_number})")
            ColoredLogger.info(f"🚦 Starting Round: {int(current_round_number)}", ColoredLogger.GREEN)
        else:
            bt.logging.info("🚀 Starting round-based forward")

        if not self.round_manager.can_start_round(current_block):
            blocks_remaining = self.round_manager.blocks_until_allowed(current_block)
            seconds_remaining = blocks_remaining * self.round_manager.SECONDS_PER_BLOCK
            minutes_remaining = seconds_remaining / 60
            hours_remaining = minutes_remaining / 60

            current_epoch = current_block / 360
            target_epoch = DZ_STARTING_BLOCK / 360

            eta = f"~{hours_remaining:.1f}h" if hours_remaining >= 1 else f"~{minutes_remaining:.0f}m"
            bt.logging.warning(
                f"🔒 Locked until block {DZ_STARTING_BLOCK:,} (epoch {target_epoch:.2f}) | "
                f"now {current_block:,} (epoch {current_epoch:.2f}) | ETA {eta}"
            )

            wait_seconds = min(max(seconds_remaining, 30), 600)
            self.round_manager.enter_phase(
                RoundPhase.WAITING,
                block=current_block,
                note=f"Waiting for minimum start block {DZ_STARTING_BLOCK}",
            )
            bt.logging.warning(f"💤 Rechecking in {wait_seconds:.0f}s...")

            await asyncio.sleep(wait_seconds)
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
    try:
        from autoppia_iwa.src.bootstrap import AppBootstrap
    except ImportError as exc:  # pragma: no cover - bootstrap only in runtime
        bt.logging.warning("autoppia_iwa bootstrap import failed; validator will exit")
        raise exc

    AppBootstrap()
    logger.remove()
    logger.add("logfile.log", level="INFO")
    logger.add(lambda msg: print(msg, end=""), level="WARNING")

    with Validator(config=config(role="validator")) as validator:
        while True:
            bt.logging.debug(f"Heartbeat — validator running... {time.time()}")
            time.sleep(120)
