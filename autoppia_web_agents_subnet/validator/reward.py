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
from autoppia_iwa.src.evaluation.classes import EvaluationResult
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_iwa.src.demo_webs.classes import WebProject


def normalize_execution_times(times: List[Optional[float]]) -> List[float]:
    """
    Normalizes execution times to a [0..1] range (1 is the fastest, 0 is slowest).
    If all times are equal, returns an array of 1.0 for those that are not None.
    """
    if not times:
        return []

    valid_times = [t for t in times if t is not None]
    if not valid_times:
        return [0.0] * len(times)

    min_time = min(valid_times)
    max_time = max(valid_times)

    if max_time == min_time:
        # All times are the same -> each becomes 1.0
        return [1.0 if t is not None else 0.0 for t in times]

    normalized = [
        (max_time - t) / (max_time - min_time) if t is not None else 0.0 for t in times
    ]
    bt.logging.debug(f"Execution times: {times}, normalized times: {normalized}")
    return normalized


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
    Computes final reward for each solution.
    - base_score (from concurrent evaluator)
    - plus optional time factor
    - ensures a minimum reward if solution is non-empty.
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
            # No partial solution or evaluation is 0
            final_rewards.append(eval_score)
        else:
            combined = eval_weight * eval_score + time_weight * time_score
            final_rewards.append(combined)

    # If solution has no actions, set reward=0
    # If reward <=0 but has actions, set it to min_response_reward or min_correct_format_score
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
    Extended version of get_rewards that also returns:
    - test_results_matrices for each miner
    - detailed evaluation dict for each miner (with raw_score, final_score, reward_score, etc.)
    """
    bt.logging.info(
        f"Evaluating {len(task_solutions)} task solutions with detailed results"
    )

    # Evaluator configuration
    evaluator_config = EvaluatorConfig(
        save_results_in_db=False,
        exclude_random_passed_tests=True,
        normalize_scores=True,
        starting_url=task.url,
    )
    evaluator = ConcurrentEvaluator(web_project, evaluator_config)

    # We'll fill these as we go
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

        # For time factor, we "invert" time to 0..1
        max_time = 60.0  # or some other threshold
        # If a miner took > max_time, they get near 0 for time_factor
        # If they took near 0, they get 1

        for i, result in enumerate(detailed_results):
            # Test result matrix from the evaluator
            test_results_matrices.append(result.test_results_matrix)

            raw_score = result.final_score if result.final_score is not None else 0.0

            # Compute time_factor
            t = execution_times[i] if i < len(execution_times) else None
            if t is not None:
                time_factor = max(0.0, 1.0 - (t / max_time))  # 1->fast, 0->too slow
            else:
                time_factor = 0.0

            # Weighted final. This is different from result.final_score:
            # we add time factor here
            final_score_time_adjusted = (
                1.0 - time_weight
            ) * raw_score + time_weight * time_factor

            # Guarantee min reward if it has some valid format
            if raw_score >= min_correct_format_score:
                final_score_time_adjusted = max(
                    final_score_time_adjusted, min_response_reward
                )

            # We store the final reward in rewards[i]
            rewards[i] = final_score_time_adjusted

            # Build the evaluation dict
            eval_dict: Dict[str, Any] = {
                "raw_score": result.raw_score if result.raw_score is not None else 0.0,
                "final_score": raw_score,  # from the Evaluator
                "reward_score": final_score_time_adjusted,  # after time factor + min reward
                "random_clicker_score": (
                    result.random_clicker_score if result.random_clicker_score else 0.0
                ),
                "time_factor": time_factor,
                "execution_time": t,
            }

            # If there's feedback in the result (like passed/failed tests count, etc.)
            if result.feedback:
                eval_dict["feedback"] = {
                    "passed_tests": getattr(result.feedback, "passed_tests", 0),
                    "failed_tests": getattr(result.feedback, "failed_tests", 0),
                    "total_execution_time": getattr(
                        result.feedback, "total_execution_time", 0.0
                    ),
                    "executed_actions": getattr(result.feedback, "executed_actions", 0),
                    "failed_actions": getattr(result.feedback, "failed_actions", 0),
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


async def _evaluate_all_task_solutions(
    web_project: WebProject, task: Task, task_solutions: List[TaskSolution]
) -> List[float]:
    """
    Simplified utility to get a 'base' score from each solution using the Evaluator.
    """
    start_time = time.time()
    evaluator_config = EvaluatorConfig(starting_url=task.url)
    evaluator = ConcurrentEvaluator(web_project, evaluator_config)

    try:
        results: List[EvaluationResult] = await evaluator.evaluate_task_solutions(
            task=task, task_solutions=task_solutions
        )
        # We just extract result.final_score or 0
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
