from __future__ import annotations

from dataclasses import dataclass
from typing import List

# IWA domain types
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.data_generation.tasks.classes import Task


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
