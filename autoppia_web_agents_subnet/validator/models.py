from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, List, Optional, Tuple, Dict

import numpy as np
from numpy.typing import NDArray

# IWA domain types
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.web_agents.classes import TaskSolution


# ─────────────────────────────────────────────────────────────────────────────
# Task collection modeling
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProjectTasks:
    """
    Tasks belonging to a single project.
    """
    project: WebProject
    tasks: List[Task]


@dataclass
class TaskWithProject:
    """
    A single task paired with its project.
    Simple, clear alternative to tuples for better code readability.
    """
    project: WebProject
    task: Task
