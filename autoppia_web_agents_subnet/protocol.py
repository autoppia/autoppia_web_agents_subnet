from pydantic import Field, BaseModel
from typing import List, Optional
from bittensor import Synapse
from autoppia_iwa.src.execution.actions.actions import AllActionsUnion
from autoppia_iwa.src.data_generation.domain.classes import Task


class MinerStats(BaseModel):
    avg_score: float = 0.0
    avg_execution_time: float = 0.0
    avg_evaluation_time: float = 0.0
    total_tasks: int = 0
    last_task: Optional["Task"] = None
    sum_score: float = 0.0
    sum_execution_time: float = 0.0
    sum_evaluation_time: float = 0.0

    def update(self, score: float, execution_time: float, evaluation_time: float, last_task: "Task"):
        self.total_tasks += 1
        self.sum_score += score
        self.sum_execution_time += execution_time
        self.sum_evaluation_time += evaluation_time
        self.avg_score = self.sum_score / self.total_tasks
        self.avg_execution_time = self.sum_execution_time / self.total_tasks
        self.avg_evaluation_time = self.sum_evaluation_time / self.total_tasks
        self.last_task = last_task


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


class FeedbackSynapse(Synapse):
    version: str = ""
    stats: MinerStats
    # Add aggregated_stats if needed
    # aggregated_stats: MinerStats

    class Config:
        extra = "allow"

    def deserialize(self) -> "FeedbackSynapse":
        return self
