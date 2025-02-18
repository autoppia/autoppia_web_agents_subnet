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
FORWARD_SLEEP_SECONDS = 60 * 10  # 10 Minutes
TASK_SLEEP = 60 * 3  # 3 Minutes
TIME_WEIGHT = 0.2
MIN_SCORE_FOR_CORRECT_FORMAT = 0.1


async def forward(self) -> None:
    try:
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
        bt.logging.warning(f"Generating tasks for Web Project: '{demo_web_project.name}' ...")
        tasks_generated:List[Task] = await _generate_tasks_for_url(demo_web_project=demo_web_project)

        if not tasks_generated:
            bt.logging.warning("No tasks generated, skipping forward step.")
            return
        bt.logging.info(f"Generated {len(tasks_generated)} tasks for {web_url}")

        for index, task in enumerate(tasks_generated):
            bt.logging.debug(f"Task #{index}: {task.prompt}")

            # 4) Task Cleaning for miner
            miner_task = _clean_miner_task(task=task)
            bt.logging.info(f"Miner task: {miner_task}")

            # 5) Get random UIDs
            miner_uids = get_random_uids(self, k=self.config.neuron.sample_size)
            bt.logging.info(f"Miner UIDs chosen: {miner_uids}")

            # 6) Build the synapse and send query with a timeout
            bt.logging.info(f"Sending TaskSynapse to {len(miner_uids)} miners.")

            miner_axons = [self.metagraph.axons[uid] for uid in miner_uids]
            responses: List[TaskSynapse] = await _dendrite_with_retries(
                dendrite=self.dendrite,
                axons=miner_axons,
                synapse=TaskSynapse(prompt=miner_task.prompt, url=miner_task.url, actions=[]),
                deserialize=True,
                timeout=TIMEOUT,
            )

            bt.logging.info(f"Received {len(responses)} responses.")

            # 7) Construct task solutions and track execution times
            task_solutions = []
            execution_times = []

            for miner_uid, response in zip(miner_uids, responses):
                task_solution = None
                if response:
                    bt.logging.debug(f"Miner {miner_uid} actions: {response.actions}")
                else:
                    bt.logging.debug(f"Miner {miner_uid} Response None")
                try:
                    task_solution = _get_task_solution_from_synapse(
                        task=task,
                        synapse=response,
                        web_agent_id=str(miner_uid),
                    )
                except Exception as e:
                    bt.logging.error(f"Error in Miner Response Format: {e}")
                    task_solution = TaskSolution(task=task, actions=[], web_agent_id=str(miner_uid))

                task_solutions.append(task_solution)

                process_time = (
                    getattr(response.dendrite, "process_time", TIMEOUT) if response else TIMEOUT
                )
                execution_times.append(process_time)

            # 8) Compute rewards
            rewards: np.ndarray = await get_rewards(
                self,
                task_solutions=task_solutions,
                web_url=web_url,
                execution_times=execution_times,
                time_weight=TIME_WEIGHT,  # Example parameter usage
                min_correct_format_score=MIN_SCORE_FOR_CORRECT_FORMAT  # Example parameter usage
            )

            # Log each miner’s final reward
            bt.logging.info(f"Miners Final Rewards: {rewards}")

            # 9) Update scores
            self.update_scores(rewards, miner_uids)
            bt.logging.info("Scores updated for miners")
            bt.logging.success("Task step completed successfully.")

            bt.logging.info(f"Sleeping for {FORWARD_SLEEP_SECONDS}s....")
            await asyncio.sleep(FORWARD_SLEEP_SECONDS)

        bt.logging.success("Forward step completed successfully.")
        bt.logging.info(f"Sleeping for {FORWARD_SLEEP_SECONDS}s....")
        await asyncio.sleep(FORWARD_SLEEP_SECONDS)
    except Exception as e:
        bt.logging.error(f"Error on validation forward: {e}")


async def _dendrite_with_retries(dendrite: bt.dendrite, axons: list, synapse: TaskSynapse, deserialize: bool, timeout: float, cnt_attempts=3) -> List[TaskSynapse]:
    res: List[TaskSynapse | None] = [None] * len(axons)
    idx = list(range(len(axons)))
    axons = axons.copy()
    for attempt in range(cnt_attempts):
        responses: List[TaskSynapse] = await dendrite(
            axons=axons,
            synapse=synapse,
            deserialize=deserialize,
            timeout=timeout
        )

        new_idx = []
        new_axons = []
        for i, synapse in enumerate(responses):
            if synapse.dendrite.status_code is not None and int(synapse.dendrite.status_code) == 422:
                if attempt == cnt_attempts - 1:
                    res[idx[i]] = synapse
                    bt.logging.info("Wasn't able to get answers from axon {} after 3 attempts".format(axons[i]))
                else:
                    new_idx.append(idx[i])
                    new_axons.append(axons[i])
            else:
                res[idx[i]] = synapse

        if len(new_idx):
            bt.logging.info('Found {} synapses with broken pipe, retrying them'.format(len(new_idx)))
        else:
            break

        idx = new_idx
        axons = new_axons

    assert all([el is not None for el in res])
    return res


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


async def _generate_tasks_for_url(demo_web_project: WebProject) -> List[Task]:
    config = TaskGenerationConfig(web_project=demo_web_project, save_web_analysis_in_db=True, save_task_in_db=False)
    pipeline = TaskGenerationPipeline(config)
    output: TasksGenerationOutput = await pipeline.generate()
    bt.logging.warning(output)
    return output.tasks


def _clean_miner_task(task: Task) -> Task:
    task_copy = deepcopy(task)
    task_copy.tests = None
    task_copy.milestones = None
    task_copy.web_analysis = None
    return task_copy
