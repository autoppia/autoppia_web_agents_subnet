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

# Feature flag from miner config
try:
    from autoppia_web_agents_subnet.miner.config import SAVE_FEEDBACK_TO_JSON, FEEDBACK_JSON_FILE
except Exception:
    SAVE_FEEDBACK_TO_JSON = False
    FEEDBACK_JSON_FILE = "feedback_tasks.json"


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

    # DEBUG: Log task creation and test assignment
    console.print(f"[yellow]🔍 DEBUG: Creating task with tests[/yellow]")
    console.print(f"[gray]  - Task ID: {task.id}[/gray]")
    console.print(f"[gray]  - Tests from feedback: {fb.tests}[/gray]")

    if fb.tests:
        # attach tests for the visualizer if present
        try:
            task.tests = fb.tests
            console.print(f"[green]✅ Successfully assigned {len(fb.tests)} tests to task[/green]")
        except Exception as e:
            console.print(f"[red]❌ Failed to assign tests to task: {e}[/red]")
            # Try alternative assignment methods
            if hasattr(task, '__dict__'):
                task.__dict__['tests'] = fb.tests
                console.print(f"[yellow]⚠️ Used __dict__ to assign tests[/yellow]")

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
    if SAVE_FEEDBACK_TO_JSON:
        save_feedback_to_json(fb, filename=FEEDBACK_JSON_FILE)
