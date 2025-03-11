from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_web_agents_subnet.protocol import (
    TaskFeedbackSynapse,
)
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.protocol import TaskSynapse
import bittensor as bt
from typing import List, Dict, Any
import asyncio


async def send_feedback_synapse_to_miners(
    validator,
    miner_axons: List[bt.axon],
    miner_uids: List[int],
    task: Task,
    task_solutions: List[TaskSolution],
    test_results_matrices: List[List[List[Any]]],
    evaluation_results: List[Dict[str, Any]],
    screenshot_policy: str = "remove"
) -> List[List[TaskFeedbackSynapse]]:
    """
    Sends a TaskFeedbackSynapse to each miner with the relevant evaluation details.

    :param validator: The validator instance, which holds the dendrite and other context.
    :param miner_axons: List of miner axons corresponding to the chosen miner_uids.
    :param miner_uids: The UIDs of the miners to send feedback to.
    :param task: The original Task object.
    :param task_solutions: List of TaskSolution objects from each miner.
    :param test_results_matrices: List of test-result matrices returned by the reward function.
    :param evaluation_results: List of evaluation details for each miner (scores, etc.).
    :param screenshot_policy: Either "remove" or "keep". If "remove", the screenshot is cleared.
    :return: A list of responses from each miner (each response is typically a list of TaskFeedbackSynapse).
    """

    feedback_list = []

    for i, miner_uid in enumerate(miner_uids):
        # Optionally strip out large fields from the Task
        # if screenshot_policy == "remove":
        #     task.screenshot = ""
        #     task.html = ""
        #     if hasattr(task, "clean_html"):
        #         task.clean_html = ""

        # Build the feedback synapse
        feedback = TaskFeedbackSynapse(
            version=__version__,
            miner_id=str(miner_uid),
            task=task,
            actions=(
                task_solutions[i].actions if i < len(task_solutions) else []
            ),
            test_results_matrix=(
                test_results_matrices[i] if i < len(test_results_matrices) else None
            ),
            evaluation_result=(
                evaluation_results[i] if i < len(evaluation_results) else None
            ),
            stats=None,
        )

        feedback_list.append(feedback)

    ColoredLogger.info(
        f"Sending TaskFeedbackSynapse to {len(miner_axons)} miners in parallel",
        ColoredLogger.BLUE,
    )

    # Create tasks to send each feedback synapse (in parallel) via dendrite
    feedback_tasks = []
    for axon, feedback_synapse in zip(miner_axons, feedback_list):
        feedback_tasks.append(
            asyncio.create_task(
                dendrite_with_retries(
                    dendrite=validator.dendrite,
                    axons=[axon],
                    synapse=feedback_synapse,
                    deserialize=True,
                    timeout=60,  # adjust as needed
                )
            )
        )

    # Wait for all feedback requests to complete
    results = await asyncio.gather(*feedback_tasks)
    bt.logging.info("Feedback responses received from miners.")
    return results


async def handle_feedback_and_stats(
    validator,
    web_project: WebProject,
    task: Task,
    responses: List[TaskSynapse],
    miner_axons: List[bt.axon],                 # <-- Add the miner_axons
    miner_uids: List[int],
    execution_times: List[float],
    task_solutions: List[TaskSolution],
    rewards,
    test_results_matrices,
    evaluation_results,
):
    """
    Given all the data about a single task evaluation, update stats, store feedback
    if necessary, and return a dictionary with aggregated metrics for logging.
    """
    # -- Basic aggregator logic (unchanged) --
    num_no_response = sum(
        1 for sol in task_solutions if not sol.actions or len(sol.actions) == 0
    )
    successful_idx = [i for i, r in enumerate(rewards) if r >= 1.0]
    num_success = len(successful_idx)
    num_wrong = len([r for r in rewards if 0.0 < r < 1.0])

    avg_miner_time = sum(execution_times) / len(execution_times) if execution_times else 0
    evaluation_time = 0.0  # If you measure your evaluator time, assign it here
    avg_score_for_task = float(sum(rewards) / len(rewards)) if len(rewards) > 0 else 0.0

    # Update per-miner stats in the validator
    for i, uid in enumerate(miner_uids):
        miner_stats = validator.miner_stats[uid]
        success_bool = i in successful_idx
        miner_stats.update(
            score=float(rewards[i]),
            execution_time=execution_times[i],
            evaluation_time=evaluation_time,
            last_task=task,
            success=success_bool,
        )

    # -- Now send the TaskFeedbackSynapse to each miner so they have the evaluation details --
    feedback_responses = await send_feedback_synapse_to_miners(
        validator=validator,
        miner_axons=miner_axons,
        miner_uids=miner_uids,
        task=task,
        task_solutions=task_solutions,
        test_results_matrices=test_results_matrices,
        evaluation_results=evaluation_results,
        screenshot_policy="remove",  # or "keep", depending on your preference
    )

    ColoredLogger.info(
        f"Feedback synapse responses received: {feedback_responses}",
        ColoredLogger.BLUE,
    )

    # Return a dictionary for usage by the parent flow
    return {
        "num_no_response": num_no_response,
        "num_success": num_success,
        "num_wrong": num_wrong,
        "avg_miner_time": avg_miner_time,
        "evaluation_time": evaluation_time,
        "avg_score_for_task": avg_score_for_task,
    }
