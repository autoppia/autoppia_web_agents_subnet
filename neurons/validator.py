from __future__ import annotations

import time
import queue
import bittensor as bt
from loguru import logger

from autoppia_web_agents_subnet import __version__

from autoppia_web_agents_subnet.base.validator import BaseValidatorNeuron
from autoppia_web_agents_subnet.bittensor_config import config
from autoppia_web_agents_subnet.validator.config import (
    ROUND_SIZE_EPOCHS,
    SETTLEMENT_FRACTION,
)
from autoppia_web_agents_subnet.validator.round_manager import RoundManager
from autoppia_web_agents_subnet.validator.season_manager import SeasonManager
from autoppia_web_agents_subnet.validator.round_start.mixin import ValidatorRoundStartMixin
from autoppia_web_agents_subnet.validator.round_start.types import StartRoundResult
from autoppia_web_agents_subnet.validator.evaluation.mixin import ValidatorEvaluationMixin
from autoppia_web_agents_subnet.validator.settlement.mixin import ValidatorSettlementMixin
from autoppia_web_agents_subnet.platform.validator_mixin import ValidatorPlatformMixin

from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import SandboxManager
from autoppia_web_agents_subnet.validator.models import AgentInfo


class Validator(
    ValidatorRoundStartMixin,
    ValidatorEvaluationMixin,
    ValidatorSettlementMixin,
    ValidatorPlatformMixin,
    BaseValidatorNeuron,
):
    def __init__(self, config=None):
        super().__init__(config=config)

        self.version: str = __version__

        self.agents_queue: queue.Queue[AgentInfo] = queue.Queue()
        self.agents_dict: dict[int, AgentInfo] = {}
        self.agents_on_first_handshake: list[int] = []
        self.should_update_weights: bool = False

        try:
            self.sandbox_manager = SandboxManager()
            self.sandbox_manager.deploy_gateway()
        except Exception as e:
            import sys            
            bt.logging.warning(f"Sandbox manager failed to initialize: {e}")
            sys.exit(1)

        # Season manager for task generation
        self.season_manager = SeasonManager()

        # Round manager for round timing and boundaries
        self.round_manager = RoundManager()

        bt.logging.info("load_state()")
        self.load_state()

    async def forward(self) -> None:
        """
        Forward pass for the validator.
        """
        if await self._wait_for_minimum_start_block():
            return
        
        bt.logging.info(f"🚀 Starting round-based forward (epochs per round: {ROUND_SIZE_EPOCHS:.1f})")
        start_result: StartRoundResult = await self._start_round()

        if not start_result.continue_forward:
            bt.logging.info(f"Round start skipped ({start_result.reason}); waiting for next boundary")
            await self._wait_until_specific_block(
                target_block=self.round_manager.target_block,
                target_description="round boundary block",
            )
            return

        try:
            self._log_phase_plan()
        except Exception as exc:
            bt.logging.debug(f"Phase plan logging failed: {exc}")

        # 1) Handshake & agent discovery
        await self._perform_handshake()

        # 2) Evaluation phase
        agents_evaluated = await self._run_evaluation_phase()

        # 3) Settlement / weight update
        await self._run_settlement_phase(agents_evaluated=agents_evaluated)

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
        bt.logging.info(_line("Settlement", SETTLEMENT_FRACTION))
        bt.logging.info(_line("Round end", 1.0))


if __name__ == "__main__":
    # Initialize IWA with default logging (best-effort)
    AppBootstrap()

    logger.remove()
    logger.add("logfile.log", level="INFO")
    logger.add(lambda msg: print(msg, end=""), level="WARNING")

    with Validator(config=config(role="validator")) as validator:
        while True:
            bt.logging.debug(f"Heartbeat — validator running... {time.time()}")
            time.sleep(120)
