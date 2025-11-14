from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import bittensor as bt
from rich import box
from rich.console import Console
from rich.table import Table

from autoppia_web_agents_subnet.protocol import TaskSynapse
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.config import (
    TIME_WEIGHT,
    EVAL_SCORE_WEIGHT,
)
from autoppia_web_agents_subnet.validator.dataset import RoundDatasetCollector
from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.validator.evaluation.eval import evaluate_task_solutions
from autoppia_web_agents_subnet.validator.evaluation.rewards import calculate_rewards_for_task
from autoppia_web_agents_subnet.validator.evaluation.synapse_handlers import (
    send_feedback_synapse_to_miners,
    send_task_synapse_to_miners,
)
from autoppia_web_agents_subnet.validator.evaluation.tasks import (
    collect_task_solutions_and_execution_times,
)


async def _execute_single_final_task(
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
                title=f"[bold cyan]📋 Task {task_index + 1}/{len(self.final_tasks)}[/bold cyan]",
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

        self.round_manager.accumulate_final_rewards(
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
