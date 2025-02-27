from pydantic import Field, BaseModel
from typing import List, Optional, Any, Dict
from bittensor import Synapse
from autoppia_iwa.src.execution.actions.actions import AllActionsUnion
from autoppia_iwa.src.data_generation.domain.classes import Task

# Added imports for rich
from rich.console import Console
from rich.table import Table


class MinerStats(BaseModel):
    """
    Stores basic stats about a miner, updated after each task.
    """

    avg_score: float = 0.0
    avg_execution_time: float = 0.0
    avg_evaluation_time: float = 0.0
    total_tasks: int = 0
    total_successful_tasks: int = 0
    last_task: Optional[Task] = None
    sum_score: float = 0.0
    sum_execution_time: float = 0.0
    sum_evaluation_time: float = 0.0

    # Additional fields
    last_task_score: float = 0.0
    last_execution_time: float = 0.0

    class Config:
        extra = "allow"
        arbitrary_types_allowed = True

    def update(
        self,
        score: float,
        execution_time: float,
        evaluation_time: float,
        last_task: Task,
        success: bool = False,
    ):
        self.total_tasks += 1
        self.sum_score += score
        self.sum_execution_time += execution_time
        self.sum_evaluation_time += evaluation_time

        if success:
            self.total_successful_tasks += 1

        self.avg_score = self.sum_score / self.total_tasks
        self.avg_execution_time = self.sum_execution_time / self.total_tasks
        self.avg_evaluation_time = self.sum_evaluation_time / self.total_tasks

        self.last_task = last_task
        self.last_task_score = score
        self.last_execution_time = execution_time


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

    def deserialize(self) -> "TaskSynapse":
        # We can transform or sanitize fields here if needed
        return self


class TaskFeedbackSynapse(Synapse):
    """
    Synapse carrying feedback from validator back to miner,
    including test_results, evaluation scores, and stats.
    """

    version: str = ""
    miner_id: str
    task: Optional[Task] = None
    actions: List[AllActionsUnion] = Field(default_factory=list)
    test_results_matrix: Optional[List[List[Any]]] = None
    evaluation_result: Optional[Dict[str, Any]] = None
    stats: MinerStats = None

    class Config:
        extra = "allow"
        arbitrary_types_allowed = True

    def deserialize(self) -> "TaskFeedbackSynapse":
        return self

    def print_in_terminal(self):
        """
        Show a detailed view of the results using the SubnetVisualizer
        """
        from autoppia_iwa.src.shared.visualizator import SubnetVisualizer

        visualizer = SubnetVisualizer()

        # If we have enough data for a full evaluation
        if (
            self.task
            and hasattr(self.task, "id")
            and self.actions
            and self.test_results_matrix
        ):
            # Show the full details
            visualizer.show_full_evaluation(
                agent_id=self.miner_id,
                task=self.task,
                actions=self.actions,
                test_results_matrix=self.test_results_matrix,
                evaluation_result=self.evaluation_result,
            )

        # If we only have the task, at least show that
        elif self.task and hasattr(self.task, "id"):
            visualizer.show_task_with_tests(self.task)
            console = Console()
            console.print(
                f"\n[bold yellow]Insufficient actions or test results for {self.miner_id}[/bold yellow]"
            )

        # Otherwise, just show minimal stats
        else:
            console = Console()
            table = Table(
                title=f"Miner Feedback Stats for {self.miner_id}",
                show_header=True,
                header_style="bold magenta",
            )
            table.add_column("Metric", style="dim")
            table.add_column("Value", justify="right")

            validator_hotkey = getattr(self.dendrite, "hotkey", None)
            table.add_row(
                "Validator Hotkey", validator_hotkey if validator_hotkey else "None"
            )
            table.add_row("Miner ID", self.miner_id)

            if self.stats:
                table.add_row("Total Tasks", str(self.stats.total_tasks))
                table.add_row(
                    "Successful Tasks", str(self.stats.total_successful_tasks)
                )
                table.add_row("Avg Score", f"{self.stats.avg_score:.2f}")
                table.add_row("Avg Exec Time", f"{self.stats.avg_execution_time:.2f}s")

                if self.stats.last_task:
                    table.add_row("Last Task ID", str(self.stats.last_task.id or "N/A"))
                    table.add_row(
                        "Last Task Score", f"{self.stats.last_task_score:.2f}"
                    )

            console.print(table)
