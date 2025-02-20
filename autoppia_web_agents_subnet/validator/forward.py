import asyncio
import random
import time
import numpy as np
import bittensor as bt
from copy import deepcopy
from typing import List, Optional

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
from autoppia_web_agents_subnet.protocol import TaskSynapse, FeedbackSynapse, MinerStats

# Constants
TIMEOUT = 120
FORWARD_SLEEP_SECONDS = 60 * 10  # 10 Minutes
TASK_SLEEP = 60 * 3             # 3 Minutes
TIME_WEIGHT = 0.2
MIN_SCORE_FOR_CORRECT_FORMAT = 0.1
MIN_RESPONSE_REWARD = 0.1
SAMPLE_SIZE = 256  # All Miners


async def forward(self) -> None:
    try:
        self._init_miner_stats()

        bt.logging.info("Starting forward step for validator (vali).")

        demo_web_projects = get_demo_webs_projects()
        bt.logging.debug(f"Retrieved {len(demo_web_projects)} demo web projects.")

        demo_web_project = _select_demo_project(demo_web_projects)
        if demo_web_project is None:
            bt.logging.error("No valid demo web project selected. Aborting forward step.")
            return

        web_url = demo_web_project.frontend_url
        bt.logging.info(f"Selected demo web project with URL: {web_url}")

        bt.logging.warning(f"Generating tasks for Web Project: '{demo_web_project.name}'.")
        tasks_generated: List[Task] = await _generate_tasks_for_url(demo_web_project)
        if not tasks_generated:
            bt.logging.warning("No tasks generated. Skipping forward step.")
            return

        bt.logging.info(f"Generated {len(tasks_generated)} tasks for {web_url}")
        await _process_tasks(self, tasks_generated, web_url)

        bt.logging.success("Forward step completed successfully.")
        bt.logging.info(f"Sleeping for {FORWARD_SLEEP_SECONDS}s before next forward step.")
        await asyncio.sleep(FORWARD_SLEEP_SECONDS)

    except Exception as e:
        bt.logging.error(f"Error during forward step: {e}")


def _init_miner_stats(self) -> None:
    if not hasattr(self, "miner_stats"):
        self.miner_stats = {}
    if "aggregated" not in self.miner_stats:
        self.miner_stats["aggregated"] = MinerStats()
    bt.logging.debug("Initialized miner statistics.")


def _select_demo_project(projects: List[WebProject]) -> Optional[WebProject]:
    try:
        project = _get_random_demo_web_project(projects)
        bt.logging.debug(f"Randomly selected demo web project: {project.name}")
        return project
    except Exception as e:
        bt.logging.error(f"Failed to select a demo web project: {e}")
        return None


async def _process_tasks(self, tasks_generated: List[Task], web_url: str) -> None:
    total_time_start = time.time()
    tasks_count = 0
    tasks_total_time = 0.0

    for index, task in enumerate(tasks_generated):
        task_start_time = time.time()
        bt.logging.info(f"Processing Task #{index} (ID: {task.id}): {task.prompt}")

        miner_task: Task = _clean_miner_task(task)
        bt.logging.debug(f"Prepared miner task: {miner_task}")

        miner_uids = get_random_uids(self, k=SAMPLE_SIZE)
        bt.logging.info(f"Miner UIDs selected: {miner_uids}")

        miner_axons = [self.metagraph.axons[uid] for uid in miner_uids]
        responses: List[TaskSynapse] = await _send_task_to_miners(self, miner_axons, miner_task)
        bt.logging.info(f"Received {len(responses)} responses from miners.")

        task_solutions, execution_times = _process_responses(task, miner_uids, responses)

        evaluation_time = await _evaluate_and_update(self, task, web_url, miner_uids, task_solutions, execution_times)
        bt.logging.info(f"Completed evaluation for Task #{index} in {evaluation_time:.2f}s.")

        await _send_feedback(self, miner_axons, miner_uids)
        bt.logging.info("Feedback sent to miners.")

        task_duration = time.time() - task_start_time
        tasks_count += 1
        tasks_total_time += task_duration

        avg_miner_time = sum(execution_times) / len(execution_times) if execution_times else 0.0
        bt.logging.info(
            f"Task #{index} metrics: duration {task_duration:.2f}s, average miner response time {avg_miner_time:.2f}s, evaluation time {evaluation_time:.2f}s."
        )

        bt.logging.info(f"Sleeping for {FORWARD_SLEEP_SECONDS}s before processing next task...")
        await asyncio.sleep(FORWARD_SLEEP_SECONDS)

    total_duration = time.time() - total_time_start
    avg_task_time = tasks_total_time / tasks_count if tasks_count else 0.0
    bt.logging.info(
        f"Processed {tasks_count} tasks in {total_duration:.2f}s; average time per task: {avg_task_time:.2f}s."
    )


async def _send_task_to_miners(self, miner_axons: list, miner_task: Task) -> List[TaskSynapse]:
    bt.logging.info("Sending TaskSynapse to miners.")
    responses: List[TaskSynapse] = await _dendrite_with_retries(
        dendrite=self.dendrite,
        axons=miner_axons,
        synapses=[
            TaskSynapse(prompt=miner_task.prompt, url=miner_task.url, actions=[])
            for _ in miner_axons
        ],
        deserialize=True,
        timeout=TIMEOUT,
    )
    return responses


def _process_responses(task: Task, miner_uids: List, responses: List[TaskSynapse]) -> (List[TaskSolution], List[float]):
    task_solutions = []
    execution_times = []
    for miner_uid, response in zip(miner_uids, responses):
        if response:
            bt.logging.debug(f"Miner {miner_uid} returned actions: {response.actions}")
        else:
            bt.logging.debug(f"Miner {miner_uid} returned no response.")

        try:
            task_solution = _get_task_solution_from_synapse(task, response, str(miner_uid))
        except Exception as e:
            bt.logging.error(f"Error processing response from miner {miner_uid}: {e}")
            task_solution = TaskSolution(task=task, actions=[], web_agent_id=str(miner_uid))

        task_solutions.append(task_solution)
        process_time = getattr(response.dendrite, "process_time", TIMEOUT) if response else TIMEOUT
        execution_times.append(process_time)
    return task_solutions, execution_times


async def _evaluate_and_update(self, task: Task, web_url: str, miner_uids: List, task_solutions: List[TaskSolution], execution_times: List[float]) -> float:
    bt.logging.info("Evaluating miner responses and calculating rewards.")
    evaluation_start_time = time.time()
    rewards: np.ndarray = await get_rewards(
        self,
        task_solutions=task_solutions,
        web_url=web_url,
        execution_times=execution_times,
        time_weight=TIME_WEIGHT,
        min_correct_format_score=MIN_SCORE_FOR_CORRECT_FORMAT,
        min_response_reward=MIN_RESPONSE_REWARD
    )
    evaluation_time = time.time() - evaluation_start_time
    bt.logging.info(f"Calculated rewards for miners: {rewards}")

    self.update_scores(rewards, miner_uids)
    bt.logging.debug("Updated miner scores.")

    for i, miner_uid in enumerate(miner_uids):
        if miner_uid not in self.miner_stats:
            self.miner_stats[miner_uid] = MinerStats()
        self.miner_stats[miner_uid].update(
            score=float(rewards[i]),
            execution_time=float(execution_times[i]),
            evaluation_time=evaluation_time,
            last_task=task
        )
        self.miner_stats["aggregated"].update(
            score=float(rewards[i]),
            execution_time=float(execution_times[i]),
            evaluation_time=evaluation_time,
            last_task=task
        )
    return evaluation_time


async def _send_feedback(self, miner_axons: list, miner_uids: List) -> None:
    bt.logging.info("Preparing feedback for miners.")
    feedback_list = []
    for miner_uid in miner_uids:
        feedback_list.append(
            FeedbackSynapse(
                version="v1",
                stats=self.miner_stats[miner_uid],
            )
        )
    bt.logging.info("Sending feedback synapses to miners.")
    _ = await _dendrite_with_retries(
        dendrite=self.dendrite,
        axons=miner_axons,
        synapses=feedback_list,
        deserialize=True,
        timeout=TIMEOUT,
    )


async def _dendrite_with_retries(
    dendrite: bt.dendrite,
    axons: list,
    synapses: List[TaskSynapse],
    deserialize: bool,
    timeout: float,
    cnt_attempts=3
) -> List[TaskSynapse]:
    bt.logging.debug("Starting dendrite communication with retries.")
    res: List[Optional[TaskSynapse]] = [None] * len(axons)
    idx = list(range(len(axons)))
    current_axons = axons.copy()
    current_synapses = synapses.copy()

    for attempt in range(cnt_attempts):
        bt.logging.info(f"Dendrite attempt {attempt+1} for {len(current_axons)} axons.")
        responses: List[TaskSynapse] = await dendrite(
            axons=current_axons,
            synapses=current_synapses,
            deserialize=deserialize,
            timeout=timeout
        )

        new_idx = []
        new_axons = []
        new_synapses = []
        for i, syn_rsp in enumerate(responses):
            if syn_rsp.dendrite.status_code is not None and int(syn_rsp.dendrite.status_code) == 422:
                bt.logging.warning(f"Axon {current_axons[i]} returned status 422 on attempt {attempt+1}.")
                if attempt == cnt_attempts - 1:
                    res[idx[i]] = syn_rsp
                    bt.logging.info(f"Axon {current_axons[i]} failed after {cnt_attempts} attempts.")
                else:
                    new_idx.append(idx[i])
                    new_axons.append(current_axons[i])
                    new_synapses.append(current_synapses[i])
            else:
                res[idx[i]] = syn_rsp

        if new_idx:
            bt.logging.info(f"Retrying {len(new_idx)} axons with errors.")
            idx = new_idx
            current_axons = new_axons
            current_synapses = new_synapses
        else:
            break

    assert all(el is not None for el in res)
    return res


def _get_task_solution_from_synapse(
    task: Task,
    synapse: TaskSynapse,
    web_agent_id: str
) -> TaskSolution:
    if not synapse or not hasattr(synapse, 'actions') or not isinstance(synapse.actions, list):
        return TaskSolution(task=task, actions=[], web_agent_id=web_agent_id)
    return TaskSolution(task=task, actions=synapse.actions, web_agent_id=web_agent_id)


def _get_random_demo_web_project(projects: List[WebProject]) -> WebProject:
    if not projects:
        raise Exception("No projects available.")
    return random.choice(projects)


async def _generate_tasks_for_url(demo_web_project: WebProject) -> List[Task]:
    config = TaskGenerationConfig(
        web_project=demo_web_project,
        save_web_analysis_in_db=True,
        save_task_in_db=False
    )
    pipeline = TaskGenerationPipeline(config)
    output: TasksGenerationOutput = await pipeline.generate()
    return output.tasks


def _clean_miner_task(task: Task) -> Task:
    task_copy = deepcopy(task)
    task_copy.tests = None
    task_copy.milestones = None
    task_copy.web_analysis = None
    return task_copy
