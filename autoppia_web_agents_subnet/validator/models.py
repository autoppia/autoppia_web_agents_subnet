from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, List, Optional, Tuple, Dict

import numpy as np
from numpy.typing import NDArray

# IWA domain types
from autoppia_iwa_module.autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa_module.autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa_module.autoppia_iwa.src.web_agents.classes import TaskSolution


# ─────────────────────────────────────────────────────────────────────────────
# Task plan modeling
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProjectTaskBatch:
    """
    A batch of tasks belonging to a single project.
    """
    project: WebProject
    tasks: List[Task]


@dataclass
class TaskPlan:
    """
    Full multi-project plan for a forward. Wraps convenience iterators and lookups.
    """
    batches: List[ProjectTaskBatch]

    def __len__(self) -> int:
        return sum(len(b.tasks) for b in self.batches)

    def empty(self) -> bool:
        return all(len(b.tasks) == 0 for b in self.batches)

    def iter_interleaved(self) -> Iterator[Tuple[WebProject, Task]]:
        """
        Round-robin interleave across project batches yielding (project, task).
        """
        queues: List[Tuple[WebProject, List[Task]]] = [
            (b.project, list(b.tasks)) for b in self.batches if b.tasks
        ]
        i = 0
        while queues:
            proj, q = queues[i % len(queues)]
            if q:
                yield proj, q.pop(0)
            if not q:
                queues.pop(i % len(queues))
            else:
                i += 1


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
