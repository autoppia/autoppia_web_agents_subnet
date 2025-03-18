import numpy as np
from typing import List, Optional, Dict, Any, Tuple, Set
import bittensor as bt
from autoppia_iwa.src.evaluation.evaluator.evaluator import (
    ConcurrentEvaluator,
    EvaluatorConfig,
)
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.evaluation.classes import EvaluationResult
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_web_agents_subnet.utils.logging import ColoredLogger

APPLY_WEIGHTS_VERSION_CHECK_PENALTY = False


def _test_result_to_dict(tr: Any) -> Dict[str, Any]:
    """
    Converts a TestResult-like object to a dictionary that's JSON-serializable.
    We only keep attributes like 'success', 'message', etc.
    """
    if hasattr(tr, "success"):
        return {
            "success": bool(getattr(tr, "success", False)),
            "message": str(getattr(tr, "message", "")),
        }
    elif isinstance(tr, dict):
        # Already a dict
        return tr
    else:
        # fallback minimal
        return {"success": False, "message": f"Unknown object {str(tr)}"}


def _convert_test_results_matrix(
    test_results_matrix: Optional[List[List[Any]]],
) -> List[List[Dict[str, Any]]]:
    """
    Safely converts each item in test_results_matrix into a JSON-friendly dictionary.
    """
    if not test_results_matrix:
        return []

    matrix_converted = []
    for test_result in test_results_matrix:
        row = [_test_result_to_dict(tr) for tr in test_result]

        matrix_converted.append(row)
    return matrix_converted


def _normalize_times_for_valid_solutions(
    execution_times: List[Optional[float]],
    raw_scores: List[float],
) -> List[float]:
    """
    Normalize execution times only over solutions that have raw_score > 0:
      - If raw_score > 0 AND we have a valid execution_time, that time is included
        for computing [0..1] range (min_time -> max_time).
      - Solutions with raw_score <= 0 or None times are assigned a factor of 0.0
        and also excluded from min/max computations.

    Return a list of time_factors (same length as `execution_times`).
    """
    print("Scores and times lengths")
    print(len(raw_scores))
    print(len(execution_times))
    # Gather (time, idx) only for solutions that have raw_score > 0 and valid time
    valid_pairs = [
        (t, idx)
        for idx, t in enumerate(execution_times)
        if t is not None and raw_scores[idx] > 0
    ]
    n = len(execution_times)

    # If no valid times at all => everyone gets 0.0
    if not valid_pairs:
        return [0.0] * n

    valid_times = [vp[0] for vp in valid_pairs]
    min_time = min(valid_times)
    max_time = max(valid_times)
    denom = max_time - min_time if max_time > min_time else 1e-9

    time_factors = [0.0] * n  # default all 0.0
    for t, idx in valid_pairs:
        factor = 1.0 - ((t - min_time) / denom)
        factor = max(0.0, min(factor, 1.0))  # clamp to [0,1]
        time_factors[idx] = factor

    return time_factors


def _apply_invalid_version_responders(
    invalid_version_responders: Optional[Set[int]],
    task_solutions: List[TaskSolution],
    rewards: np.ndarray,
    evaluation_results: List[Dict[str, Any]],
) -> None:
    """
    If a responder is in invalid_version_responders, set that solution's
    reward to 0 (overriding any previous computation).
    """
    if not invalid_version_responders:
        return

    for i, solution in enumerate(task_solutions):
        try:
            miner_uid = int(solution.web_agent_id)
        except ValueError:
            miner_uid = -1

        if miner_uid in invalid_version_responders:
            rewards[i] = 0.0
            if i < len(evaluation_results):
                evaluation_results[i]["reward_score"] = 0.0


def _process_evaluation_results(
    detailed_results: List[EvaluationResult],
    rewards: np.ndarray,
    test_results_matrices: List[List[List[Any]]],
    evaluation_results: List[Dict[str, Any]],
    execution_times: List[float],
    time_weight: float,
    min_correct_format_score: float,
    min_response_reward: float,
) -> Tuple[np.ndarray, List[List[List[Any]]], List[Dict[str, Any]]]:
    """
    1. Convert test_results_matrix to JSON-friendly shape.
    2. Compute the final reward as (1 - time_weight)*raw_score + time_weight*time_factor,
       where time_factor is normalized *only over solutions with raw_score>0*.
       - If raw_score <= 0, final_score is 0.0 (i.e., no time bonus).
       - If raw_score >= min_correct_format_score, ensure at least min_response_reward.
    """
    # Gather raw_scores
    raw_scores = [
        (r.final_score if r.final_score is not None else 0.0) for r in detailed_results
    ]

    # Create time_factors only for solutions with raw_score>0
    time_factors = _normalize_times_for_valid_solutions(execution_times, raw_scores)

    # For each result/solution, finalize the reward
    for i, result in enumerate(detailed_results):
        # 1) Convert test_results_matrix to JSON-friendly shape
        matrix_converted = _convert_test_results_matrix(result.test_results_matrix)
        test_results_matrices.append(matrix_converted)

        raw_score = raw_scores[i]
        time_factor = time_factors[i]

        # If the solution is valid (raw_score > 0), combine with time factor
        if raw_score > 0:
            final_score_time_adjusted = ((1.0 - time_weight) * raw_score) + (
                time_weight * time_factor
            )
            final_score_time_adjusted = max(0.0, min(final_score_time_adjusted, 1.0))
        else:
            final_score_time_adjusted = 0.0

        # Enforce a minimum reward if raw_score >= min_correct_format_score
        if raw_score >= min_correct_format_score:
            final_score_time_adjusted = max(
                final_score_time_adjusted, min_response_reward
            )

        rewards[i] = final_score_time_adjusted

        # Build a JSON-friendly dict for evaluation
        eval_dict: Dict[str, Any] = {
            "raw_score": float(result.raw_score or 0.0),
            "final_score": float(raw_score),
            "reward_score": float(final_score_time_adjusted),
            "random_clicker_score": float(result.random_clicker_score or 0.0),
            "time_factor": float(time_factor),
            "execution_time": (
                float(execution_times[i]) if i < len(execution_times) else None
            ),
        }

        # If there's feedback with test counts, add it
        if result.feedback:
            eval_dict["feedback"] = {
                "passed_tests": int(getattr(result.feedback, "passed_tests", 0)),
                "failed_tests": int(getattr(result.feedback, "failed_tests", 0)),
                "total_execution_time": float(
                    getattr(result.feedback, "total_execution_time", 0.0)
                ),
                "executed_actions": int(
                    getattr(result.feedback, "executed_actions", 0)
                ),
                "failed_actions": int(getattr(result.feedback, "failed_actions", 0)),
            }

        evaluation_results.append(eval_dict)

    return rewards, test_results_matrices, evaluation_results


async def get_rewards_with_details(
    validator,
    web_project: WebProject,
    task: Task,
    task_solutions: List[TaskSolution],
    execution_times: List[float],
    time_weight: float = 0.2,
    min_correct_format_score: float = 0.1,
    min_response_reward: float = 0.0,
    invalid_version_responders: Optional[Set[int]] = None,
) -> Tuple[np.ndarray, List[List[List[Any]]], List[Dict[str, Any]]]:
    """
    Extended version returning:
      - rewards array
      - test_results_matrices (JSON-friendly)
      - evaluation_results (dictionaries with raw_score, final_score, etc.)

    If a miner is in 'invalid_version_responders', we override that miner's reward to 0.

    The main fix: we only normalize execution_time among solutions with raw_score>0.
    """
    bt.logging.info(
        f"Evaluating {len(task_solutions)} task solutions with detailed results"
    )

    # Create the evaluator
    evaluator_config = EvaluatorConfig(
        save_results_in_db=False,
        normalize_scores=True,
    )
    evaluator = ConcurrentEvaluator(web_project, evaluator_config)

    # Prepare containers
    rewards = np.zeros(len(task_solutions))
    test_results_matrices: List[List[List[Any]]] = []
    evaluation_results: List[Dict[str, Any]] = []

    try:
        # Evaluate solutions
        detailed_results: List[EvaluationResult] = (
            await evaluator.evaluate_task_solutions(
                task=task, task_solutions=task_solutions
            )
        )

        (
            rewards,
            test_results_matrices,
            evaluation_results,
        ) = _process_evaluation_results(
            detailed_results=detailed_results,
            rewards=rewards,
            test_results_matrices=test_results_matrices,
            evaluation_results=evaluation_results,
            execution_times=execution_times,
            time_weight=time_weight,  # 20% goes to time
            min_correct_format_score=min_correct_format_score,
            min_response_reward=min_response_reward,
        )

    except Exception as e:
        raise e
        ColoredLogger.error(
            
            f"Error evaluating task solutions with details: {str(e)}",
            ColoredLogger.RED,
        )
        # In case of errors, set all rewards to 0, store empty test results, and note the error
        for i in range(len(task_solutions)):
            rewards[i] = 0.0
            test_results_matrices.append([])
            evaluation_results.append({"error": str(e), "reward_score": 0.0})

    # Override rewards for invalid-version responders if needed
    if APPLY_WEIGHTS_VERSION_CHECK_PENALTY:
        _apply_invalid_version_responders(
            invalid_version_responders=invalid_version_responders,
            task_solutions=task_solutions,
            rewards=rewards,
            evaluation_results=evaluation_results,
        )

    bt.logging.info(f"Detailed evaluation complete. Rewards: {rewards}")
    return rewards, test_results_matrices, evaluation_results
