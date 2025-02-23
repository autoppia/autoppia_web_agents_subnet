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


TIMEOUT = 120
FORWARD_SLEEP_SECONDS = 60 * 10  # 10 Minutes
TASK_SLEEP = 60 * 3  # 3 Minutes
TIME_WEIGHT = 0.2
MIN_SCORE_FOR_CORRECT_FORMAT = 0.1
MIN_RESPONSE_REWARD = 0.1
SAMPLE_SIZE = 256  # All Miners


async def forward(self) -> None:
    try:
        if not hasattr(self, "miner_stats"):
            self.miner_stats = {}
        bt.logging.info("Starting forward step.")

        demo_web_projects = get_demo_webs_projects()
        bt.logging.debug(f"Retrieved {len(demo_web_projects)} demo web projects.")

        try:
            demo_web_project = _get_random_demo_web_project(demo_web_projects)
        except Exception as e:
            bt.logging.error(f"Failed to select a demo web project: {e}")
            return

        web_url = demo_web_project.frontend_url
        bt.logging.info(f"Selected demo web project with URL: {web_url}")

        ColoredLogger.info(
            f"Generating tasks for Web Project: '{demo_web_project.name}'",
            ColoredLogger.YELLOW,
        )
        start_time = time.time()
        tasks_generated: List[Task] = await _generate_tasks_for_url(
            demo_web_project=demo_web_project
        )
        ColoredLogger.info(
            f"Generated {len(tasks_generated)} tasks in {time.time()-start_time}s",
            ColoredLogger.YELLOW,
        )

        if not tasks_generated:
            bt.logging.warning("No tasks generated, skipping forward step.")
            return

        total_time_start = time.time()
        tasks_count = 0
        tasks_total_time = 0.0

        if "aggregated" not in self.miner_stats:
            self.miner_stats["aggregated"] = MinerStats()

        for index, task in enumerate(tasks_generated):
            task_start_time = time.time()
            bt.logging.debug(f"Task #{index} (ID: {task.id}): {task.prompt}")

            miner_task: Task = _clean_miner_task(task=task)
            bt.logging.info(f"Miner task: {miner_task}")

            miner_uids = get_random_uids(self, k=SAMPLE_SIZE)
            bt.logging.info(f"Miner UIDs chosen: {miner_uids}")

            miner_axons = [self.metagraph.axons[uid] for uid in miner_uids]

            task_synapse = TaskSynapse(
                prompt=miner_task.prompt, url=miner_task.url, actions=[]
            )
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

            task_solutions = []
            execution_times = []

            for miner_uid, response in zip(miner_uids, responses):
                try:
                    task_solution = _get_task_solution_from_synapse(
                        task=task,
                        synapse=response,
                        web_agent_id=str(miner_uid),
                    )
                except Exception as e:
                    bt.logging.error(f"Error in Miner Response Format: {e}")
                    task_solution = TaskSolution(
                        task=task, actions=[], web_agent_id=str(miner_uid)
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
            evaluation_time = evaluation_end_time - evaluation_start_time

            bt.logging.info(f"Miners Final Rewards: {rewards}")

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
                    evaluation_time=evaluation_time,
                    last_task=task,
                    success=success,
                )
                self.miner_stats["aggregated"].update(
                    score=float(score_value),
                    execution_time=float(exec_time_value),
                    evaluation_time=evaluation_time,
                    last_task=task,
                    success=success,
                )

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
                            timeout=5,
                        )
                    )
                )
            _ = await asyncio.gather(*feedback_tasks)
            bt.logging.info("TaskFeedbackSynapse responses received.")
            bt.logging.success("Task step completed successfully.")

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

            bt.logging.info(f"Sleeping for {FORWARD_SLEEP_SECONDS}s....")
            await asyncio.sleep(FORWARD_SLEEP_SECONDS)

        end_time = time.time()
        total_duration = end_time - total_time_start
        avg_task_time = tasks_total_time / tasks_count if tasks_count else 0.0

        bt.logging.success("Forward step completed successfully.")
        bt.logging.info(
            f"Total tasks processed: {tasks_count}, total time: {total_duration:.2f}s, "
            f"average time per task: {avg_task_time:.2f}s"
        )

        bt.logging.info(f"Sleeping for {FORWARD_SLEEP_SECONDS}s....")
        await asyncio.sleep(FORWARD_SLEEP_SECONDS)

    except Exception as e:
        bt.logging.error(f"Error on validation forward: {e}")


def _get_task_solution_from_synapse(
    task: Task, synapse: TaskSynapse, web_agent_id: str
):
    if (
        not synapse
        or not hasattr(synapse, "actions")
        or not isinstance(synapse.actions, list)
    ):
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
        save_task_in_db=False,
    )
    pipeline = TaskGenerationPipeline(config)
    output: TasksGenerationOutput = await pipeline.generate()
    return output.tasks


def _clean_miner_task(task: Task) -> Task:
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
