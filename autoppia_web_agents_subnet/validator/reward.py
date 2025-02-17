import numpy as np
from typing import List, Optional
import bittensor as bt
from autoppia_iwa.src.evaluation.evaluator.evaluator import (
    ConcurrentEvaluator,
    EvaluatorConfig,
)
from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.evaluation.classes import EvaluationResult


def normalize_execution_times(times: List[Optional[float]]) -> List[float]:
    if not times:
        return []

    valid_times = [t for t in times if t is not None]
    if not valid_times:
        return [0.0] * len(times)

    min_time = min(valid_times)
    max_time = max(valid_times)

    if max_time == min_time:
        # If they are all the same, assign 1.0 to any non-None and 0.0 to None
        return [1.0 if t is not None else 0.0 for t in times]

    # Best (lowest) time => 1.0, Worst (highest) time => 0.0
    normalized = [
        (max_time - t) / (max_time - min_time) if t is not None else 0.0
        for t in times
    ]

    bt.logging.debug(f"Execution times: {times}, normalized times: {normalized}")
    return normalized


async def get_rewards(
    self,
    task_solutions: List[TaskSolution],
    web_url: str,
    execution_times: List[float],
    time_weight: float = 0.2,
    min_correct_format_score: float = 0.1,
) -> np.ndarray:
    evaluator_config = EvaluatorConfig(current_url=web_url)
    evaluator = ConcurrentEvaluator(evaluator_config)

    evaluation_scores: List[float] = await _evaluate_all_task_solutions(
        evaluator=evaluator,
        task_solutions=task_solutions
    )
    bt.logging.debug(f"Evaluation Scores: {evaluation_scores}")

    normalized_times = normalize_execution_times(execution_times)

    final_rewards = []
    eval_weight = 1.0 - time_weight

    for eval_score, time_score in zip(evaluation_scores, normalized_times):
        combined = eval_weight * eval_score + time_weight * time_score
        final_rewards.append(combined)

    # Apply format checks
    for i, solution in enumerate(task_solutions):
        # If no actions => 0
        if not solution.actions:
            final_rewards[i] = 0.0
        else:
            # Ensure at least min_correct_format_score if actions are valid
            final_rewards[i] = max(final_rewards[i], min_correct_format_score)

    bt.logging.debug(f"Final Rewards after format checks: {final_rewards}")
    return np.array(final_rewards)


async def _evaluate_all_task_solutions(
    evaluator: ConcurrentEvaluator,
    task_solutions: List[TaskSolution]
) -> List[float]:
    try:
        results: List[EvaluationResult] = await evaluator.evaluate_all_tasks(
            task_solutions=task_solutions
        )
        return [get_score_from_evaluation_result(r) for r in results]
    except Exception as exc:
        bt.logging.error(f"Error evaluating task solutions: {exc}")
        # Return 0 for all in case of a global evaluation failure
        return [0.0] * len(task_solutions)


def get_score_from_evaluation_result(result: EvaluationResult) -> float:
    if result.final_score is None:
        return 0.0
    return result.final_score
