from pydantic import Field, BaseModel
from typing import List, Optional
from bittensor import Synapse
from autoppia_iwa.src.execution.actions.actions import AllActionsUnion
from autoppia_iwa.src.data_generation.domain.classes import Task

# Added imports for rich
from rich.console import Console
from rich.table import Table


class MinerStats(BaseModel):
    avg_score: float = 0.0
    avg_execution_time: float = 0.0
    avg_evaluation_time: float = 0.0
    total_tasks: int = 0
    total_successful_tasks: int = 0
    last_task: Optional["Task"] = None
    sum_score: float = 0.0
    sum_execution_time: float = 0.0
    sum_evaluation_time: float = 0.0

    # New fields
    last_task_score: float = 0.0
    last_execution_time: float = 0.0

    # Allow extra fields to avoid strict validation on nested objects
    class Config:
        extra = "allow"
        arbitrary_types_allowed = True

    def update(
        self,
        validator_hotkey, 
        score: float,
        execution_time: float,
        evaluation_time: float,
        last_task: "Task",
        success: bool = False
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
    version: str = ""
    prompt: str = ""
    url: str = ""

    actions: List[AllActionsUnion] = Field(
        default_factory=list,
        description="The actions that solve the task"
    )

    class Config:
        extra = "allow"

    def deserialize(self) -> "TaskSynapse":
        return self


class TaskFeedbackSynapse(Synapse):
    version: str = ""
    stats: MinerStats

    class Config:
        extra = "allow"
        arbitrary_types_allowed = True

    def deserialize(self) -> "TaskFeedbackSynapse":
        return self

    def print_in_terminal(self):
        validator_hotkey = getattr(self.dendrite, "hotkey", None)  

        console = Console()
        table = Table(title="Miner Feedback Stats", show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="dim")
        table.add_column("Value", justify="right")

        table.add_row("Synapse Version", self.version)
        table.add_row("Total Tasks", str(self.stats.total_tasks))
        table.add_row("Successful Tasks", str(self.stats.total_successful_tasks))
        table.add_row("Avg Score", f"{self.stats.avg_score:.2f}")
        table.add_row("Avg Exec Time", f"{self.stats.avg_execution_time:.2f}s")
        table.add_row("Avg Eval Time", f"{self.stats.avg_evaluation_time:.2f}s")

        # Add empty row between global stats and last task stats
        table.add_row("", "")
        table.add_row("Validator Hotkey", validator_hotkey if validator_hotkey else "None")

        if self.stats.last_task:
            last_task_id = self.stats.last_task.id or "N/A"
            last_task_prompt = self.stats.last_task.prompt or "N/A"
            table.add_row("Last Task ID", str(last_task_id))
            table.add_row("Last Task Prompt", last_task_prompt)
        else:
            table.add_row("Last Task ID", "None")
            table.add_row("Last Task Prompt", "None")

        # Display new fields for the last task
        table.add_row("Last Task Score", f"{self.stats.last_task_score:.2f}")
        table.add_row("Last Exec Time", f"{self.stats.last_execution_time:.2f}s")

        

        console.print(table)
