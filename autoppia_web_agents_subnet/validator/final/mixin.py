from __future__ import annotations

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.config import (
    ENABLE_DISTRIBUTED_CONSENSUS,
    FINAL_STOP_FRACTION,
    FINAL_PRE_GENERATED_TASKS,
)
from autoppia_web_agents_subnet.validator.dataset import RoundDatasetCollector
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.evaluation.tasks import generate_tasks

from autoppia_web_agents_subnet.validator.final.execute import _execute_single_final_task
from autoppia_web_agents_subnet.validator.final.opensource import deploy_all_agents

class ValidatorFinalMixin:
    """Handles task dispatch, evaluation, and mid-round consensus triggers."""

    async def _run_final_phase(self) -> None:
        self.round_manager.enter_phase(
            RoundPhase.SCREENING_CONSENSUS,
            block=self.block,
            note="Starting screening consensus phase",
        )
        await self._aggregate_screening_scores()
        await self._select_final_top_k_uids()
        github_urls = {
            uid: getattr(self.handshake_payloads[uid], "github_url", None) 
            for uid in self.final_top_k_uids 
            if uid in self.handshake_payloads 
            and getattr(self.handshake_payloads[uid], "github_url", None) is not None
        }
        self.final_endpoints = await deploy_all_agents(github_urls)

        all_tasks = await generate_tasks(FINAL_PRE_GENERATED_TASKS)
        self.final_tasks = all_tasks

        current_block = self.block
        self.round_manager.enter_phase(
            RoundPhase.FINAL_TASK_EXECUTION,
            block=current_block,
            note="Starting final task execution phase",
        )
        ColoredLogger.info("🔄 Starting final task execution phase", ColoredLogger.MAGENTA)

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
                    f"📍 Final Task {task_index + 1}/{len(all_tasks)} | block {current_block}/"
                    f"{boundaries['round_target_block']} | remaining {wait_info['minutes_to_target']:.1f}m"
                ),
                ColoredLogger.CYAN,
            )

            task_sent = await _execute_single_final_task(self, task, task_index)
            if task_sent:
                tasks_completed += 1

            if not self.round_manager.should_send_next_task(self.block):
                ColoredLogger.error("\n" + "=" * 80, ColoredLogger.RED)
                ColoredLogger.error(
                    f"🛑🛑🛑 FINAL STOP FRACTION REACHED: {FINAL_STOP_FRACTION:.0%} 🛑🛑🛑",
                    ColoredLogger.RED,
                )
                ColoredLogger.error("⏸️⏸️⏸️  HALTING ALL TASK EXECUTION ⏸️⏸️⏸️", ColoredLogger.RED)

                if ENABLE_DISTRIBUTED_CONSENSUS:
                    await self._publish_final_snapshot(
                        tasks_completed=tasks_completed,
                    )

                ColoredLogger.error("=" * 80 + "\n", ColoredLogger.RED)
                break
        
        self._wait_until_specific_block(
            target_block=self.round_manager.settlement_block,
            target_discription="settlement block",
        )

