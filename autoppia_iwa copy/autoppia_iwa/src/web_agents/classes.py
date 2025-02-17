from typing import List, Optional

from pydantic import BaseModel, Field

from ..data_generation.domain.classes import Task
from ..execution.actions.base import BaseAction


class TaskSolution(BaseModel):
    task: Task
    actions: List[BaseAction] = Field(default_factory=list)
    web_agent_id: Optional[str] = None
