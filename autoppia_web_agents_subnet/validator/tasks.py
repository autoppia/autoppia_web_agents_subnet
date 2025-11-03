from __future__ import annotations

"""Backward-compatible re-exports for task utilities."""

from autoppia_web_agents_subnet.validator.evaluation.tasks import (
    collect_task_solutions_and_execution_times,
    get_task_collection_interleaved,
    get_task_solution_from_synapse,
)

__all__ = [
    "get_task_collection_interleaved",
    "get_task_solution_from_synapse",
    "collect_task_solutions_and_execution_times",
]
