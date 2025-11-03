from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvaluationPhaseResult:
    tasks_completed: int
    finished_early: bool = False
