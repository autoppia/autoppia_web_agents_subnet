import numpy as np
from typing import List, Optional, Dict, Any, Tuple
import time
import bittensor as bt
from autoppia_iwa.src.evaluation.evaluator.evaluator import (
    ConcurrentEvaluator,
    EvaluatorConfig,
)
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.evaluation.classes import EvaluationResult, TestResult
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_iwa.src.demo_webs.classes import WebProject


def normalize_execution_times(times: List[Optional[float]]) -> List[float]:
    """
    Normalizes execution times to a [0..1] range (1 = fastest, 0 = slowest).
    If all times are equal, returns 1.0 for those not None.
    """
    if not times:
        return []
    valid_times = [t for t in times if t is not None]
    if not valid_times:
        return [0.0] * len(times)
    min_time = min(valid_times)
    max_time = max(valid_times)

    if max_time == min_time:
        return [1.0 if t is not None else 0.0 for t in times]

    normalized = [
        (max_time - t) / (max_time - min_time) if t is not None else 0.0 for t in times
    ]
    bt.logging.debug(f"Execution times: {times}, normalized times: {normalized}")
    return normalized


def _test_result_to_dict(tr: Any) -> Dict[str, Any]:
    """
    Converts a TestResult-like object to a dictionary that's JSON-serializable.
    We only keep attributes like 'success', 'message', etc.
    If 'tr' is not recognized, we fallback to a minimal dict.
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


async def _evaluate_all_task_solutions(
    web_project: WebProject, task: Task, task_solutions: List[TaskSolution]
) -> List[float]:
    """
    A utility that fetches a 'base' numeric final_score from each solution
    using the concurrency evaluator.
    """
    start_time = time.time()
    evaluator_config = EvaluatorConfig(starting_url=task.url)
    evaluator = ConcurrentEvaluator(web_project, evaluator_config)

    try:
        results: List[EvaluationResult] = await evaluator.evaluate_task_solutions(
            task=task, task_solutions=task_solutions
        )
        # Just extract final_score or 0
        scores = [r.final_score if r.final_score is not None else 0.0 for r in results]
    except Exception as exc:
        bt.logging.error(f"Error evaluating task solutions: {exc}")
        scores = [0.0] * len(task_solutions)

    end_time = time.time()
    total_time = end_time - start_time
    avg_time = total_time / len(task_solutions) if task_solutions else 0.0
    ColoredLogger.info(
        f"Evaluation took {total_time:.3f}s total, average {avg_time:.3f}s per miner",
        ColoredLogger.YELLOW,
    )
    return scores


async def get_rewards(
    self,
    web_project: WebProject,
    task: Task,
    task_solutions: List[TaskSolution],
    execution_times: List[float],
    time_weight: float = 0.2,
    min_correct_format_score: float = 0.1,
    min_response_reward: float = 0.01,
) -> np.ndarray:
    """
    Computes final reward for each solution, with:
      - base score
      - time factor
      - ensures min reward if solution is non-empty
    """
    evaluation_scores: List[float] = await _evaluate_all_task_solutions(
        web_project=web_project, task=task, task_solutions=task_solutions
    )
    bt.logging.debug(f"Evaluation Scores: {evaluation_scores}")

    normalized_times = normalize_execution_times(execution_times)
    final_rewards = []
    eval_weight = 1.0 - time_weight

    for eval_score, time_score in zip(evaluation_scores, normalized_times):
        if eval_score <= 0.0:
            final_rewards.append(eval_score)
        else:
            combined = eval_weight * eval_score + time_weight * time_score
            final_rewards.append(combined)

    # If solution has no actions => reward=0
    # If reward <=0 but has actions => min_response_reward or min_correct_format_score
    for i, solution in enumerate(task_solutions):
        if not solution.actions:
            final_rewards[i] = 0.0
        else:
            if final_rewards[i] <= 0.0:
                final_rewards[i] = min_response_reward
            else:
                final_rewards[i] = max(final_rewards[i], min_correct_format_score)

    bt.logging.debug(f"Final Rewards after format checks: {final_rewards}")
    return np.array(final_rewards)


async def get_rewards_with_details(
    self,
    web_project: WebProject,
    task: Task,
    task_solutions: List[TaskSolution],
    execution_times: List[float],
    time_weight: float = 0.2,
    min_correct_format_score: float = 0.1,
    min_response_reward: float = 0.0,
) -> Tuple[np.ndarray, List[List[List[Any]]], List[Dict[str, Any]]]:
    """
    Extended version returning:
      - rewards array
      - test_results_matrices (JSON-friendly)
      - evaluation_results (dictionaries with raw_score, final_score, reward_score, etc.)
    """
    bt.logging.info(
        f"Evaluating {len(task_solutions)} task solutions with detailed results"
    )

    evaluator_config = EvaluatorConfig(
        save_results_in_db=False,
        exclude_random_passed_tests=True,
        normalize_scores=True,
        starting_url=task.url,
    )
    evaluator = ConcurrentEvaluator(web_project, evaluator_config)

    rewards = np.zeros(len(task_solutions))
    test_results_matrices: List[List[List[Any]]] = []
    evaluation_results: List[Dict[str, Any]] = []

    try:
        # Evaluate each solution in detail
        detailed_results: List[EvaluationResult] = (
            await evaluator.evaluate_task_solutions(
                task=task, task_solutions=task_solutions
            )
        )

        max_time = 60.0  # threshold for time penalty

        for i, result in enumerate(detailed_results):
            # 1) Convert test results to a JSON-friendly shape
            #    result.test_results_matrix might be something like
            #    List[List[TestResult]] or similar
            matrix_converted = []
            if result.test_results_matrix:
                for action_list in result.test_results_matrix:
                    # convert each test result to dict
                    row = [_test_result_to_dict(tr) for tr in action_list]
                    matrix_converted.append(row)
            else:
                matrix_converted = []

            test_results_matrices.append(matrix_converted)

            # 2) Compute raw_score & time factor
            raw_score = result.final_score if result.final_score is not None else 0.0
            t = execution_times[i] if i < len(execution_times) else None
            if t is not None:
                time_factor = max(0.0, 1.0 - (t / max_time))
            else:
                time_factor = 0.0

            final_score_time_adjusted = (
                1.0 - time_weight
            ) * raw_score + time_weight * time_factor

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
                "execution_time": float(t) if t is not None else None,
            }

            # 4) If there's feedback with test counts, etc.
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
                    "failed_actions": int(
                        getattr(result.feedback, "failed_actions", 0)
                    ),
                }

            evaluation_results.append(eval_dict)

    except Exception as e:
        bt.logging.error(f"Error evaluating task solutions with details: {e}")
        for i in range(len(task_solutions)):
            rewards[i] = 0.0
            test_results_matrices.append([])
            evaluation_results.append({"error": str(e), "reward_score": 0.0})

    bt.logging.info(f"Detailed evaluation complete. Rewards: {rewards}")
    return rewards, test_results_matrices, evaluation_results
