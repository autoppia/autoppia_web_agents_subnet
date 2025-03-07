import time
import numpy as np
import bittensor as bt
from typing import List
import asyncio

from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.data_generation.domain.classes import (
    Task,
    TaskGenerationConfig,
)
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.data_generation.application.tasks_generation_pipeline import (
    TaskGenerationPipeline,
)
from autoppia_web_agents_subnet.validator.reward import get_rewards
from autoppia_web_agents_subnet.utils.uids import get_random_uids
from autoppia_web_agents_subnet.protocol import TaskSynapse
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.validator.config import (
    FORWARD_SLEEP_SECONDS, 
    NUM_URLS,
    SAMPLE_SIZE,
    TASK_SLEEP,
    TIME_WEIGHT,
    MIN_SCORE_FOR_CORRECT_FORMAT,
    MIN_RESPONSE_REWARD
)
from autoppia_web_agents_subnet.validator.utils import (
    clean_miner_task,
    collect_task_solutions,
    init_miner_stats,
    send_feedback_synapse_to_miners,
    send_task_synapse_to_miners,
    update_miner_stats_and_scores,
    retrieve_random_demo_web_project,
    # NEW IMPORTS FOR VALIDATOR TRACKING
    init_validator_performance_stats,
    update_validator_performance_stats,
    print_validator_performance_stats
)


async def generate_tasks_for_web_project(demo_web_project: WebProject) -> List[Task]:
    """
    Generates tasks for the given web project using the TaskGenerationPipeline.
    """
    config = TaskGenerationConfig(
        web_project=demo_web_project,
        save_domain_analysis_in_db=True,
        save_task_in_db=False,
        num_or_urls=NUM_URLS
    )
    pipeline = TaskGenerationPipeline(config=config, web_project=demo_web_project)
    start_time = time.time()
    tasks_generated: List[Task] = await pipeline.generate()
    ColoredLogger.info(
        f"Generated {len(tasks_generated)} tasks in {time.time() - start_time:.2f}s",
        ColoredLogger.YELLOW,
    )
    for task in tasks_generated:
        bt.logging.info(task.prompt)

    return tasks_generated


async def process_tasks(validator, web_project, tasks_generated: List[Task]) -> None:
    """
    Iterates over each task, sends it to the miners, evaluates responses, updates scores,
    and sends feedback. Also manages timing and logging.

    This function now also collects stats to update the validator's performance tracking.
    """
    total_time_start = time.time()

    # Performance accumulators per forward cycle
    tasks_count = 0
    tasks_total_time = 0.0

    # Stats about tasks:
    #   - how many had at least one *valid* response
    #   - how many had all responses None or empty
    #   - how many had at least one "successful" reward
    #   - how many had no successful reward
    # Also track sum of avg response times, sum of evaluation times, sum of avg scores
    num_success = 0
    num_wrong = 0
    num_no_response = 0
    sum_of_avg_response_times = 0.0
    sum_of_evaluation_times = 0.0
    sum_of_avg_scores = 0.0

    for index, task in enumerate(tasks_generated):
        task_start_time = time.time()
        bt.logging.debug(f"Task #{index} (URL: {task.url} ID: {task.id}): {task.prompt}")
        bt.logging.debug(f"Task tests {task.tests}")

        # Clean task for miners
        miner_task: Task = clean_miner_task(task=task)

        # Get random UIDs & miner axons
        miner_uids = get_random_uids(validator, k=SAMPLE_SIZE)
        bt.logging.info(f"Miner UIDs chosen: {miner_uids}")
        miner_axons = [validator.metagraph.axons[uid] for uid in miner_uids]

        # Create synapse and send tasks
        task_synapse = TaskSynapse(
            prompt=miner_task.prompt,
            url=miner_task.url,
            html=miner_task.html, 
            screenshot=miner_task.screenshot,
            actions=[],
        )
        responses = await send_task_synapse_to_miners(
            validator, miner_axons, task_synapse, miner_uids
        )

        # Evaluate & compute rewards
        task_solutions, execution_times = collect_task_solutions(
            task, responses, miner_uids
        )
        rewards = await compute_rewards(
            validator, web_project, task, task_solutions, execution_times
        )
        bt.logging.info(f"Miners Final Rewards: {rewards}")

        # Collect simple stats about the task
        # 1) No response => if all responses are None
        valid_responses_count = sum(resp is not None for resp in responses)
        if valid_responses_count == 0:
            num_no_response += 1

        # 2) Success => at least one reward > 0
        if np.any(rewards > 0):
            num_success += 1
        else:
            # If we had valid responses but no reward > 0
            if valid_responses_count > 0:
                num_wrong += 1
            else:
                # If 0 valid responses => it's also "no_response",
                # but let's keep `num_no_response` as is. 
                # Typically you might consider that "wrong" or a separate category.
                pass

        # Compute average response time for this task
        avg_miner_time = (
            sum(execution_times) / len(execution_times) if execution_times else 0.0
        )
        sum_of_avg_response_times += avg_miner_time

        # Update miners' scores
        evaluation_time = await update_miner_stats_and_scores(
            validator, rewards, miner_uids, execution_times, task
        )
        sum_of_evaluation_times += evaluation_time

        # Average score for this task across responding miners
        # (Ignore None or negative if you prefer, but here we just use np.mean.)
        if len(rewards) > 0:
            avg_score_for_task = float(np.mean(rewards))
        else:
            avg_score_for_task = 0.0
        sum_of_avg_scores += avg_score_for_task

        # Send feedback synapse
        await send_feedback_synapse_to_miners(validator, miner_axons, miner_uids)

        # Wrap up iteration stats
        task_end_time = time.time()
        task_duration = task_end_time - task_start_time
        tasks_count += 1
        tasks_total_time += task_duration

        ColoredLogger.info(
            f"Task iteration time: {task_duration:.2f}s, average miner request time: {avg_miner_time:.2f}s.",
            ColoredLogger.YELLOW,
        )
        bt.logging.info(f"Sleeping for {TASK_SLEEP}s....")
        await asyncio.sleep(TASK_SLEEP)

    # Done with all tasks
    end_time = time.time()
    total_duration = end_time - total_time_start
    avg_task_time = tasks_total_time / tasks_count if tasks_count else 0.0

    bt.logging.info(
        f"Total tasks processed: {tasks_count}, total time: {total_duration:.2f}s, "
        f"average time per task: {avg_task_time:.2f}s"
    )

    # Update the validator-level performance stats
    update_validator_performance_stats(
        validator=validator,
        tasks_count=tasks_count,
        num_success=num_success,
        num_wrong=num_wrong,
        num_no_response=num_no_response,
        sum_of_avg_response_times=sum_of_avg_response_times,
        sum_of_evaluation_times=sum_of_evaluation_times,
        sum_of_avg_scores=sum_of_avg_scores
    )


async def compute_rewards(
    validator,
    web_project: WebProject,
    task: Task,
    task_solutions: List[TaskSolution],
    execution_times: List[float],
) -> np.ndarray:
    """
    Computes the rewards for each miner based on their TaskSolutions.
    """
    evaluation_start_time = time.time()
    rewards: np.ndarray = await get_rewards(
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
    return rewards


async def forward(self) -> None:
    """
    Main entry point for the forward process:
      1. Retrieves random web project and generates tasks.
      2. Sends tasks to miners, gathers responses, evaluates them.
      3. Updates miners' scores and sends feedback.
      4. Tracks performance stats at validator level.
      5. Sleeps to avoid flooding.
    """
    try:
        # Ensure we have stats dicts
        init_miner_stats(self)
        init_validator_performance_stats(self)

        bt.logging.info(f"Starting forward step with __version__ {__version__}")
        forward_start_time = time.time()

        # 1. Retrieve a random demo web project
        demo_web_project: WebProject = await retrieve_random_demo_web_project()
        bt.logging.info(f"Selected demo web project with URL: {demo_web_project.frontend_url}")

        # 2. Generate tasks
        tasks_generated_start_time = time.time()
        tasks_generated = await generate_tasks_for_web_project(demo_web_project)
        tasks_generated_end_time = time.time()
        tasks_generated_time = tasks_generated_end_time - tasks_generated_start_time

        # Update stats about tasks generation
        self.validator_performance_stats["total_tasks_generated"] += len(tasks_generated)
        self.validator_performance_stats["total_generated_tasks_time"] += tasks_generated_time

        if not tasks_generated:
            bt.logging.warning("No tasks generated, skipping forward step.")
            return

        # 3. Process each task
        tasks_processed_start_time = time.time()
        await process_tasks(self, demo_web_project, tasks_generated)
        tasks_processed_end_time = time.time()
        tasks_processed_time = tasks_processed_end_time - tasks_processed_start_time
        self.validator_performance_stats["total_processing_tasks_time"] += tasks_processed_time

        # 4. This forward step is done; track the time
        forward_end_time = time.time()
        forward_time = forward_end_time - forward_start_time
        self.validator_performance_stats["total_forwards_time"] += forward_time
        self.validator_performance_stats["total_forwards_count"] += 1

        # Print stats in a nice table
        print_validator_performance_stats(self)

        # 5. Sleep
        bt.logging.success("Forward step completed successfully.")
        bt.logging.info(f"Sleeping for {FORWARD_SLEEP_SECONDS}s....")
        await asyncio.sleep(FORWARD_SLEEP_SECONDS)
    except Exception as e:
        bt.logging.error(f"Error on validation forward: {e}")
