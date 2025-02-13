from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.data_generation.domain.classes import WebProject
from autoppia_iwa.src.backend_demo_web.config import get_demo_webs_projects
from autoppia_iwa.src.data_generation.domain.classes import (
    Task,
    TaskGenerationConfig,
    TasksGenerationOutput,
)
from autoppia_iwa.src.data_generation.application.tasks_generation_pipeline import (
    TaskGenerationPipeline,
)
from autoppia_web_agents_subnet.validator.reward import get_rewards
from autoppia_web_agents_subnet.utils.uids import get_random_uids
from autoppia_web_agents_subnet.protocol import TaskSynapse
import numpy as np
import bittensor as bt
from typing import List
import asyncio
import random
from copy import deepcopy

TIMEOUT = 10
FORWARD_SLEEP_SECONDS = 5
TIME_WEIGHT = 0.2
MIN_SCORE_FOR_CORRECT_FORMAT = 0.1


async def forward(self) -> None:
    bt.logging.info("Starting forward step.")

    # 1) Get Demo Web Projects
    demo_web_projects = get_demo_webs_projects()
    bt.logging.debug(f"Retrieved {len(demo_web_projects)} demo web projects.")

    # 2) Generate a random web URL
    try:
        demo_web_project = _get_random_demo_web_project(demo_web_projects)
    except Exception as e:
        bt.logging.error(f"Failed to select a demo web project: {e}")
        return
    web_url = demo_web_project.frontend_url
    bt.logging.info(f"Selected demo web project with URL: {web_url}")

    # 3) Create a pipeline and generate tasks
    tasks_generated = _generate_tasks_for_url(demo_web_project=demo_web_project)
    if not tasks_generated:
        bt.logging.warning("No tasks generated, skipping forward step.")
        return
    bt.logging.info(f"Generated {len(tasks_generated)} tasks for {web_url}")

    # 4) Task Cleaning for miner
    task = tasks_generated[0]
    miner_task = _clean_miner_task(task=task)
    bt.logging.debug("Cleaned task for miner.")

    # 5) Get random UIDs
    miner_uids = get_random_uids(self, k=self.config.neuron.sample_size)
    bt.logging.info(f"Miner UIDs chosen: {miner_uids}")

    # 6) Build the synapse and send query with a timeout
    synapse_request = TaskSynapse(task=miner_task, actions=[])
    bt.logging.info(f"Sending TaskSynapse to {len(miner_uids)} miners.")

    try:
        responses: List[TaskSynapse] = await asyncio.wait_for(
            self.dendrite(
                axons=[self.metagraph.axons[uid] for uid in miner_uids],
                synapse=synapse_request,
                deserialize=True,
            ),
            timeout=TIMEOUT,
        )
    except Exception as e:
        bt.logging.error(f"Error while querying dendrite: {e}")
        return

    bt.logging.info(f"Received {len(responses)} responses.")

    # 7) Construct task solutions and track execution times
    task_solutions = []
    execution_times = []
    for miner_uid, response in zip(miner_uids, responses):
        if response and getattr(response, 'actions', None):
            bt.logging.debug(f"Miner {miner_uid} actions: {response.actions}")
        task_solution = _get_task_solution_from_synapse(
            task=task,
            synapse=response,
            web_agent_id=miner_uid,
        )
        task_solutions.append(task_solution)
        process_time = getattr(response.dendrite, 'process_time', TIMEOUT) if response else TIMEOUT
        execution_times.append(process_time)

    # 8) Compute rewards
    rewards: np.ndarray = get_rewards(
        self,
        task_solutions=task_solutions,
        web_url=web_url,
        execution_times=execution_times,
        time_weight=TIME_WEIGHT,  # Example parameter usage
        min_correct_format_score=MIN_SCORE_FOR_CORRECT_FORMAT  # Example parameter usage
    )

    # Log each miner’s final reward
    for uid, ex_time, rw in zip(miner_uids, execution_times, rewards):
        bt.logging.info(f"Miner {uid}: time={ex_time:.2f}s, reward={rw:.3f}")

    # 9) Update scores
    self.update_scores(rewards, miner_uids)
    bt.logging.info("Scores updated for miners.")

    await asyncio.sleep(FORWARD_SLEEP_SECONDS)
    bt.logging.info("SUCCESS: Forward step completed successfully.")


def _get_task_solution_from_synapse(
    task: Task, synapse: TaskSynapse, web_agent_id: str
) -> TaskSolution:
    if not synapse or not hasattr(synapse, 'actions') or not isinstance(synapse.actions, list):
        return TaskSolution(task=task, actions=[], web_agent_id=web_agent_id)
    return TaskSolution(task=task, actions=synapse.actions, web_agent_id=web_agent_id)


def _get_random_demo_web_project(projects: List[WebProject]) -> WebProject:
    if not projects:
        raise Exception("No projects available.")
    return random.choice(projects)


def _generate_tasks_for_url(demo_web_project: WebProject) -> List[Task]:
    config = TaskGenerationConfig(
        web_project=demo_web_project,
        save_task_in_db=True,
        save_web_analysis_in_db=False,
        enable_crawl=True,
        number_of_prompts_per_task=1
    )
    pipeline = TaskGenerationPipeline(config)
    output: TasksGenerationOutput = pipeline.generate()
    return output.tasks


def _clean_miner_task(task: Task) -> Task:
    task_copy = deepcopy(task)
    task_copy.tests = []
    task_copy.milestones = None
    task_copy.web_analysis = None
    return task_copy
