# autoppia_web_agents_subnet/validator/eval.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Iterable
import numpy as np
from numpy.typing import NDArray
import bittensor as bt

from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.evaluation.evaluator.evaluator import (
    ConcurrentEvaluator,
    EvaluatorConfig,
)


def _test_result_to_dict(tr: Any) -> Dict[str, Any]:
    """
    Converts a TestResult-like object to a compact, JSON-safe dict.
    Only keeps simple, generally-present attributes.
    """
    try:
        # Common attributes on typical test result objects
        success = bool(getattr(tr, "success", False))
        message = str(getattr(tr, "message", ""))
        name = str(getattr(tr, "name", "")) if hasattr(tr, "name") else ""
        return {"success": success, "message": message, "name": name}
    except Exception:
        # Fallback very defensive path
        return {"success": False, "message": "unserializable test result"}


async def evaluate_task_solutions(
    *,
    web_project: WebProject,
    task: Task,
    task_solutions: List[Optional[TaskSolution]],  # aligned to miner_uids
    execution_times: List[float],                  # aligned to miner_uids (not used here, but kept for interface symmetry)
    normalize_scores: bool = True,
) -> Tuple[NDArray[np.float32], List[List[Any]], List[Dict[str, Any]]]:
    """
    Single evaluation entrypoint.

    Returns:
      - eval_scores: float32 array in [0,1], aligned with input miners
      - test_results_list: per-miner list of test result dicts (List[List[Dict]])
      - evaluation_results: per-miner summary dicts
    """
    # Replace Nones with empty-action solutions to keep alignment consistent
    safe_solutions: List[TaskSolution] = [
        s if s is not None else TaskSolution(actions=[]) for s in task_solutions
    ]

    cfg = EvaluatorConfig(normalize_scores=normalize_scores)
    evaluator = ConcurrentEvaluator(web_project, cfg)

    try:
        detailed_results = await evaluator.evaluate_task_solutions(
            task=task,
            task_solutions=safe_solutions,
        )
    except Exception as e:
        bt.logging.error(f"Evaluator failed for task '{task.prompt}': {e}")
        n = len(safe_solutions)
        return (
            np.zeros(n, dtype=np.float32),
            [[] for _ in range(n)],
            [{} for _ in range(n)],
        )

    # Build outputs with careful defaults
    eval_scores: List[float] = []
    test_results_list: List[List[Any]] = []  # Simplified: one list per miner
    evaluation_results: List[Dict[str, Any]] = []

    for res in detailed_results:
        score = float(getattr(res, "final_score", 0.0) or 0.0)
        eval_scores.append(score)

        # Tests - simple list of test results
        tr_list: Iterable[Any] = getattr(res, "test_results", []) or []
        tr_dicts = [_test_result_to_dict(tr) for tr in tr_list]
        test_results_list.append(tr_dicts)  # Just a simple list, no 2-level nesting

        # Summary (add simple, durable fields only)
        evaluation_results.append({
            "final_score": score,
            "version_ok": bool(getattr(res, "version_ok", True)),
            "notes": str(getattr(res, "notes", "")) if hasattr(res, "notes") else "",
        })

    scores_arr = np.asarray(eval_scores, dtype=np.float32).ravel()
    np.clip(scores_arr, 0.0, 1.0, out=scores_arr)
    return scores_arr, test_results_list, evaluation_results
