import random
import time
import numpy as np
import bittensor as bt
from copy import deepcopy
from typing import List, Dict, Any, Tuple, Optional
from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.data_generation.domain.classes import (
    Task,
    TaskGenerationConfig,
)
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.demo_webs.config import initialize_demo_webs_projects
from autoppia_iwa.src.data_generation.application.tasks_generation_pipeline import (
    TaskGenerationPipeline,
)
from autoppia_web_agents_subnet.validator.reward import (
    get_rewards_with_details,
)
from autoppia_web_agents_subnet.utils.uids import get_random_uids
from autoppia_web_agents_subnet.protocol import (
    TaskSynapse,
    TaskFeedbackSynapse,
    MinerStats,
)
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
import asyncio


TIMEOUT = 60 * 2  # 2 min
FORWARD_SLEEP_SECONDS = 60 * 1  # 1 min
TASK_SLEEP = 60 * 1  # 1 min
TIME_WEIGHT = 0.2
MIN_SCORE_FOR_CORRECT_FORMAT = 0.1  # 10%
MIN_RESPONSE_REWARD = 0
SAMPLE_SIZE = 256  # number of Miners
MAX_ACTIONS_LENGTH = 15
NUM_URLS = 1


def init_miner_stats(validator) -> None:
    """
    Ensure `validator.miner_stats` is initialized with a 'aggregated' key.
    """
    if not hasattr(validator, "miner_stats"):
        validator.miner_stats = {}
    if "aggregated" not in validator.miner_stats:
        validator.miner_stats["aggregated"] = MinerStats()


async def retrieve_random_demo_web_project() -> WebProject:
    """
    Retrieves a random demo web project.
    Raises if none are available.
    """
    demo_web_projects = await initialize_demo_webs_projects()
    bt.logging.debug(f"Retrieved {len(demo_web_projects)} demo web projects.")
    if not demo_web_projects:
        raise Exception("No demo web projects available.")

    project = random.choice(demo_web_projects)
    ColoredLogger.info(
        f"Generating tasks for Web Project: '{project.name}'", ColoredLogger.YELLOW
    )
    return project


async def generate_tasks_for_web_project(demo_web_project: WebProject) -> List[Task]:
    """
    Uses TaskGenerationPipeline to create tasks for the given web project.
    """
    config = TaskGenerationConfig(
        web_project=demo_web_project,
        save_domain_analysis_in_db=True,
        save_task_in_db=False,
        num_or_urls=NUM_URLS,
    )
    pipeline = TaskGenerationPipeline(config=config, web_project=demo_web_project)
    start_time = time.time()
    tasks_generated: List[Task] = await pipeline.generate()
    ColoredLogger.info(
        f"Generated {len(tasks_generated)} tasks in {time.time() - start_time:.2f}s",
        ColoredLogger.YELLOW,
    )

    for t in tasks_generated:
        ColoredLogger.info(
            f"Task {t.prompt}",
            ColoredLogger.BLUE,
        )

    return tasks_generated


async def process_tasks(validator, web_project, tasks_generated: List[Task]) -> None:
    """
    Processes each task in tasks_generated:
     - Creates TaskSynapse, sends to miners
     - Collects TaskSolutions
     - Evaluates solutions w/ details
     - Updates miner stats
     - Sends feedback to miners
    """
    total_time_start = time.time()
    tasks_count = 0
    tasks_total_time = 0.0
    ColoredLogger.info(
        f"VOY A PROCESAR LAS TAREAS",
        ColoredLogger.YELLOW,
    )
    for index, task in enumerate(tasks_generated):
        task_start_time = time.time()
        bt.logging.debug(
            f"Task #{index} (URL: {task.url} ID: {task.id}): {task.prompt}"
        )
        bt.logging.debug(f"Task tests {task.tests}")

        miner_task: Task = clean_miner_task(task=task)

        # Choose random subset of miners
        miner_uids = get_random_uids(validator, k=SAMPLE_SIZE)
        ColoredLogger.info(
            f"Miner UIDs chosen: {miner_uids}",
            ColoredLogger.RED,
        )
        miner_axons = [validator.metagraph.axons[uid] for uid in miner_uids]

        # Prepare synapse
        task_synapse = TaskSynapse(
            prompt=miner_task.prompt,
            url=miner_task.url,
            html=miner_task.html,
            screenshot=miner_task.screenshot,
            actions=[],
        )

        # Send to miners
        responses = await send_task_synapse_to_miners(
            validator, miner_axons, task_synapse, miner_uids
        )

        # Collect solutions
        task_solutions, execution_times = collect_task_solutions(
            task, responses, miner_uids
        )

        # Evaluate (with details: test matrix + evaluation dict)
        rewards, test_results_matrices, evaluation_results = (
            await compute_rewards_with_details(
                validator, web_project, task, task_solutions, execution_times
            )
        )

        bt.logging.info(f"Miners Final Rewards: {rewards}")

        # Update stats
        evaluation_time = await update_miner_stats_and_scores(
            validator, rewards, miner_uids, execution_times, task
        )

        bt.logging.info(f"VOY A ENVIAR FEEDBACK")
        # Send feedback
        await send_feedback_synapse_to_miners(
            validator,
            miner_axons,
            miner_uids,
            task,
            task_solutions,
            test_results_matrices,
            evaluation_results,
        )

        # Tally time
        task_end_time = time.time()
        task_duration = task_end_time - task_start_time
        tasks_count += 1
        tasks_total_time += task_duration

        avg_miner_time = (
            sum(execution_times) / len(execution_times) if execution_times else 0.0
        )

        ColoredLogger.info(
            f"Task iteration time: {task_duration:.2f}s, average miner request time: {avg_miner_time:.2f}s",
            ColoredLogger.YELLOW,
        )

        bt.logging.info(f"Sleeping for {TASK_SLEEP}s....")
        await asyncio.sleep(TASK_SLEEP)

    end_time = time.time()
    total_duration = end_time - total_time_start
    avg_task_time = tasks_total_time / tasks_count if tasks_count else 0.0

    bt.logging.info(
        f"Total tasks processed: {tasks_count}, total time: {total_duration:.2f}s, "
        f"average time per task: {avg_task_time:.2f}s"
    )


async def send_task_synapse_to_miners(
    validator,
    miner_axons: List[bt.axon],
    task_synapse: TaskSynapse,
    miner_uids: List[int],
) -> List[TaskSynapse]:
    """
    Sends a TaskSynapse to multiple miners, returns their responses.
    """
    bt.logging.info(f"Sending TaskSynapse to {len(miner_uids)} miners. Miner Timeout : {TIMEOUT}s")
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
        f"Received {len(responses)} responses: {num_valid_responses} valid, {num_none_responses} errors."
    )
    return responses


def collect_task_solutions(
    task: Task,
    responses: List[TaskSynapse],
    miner_uids: List[int],
) -> Tuple[List[TaskSolution], List[float]]:
    """
    Collects TaskSolutions from the miners' responses, also tracks process_time as execution_times.
    """
    task_solutions: List[TaskSolution] = []
    execution_times: List[float] = []

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


async def compute_rewards_with_details(
    validator,
    web_project: WebProject,
    task: Task,
    task_solutions: List[TaskSolution],
    execution_times: List[float],
) -> Tuple[np.ndarray, List[List[List[Any]]], List[Dict[str, Any]]]:
    """
    Calls get_rewards_with_details to produce:
      - final rewards
      - test_results_matrices
      - evaluation_results (dict with raw_score, final_score, reward_score, etc.)
    """
    evaluation_start_time = time.time()

    rewards, test_results_matrices, evaluation_results = await get_rewards_with_details(
        validator,
        web_project=web_project,
        task=task,
        task_solutions=task_solutions,
        execution_times=execution_times,
        time_weight=TIME_WEIGHT,
        min_correct_format_score=MIN_SCORE_FOR_CORRECT_FORMAT,
        min_response_reward=MIN_RESPONSE_REWARD,
    )

    evaluation_end_time = time.time()
    bt.logging.info(
        f"Rewards computed in {evaluation_end_time - evaluation_start_time:.2f}s."
    )
    return rewards, test_results_matrices, evaluation_results


async def update_miner_stats_and_scores(
    validator,
    rewards: np.ndarray,
    miner_uids: List[int],
    execution_times: List[float],
    task: Task,
) -> float:
    """
    Updates validator's miner scores + local MinerStats, returns time spent updating.
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

            # Update the miner's stats
            validator.miner_stats[miner_uid].update(
                score=float(score_value),
                execution_time=float(exec_time_value),
                evaluation_time=(time.time() - evaluation_time_start),
                last_task=task,
                success=success,
            )
            # Also update the aggregator
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


import copy
import asyncio
import bittensor as bt
from typing import List, Dict, Any
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.protocol import TaskFeedbackSynapse, MinerStats
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.web_agents.classes import TaskSolution


async def send_feedback_synapse_to_miners(
    validator,
    miner_axons: List[bt.axon],
    miner_uids: List[int],
    task: Task,
    task_solutions: List[TaskSolution],
    test_results_matrices: List[List[List[Any]]],
    evaluation_results: List[Dict[str, Any]],
) -> None:
    """
    Sends a TaskFeedbackSynapse to each miner, removing the screenshot
    (if you don't want to send the screenshot or heavy fields).
    """
    feedback_list = []
    for i, miner_uid in enumerate(miner_uids):
        feedback_task = copy.deepcopy(task)
        # Eliminar o dejar en None el screenshot en el feedback
        feedback_task.screenshot = ""
        feedback_task.html = ""
        feedback_task.clean_html = ""
        # Crear una copia para no modificar el 'Task' original:

        # Construir el TaskFeedbackSynapse con el 'Task' ya sin screenshot
        feedback = TaskFeedbackSynapse(
            version="v1",
            miner_id=str(miner_uid),
            task=feedback_task,
            actions=task_solutions[i].actions if i < len(task_solutions) else [],
            test_results_matrix=(
                test_results_matrices[i] if i < len(test_results_matrices) else None
            ),
            evaluation_result=(
                evaluation_results[i] if i < len(evaluation_results) else None
            ),
            stats=None,
        )
        ColoredLogger.info(
            f"{feedback.model_dump()}",
            ColoredLogger.BLUE,
        )
        ColoredLogger.info(
            f"{feedback_task.tests}",
            ColoredLogger.RED,
        )
        feedback_list.append(feedback)

    ColoredLogger.info(
        f"Sending TaskFeedbackSynapse to {len(miner_uids)} miners in parallel",
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
                    timeout=30,
                )
            )
        )

    results = await asyncio.gather(*feedback_tasks)
    bt.logging.info("TaskFeedbackSynapse responses received.")
    bt.logging.success("Task step completed successfully.")


def get_task_solution_from_synapse(
    task_id: Any, synapse: TaskSynapse, web_agent_id: str
) -> TaskSolution:
    """
    Safely extracts actions from a TaskSynapse response
    and builds a TaskSolution (max 15 actions).
    """
    actions = []
    if synapse and hasattr(synapse, "actions") and isinstance(synapse.actions, list):
        actions = synapse.actions[:MAX_ACTIONS_LENGTH]

    return TaskSolution(task_id=task_id, actions=actions, web_agent_id=web_agent_id)


def clean_miner_task(task: Task) -> Task:
    """
    Creates a shallow copy of the Task removing fields not needed by miners,
    ensures 'html' is never None, etc.
    """
    task_copy = deepcopy(task)
    task_copy.tests = None
    task_copy.milestones = None

    if hasattr(task_copy, "html") and task_copy.html is None:
        task_copy.html = ""

    if hasattr(task_copy, "id") and isinstance(task_copy.id, str):
        try:
            task_copy.id = int(task_copy.id)
        except ValueError:
            pass

    return task_copy


async def forward(self) -> None:
    """
    Main entry for the forward logic:
      1) random web project
      2) generate tasks
      3) process tasks
      4) sleep
    """
    try:
        init_miner_stats(self)
        bt.logging.info("Starting forward step.")

        demo_web_project: WebProject = await retrieve_random_demo_web_project()
        bt.logging.info(
            f"Selected demo web project with URL: {demo_web_project.frontend_url}"
        )

        tasks_generated = await generate_tasks_for_web_project(demo_web_project)
        if not tasks_generated:
            bt.logging.warning("No tasks generated, skipping forward step.")
            return

        # 3. Process each task
        await process_tasks(self, demo_web_project, tasks_generated)

        bt.logging.success("Forward step completed successfully.")
        bt.logging.info(f"Sleeping for {FORWARD_SLEEP_SECONDS}s....")
        await asyncio.sleep(FORWARD_SLEEP_SECONDS)

    except Exception as e:
        bt.logging.error(f"Error on validation forward: {e}")
