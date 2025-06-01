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
from autoppia_web_agents_subnet.validator.leaderboard import log_task_to_leaderboard

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

        console.print("\n[bold green]Task Feedback[/bold green]\n", style="cyan")
        console.print(
            f"[bold]Task ID:[/bold] {self.task_id}\n"
            f"[bold]Validator:[/bold] {self.validator_id}\n"
            f"[bold]Miner:[/bold] {self.miner_id}\n"
            f"[bold]URL:[/bold] {self.task_url}\n"
            f"[bold]Prompt:[/bold] {self.prompt}\n"
        )
        console.print(
            f"[bold]Score:[/bold] {self.score} | "
            f"[bold]Execution Time:[/bold] {self.execution_time:.2f}s\n",
            style="cyan"
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
                f" • Avg. Exec Time: [bold]{miner_stats.avg_execution_time:.2f}s[/bold]"
            )

        # optionally persist locally
        if SAVE_SUCCESSFUL_TASK_IN_JSON:
            self._save_successful_task_if_needed()

        # always save feedback
        self.save_to_json()

        # === NEW: fire off to leaderboard endpoint ===
        try:
            # extract block & timestamp however you get them in your app
            current_block = bt.wallet.get_current_block()  # or however you fetch it
            resp = log_task_to_leaderboard(
                task=task,
                stats=self.evaluation_result.get("stats"),
                validator_hotkey=self.validator_id,
                validator_uid=int(self.validator_id),
                miner_hotkey=self.miner_id,
                miner_uid=int(self.miner_id),
                block_number=current_block,
            )
            console.print(f"[bold green]Logged to leaderboard:[/bold green] {resp.status_code}")
        except Exception as e:
            console.print(f"[bold red]Failed to log to leaderboard:[/bold red] {e}")

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

    def _save_successful_task_if_needed(self):
        """Append only high-scoring runs to SUCCESSFUL_TASKS_JSON_FILENAME."""
        if not self.evaluation_result:
            return
        final_score = self.evaluation_result.get("stats", {}).get("final_score", 0)
        if final_score < 1:
            return

        # build a de-duped list of prompts
        fn = SUCCESSFUL_TASKS_JSON_FILENAME
        if Path(fn).exists():
            try:
                arr = json.loads(Path(fn).read_text())
            except json.JSONDecodeError:
                arr = []
        else:
            arr = []

        if any(entry.get("prompt") == self.prompt for entry in arr):
            bt.logging.info("Prompt already saved – skipping.")
            return

        entry = {
            "task_id": self.task_id,
            "miner_id": self.miner_id,
            "prompt": self.prompt,
            "score": self.score,
            "actions": [a.dict() for a in (self.actions or [])],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        arr.append(entry)
        Path(fn).write_text(json.dumps(arr, indent=2))
        bt.logging.info(f"Saved successful task: {self.task_id}")


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
