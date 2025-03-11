from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_web_agents_subnet.protocol import (
    TaskFeedbackSynapse,
)
from autoppia_web_agents_subnet.validator.utils import (
    update_miner_stats_and_scores,
)
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.protocol import TaskSynapse
import bittensor as bt
import copy
from typing import List, Dict, Any
import asyncio
import numpy as np


async def send_feedback_synapse_to_miners(
    validator,
    miner_axons: List[bt.axon],
    miner_uids: List[int],
    task: Task,
    task_solutions: List[TaskSolution],
    test_results_matrices: List[List[List[Any]]],
    evaluation_results: List[Dict[str, Any]],
    screenshot_policy: str = "remove"
) -> None:
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
    """
    feedback_list = []

    for i, miner_uid in enumerate(miner_uids):
        # Make a shallow copy so we can strip out large fields
        feedback_task = copy.copy(task)

        # # Remove or strip heavy fields if screenshot_policy is "remove"
        # if screenshot_policy == "remove":
        #     feedback_task.screenshot = ""
        #     feedback_task.html = ""
        #     feedback_task.clean_html = ""

        # Build the feedback synapse
        feedback = TaskFeedbackSynapse(
            version=__version__,
            miner_id=str(miner_uid),
            task=task,
            actions=task_solutions[i].actions if i < len(task_solutions) else [],
            test_results_matrix=test_results_matrices[i] if i < len(test_results_matrices) else None,
            evaluation_result=evaluation_results[i] if i < len(evaluation_results) else None,
            stats=None, 
        )

        feedback_list.append(feedback)

    ColoredLogger.info(
        f"Sending TaskFeedbackSynapse to {len(miner_axons)} miners in parallel",
        ColoredLogger.BLUE,
    )

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
    miner_uids: List[int],
    execution_times: List[float],
    task_solutions,
    rewards: np.ndarray,
    test_results_matrices,
    evaluation_results
) -> dict:
    """
    Handles post-evaluation steps:
      1) Collecting stats about responses (success, no-response, etc.).
      2) Updating miner stats and scores.
      3) Sending feedback synapse to miners.
      4) Returning computed statistics for this specific task iteration.
    """
    # Count valid (non-None) responses
    valid_responses_count = sum(resp is not None for resp in responses)
    num_no_response = 0
    num_success = 0
    num_wrong = 0

    if valid_responses_count == 0:
        num_no_response += 1

    if np.any(rewards > 0):
        num_success += 1
    else:
        if valid_responses_count > 0:
            num_wrong += 1

    # Miner request time average
    avg_miner_time = (sum(execution_times) / len(execution_times)) if execution_times else 0.0

    # Update miner stats and get evaluation time
    evaluation_time = await update_miner_stats_and_scores(
        validator, rewards, miner_uids, execution_times, task
    )

    # Average reward across miners
    avg_score_for_task = float(np.mean(rewards)) if len(rewards) > 0 else 0.0

    # Send feedback (includes test matrices & evaluation dict)
    miner_axons = [validator.metagraph.axons[uid] for uid in miner_uids]
    await send_feedback_synapse_to_miners(
        validator,
        miner_axons,
        miner_uids,
        task,
        task_solutions,
        test_results_matrices,
        evaluation_results
    )

    return {
        "num_no_response": num_no_response,
        "num_success": num_success,
        "num_wrong": num_wrong,
        "avg_miner_time": avg_miner_time,
        "avg_score_for_task": avg_score_for_task,
        "evaluation_time": evaluation_time
    }
