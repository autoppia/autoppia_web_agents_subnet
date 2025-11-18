from __future__ import annotations

from typing import Any, Dict, List, Optional

import bittensor as bt
import numpy as np
from numpy.typing import NDArray

from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.evaluation.evaluator.evaluator import (
    ConcurrentEvaluator,
    EvaluatorConfig,
)
from autoppia_web_agents_subnet.validator.config import SHOULD_RECORD_GIF
from autoppia_web_agents_subnet.validator.penalties import apply_same_solution_penalty_with_meta


def _test_result_to_dict(tr: Any) -> Dict[str, Any]:
    """
    Converts a TestResult-like object to a compact, JSON-safe dict.
    TestResult has: success (bool) and extra_data (dict|None)
    """
    try:
        success = bool(getattr(tr, "success", False))
        extra_data = getattr(tr, "extra_data", None) or {}
        return {"success": success, "extra_data": extra_data}
    except Exception:
        return {"success": False, "extra_data": {}}


async def evaluate_task_solutions(
    *,
    web_project: WebProject,
    task: Task,
    task_solutions: List[Optional[TaskSolution]],
    normalize_scores: bool = True,
) -> tuple[
    NDArray[np.float32],
    List[List[Any]],
    List[Dict[str, Any]],
]:
    """
    Evaluate miner submissions using the IWA ConcurrentEvaluator.

    Returns:
      - eval_scores: float32 array in [0,1], aligned with input miners
      - test_results_list: per-miner list of test result dicts
      - evaluation_results: per-miner summary dicts (includes gif/error info)
    """
    safe_solutions: List[TaskSolution] = [
        s if s is not None else TaskSolution(actions=[]) for s in task_solutions
    ]
    cfg = EvaluatorConfig(
        normalize_scores=normalize_scores,
        should_record_gif=SHOULD_RECORD_GIF,
    )
    evaluator = ConcurrentEvaluator(web_project, cfg)

    try:
        detailed_results = await evaluator.evaluate_task_solutions(
            task=task,
            task_solutions=safe_solutions,
        )
    except Exception as exc:
        bt.logging.error(f"Evaluator failed for task '{task.prompt}': {exc}")
        n = len(safe_solutions)
        return (
            np.zeros(n, dtype=np.float32),
            [[] for _ in range(n)],
            [{} for _ in range(n)],
        )

    eval_scores: List[float] = []
    test_results_list: List[List[Any]] = []
    evaluation_results: List[Dict[str, Any]] = []

    for res in detailed_results:
        score = float(getattr(res, "final_score", 0.0) or 0.0)
        eval_scores.append(score)

        tr_list = getattr(res, "test_results", []) or []
        test_results_list.append([_test_result_to_dict(tr) for tr in tr_list])

        gif_recording = getattr(res, "gif_recording", None)
        if gif_recording:
            bt.logging.debug(f"🎬 GIF captured: {len(str(gif_recording))} bytes (base64)")

        error_msg = ""
        if hasattr(res, "stats") and res.stats:
            error_msg = str(getattr(res.stats, "error_message", "")) or ""

        evaluation_results.append(
            {
                "final_score": score,
                "version_ok": bool(getattr(res, "version_ok", True)),
                "notes": str(getattr(res, "notes", "")) if hasattr(res, "notes") else "",
                "error_message": error_msg,
                "gif_recording": gif_recording,
            }
        )

    scores_arr = np.asarray(eval_scores, dtype=np.float32).ravel()
    np.clip(scores_arr, 0.0, 1.0, out=scores_arr)

    penalized_scores, duplicate_groups = apply_same_solution_penalty_with_meta(
        safe_solutions,
        scores_arr,
    )

    try:
        penalized_mask = [False] * len(safe_solutions)
        for group_id, group in enumerate(duplicate_groups):
            for idx in group:
                penalized_mask[idx] = True
                if idx < len(evaluation_results) and isinstance(evaluation_results[idx], dict):
                    evaluation_results[idx]["same_solution_penalized"] = True
                    evaluation_results[idx]["same_solution_group_id"] = int(group_id)
                    evaluation_results[idx]["same_solution_group_size"] = int(len(group))
        for idx in range(len(safe_solutions)):
            if idx < len(evaluation_results) and isinstance(evaluation_results[idx], dict):
                evaluation_results[idx].setdefault("same_solution_penalized", penalized_mask[idx])
    except Exception:
        pass

    return penalized_scores.astype(np.float32), test_results_list, evaluation_results
