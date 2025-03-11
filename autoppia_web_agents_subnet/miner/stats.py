from pydantic import BaseModel
from typing import Optional
from autoppia_iwa.src.data_generation.domain.classes import Task


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
