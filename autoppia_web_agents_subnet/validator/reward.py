import numpy as np
from typing import List, Optional
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
        (max_time - t) / (max_time - min_time) if t is not None else 0.0
        for t in times
    ]
    bt.logging.debug(f"Execution times: {times}, normalized times: {normalized}")
    return normalized


async def get_rewards(
    self,
    task:Task,
    web_project:WebProject,
    task_solutions: List[TaskSolution],
    execution_times: List[float],
    time_weight: float = 0.2,
    min_correct_format_score: float = 0.1,
    min_response_reward: float = 0.01
) -> np.ndarray:

    evaluation_scores: List[float] = await _evaluate_all_task_solutions(
        web_project=web_project,
        task=task,
        task_solutions=task_solutions
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


async def _evaluate_all_task_solutions(
    web_project:WebProject,
    task:Task, 
    task_solutions: List[TaskSolution]
) -> List[float]:
    start_time = time.time()

    evaluator_config = EvaluatorConfig(current_url=task.url)
    evaluator = ConcurrentEvaluator(web_project, evaluator_config)

    try:
        results: List[EvaluationResult] = await evaluator.evaluate_task_solutions(
            task=task, task_solutions=task_solutions
        )
        scores = [get_score_from_evaluation_result(r) for r in results]
    except Exception as exc:
        bt.logging.error(f"Error evaluating task solutions: {exc}")
        scores = [0.0] * len(task_solutions)
    end_time = time.time()

    total_time = end_time - start_time
    avg_time = total_time / len(task_solutions) if task_solutions else 0.0
    ColoredLogger.info(f"Evaluation took {total_time:.3f}s total, average {avg_time:.3f}s per miner", ColoredLogger.YELLOW)

    return scores


def get_score_from_evaluation_result(result: EvaluationResult) -> float:
    if result.final_score is None:
        return 0.0
    return result.final_score
