from pydantic import Field
from typing import List, Optional, Any, Dict
from bittensor import Synapse
from autoppia_iwa.src.execution.actions.actions import AllActionsUnion
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.shared.visualizator import SubnetVisualizer
from rich.console import Console
from autoppia_iwa.src.data_generation.domain.classes import TestUnion


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
    miner_id: str
    task_id: str
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
        # If we have enough data for a full evaluation
        if (
            self.task_id
            and self.actions
            and self.test_results_matrix
        ):
            # Create a temporary task object with the available attributes
            task = Task(id=self.task_id, prompt=self.prompt)
            if self.tests:
                task.tests = self.tests

            visualizer.show_full_evaluation(
                agent_id=self.miner_id,
                task=task,
                actions=self.actions,
                test_results_matrix=self.test_results_matrix,
                evaluation_result=self.evaluation_result,
            )
        elif self.task_id:
            # Partial data => just show the task
            task = Task(id=self.task_id, prompt=self.prompt)
            if self.tests:
                task.tests = self.tests

            visualizer.show_task_with_tests(task)
            console = Console()
            console.print(
                f"\n[bold yellow]Insufficient actions or test results for {self.miner_id}[/bold yellow]"
            )
