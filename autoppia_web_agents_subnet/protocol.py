from pydantic import Field
from typing import List, Optional, Any, Dict
from bittensor import Synapse
from autoppia_iwa.src.execution.actions.actions import AllActionsUnion
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.shared.visualizator import SubnetVisualizer
from autoppia_iwa.src.data_generation.domain.classes import TestUnion
from rich.console import Console
import bittensor as bt


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
                task.tests = self.tests
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
                task.tests = self.tests

            visualizer.show_task_with_tests(task_prepared_for_agent)
            console = Console()
            console.print(
                f"\n[bold yellow]Insufficient actions or test results for {self.miner_id}[/bold yellow]"
            )
