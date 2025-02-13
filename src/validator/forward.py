import time
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
    """
    The forward function is called by the validator every time step.

    It is responsible for querying the network and scoring the responses.

    Args:
        self (:obj:`bittensor.neuron.Neuron`): The neuron object which contains all the necessary state for the validator.

    """

    # 1) Get Demo Web Projects
    demo_web_projects = get_demo_webs_projects()

    # 2) Generate a random web URL
    demo_web_project = _get_random_demo_web_project(demo_web_projects)
    web_url = demo_web_project.frontend_url

    # 3) Create a pipeline and generate tasks
    tasks_generated = _generate_tasks_for_url(demo_web_project=demo_web_project)
    if not tasks_generated:
        bt.logging.warning("No tasks generated, skipping forward step.")
        return

    # 4) Task Cleaning for miner
    task = tasks_generated[0]
    miner_task = _clean_miner_task(task=task)

    # 5) Get random UIDs. For now we assume all miners will get same task
    miner_uids = get_random_uids(self, k=self.config.neuron.sample_size)

    # 6) Build the synapse and send query
    synapse_request = TaskSynapse(task=miner_task, actions=[])

    try:
        # The dendrite client queries the network.
        responses: List[TaskSynapse] = await self.dendrite(
            # Send the query to selected miner axons in the network.
            axons=[self.metagraph.axons[uid] for uid in miner_uids],
            # Construct a dummy query. This simply contains a single integer.
            synapse=synapse_request,
            # All responses have the deserialize function called on them before returning.
            # You are encouraged to define your own deserialization function.
            deserialize=True,
        )
    except Exception as e:
        bt.logging.error(f"Error while querying dendrite: {e}")
        return

    bt.logging.info(f"Received responses: {responses}")

    # 7) Save original task into synapses to have all attributes and to avoid miner modifying tas
    task_solutions = []
    for miner_uid, response in zip(miner_uids, responses):
        task_solutions.append(
            _get_task_solution_from_synapse(
                task=task,
                synapse=response,
                web_agent_id=miner_uid,
            )
        )
    rewards: np.ndarray = get_rewards(
        self, task_solutions=task_solutions, web_url=web_url
    )

    bt.logging.info(f"Rewards: {rewards}")

    self.update_scores(rewards, miner_uids)

    await asyncio.sleep(FORWARD_SLEEP_SECONDS)


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
