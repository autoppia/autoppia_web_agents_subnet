import random
import time
import numpy as np
import bittensor as bt
import copy
from typing import List, Dict, Any
import asyncio

from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.demo_webs.utils import initialize_demo_webs_projects
from autoppia_iwa.src.demo_webs.config import demo_web_projects

from autoppia_web_agents_subnet.protocol import (
    TaskSynapse,
    TaskFeedbackSynapse,
    MinerStats,
)
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries
from autoppia_web_agents_subnet.utils.logging import ColoredLogger

from autoppia_web_agents_subnet.validator.config import (
    MAX_ACTIONS_LENGTH,
    TIME_WEIGHT,
    TIMEOUT
)
from autoppia_web_agents_subnet import __version__
from copy import deepcopy


# --------------------------------------------------------------------
# MINER STATS INIT
# --------------------------------------------------------------------


def init_miner_stats(validator) -> None:
    """
    Ensure `validator.miner_stats` is initialized.
    """
    if not hasattr(validator, "miner_stats"):
        validator.miner_stats = {}
    if "aggregated" not in validator.miner_stats:
        validator.miner_stats["aggregated"] = MinerStats()


# --------------------------------------------------------------------
# VALIDATOR-LEVEL PERFORMANCE STATS
# --------------------------------------------------------------------

def init_validator_performance_stats(validator) -> None:
    """
    Initialize a performance statistics dictionary on the validator if not present.
    This dictionary will track data across multiple forward calls.
    """
    if not hasattr(validator, "validator_performance_stats"):
        validator.validator_performance_stats = {
            "total_forwards_count": 0,           # how many forward passes occurred
            "total_forwards_time": 0.0,          # sum of all forward iteration times

            "total_tasks_generated": 0,          # how many tasks have been generated in total
            "total_generated_tasks_time": 0.0,   # total time spent generating tasks

            "total_processing_tasks_time": 0.0,  # total time spent in process_tasks

            "total_tasks_sent": 0,               # how many tasks have been sent overall (accum. from all forwards)
            "total_tasks_success": 0,            # tasks with at least one reward>0
            "total_tasks_wrong": 0,              # tasks with responses but no reward>0
            "total_tasks_no_response": 0,        # tasks with 0 valid responses

            "total_sum_of_avg_response_times": 0.0,  # sum of average miner solve times per task
            "total_sum_of_evaluation_times": 0.0,     # sum of times spent evaluating (score updates)
            "total_sum_of_avg_scores": 0.0,           # sum of average rewards per task

            "overall_tasks_processed": 0,             # total tasks processed for stats
        }


def update_validator_performance_stats(
    validator,
    tasks_count: int,
    num_success: int,
    num_wrong: int,
    num_no_response: int,
    sum_of_avg_response_times: float,
    sum_of_evaluation_times: float,
    sum_of_avg_scores: float
) -> None:
    """
    Accumulates stats from a single batch of processed tasks into
    the validator's performance stats dictionary.
    """
    if not hasattr(validator, "validator_performance_stats"):
        init_validator_performance_stats(validator)

    vps = validator.validator_performance_stats

    # update global counters
    vps["total_tasks_sent"] += tasks_count
    vps["total_tasks_success"] += num_success
    vps["total_tasks_wrong"] += num_wrong
    vps["total_tasks_no_response"] += num_no_response

    # sums used to compute averages
    vps["total_sum_of_avg_response_times"] += sum_of_avg_response_times
    vps["total_sum_of_evaluation_times"] += sum_of_evaluation_times
    vps["total_sum_of_avg_scores"] += sum_of_avg_scores

    vps["overall_tasks_processed"] += tasks_count


def print_validator_performance_stats(validator) -> None:
    """
    Pretty-prints the validator performance stats using a Rich-styled table.
    """
    from rich.table import Table
    from rich.console import Console
    from rich import box

    vps = getattr(validator, "validator_performance_stats", None)
    if not vps:
        bt.logging.warning("No validator performance stats to display.")
        return

    # Compute derived stats
    total_forwards = vps["total_forwards_count"]
    avg_forward_time = (
        vps["total_forwards_time"] / total_forwards if total_forwards > 0 else 0.0
    )

    total_gen_tasks = vps["total_tasks_generated"]
    avg_task_gen_time = (
        vps["total_generated_tasks_time"] / total_gen_tasks if total_gen_tasks > 0 else 0.0
    )

    overall_tasks = vps["overall_tasks_processed"]
    avg_processing_time_per_task = (
        vps["total_processing_tasks_time"] / overall_tasks if overall_tasks > 0 else 0.0
    )

    # success rate, etc
    tasks_sent = vps["total_tasks_sent"]
    tasks_success = vps["total_tasks_success"]
    tasks_wrong = vps["total_tasks_wrong"]
    tasks_no_resp = vps["total_tasks_no_response"]
    success_rate = (tasks_success / tasks_sent) if tasks_sent > 0 else 0.0

    avg_response_time = (
        vps["total_sum_of_avg_response_times"] / overall_tasks if overall_tasks > 0 else 0.0
    )
    avg_evaluation_time = (
        vps["total_sum_of_evaluation_times"] / overall_tasks if overall_tasks > 0 else 0.0
    )
    avg_score = (
        vps["total_sum_of_avg_scores"] / overall_tasks if overall_tasks > 0 else 0.0
    )

    console = Console()
    table = Table(
        title="[bold yellow]Validator Performance Stats[/bold yellow]",
        header_style="bold magenta",
        box=box.SIMPLE,
    )
    table.add_column("Stat", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Total Forwards", str(total_forwards))
    table.add_row("Average Forward Time (s)", f"{avg_forward_time:.2f}")

    table.add_row("Tasks Generated (total)", str(total_gen_tasks))
    table.add_row("Total Time Generating Tasks (s)", f"{vps['total_generated_tasks_time']:.2f}")
    table.add_row("Average Time per Generated Task (s)", f"{avg_task_gen_time:.2f}")

    table.add_row("Tasks Processed (total)", str(tasks_sent))
    table.add_row("Tasks with Success", str(tasks_success))
    table.add_row("Tasks with Wrong", str(tasks_wrong))
    table.add_row("Tasks with No Response", str(tasks_no_resp))
    table.add_row("Success Rate", f"{(success_rate * 100):.2f}%")

    table.add_row("Avg Miner Solve Time (s)", f"{avg_response_time:.2f}")
    table.add_row("Avg Evaluation Time per Task (s)", f"{avg_evaluation_time:.4f}")
    table.add_row("Avg Score per Task", f"{avg_score:.4f}")

    table.add_row("Total Time Processing Tasks (s)", f"{vps['total_processing_tasks_time']:.2f}")
    table.add_row("Average Processing Time per Task (s)", f"{avg_processing_time_per_task:.2f}")

    console.print(table)
    console.print()  # extra newline


# --------------------------------------------------------------------
# TASK / RESPONSE UTILITIES
# --------------------------------------------------------------------


def clean_miner_task(task: Task) -> Task:
    """
    Creates a shallow copy of the Task removing fields not needed by miners,
    and ensures the `html` attribute is never None.
    """
    task_copy = deepcopy(task)
    task_copy.tests = None
    task_copy.milestones = None

    # Ensure `html` is never None
    if hasattr(task_copy, "html") and task_copy.html is None:
        task_copy.html = ""
    # Convert any string 'id' to int if needed
    if hasattr(task_copy, "id") and isinstance(task_copy.id, str):
        try:
            task_copy.id = int(task_copy.id)
        except ValueError:
            pass
    return task_copy


def collect_task_solutions(
    task: Task,
    responses: List[TaskSynapse],
    miner_uids: List[int],
) -> (List[TaskSolution], List[float]):
    """
    Collects TaskSolutions from the miners' responses and keeps track of their execution times.
    """
    task_solutions = []
    execution_times = []
    for miner_uid, response in zip(miner_uids, responses):
        try:
            task_solution = get_task_solution_from_synapse(
                task_id=task.id,
                synapse=response,
                web_agent_id=str(miner_uid),
            )
        except Exception as e:
            bt.logging.error(f"Error in Miner Response Format: {e}")
            task_solution = TaskSolution(
                task_id=task.id, actions=[], web_agent_id=str(miner_uid)
            )
        task_solutions.append(task_solution)
        if (
            response
            and hasattr(response.dendrite, "process_time")
            and response.dendrite.process_time is not None
        ):
            process_time = response.dendrite.process_time
        else:
            process_time = TIMEOUT
        execution_times.append(process_time)
    return task_solutions, execution_times


def get_task_solution_from_synapse(
    task_id, synapse: TaskSynapse, web_agent_id: str
) -> TaskSolution:
    """
    Safely extracts actions from a TaskSynapse response and creates a TaskSolution
    with the original task reference, limiting actions to a maximum of 15.
    """
    actions = []
    if synapse and hasattr(synapse, "actions") and isinstance(synapse.actions, list):
        actions = synapse.actions[:MAX_ACTIONS_LENGTH]  # Limit actions to at most 15

    # Create a TaskSolution with our trusted task object, not one from the miner
    return TaskSolution(task_id=task_id, actions=actions, web_agent_id=web_agent_id)


async def send_task_synapse_to_miners(
    validator,
    miner_axons: List[bt.axon],
    task_synapse: TaskSynapse,
    miner_uids: List[int],
) -> List[TaskSynapse]:
    """
    Sends a TaskSynapse to a list of miner axons and returns their responses.
    """
    bt.logging.info(f"Sending TaskSynapse to {len(miner_uids)} miners. Miner Timeout: {TIMEOUT}s")
    responses: List[TaskSynapse] = await dendrite_with_retries(
        dendrite=validator.dendrite,
        axons=miner_axons,
        synapse=task_synapse,
        deserialize=True,
        timeout=TIMEOUT,
    )
    num_valid_responses = sum(resp is not None for resp in responses)
    num_none_responses = len(responses) - num_valid_responses
    bt.logging.info(
        f"Received {len(responses)} responses: "
        f"{num_valid_responses} valid, {num_none_responses} errors."
    )
    return responses


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


async def update_miner_stats_and_scores(
    validator,
    rewards: np.ndarray,
    miner_uids: List[int],
    execution_times: List[float],
    task: Task,
) -> float:
    """
    Updates scores for miners based on computed rewards, updates local miner_stats,
    and returns the time it took to evaluate miners.
    """
    evaluation_time = 0.0
    if rewards is not None:
        evaluation_time_start = time.time()
        validator.update_scores(rewards, miner_uids)
        bt.logging.info("Scores updated for miners")

        for i, miner_uid in enumerate(miner_uids):
            score_value = rewards[i] if rewards[i] is not None else 0.0
            exec_time_value = (
                execution_times[i] if execution_times[i] is not None else TIMEOUT
            )
            success = score_value >= TIME_WEIGHT
            if miner_uid not in validator.miner_stats:
                validator.miner_stats[miner_uid] = MinerStats()
            validator.miner_stats[miner_uid].update(
                score=float(score_value),
                execution_time=float(exec_time_value),
                evaluation_time=(time.time() - evaluation_time_start),
                last_task=task,
                success=success,
            )
            validator.miner_stats["aggregated"].update(
                score=float(score_value),
                execution_time=float(exec_time_value),
                evaluation_time=(time.time() - evaluation_time_start),
                last_task=task,
                success=success,
            )
        evaluation_time_end = time.time()
        evaluation_time = evaluation_time_end - evaluation_time_start
    return evaluation_time


async def retrieve_random_demo_web_project() -> WebProject:
    """
    Retrieves a random demo web project from the available ones.
    Raises an Exception if none are available.
    """
    web_projects = await initialize_demo_webs_projects(demo_web_projects)
    bt.logging.debug(f"Retrieved {len(web_projects)} demo web projects.")
    if not web_projects:
        raise Exception("No demo web projects available.")
    project = random.choice(web_projects)
    ColoredLogger.info(
        f"Generating tasks for Web Project: '{project.name}'",
        ColoredLogger.YELLOW,
    )
    return project
