import time
import numpy as np
import bittensor as bt
import asyncio
from typing import List

# Adjust imports to your project's organization
from autoppia_iwa.src.data_generation.domain.classes import (
    Task,
    TaskGenerationConfig,
)
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.data_generation.application.tasks_generation_pipeline import (
    TaskGenerationPipeline,
)
from autoppia_web_agents_subnet.validator.reward import get_rewards_with_details
from autoppia_web_agents_subnet.utils.uids import get_random_uids
from autoppia_web_agents_subnet.protocol import TaskSynapse

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet import __version__

# Imports from your validator config and utils
from autoppia_web_agents_subnet.validator.config import (
    FORWARD_SLEEP_SECONDS,
    SAMPLE_SIZE,
    TASK_SLEEP,
    TIME_WEIGHT,
    MIN_SCORE_FOR_CORRECT_FORMAT,
    MIN_RESPONSE_REWARD,
    PROMPTS_PER_ITERATION,
)
from autoppia_web_agents_subnet.validator.utils import (
    collect_task_solutions,
    init_miner_stats,
    send_feedback_synapse_to_miners,
    send_task_synapse_to_miners,
    update_miner_stats_and_scores,
    retrieve_random_demo_web_project,
    init_validator_performance_stats,
    update_validator_performance_stats,
    print_validator_performance_stats,
)


async def generate_tasks_for_web_project(
    demo_web_project: WebProject, prompts_per_use_case: int
) -> List[Task]:
    """
    Creates tasks for the specified web project using the TaskGenerationPipeline.
    """
    config = TaskGenerationConfig(
        web_project=demo_web_project,
        save_domain_analysis_in_db=True,
        save_task_in_db=False,
        prompts_per_use_case=prompts_per_use_case,
    )
    pipeline = TaskGenerationPipeline(config=config, web_project=demo_web_project)
    start_time = time.time()
    tasks_generated = await pipeline.generate()

    ColoredLogger.info(
        f"Generated {len(tasks_generated)} tasks in {time.time() - start_time:.2f}s",
        ColoredLogger.YELLOW,
    )
    for task in tasks_generated:
        bt.logging.info(f"Task prompt: {task.prompt}")

    return tasks_generated


async def handle_feedback_and_stats(
    validator,
    web_project: WebProject,
    task: Task,
    responses: List[TaskSynapse],
    miner_uids: List[int],
    execution_times: List[float],
    task_solutions,
    rewards: np.ndarray,
    test_results_matrices,
    evaluation_results,
) -> dict:
    """
    Handles post-evaluation steps:
      1) Collecting stats about responses (success, no-response, etc.).
      2) Updating miner stats and scores.
      3) Sending feedback synapse to miners.
      4) Returning computed statistics for this specific task iteration.
    """
    # Count valid (non-None) responses
    valid_responses_count = sum(resp is not None for resp in responses)
    num_no_response = 0
    num_success = 0
    num_wrong = 0

    if valid_responses_count == 0:
        num_no_response += 1

    if np.any(rewards > 0):
        num_success += 1
    else:
        if valid_responses_count > 0:
            num_wrong += 1

    # Miner request time average
    avg_miner_time = (
        (sum(execution_times) / len(execution_times)) if execution_times else 0.0
    )

    # Update miner stats and get evaluation time
    evaluation_time = await update_miner_stats_and_scores(
        validator, rewards, miner_uids, execution_times, task
    )

    # Average reward across miners
    avg_score_for_task = float(np.mean(rewards)) if len(rewards) > 0 else 0.0

    # Send feedback (includes test matrices & evaluation dict)
    miner_axons = [validator.metagraph.axons[uid] for uid in miner_uids]
    await send_feedback_synapse_to_miners(
        validator,
        miner_axons,
        miner_uids,
        task,
        task_solutions,
        test_results_matrices,
        evaluation_results,
    )

    return {
        "num_no_response": num_no_response,
        "num_success": num_success,
        "num_wrong": num_wrong,
        "avg_miner_time": avg_miner_time,
        "avg_score_for_task": avg_score_for_task,
        "evaluation_time": evaluation_time,
    }


async def process_tasks(
    validator, web_project: WebProject, tasks_generated: List[Task]
) -> None:
    """
    Sends tasks to sampled miners, gathers responses, evaluates them, and delegates
    feedback/stats logic to a separate helper method. Also aggregates task-level stats.
    """
    total_time_start = time.time()
    tasks_count = 0
    tasks_total_time = 0.0

    num_success = 0
    num_wrong = 0
    num_no_response = 0
    sum_of_avg_response_times = 0.0
    sum_of_evaluation_times = 0.0
    sum_of_avg_scores = 0.0

    for index, task in enumerate(tasks_generated):
        task_start_time = time.time()
        bt.logging.debug(
            f"Task #{index} (URL: {task.url}, ID: {task.id}): {task.prompt}"
        )
        bt.logging.debug(f"Task tests: {task.tests}")

        # Choose a random subset of miners
        miner_uids = get_random_uids(validator, k=SAMPLE_SIZE)
        bt.logging.info(f"Miner UIDs chosen: {miner_uids}")
        miner_axons = [validator.metagraph.axons[uid] for uid in miner_uids]

        # Build synapse and send
        task_synapse = TaskSynapse(
            prompt=task.prompt,
            url=task.url,
            html=task.html,
            screenshot=task.screenshot,
            actions=[],
        )
        responses = await send_task_synapse_to_miners(
            validator, miner_axons, task_synapse, miner_uids
        )

        # Convert responses into TaskSolutions
        task_solutions, execution_times = collect_task_solutions(
            task, responses, miner_uids
        )

        # Evaluate solutions
        start_eval = time.time()
        rewards, test_results_matrices, evaluation_results = (
            await get_rewards_with_details(
                validator,
                web_project=web_project,
                task=task,
                task_solutions=task_solutions,
                execution_times=execution_times,
                time_weight=TIME_WEIGHT,
                min_correct_format_score=MIN_SCORE_FOR_CORRECT_FORMAT,
                min_response_reward=MIN_RESPONSE_REWARD,
            )
        )
        end_eval = time.time()
        bt.logging.info(f"Miners final rewards: {rewards}")
        bt.logging.info(f"Rewards computed in {end_eval - start_eval:.2f}s.")

        # Handle feedback & stats in a separate helper
        feedback_data = await handle_feedback_and_stats(
            validator=validator,
            web_project=web_project,
            task=task,
            responses=responses,
            miner_uids=miner_uids,
            execution_times=execution_times,
            task_solutions=task_solutions,
            rewards=rewards,
            test_results_matrices=test_results_matrices,
            evaluation_results=evaluation_results,
        )

        # Aggregate the returned stats
        num_no_response += feedback_data["num_no_response"]
        num_success += feedback_data["num_success"]
        num_wrong += feedback_data["num_wrong"]
        sum_of_avg_response_times += feedback_data["avg_miner_time"]
        sum_of_evaluation_times += feedback_data["evaluation_time"]
        sum_of_avg_scores += feedback_data["avg_score_for_task"]

        # Log iteration timing
        task_end_time = time.time()
        task_duration = task_end_time - task_start_time
        tasks_count += 1
        tasks_total_time += task_duration

        ColoredLogger.info(
            f"Task iteration time: {task_duration:.2f}s, avg miner request: {feedback_data['avg_miner_time']:.2f}s.",
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

    # Update validator-level stats
    update_validator_performance_stats(
        validator=validator,
        tasks_count=tasks_count,
        num_success=num_success,
        num_wrong=num_wrong,
        num_no_response=num_no_response,
        sum_of_avg_response_times=sum_of_avg_response_times,
        sum_of_evaluation_times=sum_of_evaluation_times,
        sum_of_avg_scores=sum_of_avg_scores,
    )


async def forward(self) -> None:
    """
    Main entry point that runs each forward cycle:
      1. Retrieve a random web project and generate tasks.
      2. Send tasks to miners, gather and evaluate responses, update scores, send feedback.
      3. Track performance stats, log them, and sleep.
    """
    try:
        init_miner_stats(self)
        init_validator_performance_stats(self)

        bt.logging.info(f"Starting forward step with version {__version__}")
        forward_start_time = time.time()

        # 1. Pick a random demo web project
        demo_web_project = await retrieve_random_demo_web_project()
        bt.logging.info(f"Selected demo web project: {demo_web_project.frontend_url}")

        # 2. Generate tasks
        tasks_generated_start_time = time.time()
        tasks_generated = await generate_tasks_for_web_project(
            demo_web_project, PROMPTS_PER_ITERATION
        )
        tasks_generated_end_time = time.time()
        tasks_generated_time = tasks_generated_end_time - tasks_generated_start_time
        self.validator_performance_stats["total_tasks_generated"] += len(
            tasks_generated
        )
        self.validator_performance_stats[
            "total_generated_tasks_time"
        ] += tasks_generated_time

        if not tasks_generated:
            bt.logging.warning("No tasks generated, skipping forward step.")
            return

        # 3. Process tasks
        tasks_processed_start_time = time.time()
        await process_tasks(self, demo_web_project, tasks_generated)
        tasks_processed_end_time = time.time()
        tasks_processed_time = tasks_processed_end_time - tasks_processed_start_time
        self.validator_performance_stats[
            "total_processing_tasks_time"
        ] += tasks_processed_time

        # Finalize
        forward_end_time = time.time()
        forward_time = forward_end_time - forward_start_time
        self.validator_performance_stats["total_forwards_time"] += forward_time
        self.validator_performance_stats["total_forwards_count"] += 1

        # Print stats in a table
        print_validator_performance_stats(self)

        bt.logging.success("Forward step completed successfully.")
        bt.logging.info(f"Sleeping for {FORWARD_SLEEP_SECONDS}s....")
        await asyncio.sleep(FORWARD_SLEEP_SECONDS)

    except Exception as e:
        bt.logging.error(f"Error in validation forward: {e}")
