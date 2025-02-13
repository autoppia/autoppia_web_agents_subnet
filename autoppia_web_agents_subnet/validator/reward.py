import numpy as np
from typing import List
import bittensor as bt
from autoppia_iwa.src.evaluation.evaluator.evaluator import (
    ConcurrentEvaluator,
    EvaluatorConfig,
)
from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.evaluation.classes import EvaluationResult


def get_rewards(
    self,
    task_solutions: List[TaskSolution],
    web_url: str,
) -> np.ndarray:
    """
    Returns an array of rewards for the given query and responses,
    evaluating one Task per response with a ConcurrentEvaluator.

    Args:
        self: Typically your validator/neuron instance.
        query (int): The query index or step number.
        responses (List[TaskSynapse]): A list of TaskSynapse objects.
        web_url (str): The URL associated with the tasks.

    Returns:
        np.ndarray: An array of final scores for each response.
    """
    evaluator_config = EvaluatorConfig(current_url=web_url)
    evaluator = ConcurrentEvaluator(evaluator_config)

    final_scores: List[float] = _evaluate_all_task_solutions(
        evaluator=evaluator, task_solutions=task_solutions
    )

    return np.array(final_scores)


def _evaluate_all_task_solutions(
    evaluator: ConcurrentEvaluator, task_solutions: List[TaskSolution]
) -> List[float]:
    """
    Evaluates a single MinerResponse using evaluate_single_task.
    Returns the final_score (float) from the result feedback.
    """

    try:
        results: List[EvaluationResult] = evaluator.evaluate_all_tasks(
            task_solutions=task_solutions
        )

        scores = []
        for result in results:
            scores.append(get_score_from_evaluation_result(result=result))

    except Exception as exc:
        bt.logging.error(f"Error evaluating single response: {exc}")
        return


def get_score_from_evaluation_result(result: EvaluationResult) -> float:
    return result.final_score
