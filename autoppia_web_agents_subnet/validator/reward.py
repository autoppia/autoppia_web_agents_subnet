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


async def get_rewards_with_details(
    self,
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
      - test_results_matrices  (JSON-friendly)
      - evaluation_results (dictionaries with raw_score, final_score, etc.)

    If a miner is in the 'invalid_version_responders' set, we set that miner's reward to 0.
    """
    bt.logging.info(f"Evaluating {len(task_solutions)} task solutions with detailed results")

    # Create the evaluator and config
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
            # 1) Convert test results to JSON-friendly shape
            matrix_converted = []
            if result.test_results_matrix:
                for action_list in result.test_results_matrix:
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

            final_score_time_adjusted = (1.0 - time_weight) * raw_score + time_weight * time_factor

            # Ensure at least min_response_reward if the raw_score is >= min_correct_format_score
            if raw_score >= min_correct_format_score:
                final_score_time_adjusted = max(final_score_time_adjusted, min_response_reward)

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
        ColoredLogger.error(
            f"Error evaluating task solutions with details: {e}",
            ColoredLogger.RED,
        )
        for i in range(len(task_solutions)):
            rewards[i] = 0.0
            test_results_matrices.append([])
            evaluation_results.append({"error": str(e), "reward_score": 0.0})

    # ---------------------------------------------------
    # 5) Override the reward to 0 if the miner responded
    #    incorrectly to the *invalid version* check.
    # ---------------------------------------------------
    if invalid_version_responders is not None:
        for i, solution in enumerate(task_solutions):
            # If the miner's UID is in invalid_version_responders, set reward to 0
            try:
                miner_uid = int(solution.web_agent_id)
            except ValueError:
                miner_uid = -1

            if miner_uid in invalid_version_responders:
                # Set that miner's reward to 0, ignoring any prior calculation
                rewards[i] = 0.0
                if i < len(evaluation_results):
                    evaluation_results[i]["reward_score"] = 0.0

    bt.logging.info(f"Detailed evaluation complete. Rewards: {rewards}")
    return rewards, test_results_matrices, evaluation_results
