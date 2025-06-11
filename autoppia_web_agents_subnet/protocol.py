# file: autoppia_iwa/src/execution/synapses.py

import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from distutils.util import strtobool
from filelock import FileLock
from typing import Any, Dict, List, Optional

import bittensor as bt
from bittensor import Synapse
from pydantic import Field
from rich.console import Console

from autoppia_iwa.src.data_generation.domain.classes import Task, TestUnion
from autoppia_iwa.src.execution.actions.actions import AllActionsUnion
from autoppia_iwa.src.shared.visualizator import SubnetVisualizer
from .miner.stats import MinerStats

# === new import ===

SAVE_SUCCESSFUL_TASK_IN_JSON = bool(
    strtobool(os.getenv("SAVE_SUCCESSFUL_TASK_IN_JSON", "false"))
)
SUCCESSFUL_TASKS_JSON_FILENAME = "successful_tasks.json"


class TaskSynapse(Synapse):
    """
    Synapse carrying the Task prompt & data from validator to miners.
    """

    version: str = ""
    prompt: str
    url: str
    html: Optional[str] = None
    screenshot: Optional[str] = None
    actions: List[AllActionsUnion] = Field(
        default_factory=list, description="The actions that solve the task"
    )

    class Config:
        extra = "allow"
        arbitrary_types_allowed = True

    def deserialize(self) -> "TaskSynapse":
        return self


class TaskFeedbackSynapse(Synapse):
    """
    Synapse carrying feedback from validator back to miner,
    including test_results, evaluation scores, and stats.
    """

    version: str = ""
    validator_id: str
    miner_id: str
    task_id: str
    task_url: str
    prompt: str
    score: Optional[float] = 0.0
    execution_time: Optional[float] = 0.0
    tests: Optional[List[TestUnion]] = None
    actions: Optional[List[AllActionsUnion]] = Field(default_factory=list)
    test_results_matrix: Optional[List[List[Any]]] = None
    evaluation_result: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"
        arbitrary_types_allowed = True

    def deserialize(self) -> "TaskFeedbackSynapse":
        return self

    def print_in_terminal(self, miner_stats: Optional[MinerStats] = None):
        """
        Prints a detailed summary of the feedback in the terminal.
        Also shows global miner stats if provided, and optionally saves
        the task if needed.
        """

        console = Console()
        visualizer = SubnetVisualizer()

        # -- Print the specific task result:
        console.print("\n[bold green]Task Feedback[/bold green]", style="bold cyan")
        console.print(
            f"[bold]Task ID:[/bold] {self.task_id}\n"
            f"[bold]Validator:[/bold] {self.validator_id}\n"
            f"[bold]Miner:[/bold] {self.miner_id}\n"
            f"[bold]URL:[/bold] {self.task_url}\n"
            f"[bold]Prompt:[/bold] {self.prompt}\n"
        )
        console.print(
            f"[bold]Score:[/bold] {self.score} | "
            f"[bold]Execution Time:[/bold] {self.execution_time} seconds\n",
            style="cyan",
        )

        # show full or partial evaluation in the visualizer
        task = Task(id=self.task_id, prompt=self.prompt, url=self.task_url)
        task = task.prepare_for_agent(self.miner_id)
        if self.tests:
            task.tests = self.tests

        if self.actions and self.test_results_matrix:
            visualizer.show_full_evaluation(
                agent_id=self.miner_id,
                validator_id=self.validator_id,
                task=task,
                actions=self.actions,
                test_results_matrix=self.test_results_matrix,
                evaluation_result=self.evaluation_result,
            )
        else:
            visualizer.show_task_with_tests(task)
            console.print(
                "[bold yellow]Insufficient actions or test results to render full evaluation.[/bold yellow]"
            )

        # show overall miner stats if available
        if miner_stats:
            console.print("\n[bold magenta]Miner Global Stats[/bold magenta]")
            console.print(f" • Total Tasks: [bold]{miner_stats.num_tasks}[/bold]")
            console.print(f" • Avg. Score: [bold]{miner_stats.avg_score:.2f}[/bold]")
            console.print(
                "\n[bold magenta]----- Miner Global Stats -----[/bold magenta]",
                style="bold magenta",
            )
            console.print(f"  • Total Tasks: [bold]{miner_stats.num_tasks}[/bold]")
            console.print(f"  • Avg. Score: [bold]{miner_stats.avg_score:.2f}[/bold]")
            console.print(
                f"  • Avg. Execution Time: [bold]{miner_stats.avg_execution_time:.2f}[/bold] seconds"
            )

        # optionally persist locally
        if SAVE_SUCCESSFUL_TASK_IN_JSON:
            self.save_to_json()

    def save_to_json(self, filename: str = "feedback_tasks.json"):
        data = self.model_dump()
        data["local_save_timestamp"] = time.time()
        lock = FileLock(f"{filename}.lock")
        with lock:
            if not Path(filename).exists():
                Path(filename).write_text("[]")
            arr = json.loads(Path(filename).read_text())
            arr.append(data)
            Path(filename).write_text(json.dumps(arr, indent=2))


class SetOperatorEndpointSynapse(bt.Synapse):
    """
    Synapse for telling miners your operator's endpoint.
    Miners will (optionally) respond with data to be saved.
    """

    version: str = ""
    endpoint: str

    class Config:
        extra = "allow"
        arbitrary_types_allowed = True

    def deserialize(self) -> "SetOperatorEndpointSynapse":
        return self
