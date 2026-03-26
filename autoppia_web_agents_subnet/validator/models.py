from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from autoppia_iwa.src.data_generation.tasks.classes import Task

# IWA domain types
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.web_agents.classes import TaskSolution
from numpy.typing import NDArray

# ─────────────────────────────────────────────────────────────────────────────
# Task collection modeling
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ProjectTasks:
    """
    Tasks belonging to a single project.
    """

    project: WebProject
    tasks: list[Task]


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
    solutions: list[TaskSolution | None]  # aligned to miner_uids; None for non-responders
    execution_times: list[float]  # aligned to miner_uids


@dataclass
class ScoredTask:
    """
    Task record after evaluation + blending.
    """

    project: WebProject
    task: Task
    solutions: list[TaskSolution | None]  # aligned to miner_uids
    execution_times: list[float]  # aligned to miner_uids
    final_rewards: NDArray[np.float32]  # aligned to miner_uids
    test_results_matrices: list[list[list[Any]]]  # per-miner matrices (aligned)
    evaluation_results: list[dict[str, Any]]  # per-miner summaries (aligned)
    eval_scores: NDArray[np.float32]  # raw eval (aligned)


# Resultados de evaluación por tarea (separado del blending de recompensas)
@dataclass
class EvalOutput:
    eval_scores: NDArray[np.float32]  # vector alineado a uids activos
    test_results_matrices: list[list[list[Any]]]  # por-miner -> lista de tests
    evaluation_results: list[dict[str, Any]]  # por-miner -> dict resumenl


@dataclass
class AgentInfo:
    """
    Information about an agent.
    """

    uid: int
    agent_name: str
    github_url: str
    agent_image: str | None = None
    score: float | None = 0.0
    evaluated: bool = False
    # Best-effort submission identity: the commit of the submitted repo/ref (resolved by validator).
    normalized_repo: str | None = None
    git_commit: str | None = None
    # Rate limiting / scheduling metadata (validator-side).
    last_evaluated_round: int | None = None
    last_evaluated_season: int | None = None
    # Pending submission captured during cooldown (not yet evaluated).
    pending_github_url: str | None = None
    pending_agent_name: str | None = None
    pending_agent_image: str | None = None
    pending_normalized_repo: str | None = None
    pending_ref: str | None = None
    pending_received_round: int | None = None
    # When score is 0, optional reason for dashboard (e.g. over_cost_limit, task_timeout, deploy_failed).
    zero_reason: str | None = None
    early_stop_reason: str | None = None
    early_stop_message: str | None = None
