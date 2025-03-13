import copy
import time
import asyncio
import bittensor as bt
from typing import List, Set, Dict, Any, Tuple
from autoppia_iwa.src.data_generation.domain.classes import (
    Task,
    TaskGenerationConfig,
)
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.data_generation.application.tasks_generation_pipeline import (
    TaskGenerationPipeline,
)
import numpy as np

from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_web_agents_subnet.protocol import TaskFeedbackSynapse, TaskSynapse
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.validator.config import (
    FORWARD_SLEEP_SECONDS,
    SAMPLE_SIZE,
    TASK_SLEEP,
    TIME_WEIGHT,
    MIN_SCORE_FOR_CORRECT_FORMAT,
    MIN_RESPONSE_REWARD,
    PROMPTS_PER_ITERATION,
    MAX_ACTIONS_LENGTH,
    TIMEOUT,
    CHECK_VERSION_PROBABILITY,
    FEEDBACK_TIMEOUT,
    CHECK_VERSION_SYNAPSE,
)
from autoppia_web_agents_subnet.validator.utils import (
    retrieve_random_demo_web_project,
    init_validator_performance_stats,
    update_validator_performance_stats,
    print_validator_performance_stats,
    dendrite_with_retries,
)
from autoppia_web_agents_subnet.validator.reward import get_rewards_with_details
from autoppia_web_agents_subnet.utils.uids import get_random_uids
from autoppia_web_agents_subnet.validator.version import (
    check_miner_not_responding_to_invalid_version,
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


def get_task_solution_from_synapse(
    task_id: str, synapse: TaskSynapse, web_agent_id: str
) -> TaskSolution:
    """
    Safely extracts actions from a TaskSynapse response and creates a TaskSolution
    with the original task reference, limiting actions to a maximum length.
    """
    actions = []
    if synapse and hasattr(synapse, "actions") and isinstance(synapse.actions, list):
        actions = synapse.actions[:MAX_ACTIONS_LENGTH]  # Limit actions to at most 15

    return TaskSolution(task_id=task_id, actions=actions, web_agent_id=web_agent_id)


def collect_task_solutions(
    task: Task,
    responses: List[TaskSynapse],
    miner_uids: List[int],
) -> Tuple[List[TaskSolution], List[float]]:
    """
    Collects TaskSolutions from the miners' responses and keeps track of their execution times.
    """
    task_solutions = []
    execution_times = []
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


async def send_task_synapse_to_miners(
    validator, miner_axons, task_synapse: TaskSynapse, timeout: int
) -> List[TaskSynapse]:
    """
    Send the (correct-version) synapse to the given miners and retrieve their responses.
    """
    # Ensure we set the correct version here
    task_synapse.version = validator.version

    # The actual forward pass to the selected miners
    responses: List[TaskSynapse] = await dendrite_with_retries(
        dendrite=validator.dendrite,
        axons=miner_axons,
        synapse=task_synapse,
        deserialize=True,
        timeout=timeout,
        retries=1,
    )

    bt.logging.info(f"Received responses from {len(responses)} miners.")
    return responses


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
    Sends a TaskFeedbackSynapse to each miner with the relevant evaluation details.

    :param validator: The validator instance, which holds the dendrite and other context.
    :param miner_axons: List of miner axons corresponding to the chosen miner_uids.
    :param miner_uids: The UIDs of the miners to send feedback to.
    :param task: The original Task object.
    :param task_solutions: List of TaskSolution objects from each miner.
    :param test_results_matrices: List of test-result matrices returned by the reward function.
    :param evaluation_results: List of evaluation details for each miner (scores, etc.).
    :param screenshot_policy: Either "remove" or "keep". If "remove", the screenshot is cleared.
    """
    feedback_list = []
    for i, miner_uid in enumerate(miner_uids):
        feedback = TaskFeedbackSynapse(
            version=__version__,
            miner_id=str(miner_uid),
            validator_id=str(validator.uid),
            task_id=task.id,
            task_url=task.url,
            prompt=task.prompt,
            tests=task.tests,
            actions=task_solutions[i].actions if i < len(task_solutions) else [],
            test_results_matrix=(
                test_results_matrices[i] if i < len(test_results_matrices) else None
            ),
            evaluation_result=(
                evaluation_results[i] if i < len(evaluation_results) else None
            ),
        )

        feedback_list.append(feedback)

    ColoredLogger.info(
        f"Sending TaskFeedbackSynapse to {len(miner_axons)} miners in parallel",
        ColoredLogger.BLUE,
    )

    feedback_tasks = []
    for axon, feedback_synapse in zip(miner_axons, feedback_list):
        # TODO: REMOVE:
        if feedback_synapse.miner_id == "234":
            ColoredLogger.info(
                f"Sending TaskFeedbackSynapse to 'miner 234' miners in parallel --> {feedback_synapse}",
                ColoredLogger.BLUE,
            )
            feedback_tasks.append(
                asyncio.create_task(
                    validator.dendrite(
                        axons=[axon],
                        synapse=feedback_synapse,
                        deserialize=True,
                        timeout=FEEDBACK_TIMEOUT,
                    )
                )
            )

    # Wait for all feedback requests to complete
    results = await asyncio.gather(*feedback_tasks)
    bt.logging.info("Feedback responses received from miners")
    return results


async def handle_feedback_and_validator_stats(
    validator,
    task: Task,
    miner_axons: List[bt.axon],
    miner_uids: List[int],
    execution_times: List[float],
    task_solutions: List[TaskSolution],
    rewards,
    test_results_matrices,
    evaluation_results,
):
    """
    Given all the data about a single task evaluation, update stats, store feedback
    if necessary, and return a dictionary with aggregated metrics for logging.
    """
    num_no_response = sum(
        1 for sol in task_solutions if not sol.actions or len(sol.actions) == 0
    )
    successful_idx = [i for i, r in enumerate(rewards) if r >= 1.0]
    num_success = len(successful_idx)
    num_wrong = len([r for r in rewards if 0.0 < r < 1.0])

    avg_miner_time = (
        sum(execution_times) / len(execution_times) if execution_times else 0
    )
    evaluation_time = 0.0  # If you measure your evaluator time, assign it here
    avg_score_for_task = float(sum(rewards) / len(rewards)) if len(rewards) > 0 else 0.0

    await send_feedback_synapse_to_miners(
        validator=validator,
        miner_axons=miner_axons,
        miner_uids=miner_uids,
        task=task,
        task_solutions=task_solutions,
        test_results_matrices=test_results_matrices,
        evaluation_results=evaluation_results,
    )

    # Return a dictionary for usage by the parent flow
    return {
        "num_no_response": num_no_response,
        "num_success": num_success,
        "num_wrong": num_wrong,
        "avg_miner_time": avg_miner_time,
        "evaluation_time": evaluation_time,
        "avg_score_for_task": avg_score_for_task,
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

        # 1) Choose a random subset of miners.In this case the whole subnet.
        miner_uids = np.array(
            [101, 234, 103]
        )  # get_random_uids(validator, k=SAMPLE_SIZE)
        bt.logging.info(f"Miner UIDs chosen: {miner_uids}")
        miner_axons = [validator.metagraph.axons[uid] for uid in miner_uids]

        # 2) Build the normal synapse structure (correct version is set during sending)
        task_synapse = TaskSynapse(
            prompt=task.prompt,
            url=task.url,
            html="",
            screenshot="",
            actions=[],
        )

        # 3) Test the version check by sending an intentionally WRONG version
        version_responses = await check_miner_not_responding_to_invalid_version(
            validator,
            task_synapse=copy.deepcopy(task_synapse),
            miner_axons=miner_axons,
            probability=CHECK_VERSION_PROBABILITY,
            timeout=CHECK_VERSION_SYNAPSE,
        )

        # 4) Figure out which miners responded incorrectly (non-empty actions to invalid version)
        invalid_version_responders: Set[int] = set()
        for i, vresp in enumerate(version_responses):
            if vresp and hasattr(vresp, "actions") and vresp.actions:
                # This miner responded to the WRONG version with non-empty actions => penalize
                invalid_version_responders.add(miner_uids[i])

        # 5) Now actually send the correct version
        bt.logging.info("Sending Task Synapses To Miners")
        responses = await send_task_synapse_to_miners(
            validator,
            miner_axons=miner_axons,
            task_synapse=task_synapse,
            timeout=TIMEOUT,
        )

        # 6) Convert responses into TaskSolutions
        task_solutions, execution_times = collect_task_solutions(
            task, responses, miner_uids
        )

        # 7) Evaluate solutions & compute rewards
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
                invalid_version_responders=invalid_version_responders,
            )
        )
        ColoredLogger.info(
            f"task solutions: --> {task_solutions} ",
            ColoredLogger.GREEN,
        )
        ColoredLogger.info(
            f"test result matrices: --> {test_results_matrices} ",
            ColoredLogger.RED,
        )
        ColoredLogger.info(
            f"REWARDS: --> {rewards} ",
            ColoredLogger.YELLOW,
        )
        ColoredLogger.info(
            f"MINERs IDS: --> {miner_uids} ",
            ColoredLogger.BLUE,
        )
        end_eval = time.time()
        bt.logging.info(f"Miners final rewards: {rewards}")
        bt.logging.info(f"Rewards computed in {end_eval - start_eval:.2f}s.")

        # Update Validator Scores
        validator.update_scores(rewards, miner_uids)

        # 8) Handle feedback & stats
        feedback_data = await handle_feedback_and_validator_stats(
            validator=validator,
            task=task,
            miner_uids=miner_uids,
            miner_axons=miner_axons,
            execution_times=execution_times,
            task_solutions=task_solutions,
            rewards=rewards,
            test_results_matrices=test_results_matrices,
            evaluation_results=evaluation_results,
        )

        # 9) Aggregate the returned stats
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
      2. Send tasks (with an invalid version check + the correct version) to miners, gather and evaluate responses.
      3. Track performance stats, log them, and sleep.
    """
    try:
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

        # 3. Process tasks (this includes the invalid version check + correct version flow)
        tasks_processed_start_time = time.time()
        tasks_without_screenshot = []
        for task in tasks_generated:
            task_copy = copy.deepcopy(task)
            if hasattr(task_copy, "screenshot"):
                setattr(task_copy, "screenshot", None)  # Alternativa a `del`
            tasks_without_screenshot.append(task_copy)
        await process_tasks(self, demo_web_project, tasks_without_screenshot)
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
        raise e
        bt.logging.error(f"Error in validation forward: {e}")
