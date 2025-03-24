from pydantic import Field
from typing import List, Optional, Any, Dict
from bittensor import Synapse
from autoppia_iwa.src.execution.actions.actions import AllActionsUnion
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.shared.visualizator import SubnetVisualizer
from autoppia_iwa.src.data_generation.domain.classes import TestUnion
from filelock import FileLock
from rich.console import Console
import bittensor as bt
import json
import os
import time
from distutils.util import strtobool
from .miner.stats import MinerStats


SAVE_SUCCESSFULL_TASK_IN_JSON = bool(
    strtobool(os.getenv("SAVE_SUCCESSFULL_TASK_IN_JSON", "false"))
)
SUCCESSFUlL_TASKS_JSON_FILENAME = "successfull_tasks.json"


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


class OrganicTaskSynapse(Synapse):
    """
    Synapse carrying the Task prompt & data from validator to miners.
    """

    version: str = ""
    prompt: str
    url: str

    class Config:
        extra = "allow"
        arbitrary_types_allowed = True

    def deserialize(self) -> "TaskSynapse":
        return self


class TaskFeedbackSynapse(bt.Synapse):
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

    def print_in_terminal(self, miner_stats: Optional["MinerStats"] = None):
        """
        Prints a detailed summary of the feedback in the terminal.
        Also shows global miner stats if provided, and optionally saves
        the task if needed.
        """

        visualizer = SubnetVisualizer()
        console = Console()

        # -- Print the specific task result: 
        console.print("\n[bold green]Task Feedback[/bold green]", style="bold cyan")
        console.print(
            f"[bold]Task ID:[/bold] {self.task_id}\n"
            f"[bold]Validator:[/bold] {self.validator_id}\n"
            f"[bold]Miner:[/bold] {self.miner_id}\n"
            f"[bold]URL:[/bold] {self.task_url}\n"
            f"[bold]Prompt:[/bold] {self.prompt}\n"
        )

        # Show the score and execution time for this task
        console.print(
            f"[bold]Score:[/bold] {self.score} | "
            f"[bold]Execution Time:[/bold] {self.execution_time} seconds\n",
            style="cyan"
        )

        # If we have enough data (actions/tests), display them visually
        if self.task_id and self.actions and self.test_results_matrix:
            task = Task(id=self.task_id, prompt=self.prompt, url=self.task_url)
            task_prepared_for_agent = task.prepare_for_agent(self.miner_id)

            if self.tests:
                task_prepared_for_agent.tests = self.tests

            visualizer.show_full_evaluation(
                agent_id=self.miner_id,
                validator_id=self.validator_id,
                task=task_prepared_for_agent,
                actions=self.actions,
                test_results_matrix=self.test_results_matrix,
                evaluation_result=self.evaluation_result,
            )
        elif self.task_id:
            # Partial data => just show the task
            task = Task(id=self.task_id, prompt=self.prompt, url=self.task_url)
            task_prepared_for_agent = task.prepare_for_agent(self.miner_id)

            if self.tests:
                task_prepared_for_agent.tests = self.tests

            visualizer.show_task_with_tests(task_prepared_for_agent)
            console.print(
                f"\n[bold yellow]Insufficient actions or test results for {self.miner_id}[/bold yellow]"
            )

        # -- Show global miner stats after printing the specific report:
        if miner_stats:
            console.print(
                "\n[bold magenta]----- Miner Global Stats -----[/bold magenta]",
                style="bold magenta"
            )
            console.print(f"  • Total Tasks: [bold]{miner_stats.num_tasks}[/bold]")
            console.print(f"  • Avg. Score: [bold]{miner_stats.avg_score:.2f}[/bold]")
            console.print(
                f"  • Avg. Execution Time: [bold]{miner_stats.avg_execution_time:.2f}[/bold] seconds"
            )

        # --------------------------------------------
        # (Optional) Attempt to save successful tasks
        # --------------------------------------------
        if SAVE_SUCCESSFULL_TASK_IN_JSON:
            self._save_successful_task_if_needed()

        # --------------------------------------------
        # Example: Immediately store all feedback data
        # --------------------------------------------
        self.save_to_json()


    def save_to_json(self, filename: str = "feedback_tasks.json"):
        """
        Saves ALL feedback fields to a local JSON file.
        Uses a file-level lock for concurrency across processes.
        """
        # Convert this Pydantic model into a Python dict
        # This includes all fields (version, validator_id, etc.)
        data = self.model_dump()

        # Add a timestamp to track when we saved
        data["local_save_timestamp"] = time.time()

        # The .lock file ensures only one process writes at a time
        lock_file = filename + ".lock"

        with FileLock(lock_file):
            # Ensure the JSON file exists and is initialized as a list
            if not os.path.isfile(filename):
                with open(filename, "w") as f:
                    json.dump([], f)

            # Read the existing JSON contents into memory
            with open(filename, "r") as f:
                content = json.load(f)

            # Append this feedback entry
            content.append(data)

            # Write the updated content back
            with open(filename, "w") as f:
                json.dump(content, f, indent=4)

    def _save_successful_task_if_needed(self):
        """
        Checks if the current task is 'successful' according to your logic,
        and if so, appends it to SUCCESSFUlL_TASKS_JSON_FILENAME only if
        its prompt doesn't already exist in the file.
        """
        if not self.test_results_matrix:
            return

        # Example success check: all cells in test_results_matrix are True
        all_passed = all(
            all(cell is True for cell in row) for row in self.test_results_matrix
        )
        if not all_passed:
            return

        data_to_save = {
            "task_id": self.task_id,
            "miner_id": self.miner_id,
            "task_url": self.task_url,
            "prompt": self.prompt,
            "actions": (
                [action.dict() for action in self.actions] if self.actions else []
            ),
            "test_results_matrix": self.test_results_matrix,
            "evaluation_result": self.evaluation_result,
        }

        filename = SUCCESSFUlL_TASKS_JSON_FILENAME

        # Load existing data (or start with an empty dict)
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    try:
                        existing_data = json.load(f)
                    except json.JSONDecodeError:
                        existing_data = {}
            except FileNotFoundError:
                existing_data = {}
        else:
            existing_data = {}

        # Check if this prompt is already in the file. If so, skip saving.
        if data_to_save["prompt"] in existing_data:
            bt.logging.info(
                f"Task with the same prompt already exists. Skipping save for prompt: {data_to_save['prompt']}"
            )
            return

        # Otherwise, add this new prompt to the dictionary
        existing_data[data_to_save["prompt"]] = data_to_save

        # Write updated data to file
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=2)

        bt.logging.info(
            f"Successfully saved task with prompt: {data_to_save['prompt']}"
        )
