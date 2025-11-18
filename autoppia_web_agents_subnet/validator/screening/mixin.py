from __future__ import annotations

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.config import (
    ENABLE_DISTRIBUTED_CONSENSUS,
    SCREENING_STOP_FRACTION,
    SCREENING_PRE_GENERATED_TASKS,
)
from autoppia_web_agents_subnet.validator.dataset import RoundDatasetCollector
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.evaluation.tasks import generate_tasks

from autoppia_web_agents_subnet.validator.screening.handshake import _run_screening_handshake_phase
from autoppia_web_agents_subnet.validator.screening.execute import _execute_single_screening_task


class ValidatorScreeningMixin:
    """Handles task dispatch, evaluation, and mid-round consensus triggers."""

    async def _run_screening_phase(self) -> None:
        current_block = self.block
        self.round_manager.enter_phase(
            RoundPhase.SCREENING_HANDSHAKE,
            block=current_block,
            note="Starting screening handshake phase",
        )
        ColoredLogger.info("🔄 Starting screening handshake phase", ColoredLogger.MAGENTA)

        all_tasks = await generate_tasks(SCREENING_PRE_GENERATED_TASKS)
        self.screening_tasks = all_tasks
        await _run_screening_handshake_phase(self, total_prompts=len(all_tasks))

        current_block = self.block
        self.round_manager.enter_phase(
            RoundPhase.SCREENING_TASK_EXECUTION,
            block=current_block,
            note="Starting screening task execution phase",
        )
        ColoredLogger.info("🔄 Starting screening task execution phase", ColoredLogger.MAGENTA)

        if not isinstance(getattr(self, "dataset_collector", None), RoundDatasetCollector):
            try:
                self.dataset_collector = RoundDatasetCollector()
            except Exception:
                self.dataset_collector = None

        tasks_completed = 0

        for task_index, task in enumerate(all_tasks):
            current_block = self.block
            boundaries = self.round_manager.get_round_boundaries(current_block)
            wait_info = self.round_manager.get_wait_info(current_block)

            ColoredLogger.info(
                (
                    f"📍 Screening Task {task_index + 1}/{len(all_tasks)} | block {current_block}/"
                    f"{boundaries['round_final_block']} | remaining {wait_info['minutes_to_final']:.1f}m"
                ),
                ColoredLogger.CYAN,
            )

            task_sent = await _execute_single_screening_task(self, task, task_index)
            if task_sent:
                tasks_completed += 1

            if not self.round_manager.should_send_next_task(self.block):
                ColoredLogger.error("\n" + "=" * 80, ColoredLogger.RED)
                ColoredLogger.error(
                    f"🛑🛑🛑 SCREENING STOP FRACTION REACHED: {SCREENING_STOP_FRACTION:.0%} 🛑🛑🛑",
                    ColoredLogger.RED,
                )
                ColoredLogger.error("⏸️⏸️⏸️  HALTING ALL TASK EXECUTION ⏸️⏸️⏸️", ColoredLogger.RED)

                if ENABLE_DISTRIBUTED_CONSENSUS:
                    await self._publish_screening_snapshot(
                        tasks_completed=tasks_completed,
                    )

                ColoredLogger.error("=" * 80 + "\n", ColoredLogger.RED)
                break
        
        self._wait_until_specific_block(
            target_block=self.round_manager.final_block,
            target_discription="final start block",
        )
                
