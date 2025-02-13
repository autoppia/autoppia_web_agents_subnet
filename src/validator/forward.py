import numpy as np
import bittensor as bt
from typing import List
import asyncio
from src.validator.reward import get_rewards
from src.utils.uids import get_random_uids
from autoppia_iwa.autoppia_iwa.src.data_generation.application.tasks_generation_pipeline import (
    TaskGenerationPipeline,
)
import random
from copy import deepcopy
from autoppia_iwa.autoppia_iwa.src.data_generation.domain.classes import (
    Task,
    TaskGenerationConfig,
    TasksGenerationOutput,
)
from autoppia_iwa.autoppia_iwa.src.web_agents.classes import TaskSolution
from src.protocol import TaskSynapse
from autoppia_iwa.autoppia_iwa.src.data_generation.domain.classes import WebProject
from autoppia_iwa.autoppia_iwa.src.backend_demo_web.config import get_demo_webs_projects

FORWARD_SLEEP_SECONDS = 5


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
    bt.logging.debug(f"Generated {len(tasks_generated)} tasks.")

    # 4) Task Cleaning for miner
    task = tasks_generated[0]
    miner_task = _clean_miner_task(task=task)
    bt.logging.debug("Cleaned task for miner.")

    # 5) Get random UIDs. For now we assume all miners will get same task
    miner_uids = get_random_uids(self, k=self.config.neuron.sample_size)
    bt.logging.debug(f"Selected miner UIDs: {miner_uids}")

    # 6) Build the synapse and send query
    synapse_request = TaskSynapse(task=miner_task, actions=[])
    bt.logging.info(f"Sending synapse request to {len(miner_uids)} miners.")

    try:
        responses: List[TaskSynapse] = await self.dendrite(
            axons=[self.metagraph.axons[uid] for uid in miner_uids],
            synapse=synapse_request,
            deserialize=True,
        )
    except Exception as e:
        bt.logging.error(f"Error while querying dendrite: {e}")
        return

    bt.logging.info(f"Received {len(responses)} responses from dendrite.")

    # 7) Save original task into synapses to have all attributes and to avoid miner modifying task
    task_solutions = []
    for miner_uid, response in zip(miner_uids, responses):
        task_solution = _get_task_solution_from_synapse(
            task=task,
            synapse=response,
            web_agent_id=miner_uid,
        )
        task_solutions.append(task_solution)
    bt.logging.debug("Constructed task solutions from synapse responses.")

    rewards: np.ndarray = get_rewards(self, task_solutions=task_solutions, web_url=web_url)
    bt.logging.info(f"Computed rewards: {rewards}")

    self.update_scores(rewards, miner_uids)
    bt.logging.info("Updated scores for miners.")

    await asyncio.sleep(FORWARD_SLEEP_SECONDS)
    bt.logging.info("SUCCESS: Forward step completed successfully.")


def _get_task_solution_from_synapse(
    task: Task, synapse: TaskSynapse, web_agent_id: str
) -> TaskSolution:
    if not synapse:
        return TaskSolution(task=task, actions=[], web_agent_id=web_agent_id)
    return TaskSolution(task=task, actions=synapse.actions, web_agent_id=web_agent_id)


def _get_random_demo_web_project(projects: list[WebProject]) -> WebProject:
    if not projects:
        raise Exception("No projects available.")
    return random.choice(projects)


def _generate_tasks_for_url(demo_web_project: WebProject) -> list[Task]:
    config = TaskGenerationConfig(
        save_task_to_db=True,
        save_web_analysis=False,
        enable_crawl=True,
        number_of_prompts_per_task=1,
        web_project=demo_web_project,
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
