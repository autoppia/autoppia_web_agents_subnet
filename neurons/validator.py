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

        # 1) Handshake & agent discovery
        await self._perform_handshake()
        
        # Initialize IWAP round after handshake (we now know how many miners participate)
        current_block = self.block
        season_tasks = await self.round_manager.get_round_tasks(current_block, self.season_manager)
        n_tasks = len(season_tasks)
        await self._iwap_start_round(current_block=current_block, n_tasks=n_tasks)
        
        # Register miners in IWAP (creates validator_round_miners records)
        await self._iwap_register_miners()

        # 2) Evaluation phase
        agents_evaluated = await self._run_evaluation_phase()

        # 3) Settlement / weight update
        await self._run_settlement_phase(agents_evaluated=agents_evaluated)


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
