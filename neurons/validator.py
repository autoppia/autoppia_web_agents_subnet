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
    AVG_TASK_DURATION_SECONDS,
    SAFETY_BUFFER_EPOCHS,
    VALIDATOR_NAME,
    VALIDATOR_IMAGE,
    DZ_STARTING_BLOCK,
    SCREENING_STOP_FRACTION,
    STOP_TASK_EVALUATION_AT_ROUND_FRACTION,
)
from autoppia_web_agents_subnet.protocol import StartRoundSynapse
from autoppia_web_agents_subnet.validator.round_manager import RoundManager, RoundPhase
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.platform.validator_mixin import ValidatorPlatformMixin
from autoppia_web_agents_subnet.validator.round_state import (
    RoundStateValidatorMixin,
    RoundPhaseValidatorMixin,
)
from autoppia_web_agents_subnet.validator.round_start import RoundStartMixin
from autoppia_web_agents_subnet.validator.evaluation import EvaluationPhaseMixin
from autoppia_web_agents_subnet.validator.settlement import SettlementMixin
from autoppia_web_agents_subnet.validator.phases.screening import ScreeningPhase
from autoppia_web_agents_subnet.validator.phases.final import FinalPhase
from autoppia_web_agents_subnet.validator.consensus_manager import ConsensusManager
from autoppia_web_agents_subnet.validator.dataset import RoundDatasetCollector
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
            bt.logging.error(
                "VALIDATOR_NAME and VALIDATOR_IMAGE must be set in the environment before starting the validator."
            )
            raise SystemExit(1)

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

        # Two-phase evaluation state / topK helpers
        self._final_started: bool = False
        self._final_top_s_uids: list[int] = []
        self._final_endpoints: dict[int, str] = {}
        self._last_round_winner_uid: int | None = None
        self._screening_phase = ScreeningPhase()
        self._final_phase = FinalPhase()
        self._consensus = ConsensusManager()
        self.dataset_collector: RoundDatasetCollector | None = None

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
        # Sanity: ensure screening < stop fraction
        try:
            if float(SCREENING_STOP_FRACTION) >= float(STOP_TASK_EVALUATION_AT_ROUND_FRACTION):
                import sys

                bt.logging.error("Invalid validator configuration detected. Aborting startup.")
                bt.logging.error(
                    (
                        "SCREENING_STOP_FRACTION (currently {scr:.3f}) must be STRICTLY LESS than "
                        "STOP_TASK_EVALUATION_AT_ROUND_FRACTION (currently {stp:.3f})."
                    ).format(scr=float(SCREENING_STOP_FRACTION), stp=float(STOP_TASK_EVALUATION_AT_ROUND_FRACTION))
                )
                bt.logging.error(
                    (
                        "Fix: adjust environment variables so screening ends earlier than the stop window."
                    )
                )
                sys.exit(1)
        except Exception:
            pass

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
        try:
            self._log_phase_plan(current_block)
        except Exception as exc:
            bt.logging.debug(f"Phase plan logging failed: {exc}")

        start_result = await self._run_start_phase(current_block)
        if not start_result.continue_forward:
            return

        all_tasks = start_result.all_tasks
        task_result = await self._run_task_phase(all_tasks)

        await self._run_settlement_phase(
            tasks_completed=task_result.tasks_completed,
            total_tasks=len(all_tasks),
        )

    def _log_phase_plan(self, current_block: int) -> None:
        """
        Print a concise Phase Plan:
          Phase name — fraction — target block — ETA minutes
        """
        bounds = self.round_manager.get_round_boundaries(current_block, log_debug=False)
        start_block = int(bounds["round_start_block"])
        target_block = int(bounds["target_block"])
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
        bt.logging.info(_line("Screening end", SCREENING_STOP_FRACTION))
        bt.logging.info(_line("Stop tasks eval", STOP_TASK_EVALUATION_AT_ROUND_FRACTION))
        bt.logging.info(_line("Final fetch", FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION))
        bt.logging.info(_line("Round end", 1.0))

    def _deploy_local_for_miner(self, *, uid: int, github_url: str | None) -> str:
        """
        Placeholder for optional local deployment resolver.
        Override to integrate custom HTTP endpoint provisioning.
        """
        _ = (uid, github_url)
        return ""


if __name__ == "__main__":
    AppBootstrap()
    logger.remove()
    logger.add("logfile.log", level="INFO")
    logger.add(lambda msg: print(msg, end=""), level="WARNING")

    with Validator(config=config(role="validator")) as validator:
        while True:
            bt.logging.debug(f"Heartbeat — validator running... {time.time()}")
            time.sleep(120)
