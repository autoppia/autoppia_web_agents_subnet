import asyncio
import random
import time
import numpy as np
import bittensor as bt
from copy import deepcopy
from typing import List
from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.data_generation.domain.classes import (
    WebProject,
    Task,
    TaskGenerationConfig,
    TasksGenerationOutput,
)
from autoppia_iwa.src.backend_demo_web.config import get_demo_webs_projects
from autoppia_iwa.src.data_generation.application.tasks_generation_pipeline import (
    TaskGenerationPipeline,
)
from autoppia_web_agents_subnet.validator.reward import get_rewards
from autoppia_web_agents_subnet.utils.uids import get_random_uids
from autoppia_web_agents_subnet.protocol import (
    TaskSynapse,
    TaskFeedbackSynapse,
    MinerStats,
)
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries
from autoppia_web_agents_subnet.utils.logging import ColoredLogger

# Constants
TIMEOUT = 120  # 2 Min
FORWARD_SLEEP_SECONDS = 60 * 5  # 5 Minutes
TASK_SLEEP = 60  # 1 Minute
TIME_WEIGHT = 0.2
MIN_SCORE_FOR_CORRECT_FORMAT = 0.1
MIN_RESPONSE_REWARD = 0.1
SAMPLE_SIZE = 256  # Number of Miners


async def forward(self) -> None:
    """
    Main entry point for the forward process:
      1. Retrieves random web project and generates tasks.
      2. Sends tasks to miners, gathers responses, evaluates them.
      3. Updates miners' scores and sends feedback.
      4. Sleeps to avoid flooding.
    """
    try:
        self._init_miner_stats()
        bt.logging.info("Starting forward step.")

        # 1. Retrieve a random demo web project
        demo_web_project = self._retrieve_random_demo_web_project()
        web_url = demo_web_project.frontend_url
        bt.logging.info(f"Selected demo web project with URL: {web_url}")

        # 2. Generate tasks
        tasks_generated = await self._generate_tasks_for_url(demo_web_project)
        if not tasks_generated:
            bt.logging.warning("No tasks generated, skipping forward step.")
            return

        # 3. Process each task
        await self._process_tasks(web_url, tasks_generated)

        bt.logging.success("Forward step completed successfully.")
        bt.logging.info(f"Sleeping for {FORWARD_SLEEP_SECONDS}s....")
        await asyncio.sleep(FORWARD_SLEEP_SECONDS)

    except Exception as e:
        bt.logging.error(f"Error on validation forward: {e}")


def _init_miner_stats(self) -> None:
    """
    Ensure `self.miner_stats` is initialized.
    """
    if not hasattr(self, "miner_stats"):
        self.miner_stats = {}
    if "aggregated" not in self.miner_stats:
        self.miner_stats["aggregated"] = MinerStats()


def _retrieve_random_demo_web_project(self) -> WebProject:
    """
    Retrieves a random demo web project from the available ones.
    Raises an Exception if none are available.
    """
    demo_web_projects = get_demo_webs_projects()
    bt.logging.debug(f"Retrieved {len(demo_web_projects)} demo web projects.")
    if not demo_web_projects:
        raise Exception("No demo web projects available.")

    project = random.choice(demo_web_projects)
    ColoredLogger.info(
        f"Generating tasks for Web Project: '{project.name}'",
        ColoredLogger.YELLOW,
    )
    return project


async def _generate_tasks_for_url(self, demo_web_project: WebProject) -> List[Task]:
    """
    Generates tasks for the given web project using the TaskGenerationPipeline.
    """
    config = TaskGenerationConfig(
        web_project=demo_web_project,
        save_web_analysis_in_db=True,
        save_task_in_db=False,
    )
    pipeline = TaskGenerationPipeline(config)
    start_time = time.time()
    output: TasksGenerationOutput = await pipeline.generate()
    tasks_generated = output.tasks

    ColoredLogger.info(
        f"Generated {len(tasks_generated)} tasks in {time.time() - start_time:.2f}s",
        ColoredLogger.YELLOW,
    )
    return tasks_generated


async def _process_tasks(self, web_url: str, tasks_generated: List[Task]) -> None:
    """
    Iterates over each task, sends it to the miners, evaluates responses, updates scores,
    and sends feedback. Also manages timing and logging.
    """
    total_time_start = time.time()
    tasks_count = 0
    tasks_total_time = 0.0

    for index, task in enumerate(tasks_generated):
        task_start_time = time.time()
        bt.logging.debug(f"Task #{index} (ID: {task.id}): {task.prompt}")

        # Clean task for miners
        miner_task: Task = _clean_miner_task(task=task)
        bt.logging.info(f"Miner task: {miner_task}")

        # Get random UIDs & miner axons
        miner_uids = get_random_uids(self, k=SAMPLE_SIZE)
        bt.logging.info(f"Miner UIDs chosen: {miner_uids}")
        miner_axons = [self.metagraph.axons[uid] for uid in miner_uids]

        # Create synapse and send tasks
        task_synapse = TaskSynapse(
            prompt=miner_task.prompt,
            url=miner_task.url,
            actions=[],
        )
        responses = await self._send_task_synapse_to_miners(
            miner_axons, task_synapse, miner_uids
        )

        # Evaluate & compute rewards
        task_solutions, execution_times = self._collect_task_solutions(
            task, responses, miner_uids
        )
        rewards = await self._compute_rewards(
            task_solutions, web_url, execution_times
        )
        bt.logging.info(f"Miners Final Rewards: {rewards}")

        # Update miners' scores
        evaluation_time = await self._update_miner_stats_and_scores(
            rewards, miner_uids, execution_times, task
        )

        # Send feedback synapse
        await self._send_feedback_synapse_to_miners(miner_axons, miner_uids)

        task_end_time = time.time()
        task_duration = task_end_time - task_start_time
        tasks_count += 1
        tasks_total_time += task_duration

        avg_miner_time = (
            sum(execution_times) / len(execution_times) if execution_times else 0.0
        )
        ColoredLogger.info(
            f"Task analysis time: {task_duration:.2f}s, "
            f"average miner request time: {avg_miner_time:.2f}s, "
            f"evaluation time: {evaluation_time:.2f}s",
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


async def _send_task_synapse_to_miners(
    self,
    miner_axons: List[bt.axon],
    task_synapse: TaskSynapse,
    miner_uids: List[int],
) -> List[TaskSynapse]:
    """
    Sends a TaskSynapse to a list of miner axons and returns their responses.
    """
    bt.logging.info(f"Sending TaskSynapse to {len(miner_uids)} miners.")
    responses: List[TaskSynapse] = await dendrite_with_retries(
        dendrite=self.dendrite,
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


def _collect_task_solutions(
    self,
    original_task: Task,
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
            task_solution = _get_task_solution_from_synapse(
                task=original_task,
                synapse=response,
                web_agent_id=str(miner_uid),
            )
        except Exception as e:
            bt.logging.error(f"Error in Miner Response Format: {e}")
            task_solution = TaskSolution(
                task=original_task, actions=[], web_agent_id=str(miner_uid)
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


async def _compute_rewards(
    self,
    task_solutions: List[TaskSolution],
    web_url: str,
    execution_times: List[float],
) -> np.ndarray:
    """
    Computes the rewards for each miner based on their TaskSolutions.
    """
    evaluation_start_time = time.time()
    rewards: np.ndarray = await get_rewards(
        self,
        task_solutions=task_solutions,
        web_url=web_url,
        execution_times=execution_times,
        time_weight=TIME_WEIGHT,
        min_correct_format_score=MIN_SCORE_FOR_CORRECT_FORMAT,
        min_response_reward=MIN_RESPONSE_REWARD,
    )
    evaluation_end_time = time.time()
    bt.logging.info(
        f"Rewards computed in {evaluation_end_time - evaluation_start_time:.2f}s."
    )
    return rewards


async def _update_miner_stats_and_scores(
    self,
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
        # The get_rewards method encloses some of the evaluation logic time
        # We'll track only the update loop here if needed
        evaluation_time_start = time.time()

        self.update_scores(rewards, miner_uids)
        bt.logging.info("Scores updated for miners")

        for i, miner_uid in enumerate(miner_uids):
            score_value = rewards[i] if rewards[i] is not None else 0.0
            exec_time_value = (
                execution_times[i] if execution_times[i] is not None else TIMEOUT
            )
            success = score_value >= TIME_WEIGHT

            if miner_uid not in self.miner_stats:
                self.miner_stats[miner_uid] = MinerStats()

            self.miner_stats[miner_uid].update(
                score=float(score_value),
                execution_time=float(exec_time_value),
                evaluation_time=(time.time() - evaluation_time_start),
                last_task=task,
                success=success,
            )
            self.miner_stats["aggregated"].update(
                score=float(score_value),
                execution_time=float(exec_time_value),
                evaluation_time=(time.time() - evaluation_time_start),
                last_task=task,
                success=success,
            )

        evaluation_time_end = time.time()
        evaluation_time = evaluation_time_end - evaluation_time_start

    return evaluation_time


async def _send_feedback_synapse_to_miners(
    self,
    miner_axons: List[bt.axon],
    miner_uids: List[int],
) -> None:
    """
    Sends TaskFeedbackSynapse to each miner in parallel.
    """
    feedback_list = [
        TaskFeedbackSynapse(version="v1", stats=self.miner_stats[miner_uid])
        for miner_uid in miner_uids
    ]

    bt.logging.info(
        f"Sending TaskFeedbackSynapse to {len(miner_uids)} miners in parallel."
    )

    feedback_tasks = []
    for axon, feedback_synapse in zip(miner_axons, feedback_list):
        feedback_tasks.append(
            asyncio.create_task(
                dendrite_with_retries(
                    dendrite=self.dendrite,
                    axons=[axon],
                    synapse=feedback_synapse,
                    deserialize=True,
                    timeout=10,
                )
            )
        )

    _ = await asyncio.gather(*feedback_tasks)
    bt.logging.info("TaskFeedbackSynapse responses received.")
    bt.logging.success("Task step completed successfully.")


def _get_task_solution_from_synapse(
    task: Task, synapse: TaskSynapse, web_agent_id: str
) -> TaskSolution:
    """
    Safely extracts a TaskSolution from a TaskSynapse response.
    """
    if (
        not synapse
        or not hasattr(synapse, "actions")
        or not isinstance(synapse.actions, list)
    ):
        return TaskSolution(task=task, actions=[], web_agent_id=web_agent_id)
    return TaskSolution(task=task, actions=synapse.actions, web_agent_id=web_agent_id)


def _clean_miner_task(task: Task) -> Task:
    """
    Creates a shallow copy of the Task removing fields not needed by miners,
    and ensures the `html` attribute is never None.
    """
    task_copy = deepcopy(task)
    task_copy.tests = None
    task_copy.milestones = None
    task_copy.web_analysis = None

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
