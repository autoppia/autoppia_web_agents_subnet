from __future__ import annotations

from typing import List
from urllib.parse import parse_qs, urlparse

import bittensor as bt
from rich import box
from rich.console import Console
from rich.table import Table

from autoppia_web_agents_subnet.protocol import TaskSynapse
from autoppia_web_agents_subnet.utils.log_colors import consensus_tag
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.config import (
    ENABLE_DISTRIBUTED_CONSENSUS,
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION,
    SAFETY_BUFFER_EPOCHS,
    STOP_TASK_EVALUATION_AT_ROUND_FRACTION,
    TIME_WEIGHT,
    EVAL_SCORE_WEIGHT,
)
from autoppia_web_agents_subnet.validator.dataset import RoundDatasetCollector
from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.evaluation.types import EvaluationPhaseResult
from autoppia_web_agents_subnet.validator.evaluation.eval import evaluate_task_solutions
from autoppia_web_agents_subnet.validator.evaluation.rewards import calculate_rewards_for_task
from autoppia_web_agents_subnet.validator.evaluation.synapse_handlers import (
    send_feedback_synapse_to_miners,
    send_task_synapse_to_miners,
)
from autoppia_web_agents_subnet.validator.evaluation.tasks import (
    collect_task_solutions_and_execution_times,
)


class EvaluationPhaseMixin:
    """Handles task dispatch, evaluation, and mid-round consensus triggers."""

    async def _run_task_phase(self, all_tasks: List[TaskWithProject]) -> EvaluationPhaseResult:
        self.round_manager.enter_phase(
            RoundPhase.TASK_EXECUTION,
            block=self.block,
            note=f"{len(all_tasks)} tasks scheduled",
        )
        ColoredLogger.info("🔄 Starting dynamic task execution", ColoredLogger.MAGENTA)

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

            task_sent = await self._send_task_and_evaluate(all_tasks[task_index], task_index)
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

    async def _send_task_and_evaluate(
        self,
        task_item: TaskWithProject,
        task_index: int,
    ) -> bool:
        project = task_item.project
        task = task_item.task
        collector = None
        try:
            if isinstance(getattr(self, "dataset_collector", None), RoundDatasetCollector):
                collector = self.dataset_collector
                collector.add_task(project=project, task=task)
        except Exception:
            collector = None

        try:
            if not self.active_miner_uids:
                ColoredLogger.warning(
                    "⚠️ No active miners responded to handshake; skipping task send.",
                    ColoredLogger.YELLOW,
                )
                return False

            active_axons = [self.metagraph.axons[uid] for uid in self.active_miner_uids]

            seed: int | None = getattr(task, "_seed_value", None)
            if seed is None and isinstance(getattr(task, "url", None), str):
                try:
                    parsed = urlparse(task.url)
                    query = parse_qs(parsed.query)
                    raw_seed = query.get("seed", [None])[0]
                    seed = int(str(raw_seed)) if raw_seed is not None else None
                except (ValueError, TypeError):
                    seed = None

            web_project_name = getattr(project, "name", None)

            try:
                console = Console()
                task_table = Table(
                    title=f"[bold cyan]📋 Task {task_index + 1}/{len(self.current_round_tasks)}[/bold cyan]",
                    box=box.DOUBLE,
                    show_header=True,
                    header_style="bold yellow",
                    expand=False,
                )
                task_table.add_column("Field", justify="left", style="cyan", width=12)
                task_table.add_column("Value", justify="left", style="white", no_wrap=False)
                task_table.add_row("📦 Project", f"[magenta]{web_project_name}[/magenta]")

                task_url_display = project.frontend_url
                if seed is not None:
                    separator = "&" if "?" in task_url_display else "?"
                    task_url_display = f"{task_url_display}{separator}seed={seed}"
                task_table.add_row("🌐 URL", f"[blue]{task_url_display}[/blue]")
                task_table.add_row("📝 Prompt", f"[white]{task.prompt}[/white]")

                tests_count = len(task.tests) if task.tests else 0
                tests_info = []
                if task.tests:
                    for test_idx, test in enumerate(task.tests, 1):
                        test_lines = [f"[yellow]{test_idx}. {test.type}[/yellow]: {test.description}"]
                        if hasattr(test, "event_name"):
                            test_lines.append(f"   Event: [cyan]{test.event_name}[/cyan]")
                        if hasattr(test, "event_criteria") and test.event_criteria:
                            import json

                            criteria_str = json.dumps(test.event_criteria, indent=2)
                            test_lines.append(f"   Criteria: [dim]{criteria_str}[/dim]")
                        tests_info.append("\n".join(test_lines))
                    tests_str = "\n\n".join(tests_info)
                else:
                    tests_str = "[dim]No tests[/dim]"
                task_table.add_row(f"🧪 Tests ({tests_count})", tests_str)

                console.print()
                console.print(task_table)
                console.print()
            except Exception as exc:
                bt.logging.warning(f"Failed to render task table: {exc}")
                ColoredLogger.debug(
                    f"Task {task_index + 1}: {task.prompt[:100]}...",
                    ColoredLogger.CYAN,
                )

            task_url = project.frontend_url
            if seed is not None:
                separator = "&" if "?" in task_url else "?"
                task_url = f"{task_url}{separator}seed={seed}"

            task_synapse = TaskSynapse(
                version=self.version,
                prompt=task.prompt,
                url=task_url,
                screenshot=None,
                seed=seed,
                web_project_name=web_project_name,
            )

            responses = await send_task_synapse_to_miners(
                validator=self,
                miner_axons=active_axons,
                task_synapse=task_synapse,
                timeout=120,
            )

            task_solutions, execution_times = collect_task_solutions_and_execution_times(
                task=task,
                responses=responses,
                miner_uids=list(self.active_miner_uids),
            )

            ColoredLogger.debug("🔍 STARTING EVALUATION...", ColoredLogger.CYAN)
            eval_scores, test_results_list, evaluation_results = await evaluate_task_solutions(
                web_project=project,
                task=task,
                task_solutions=task_solutions,
                execution_times=execution_times,
            )

            rewards = calculate_rewards_for_task(
                eval_scores=eval_scores,
                execution_times=execution_times,
                n_miners=len(self.active_miner_uids),
                eval_score_weight=EVAL_SCORE_WEIGHT,
                time_weight=TIME_WEIGHT,
            )

            self.round_manager.accumulate_rewards(
                miner_uids=list(self.active_miner_uids),
                rewards=rewards.tolist(),
                eval_scores=eval_scores.tolist(),
                execution_times=execution_times,
            )

            if collector is not None:
                try:
                    collector.add_solutions(
                        task_id=str(getattr(task, "id", "")),
                        task_solutions=task_solutions,
                        eval_scores=eval_scores.tolist(),
                        execution_times=execution_times,
                        miner_uids=list(self.active_miner_uids),
                    )
                except Exception:
                    pass

            for uid, task_id in zip(self.active_miner_uids, [task.id] * len(self.active_miner_uids)):
                self._completed_pairs.add((uid, task_id))

            try:
                await send_feedback_synapse_to_miners(
                    validator=self,
                    miner_axons=active_axons,
                    miner_uids=list(self.active_miner_uids),
                    task=task,
                    rewards=rewards.tolist(),
                    execution_times=execution_times,
                    task_solutions=task_solutions,
                    test_results_list=test_results_list,
                    evaluation_results=evaluation_results,
                    web_project_name=web_project_name or "Unknown",
                )
            except Exception as exc:
                bt.logging.warning(f"Feedback failed: {exc}")

            try:
                await self._iwap_submit_task_results(
                    task_item=task_item,
                    task_solutions=task_solutions,
                    eval_scores=eval_scores,
                    test_results_list=test_results_list,
                    evaluation_results=evaluation_results,
                    execution_times=execution_times,
                    rewards=rewards.tolist(),
                )
            except Exception as exc:
                bt.logging.warning(f"IWAP submission failed: {exc}")

            bt.logging.info(f"✅ Task {task_index + 1} completed")
            return True

        except Exception as exc:
            bt.logging.error(f"Task execution failed: {exc}")
            return False
