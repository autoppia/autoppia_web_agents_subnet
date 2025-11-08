from __future__ import annotations

import hashlib
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

        while task_index < len(all_tasks):
            current_block = self.block
            current_epoch = self.round_manager.block_to_epoch(current_block)
            boundaries = self.round_manager.get_current_boundaries()
            wait_info = self.round_manager.get_wait_info(current_block)

            ColoredLogger.info(
                (f"📍 Task {task_index + 1}/{len(all_tasks)} | epoch {current_epoch:.2f}/" f"{boundaries['target_epoch']} | remaining {wait_info['minutes_remaining']:.1f}m"),
                ColoredLogger.CYAN,
            )

            tasks_by_id = self.current_round_tasks or {}
            target_task_id = next(
                (task_id for task_id, payload in tasks_by_id.items() if getattr(payload, "sequence", None) == task_index),
                getattr(all_tasks[task_index].task, "id", None),
            )

            if target_task_id and self.active_miner_uids and self._completed_pairs:
                all_done = all((uid, target_task_id) in self._completed_pairs for uid in self.active_miner_uids)
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

            if not self._finalized_this_round and progress_frac >= float(FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION):
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

            if ENABLE_DISTRIBUTED_CONSENSUS and (not self._finalized_this_round) and (not self._consensus_published) and (progress_frac >= float(STOP_TASK_EVALUATION_AT_ROUND_FRACTION)):
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
                    (f"   epoch={current_epoch:.2f}, remaining={wait_info['seconds_remaining']:.0f}s, " f"buffer={SAFETY_BUFFER_EPOCHS} epochs, tasks={tasks_completed}/{len(all_tasks)}"),
                    ColoredLogger.YELLOW,
                )
                bounds_ctx = self.round_manager.get_round_boundaries(current_block, log_debug=False)
                target_epoch_ctx = bounds_ctx["target_epoch"]
                target_block_ctx = bounds_ctx["target_block"]
                round_no_ctx = await self.round_manager.calculate_round(current_block)
                ColoredLogger.info(
                    ("   Waiting for end-of-round target epoch to set weights | " f"round={round_no_ctx} | target_epoch={target_epoch_ctx:.2f} | target_block={target_block_ctx}"),
                    ColoredLogger.YELLOW,
                )
                self.state_manager.save_checkpoint()
                if ENABLE_DISTRIBUTED_CONSENSUS and (not self._consensus_published) and (not self._finalized_this_round):
                    bt.logging.info(f"[CONSENSUS] Safety buffer reached - publishing to IPFS with {tasks_completed} tasks")
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

        if ENABLE_DISTRIBUTED_CONSENSUS and (not self._consensus_published) and (not self._finalized_this_round):
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

            solution_groups = {}
            for i, (uid, solution) in enumerate(zip(self.active_miner_uids, task_solutions)):
                if solution and solution.actions:
                    actions_repr = []
                    for action in solution.actions:
                        action_str = f"{action.type}"
                        if hasattr(action, "url"):
                            action_str += f"|{action.url}"
                        if hasattr(action, "text"):
                            action_str += f"|{action.text}"
                        if hasattr(action, "selector") and action.selector:
                            selector_str = f"{getattr(action.selector, 'type', '')}:{getattr(action.selector, 'value', '')}"
                            action_str += f"|{selector_str}"
                        actions_repr.append(action_str)
                    actions_str = "||".join(actions_repr)
                    solution_hash = hashlib.md5(actions_str.encode()).hexdigest()[:8]
                else:
                    solution_hash = "no_actions"

                if solution_hash not in solution_groups:
                    solution_groups[solution_hash] = {"uids": [], "solution": solution, "indices": []}

                solution_groups[solution_hash]["uids"].append(uid)
                solution_groups[solution_hash]["indices"].append(i)

            ColoredLogger.debug("🔍 STARTING EVALUATION...", ColoredLogger.CYAN)
            eval_scores, test_results_list, evaluation_results = await evaluate_task_solutions(
                web_project=project,
                task=task,
                task_solutions=task_solutions,
                execution_times=execution_times,
            )

            try:
                console = Console()
                expected_base = project.frontend_url.rstrip("/")
                for group_idx, (solution_hash, group_data) in enumerate(solution_groups.items(), 1):
                    group_uids = group_data["uids"]
                    group_indices = group_data["indices"]
                    solution = group_data["solution"]
                    group_scores = [eval_scores[i] for i in group_indices]
                    group_times = [execution_times[i] for i in group_indices]
                    group_errors = [evaluation_results[i].get("error_message", "") for i in group_indices]

                    if solution and solution.actions:
                        seed_issues = 0
                        for action in solution.actions:
                            if hasattr(action, "url") and action.url and action.type == "NavigateAction" and seed is not None:
                                if "seed=" not in action.url:
                                    seed_issues += 1
                                else:
                                    action_seed = action.url.split("seed=")[1].split("&")[0].split("?")[0]
                                    if action_seed != str(seed):
                                        seed_issues += 1

                        status_emoji = "✅" if seed_issues == 0 else "⚠️"
                        uids_str = ", ".join([str(u) for u in group_uids])
                        actions_table = Table(
                            title=(f"[bold cyan]{status_emoji} Group {group_idx} | UIDs: [{uids_str}] - Actions Submitted[/bold cyan]"),
                            box=box.ROUNDED,
                            show_header=True,
                            header_style="bold yellow",
                            expand=False,
                        )
                        actions_table.add_column("#", justify="right", style="cyan", width=4)
                        actions_table.add_column("Action Type", justify="left", style="magenta", width=25)
                        actions_table.add_column("Details (Full)", justify="left", style="white", no_wrap=False)
                        actions_table.add_column("Status", justify="center", style="bold", width=6)

                        for j, action in enumerate(solution.actions, 1):
                            action_type = action.type
                            status = "[bold green]✅[/bold green]"
                            action_dict = vars(action)
                            details_lines = []
                            for key, value in action_dict.items():
                                if key == "type":
                                    continue
                                if hasattr(value, "__dict__"):
                                    value = vars(value)
                                details_lines.append(f"{key}: {value}")
                            details = "\n".join(details_lines)

                            if action_type == "NavigateAction" and seed is not None:
                                url = getattr(action, "url", "")
                                if "seed=" not in url:
                                    status = "[bold red]❌[/bold red]"
                                else:
                                    action_seed = url.split("seed=")[1].split("&")[0].split("?")[0]
                                    if action_seed != str(seed):
                                        status = "[bold red]❌[/bold red]"

                            actions_table.add_row(str(j), action_type, details, status)

                        console.print(actions_table)
                    else:
                        uids_str = ", ".join([str(u) for u in group_uids])
                        console.print(f"[yellow]📊 Group {group_idx} | UIDs: [{uids_str}] - NO ACTIONS SUBMITTED[/yellow]")

                    try:
                        group_tests = [test_results_list[i] if i < len(test_results_list) else [] for i in group_indices]
                        tests_table = Table(
                            title=(f"[bold green]🧪 Group {group_idx} | UIDs: [{', '.join([str(u) for u in group_uids])}] - Backend Tests[/bold green]"),
                            box=box.SIMPLE,
                            show_header=True,
                            header_style="bold green",
                            expand=False,
                        )
                        tests_table.add_column("UID", justify="right", style="cyan", width=8)
                        tests_table.add_column("Tests", justify="center", style="white", width=8)
                        tests_table.add_column("Passed", justify="center", style="white", width=8)
                        tests_table.add_column("Example Event", justify="left", style="white")

                        for uid, tests in zip(group_uids, group_tests):
                            total = len(tests or [])
                            passed = sum(1 for t in (tests or []) if bool(t.get("success", False)))
                            example = ""
                            try:
                                if tests:
                                    ed = (tests[0] or {}).get("extra_data", {}) or {}
                                    example = str(ed.get("event_name") or ed.get("type") or "")
                            except Exception:
                                example = ""
                            tests_table.add_row(str(uid), str(total), str(passed), example)

                        console.print(tests_table)
                    except Exception:
                        pass

                    uids_str = ", ".join([str(u) for u in group_uids])
                    result_table = Table(
                        title=(f"[bold magenta]📊 Group {group_idx} | UIDs: [{uids_str}] - Evaluation Results[/bold magenta]"),
                        box=box.SIMPLE,
                        show_header=True,
                        header_style="bold cyan",
                        expand=False,
                    )
                    result_table.add_column("UID", justify="right", style="cyan", width=8)
                    result_table.add_column("Score", justify="center", style="bold", width=10)
                    result_table.add_column("Time", justify="center", style="blue", width=12)
                    result_table.add_column("Status", justify="left", style="white", width=50)
                    result_table.add_column("Result", justify="center", style="bold", width=8)

                    for uid, score, exec_time, error_msg in zip(group_uids, group_scores, group_times, group_errors):
                        if score >= 0.8:
                            score_str = f"[bold green]{score:.4f}[/bold green]"
                            result_icon = "[bold green]✅[/bold green]"
                        elif score >= 0.5:
                            score_str = f"[bold yellow]{score:.4f}[/bold yellow]"
                            result_icon = "[bold yellow]⚠️[/bold yellow]"
                        else:
                            score_str = f"[bold red]{score:.4f}[/bold red]"
                            result_icon = "[bold red]❌[/bold red]"

                        time_str = f"[blue]{exec_time:.2f}s[/blue]"

                        if error_msg:
                            status_msg = f"[red]{error_msg[:47]}...[/red]" if len(error_msg) > 50 else f"[red]{error_msg}[/red]"
                        elif score >= 0.8:
                            status_msg = "[green]All tests passed[/green]"
                        elif score > 0:
                            status_msg = "[yellow]Some tests failed[/yellow]"
                        else:
                            status_msg = "[red]All tests failed[/red]"

                        result_table.add_row(str(uid), score_str, time_str, status_msg, result_icon)

                    console.print(result_table)
                    console.print()
                    console.print("[dim]" + "─" * 100 + "[/dim]")
                    console.print()
            except Exception as exc:
                bt.logging.warning(f"Failed to render miner tables: {exc}")
                import traceback

                bt.logging.warning(f"Traceback: {traceback.format_exc()}")
                for i, uid in enumerate(self.active_miner_uids):
                    ColoredLogger.debug(
                        f"UID={uid}: Score={eval_scores[i]:.4f}, Time={execution_times[i]:.2f}s",
                        ColoredLogger.GREEN,
                    )

            rewards = calculate_rewards_for_task(
                eval_scores=eval_scores,
                execution_times=execution_times,
                n_miners=len(self.active_miner_uids),
                eval_score_weight=EVAL_SCORE_WEIGHT,
                time_weight=TIME_WEIGHT,
            )

            for idx, uid in enumerate(self.active_miner_uids):
                reward_value = float(rewards[idx])
                score_value = float(eval_scores[idx])
                exec_time_value = float(execution_times[idx])

                attempts = self.round_manager.round_task_attempts
                attempts[uid] = attempts.get(uid, 0) + 1

                self.round_manager.round_rewards.setdefault(uid, []).append(reward_value)
                self.round_manager.round_eval_scores.setdefault(uid, []).append(score_value)
                self.round_manager.round_times.setdefault(uid, []).append(exec_time_value)

                # Record in round report (NEW)
                try:
                    hotkey = self.metagraph.hotkeys[uid] if uid < len(self.metagraph.hotkeys) else "unknown"
                    coldkey = self.metagraph.coldkeys[uid] if uid < len(self.metagraph.coldkeys) else "unknown"
                    success = score_value > 0.0

                    self._report_task_result(
                        uid=uid,
                        hotkey=hotkey,
                        coldkey=coldkey,
                        success=success,
                        execution_time=exec_time_value,
                        eval_score=score_value,
                        reward=reward_value,
                        web_name=web_project_name or "Unknown",
                    )
                except Exception as report_exc:
                    bt.logging.debug(f"Failed to record task result in report: {report_exc}")

            try:
                await send_feedback_synapse_to_miners(
                    validator=self,
                    miner_axons=list(active_axons),
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
            
            # Save incremental pickle after each task (NEW)
            try:
                report = self.round_manager.current_round_report
                if report:
                    self._save_round_report_pickle(report, incremental=True)
            except Exception as save_exc:
                bt.logging.debug(f"Incremental save failed: {save_exc}")
            
            return True

        except Exception as exc:
            bt.logging.error(f"Task execution failed: {exc}")
            raise
