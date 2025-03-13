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


def _normalize_execution_times(execution_times: List[Optional[float]]) -> List[float]:
    """
    Normalize execution times across all miners to a [0.0 ... 1.0] range,
    where 1.0 is the fastest (minimum time) and 0.0 is the slowest (maximum time).

    - If there's only one miner with a valid time, give them a 1.0 if their raw score > 0.
    - Any None times become 0.0 (or you can decide a different default).
    """
    valid_times = [t for t in execution_times if t is not None]
    n = len(execution_times)

    # If no valid times at all, everything is 0.0
    if len(valid_times) == 0:
        return [0.0] * n

    # If there's exactly 1 valid time
    # We will just assign 1.0 if that solution has a positive raw score,
    # but we don't have the raw scores here, so we assign 1.0 for that single entry.
    # We'll later apply the "score > 0" condition in final blending.
    if len(valid_times) == 1:
        # Find the index of the single valid time
        single_time = valid_times[0]
        normalized = []
        for t in execution_times:
            if t is None:
                normalized.append(0.0)
            elif t == single_time:
                # We'll tentatively give 1.0, but final combination with raw_score
                # can override if raw_score = 0
                normalized.append(1.0)
            else:
                normalized.append(0.0)
        return normalized

    # General case: multiple valid times
    min_time = min(valid_times)
    max_time = max(valid_times)
    denom = max_time - min_time if max_time > min_time else 1e-9

    normalized_times = []
    for et in execution_times:
        if et is None:
            # If no reported time, treat as 0.0
            normalized_times.append(0.0)
        else:
            factor = 1.0 - ((et - min_time) / denom)
            # clamp to [0, 1]
            factor = max(0.0, min(factor, 1.0))
            normalized_times.append(factor)
    return normalized_times


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
    2. Compute the final reward as 80% from raw evaluation score
       and 20% from a time factor that's normalized among all miners.
       - If raw_score <= 0, final_score is 0.0 (i.e., no time bonus).
       - If raw_score >= min_correct_format_score, ensure at least min_response_reward.
    """
    # First, gather raw_scores and store them so we can handle them in a single pass.
    raw_scores = []
    for result in detailed_results:
        raw_scores.append(result.final_score if result.final_score is not None else 0.0)

    # Create the normalized time factors array
    time_factors = _normalize_execution_times(execution_times)

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
        else:
            final_score_time_adjusted = 0.0

        # Enforce a minimum reward if raw_score is above min_correct_format_score
        if raw_score >= min_correct_format_score:
            final_score_time_adjusted = max(
                final_score_time_adjusted, min_response_reward
            )

        rewards[i] = final_score_time_adjusted

        # 3) Build a JSON-friendly dict for evaluation
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

        # 4) If there's feedback with test counts, add it
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

    If a miner is in the 'invalid_version_responders' set, we set that miner's reward to 0.
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
        for i, (solution, result) in enumerate(zip(task_solutions, detailed_results)):
            ColoredLogger.info(
                f"DEBUG: i={i}, solution.web_agent_id={solution.web_agent_id}, result={result.test_results_matrix}",
                ColoredLogger.PURPLE,
            )
            # ...
        for i, solution in enumerate(task_solutions):
            bt.logging.info(
                f"MINER CHECK: i={i}, solution.web_agent_id={solution.web_agent_id}"
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
        ColoredLogger.error(
            f"Error evaluating task solutions with details: {str(e)}",
            ColoredLogger.RED,
        )
        # In case of errors, set all rewards to 0, store empty test results, and note the error
        for i in range(len(task_solutions)):
            rewards[i] = 0.0
            test_results_matrices.append([])
            evaluation_results.append({"error": str(e), "reward_score": 0.0})

    # If you want to override rewards for invalid-version responders:
    _apply_invalid_version_responders(
        invalid_version_responders=invalid_version_responders,
        task_solutions=task_solutions,
        rewards=rewards,
        evaluation_results=evaluation_results,
    )

    bt.logging.info(f"Detailed evaluation complete. Rewards: {rewards}")
    return rewards, test_results_matrices, evaluation_results
