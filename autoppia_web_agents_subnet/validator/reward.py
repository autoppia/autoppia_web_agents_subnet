import numpy as np
from typing import List
import bittensor as bt
from autoppia_iwa.src.evaluation.evaluator.evaluator import (
    ConcurrentEvaluator,
    EvaluatorConfig,
)
from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.evaluation.classes import EvaluationResult


def normalize_execution_times(times: List[float]) -> List[float]:
    if not times:
        return []
    min_time = min(times)
    max_time = max(times)
    if max_time == min_time:
        return [1.0 for _ in times]
    # Lower execution times are better
    normalized = [(max_time - t) / (max_time - min_time) for t in times]
    bt.logging.debug(f"Execution times: {times}, normalized times: {normalized}")
    return normalized


def get_rewards(
    self,
    task_solutions: List[TaskSolution],
    web_url: str,
    execution_times: List[float],
) -> np.ndarray:
    """
    Computes rewards by combining:
      - Evaluation score (80%)
      - Normalized execution time (20%)
    Final rewards are in the range [0, 1].
    """
    evaluator_config = EvaluatorConfig(current_url=web_url)
    evaluator = ConcurrentEvaluator(evaluator_config)

    evaluation_scores: List[float] = _evaluate_all_task_solutions(
        evaluator=evaluator,
        task_solutions=task_solutions
    )
    bt.logging.debug(f"Evaluation Scores: {evaluation_scores}")

    normalized_times = normalize_execution_times(execution_times)

    final_rewards = [
        0.8 * eval_score + 0.2 * time_score
        for eval_score, time_score in zip(evaluation_scores, normalized_times)
    ]
    bt.logging.debug(f"Final Rewards: {final_rewards}")

    return np.array(final_rewards)


def _evaluate_all_task_solutions(
    evaluator: ConcurrentEvaluator,
    task_solutions: List[TaskSolution]
) -> List[float]:
    try:
        results: List[EvaluationResult] = evaluator.evaluate_all_tasks(
            task_solutions=task_solutions
        )
        return [get_score_from_evaluation_result(r) for r in results]
    except Exception as exc:
        bt.logging.error(f"Error evaluating task solutions: {exc}")
        return []


def get_score_from_evaluation_result(result: EvaluationResult) -> float:
    return result.final_score
