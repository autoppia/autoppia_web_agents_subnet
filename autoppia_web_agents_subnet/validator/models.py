from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, List, Optional, Tuple, Dict

import numpy as np
from numpy.typing import NDArray

# IWA domain types
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.data_generation.tasks.classes import Task
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


# ─────────────────────────────────────────────────────────────────────────────
# Result modeling (task-centric)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PerTaskResult:
    """
    Single task's miner outputs, already ALIGNED to `miner_uids`.
    """
    project: WebProject
    task: Task
    solutions: List[Optional[TaskSolution]]  # aligned to miner_uids; None for non-responders
    execution_times: List[float]             # aligned to miner_uids


@dataclass
class ScoredTask:
    """
    Task record after evaluation + blending.
    """
    project: WebProject
    task: Task
    solutions: List[Optional[TaskSolution]]      # aligned to miner_uids
    execution_times: List[float]                 # aligned to miner_uids
    final_rewards: NDArray[np.float32]           # aligned to miner_uids
    test_results_matrices: List[List[List[Any]]]  # per-miner matrices (aligned)
    evaluation_results: List[Dict[str, Any]]     # per-miner summaries (aligned)
    eval_scores: NDArray[np.float32]             # raw eval (aligned)


# Resultados de evaluación por tarea (separado del blending de recompensas)
@dataclass
class EvalOutput:
    eval_scores: NDArray[np.float32]                      # vector alineado a uids activos
    test_results_matrices: List[List[List[Any]]]          # por-miner -> lista de tests
    evaluation_results: List[Dict[str, Any]]              # por-miner -> dict resumenl


@dataclass
class AgentInfo:
    """
    Information about an agent.
    """
    uid: int
    agent_name: str
    github_url: str
    agent_image: Optional[str] = None
    score: Optional[float] = 0.0
    evaluated: bool = False
    # Best-effort submission identity: the commit of the submitted repo/ref (resolved by validator).
    normalized_repo: Optional[str] = None
    git_commit: Optional[str] = None
    # Rate limiting / scheduling metadata (validator-side).
    last_evaluated_round: Optional[int] = None
    # Pending submission captured during cooldown (not yet evaluated).
    pending_github_url: Optional[str] = None
    pending_agent_name: Optional[str] = None
    pending_agent_image: Optional[str] = None
    pending_normalized_repo: Optional[str] = None
    pending_ref: Optional[str] = None
    pending_received_round: Optional[int] = None
