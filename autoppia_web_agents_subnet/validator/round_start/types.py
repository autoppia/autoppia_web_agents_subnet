from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from autoppia_web_agents_subnet.validator.models import TaskWithProject


@dataclass
class StartPhaseResult:
    all_tasks: List[TaskWithProject]
    resumed: bool
    continue_forward: bool
    tasks_completed: int = 0
    reason: Optional[str] = None
