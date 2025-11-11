from __future__ import annotations

import bittensor as bt

from autoppia_web_agents_subnet.utils.log_colors import consensus_tag
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.config import (
    ENABLE_DISTRIBUTED_CONSENSUS,
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION,
    SAFETY_BUFFER_EPOCHS,
    STOP_TASK_EVALUATION_AT_ROUND_FRACTION,
    SCREENING_PRE_GENERATED_TASKS,
)
from autoppia_web_agents_subnet.validator.dataset import RoundDatasetCollector
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.evaluation.types import EvaluationPhaseResult
from autoppia_web_agents_subnet.validator.evaluation.tasks import generate_tasks

from autoppia_web_agents_subnet.validator.screening.handshake import _run_screening_handshake_phase
from autoppia_web_agents_subnet.validator.screening.execute import _execute_single_screening_task


class ValidatorFinalMixin:
    """Handles final phase of the validator round."""

    async def _run_final_phase(self) -> None:
        current_block = self.block
        self.round_manager.enter_phase(
            RoundPhase.FINAL,
            block=current_block,
            note="Starting final phase",
        )
        ColoredLogger.info("🔄 Starting final phase", ColoredLogger.MAGENTA)

        all_tasks = await generate_tasks(SCREENING_PRE_GENERATED_TASKS)
        await _run_screening_handshake_phase(self, total_prompts=len(all_tasks))

        task_index = 0
        tasks_completed = 0

        if not isinstance(getattr(self, "dataset_collector", None), RoundDatasetCollector):
            try:
                self.dataset_collector = RoundDatasetCollector()
            except Exception:
                self.dataset_collector = None

        while task_index < len(all_tasks):
            current_block = self.block
            current_epoch = self.round_manager.block_to_epoch(current_block)
            boundaries = self.round_manager.get_current_boundaries()
            wait_info = self.round_manager.get_wait_info(current_block)

            ColoredLogger.info(
                (
                    f"📍 Task {task_index + 1}/{len(all_tasks)} | epoch {current_epoch:.2f}/"
                    f"{boundaries['target_epoch']} | remaining {wait_info['minutes_remaining']:.1f}m"
                ),
                ColoredLogger.CYAN,
            )

            tasks_by_id = self.current_round_tasks or {}
            target_task_id = next(
                (
                    task_id
                    for task_id, payload in tasks_by_id.items()
                    if getattr(payload, "sequence", None) == task_index
                ),
                getattr(all_tasks[task_index].task, "id", None),
            )

            if target_task_id and self.active_miner_uids and self._completed_pairs:
                all_done = all(
                    (uid, target_task_id) in self._completed_pairs for uid in self.active_miner_uids
                )
                if all_done:
                    ColoredLogger.info(
                        f"⏭️ Skipping task {task_index + 1}: already completed by all active miners",
                        ColoredLogger.YELLOW,
                    )
                    tasks_completed += 1
                    task_index += 1
                    continue

            task_sent = await _execute_single_screening_task(self, all_tasks[task_index], task_index)
            if task_sent:
                tasks_completed += 1
            task_index += 1

            self.state_manager.save_checkpoint()

            current_block = self.block
            boundaries_now = self.round_manager.get_round_boundaries(current_block, log_debug=False)
            rsb = boundaries_now["round_start_block"]
            tb = boundaries_now["target_block"]
            bt_total = max(tb - rsb, 1)
            bt_done = max(current_block - rsb, 0)
            progress_frac = min(max(bt_done / bt_total, 0.0), 1.0)

            if (
                not self._finalized_this_round
                and progress_frac >= float(FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION)
            ):
                ColoredLogger.info(
                    f"⏳ Finalizing early at {FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION:.0%} to avoid boundary issues",
                    ColoredLogger.PURPLE,
                )
                self.round_manager.enter_phase(
                    RoundPhase.FINALIZING,
                    block=current_block,
                    note="Early finalize window reached",
                )
                await self._calculate_final_weights(tasks_completed)
                self._finalized_this_round = True
                break

            if (
                ENABLE_DISTRIBUTED_CONSENSUS
                and (not self._finalized_this_round)
                and (not self._consensus_published)
                and (progress_frac >= float(STOP_TASK_EVALUATION_AT_ROUND_FRACTION))
            ):
                ColoredLogger.error("\n" + "=" * 80, ColoredLogger.RED)
                ColoredLogger.error(
                    f"🛑🛑🛑 STOP FRACTION REACHED: {STOP_TASK_EVALUATION_AT_ROUND_FRACTION:.0%} 🛑🛑🛑",
                    ColoredLogger.RED,
                )
                ColoredLogger.error(
                    f"📤📤📤 PUBLISHING TO IPFS NOW WITH {tasks_completed} TASKS 📤📤📤",
                    ColoredLogger.RED,
                )
                ColoredLogger.error("⏸️⏸️⏸️  HALTING ALL TASK EXECUTION ⏸️⏸️⏸️", ColoredLogger.RED)
                ColoredLogger.error("=" * 80 + "\n", ColoredLogger.RED)
                bt.logging.info("=" * 80)
                bt.logging.info(consensus_tag(f"🛑 STOP EVAL @ {STOP_TASK_EVALUATION_AT_ROUND_FRACTION:.0%}"))
                bt.logging.info(consensus_tag(f"Progress: {progress_frac:.2f}"))
                bt.logging.info(consensus_tag(f"Current Block: {current_block:,}"))
                bt.logging.info(consensus_tag(f"Blocks Done/Total: {bt_done}/{bt_total}"))
                bt.logging.info(consensus_tag(f"Tasks Completed: {tasks_completed}"))
                bt.logging.info(consensus_tag("Publishing to IPFS now..."))
                bt.logging.info("=" * 80)
                await self._publish_final_snapshot(
                    tasks_completed=tasks_completed,
                    total_tasks=len(all_tasks),
                )
                break

            if not self.round_manager.should_send_next_task(current_block):
                self.round_manager.enter_phase(
                    RoundPhase.WAITING,
                    block=current_block,
                    note="Safety buffer reached; pausing task dispatch",
                )
                ColoredLogger.warning(
                    "🛑 Stopping task execution: safety buffer reached",
                    ColoredLogger.YELLOW,
                )
                ColoredLogger.info(
                    (
                        f"   epoch={current_epoch:.2f}, remaining={wait_info['seconds_remaining']:.0f}s, "
                        f"buffer={SAFETY_BUFFER_EPOCHS} epochs, tasks={tasks_completed}/{len(all_tasks)}"
                    ),
                    ColoredLogger.YELLOW,
                )
                bounds_ctx = self.round_manager.get_round_boundaries(current_block, log_debug=False)
                target_epoch_ctx = bounds_ctx["target_epoch"]
                target_block_ctx = bounds_ctx["target_block"]
                round_no_ctx = await self.round_manager.calculate_round(current_block)
                ColoredLogger.info(
                    (
                        "   Waiting for end-of-round target epoch to set weights | "
                        f"round={round_no_ctx} | target_epoch={target_epoch_ctx:.2f} | target_block={target_block_ctx}"
                    ),
                    ColoredLogger.YELLOW,
                )
                self.state_manager.save_checkpoint()
                if ENABLE_DISTRIBUTED_CONSENSUS and (not self._consensus_published) and (not self._finalized_this_round):
                    bt.logging.info(
                        f"[CONSENSUS] Safety buffer reached - publishing to IPFS with {tasks_completed} tasks"
                    )
                    await self._publish_final_snapshot(
                        tasks_completed=tasks_completed,
                        total_tasks=len(all_tasks),
                    )
                    self.state_manager.save_checkpoint()
                if not self._finalized_this_round:
                    bt.logging.info("[CONSENSUS] Finalizing immediately after safety-buffer publish")
                    await self._calculate_final_weights(tasks_completed)
                    self._finalized_this_round = True
                break

        if (
            ENABLE_DISTRIBUTED_CONSENSUS
            and (not self._consensus_published)
            and (not self._finalized_this_round)
        ):
            await self._publish_final_snapshot(
                tasks_completed=tasks_completed,
                total_tasks=len(all_tasks),
            )

        return EvaluationPhaseResult(
            tasks_completed=tasks_completed,
            finished_early=bool(self._finalized_this_round),
        )    

