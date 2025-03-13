from pydantic import Field
from typing import List, Optional, Any, Dict
from bittensor import Synapse
from autoppia_iwa.src.execution.actions.actions import AllActionsUnion
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.shared.visualizator import SubnetVisualizer
from autoppia_iwa.src.data_generation.domain.classes import TestUnion
from rich.console import Console
import bittensor as bt
import json
import os
from distutils.util import strtobool


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
    tests: Optional[List[TestUnion]] = None
    actions: Optional[List[AllActionsUnion]] = Field(default_factory=list)
    test_results_matrix: Optional[List[List[Any]]] = None
    evaluation_result: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"
        arbitrary_types_allowed = True

    def deserialize(self) -> "TaskFeedbackSynapse":
        return self

    def print_in_terminal(self):
        visualizer = SubnetVisualizer()
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
            console = Console()
            console.print(
                f"\n[bold yellow]Insufficient actions or test results for {self.miner_id}[/bold yellow]"
            )

        # --------------------------------------------
        # Attempt to save successful tasks as JSON
        # --------------------------------------------
        if SAVE_SUCCESSFULL_TASK_IN_JSON:
            self._save_successful_task_if_needed()

    def _save_successful_task_if_needed(self):
        """
        Checks if the current task is 'successful' according to your logic,
        and if so, appends it to SUCCESSFUlL_TASKS_JSON_FILENAME only if
        its prompt doesn't already exist in the file.
        """
        # Example success check: all cells in test_results_matrix are True
        if not self.test_results_matrix:
            return

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
            # Prompt already exists => do nothing
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
