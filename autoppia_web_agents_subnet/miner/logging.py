# file: autoppia_iwa/src/execution/logging.py
"""
Terminal/visualizer rendering and optional JSON persistence for feedback.

Keep this file side-effectful (printing to terminal, saving files), while
protocol.py and models.py remain side-effect free.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional, Any, Dict, List

from filelock import FileLock
from rich.console import Console

from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.shared.visualizator import SubnetVisualizer
from .models import MinerStats
from ..protocol import TaskFeedbackSynapse

# Feature flag (same import path you used before)
try:
    from autoppia_web_agents_subnet.config.config import SAVE_SUCCESSFUL_TASK_IN_JSON  # type: ignore
except Exception:
    SAVE_SUCCESSFUL_TASK_IN_JSON = False


def _render_task_feedback_header(console: Console, fb: TaskFeedbackSynapse) -> None:
    console.print("\n[bold green]Task Feedback[/bold green]", style="bold cyan")
    console.print(
        f"[bold]Task ID:[/bold] {fb.task_id}\n"
        f"[bold]Validator:[/bold] {fb.validator_id}\n"
        f"[bold]Miner:[/bold] {fb.miner_id}\n"
        f"[bold]URL:[/bold] {fb.task_url}\n"
        f"[bold]Prompt:[/bold] {fb.prompt}\n"
    )
    console.print(
        f"[bold]Score:[/bold] {fb.score} | "
        f"[bold]Execution Time:[/bold] {fb.execution_time} seconds\n",
        style="cyan",
    )


def _render_visualization(console: Console, fb: TaskFeedbackSynapse) -> None:
    visualizer = SubnetVisualizer()
    task = Task(id=fb.task_id, prompt=fb.prompt, url=fb.task_url).prepare_for_agent(fb.miner_id)

    if fb.tests:
        # attach tests for the visualizer if present
        task.tests = fb.tests

    # If we have actions + matrix, show full evaluation; else basic task/tests
    if fb.actions and fb.test_results_matrix:
        visualizer.show_full_evaluation(
            agent_id=fb.miner_id,
            validator_id=fb.validator_id,
            task=task,
            actions=fb.actions or [],
            test_results_matrix=fb.test_results_matrix or [],
            evaluation_result=fb.evaluation_result,
        )
    else:
        visualizer.show_task_with_tests(task)
        console.print("[bold yellow]Insufficient actions or test results to render full evaluation.[/bold yellow]")


def _render_miner_stats(console: Console, miner_stats: Optional[MinerStats]) -> None:
    if not miner_stats:
        return

    console.print("\n[bold magenta]Miner Global Stats[/bold magenta]")
    console.print(f" • Total Tasks: [bold]{miner_stats.num_tasks}[/bold]")
    console.print(f" • Avg. Score: [bold]{miner_stats.avg_score:.2f}[/bold]")
    console.print(
        "\n[bold magenta]----- Miner Global Stats -----[/bold magenta]",
        style="bold magenta",
    )
    console.print(f"  • Total Tasks: [bold]{miner_stats.num_tasks}[/bold]")
    console.print(f"  • Avg. Score: [bold]{miner_stats.avg_score:.2f}[/bold]")
    console.print(f"  • Avg. Execution Time: [bold]{miner_stats.avg_execution_time:.2f}[/bold] seconds")


def save_feedback_to_json(fb: TaskFeedbackSynapse, filename: str = "feedback_tasks.json") -> None:
    """
    Append a feedback record to a local JSON array file with a file lock.
    """
    data = fb.model_dump()  # pydantic BaseModel (bittensor.Synapse)
    data["local_save_timestamp"] = time.time()

    lock_path = f"{filename}.lock"
    lock = FileLock(lock_path)

    with lock:
        path = Path(filename)
        if not path.exists():
            path.write_text("[]")
        existing: List[Dict[str, Any]] = json.loads(path.read_text())
        existing.append(data)
        path.write_text(json.dumps(existing, indent=2))


def print_task_feedback(fb: TaskFeedbackSynapse, miner_stats: Optional[MinerStats] = None) -> None:
    """
    High-level function to reproduce the previous .print_in_terminal() behavior.
    """
    console = Console()
    _render_task_feedback_header(console, fb)
    _render_visualization(console, fb)
    _render_miner_stats(console, miner_stats)

    # Optionally persist locally
    if SAVE_SUCCESSFUL_TASK_IN_JSON:
        save_feedback_to_json(fb)
