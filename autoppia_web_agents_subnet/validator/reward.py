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
    high_percentile: float = 90.0,
) -> List[float]:
    """
    Normalize execution times only over solutions that have raw_score > 0 and valid times,
    but clamp outliers at the given 'high_percentile' to avoid skewing.

    Returns a list of the same length as execution_times, where each element is in [0, 1].

    Steps:
      1) Collect valid times (where raw_score > 0 and time is not None).
      2) Compute min_time and clamp max_time at the desired percentile
      3) Factor = 1 - (time-min)/(max-min)
    """
    n = len(execution_times)
    time_factors = [0.0] * n

    valid_pairs = [(t, idx) for idx, t in enumerate(execution_times) if t is not None and raw_scores[idx] > 0]
    if not valid_pairs:
        return time_factors

    valid_times = np.array([vp[0] for vp in valid_pairs], dtype=float)
    min_time = float(np.min(valid_times))
    max_time = float(np.percentile(valid_times, high_percentile))

    denom = max_time - min_time
    if denom < 1e-9:
        # If all valid times are nearly identical => assign factor=1.0
        for _, idx in valid_pairs:
            time_factors[idx] = 1.0
        return time_factors

    for t, idx in valid_pairs:
        clamped_t = min(t, max_time)
        factor = 1.0 - ((clamped_t - min_time) / denom)
        factor = max(0.0, min(factor, 1.0))
        time_factors[idx] = factor

    return time_factors


def _normalize_action_lengths_for_valid_solutions(
    actions_lengths: List[int],
    raw_scores: List[float],
    high_percentile: float = 90.0,
) -> List[float]:
    """
    Normalize the "efficiency factor" based on the number of actions returned.
    Fewer actions => higher factor in [0,1].

    Steps:
      1) Collect valid lengths (raw_score > 0).
      2) Compute min_len and clamp max_len at the desired percentile.
      3) Efficiency factor = 1 - (length - min_len)/(max_len - min_len).
      4) If no valid solutions, return all zeros.
    """
    n = len(actions_lengths)
    eff_factors = [0.0] * n

    valid_pairs = [(l, idx) for idx, l in enumerate(actions_lengths) if raw_scores[idx] > 0]
    if not valid_pairs:
        return eff_factors

    valid_lengths = np.array([vp[0] for vp in valid_pairs], dtype=float)
    min_len = float(np.min(valid_lengths))
    max_len = float(np.percentile(valid_lengths, high_percentile))

    denom = max_len - min_len
    if denom < 1e-9:
        # If all lengths are nearly identical => assign factor=1.0
        for _, idx in valid_pairs:
            eff_factors[idx] = 1.0
        return eff_factors

    for length, idx in valid_pairs:
        clamped_len = min(length, max_len)
        factor = 1.0 - ((clamped_len - min_len) / denom)
        factor = max(0.0, min(factor, 1.0))
        eff_factors[idx] = factor

    return eff_factors


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
    actions_lengths: List[int],
    time_weight: float,
    efficiency_weight: float,
    min_correct_format_score: float,
    min_response_reward: float,
) -> Tuple[np.ndarray, List[List[List[Any]]], List[Dict[str, Any]]]:
    """
    1. Convert test_results_matrix to JSON-friendly shape.
    2. Compute final reward as:
         final_score = (1 - time_weight - efficiency_weight)*raw_score
                       + time_weight*time_factor
                       + efficiency_weight*eff_factor
       - If raw_score <= 0 => final_score=0.0
       - If raw_score >= min_correct_format_score => enforce min_response_reward
    """
    raw_scores = [(r.final_score if r.final_score is not None else 0.0) for r in detailed_results]

    # Time factor for solutions with raw_score>0
    time_factors = _normalize_times_for_valid_solutions(execution_times, raw_scores)

    # Efficiency factor for solutions with raw_score>0
    eff_factors = _normalize_action_lengths_for_valid_solutions(actions_lengths, raw_scores)

    for i, result in enumerate(detailed_results):
        # 1) Convert test_results_matrix to JSON-friendly shape
        matrix_converted = _convert_test_results_matrix(result.test_results_matrix)
        test_results_matrices.append(matrix_converted)

        raw_score = raw_scores[i]
        time_factor = time_factors[i]
        eff_factor = eff_factors[i]

        if raw_score > 0:
            combined_score = (1.0 - time_weight - efficiency_weight) * raw_score + time_weight * time_factor + efficiency_weight * eff_factor
            final_score_time_adjusted = max(0.0, min(combined_score, 1.0))
        else:
            final_score_time_adjusted = 0.0

        # Enforce a minimum reward if raw_score >= min_correct_format_score
        if raw_score >= min_correct_format_score:
            final_score_time_adjusted = max(final_score_time_adjusted, min_response_reward)

        rewards[i] = final_score_time_adjusted

        eval_dict: Dict[str, Any] = {
            "raw_score": float(result.raw_score or 0.0),
            "final_score": float(raw_score),
            "reward_score": float(final_score_time_adjusted),
            "time_factor": float(time_factor),
            "efficiency_factor": float(eff_factor),
            "execution_time": (float(execution_times[i]) if i < len(execution_times) else None),
            "actions_count": actions_lengths[i],
        }
        # If there's feedback with test counts, add it
        if result.feedback:
            eval_dict["feedback"] = {
                "passed_tests": int(getattr(result.feedback, "passed_tests", 0)),
                "failed_tests": int(getattr(result.feedback, "failed_tests", 0)),
                "total_execution_time": float(getattr(result.feedback, "total_execution_time", 0.0)),
                "executed_actions": int(getattr(result.feedback, "executed_actions", 0)),
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
    efficiency_weight: float = 0.15,  # NEW efficiency weight
    min_correct_format_score: float = 0.1,
    min_response_reward: float = 0.0,
    invalid_version_responders: Optional[Set[int]] = None,
) -> Tuple[np.ndarray, List[List[List[Any]]], List[Dict[str, Any]]]:
    """
    Extended version returning:
      - rewards array
      - test_results_matrices (JSON-friendly)
      - evaluation_results (dictionaries with raw_score, final_score, etc.)

    We now also incorporate an 'efficiency_factor' weighted at 15%, based on the number of actions.
    """
    bt.logging.info(f"Evaluating {len(task_solutions)} web_project:  {web_project.backend_url}")

    evaluator_config = EvaluatorConfig(
        # save_results_in_db=False,
        normalize_scores=True,
    )
    evaluator = ConcurrentEvaluator(web_project, evaluator_config)

    # Prepare containers
    rewards = np.zeros(len(task_solutions))
    test_results_matrices: List[List[List[Any]]] = []
    evaluation_results: List[Dict[str, Any]] = []

    # Collect the actions length for each solution
    actions_lengths = [len(sol.actions) for sol in task_solutions]

    try:
        # Evaluate solutions
        detailed_results: List[EvaluationResult] = await evaluator.evaluate_task_solutions(task=task, task_solutions=task_solutions)

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
            actions_lengths=actions_lengths,  # Pass in the new data
            time_weight=time_weight,
            efficiency_weight=efficiency_weight,
            min_correct_format_score=min_correct_format_score,
            min_response_reward=min_response_reward,
        )

    except Exception as e:
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

    return rewards, test_results_matrices, evaluation_results
