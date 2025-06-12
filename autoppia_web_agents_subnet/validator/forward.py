import copy
import time
import asyncio
import os
import json
import itertools
from filelock import FileLock
import bittensor as bt
import random
from typing import List, Set, Dict, Any, Tuple
from autoppia_iwa.src.data_generation.domain.classes import (
    Task,
    TaskGenerationConfig,
)
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.data_generation.application.tasks_generation_pipeline import (
    TaskGenerationPipeline,
)
from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_web_agents_subnet.protocol import (
    TaskFeedbackSynapse,
    TaskSynapse,
    SetOperatorEndpointSynapse,
)
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.validator.config import (
    FORWARD_SLEEP_SECONDS,
    SAMPLE_SIZE,
    TASK_SLEEP,
    TIME_WEIGHT,
    EFFICIENCY_WEIGHT,
    MIN_SCORE_FOR_CORRECT_FORMAT,
    MIN_RESPONSE_REWARD,
    PROMPTS_PER_USECASE,
    MAX_ACTIONS_LENGTH,
    TIMEOUT,
    CHECK_VERSION_PROBABILITY,
    FEEDBACK_TIMEOUT,
    CHECK_VERSION_SYNAPSE,
    NUMBER_OF_PROMPTS_PER_FORWARD,
    SET_OPERATOR_ENDPOINT_FORWARDS_INTERVAL,
)
from autoppia_iwa.src.demo_webs.config import demo_web_projects
from autoppia_web_agents_subnet.validator.utils import (
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
from autoppia_web_agents_subnet.validator.leaderboard import (
    LeaderboardTaskRecord,
    send_many_tasks_to_leaderboard_async,
)


async def generate_tasks_for_web_project(
    demo_web_project: WebProject, total_prompts: int, prompts_per_use_case: int
) -> List[Task]:
    """
    Creates up to `total_prompts` tasks for the specified web project using the TaskGenerationPipeline.

    1. Initializes the pipeline with the given configuration.
    2. Iteratively calls the pipeline's `generate` method until at least `total_prompts`
       tasks have been accumulated or no more tasks can be generated.
    3. Trims any extra tasks so that only `total_prompts` are returned.
    """

    config = TaskGenerationConfig(
        # save_task_in_db=False,
        prompts_per_use_case=prompts_per_use_case,
    )
    pipeline = TaskGenerationPipeline(config=config, web_project=demo_web_project)

    start_time = time.time()

    all_generated_tasks = []

    # Keep calling pipeline.generate() until we have at least total_prompts tasks
    while len(all_generated_tasks) < total_prompts:
        new_tasks = await pipeline.generate()

        # If no new tasks are returned, break out to avoid an infinite loop
        if not new_tasks:
            break

        all_generated_tasks.extend(new_tasks)

    # Trim the list to exactly total_prompts if we have more
    tasks_to_return = all_generated_tasks[:total_prompts]

    ColoredLogger.info(
        f"Generated {len(tasks_to_return)} tasks in {time.time() - start_time:.2f}s",
        ColoredLogger.YELLOW,
    )

    # Log the prompts for debugging/inspection
    for task in tasks_to_return:
        bt.logging.info(f"Task prompt: {task.prompt}")

    return tasks_to_return


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

    # miners_uids_copy = miner_uids[:]
    # process_times_copy = execution_times[:]

    # Zip and sort by processing times (ascending)
    # sorted_pairs = sorted(zip(miners_uids_copy, process_times_copy), key=lambda x: x[1])

    # ColoredLogger.info(
    #     "Showing miner request times: ",
    #     ColoredLogger.YELLOW,
    # )

    # Print each miner UID with its corresponding sorted processing time
    # for miner_uid, proc_time in sorted_pairs:
    #     bt.logging.info(f"Miner {miner_uid} took {proc_time:.2f}s")

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
    rewards,
    execution_times,
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
            score=rewards[i],
            execution_time=execution_times[i],
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
        ColoredLogger.info(
            f"Sending TaskFeedbackSynapse to miners in parallel --> {feedback_synapse}",
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
        rewards=rewards,
        execution_times=execution_times,
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
        miner_uids = get_random_uids(validator, k=SAMPLE_SIZE)

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
                efficiency_weight=EFFICIENCY_WEIGHT,
            )
        )

        end_eval = time.time()
        bt.logging.info(f"Miners final rewards: {rewards}")
        bt.logging.info(f"Rewards computed in {end_eval - start_eval:.2f}s.")
        # 🔍 Logs para inspeccionar todos los datos

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

        try:
            miner_hotkeys = [validator.metagraph.hotkeys[uid] for uid in miner_uids]
            records = []
            for i, miner_uid in enumerate(miner_uids):
                records.append(
                    LeaderboardTaskRecord(
                        validator_uid=int(validator.uid),
                        miner_uid=int(miner_uid),
                        miner_hotkey=miner_hotkeys[i],
                        task_id=str(task.id),
                        task_prompt=task.prompt,
                        website=task.url,
                        success=(rewards[i] >= 1.0),
                        score=float(rewards[i]),
                        duration=float(execution_times[i]),
                    )
                )
            # fire-and-forget
            asyncio.create_task(send_many_tasks_to_leaderboard_async(records))
            bt.logging.info(f"Dispatched {len(records)} leaderboard logs in background")
        except Exception as e:
            bt.logging.error(f"Failed scheduling leaderboard send: {e}")
        # TODO : I cannot visualize this stats
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


async def broadcast_and_save_operator_endpoints(validator) -> None:
    """
    Constructs and sends a SetOperatorEndpointSynapse to each selected miner,
    gathers their responses, and saves them to operator_endpoints.json at your project root.
    """
    # 1. Create the synapse you want to broadcast
    from autoppia_web_agents_subnet import __version__
    from autoppia_web_agents_subnet.protocol import SetOperatorEndpointSynapse

    operator_synapse = SetOperatorEndpointSynapse(
        version=__version__, endpoint="https://your-validator-endpoint.com"
    )

    bt.logging.info("Broadcasting SetOperatorEndpointSynapse...")

    # 2. You decide how to pick which miners to broadcast to.
    miner_uids = get_random_uids(validator, k=SAMPLE_SIZE)
    miner_axons = [validator.metagraph.axons[uid] for uid in miner_uids]

    # 3. Actually send the synapse to those miners (async).
    responses: list[SetOperatorEndpointSynapse] = await dendrite_with_retries(
        dendrite=validator.dendrite,
        axons=miner_axons,
        synapse=operator_synapse,
        deserialize=True,
        timeout=10,
        retries=1,
    )

    bt.logging.info(f"Got {len(responses)} responses for SetOperatorEndpointSynapse")

    # 4. Save the responses to JSON
    await save_operator_endpoints_in_json(responses, miner_uids)


async def save_operator_endpoints_in_json(
    responses: list[SetOperatorEndpointSynapse],
    miner_uids: list[int],
    filename: str = "operator_endpoints.json",
):
    """
    Map each `miner_uid` -> the endpoint from that miner's response,
    then store in `operator_endpoints.json`.
    """
    lock_file = filename + ".lock"

    # Make sure file is initialized as a JSON dict if it doesn't exist
    if not os.path.isfile(filename):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump({}, f)

    with FileLock(lock_file):
        # Load existing content
        with open(filename, "r", encoding="utf-8") as f:
            try:
                existing_data = json.load(f)
                if not isinstance(existing_data, dict):
                    existing_data = {}
            except json.JSONDecodeError:
                existing_data = {}

        # For each response, map the miner UID => the endpoint it returns
        # or simply store the one we sent, if miners echo it or modify it.
        for uid, resp in zip(miner_uids, responses):
            # Some miners might return a different endpoint, or attach data to `resp.endpoint`.
            returned_endpoint = resp.endpoint if resp else "no_response"
            existing_data[str(uid)] = returned_endpoint

        # Save
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=4)

    bt.logging.info(f"Saved {len(responses)} endpoints to {filename}")


def _interleave(a: List[Any], b: List[Any]):
    """
    Flattened zip_longest with no None padding: [a0,b0,a1,b1,...].
    """
    for x, y in itertools.zip_longest(a, b):
        if x is not None:
            yield x
        if y is not None:
            yield y


async def forward(self) -> None:  # noqa: C901 – complex but clearer in one piece
    """
    Validator forward cycle:

      1. Grab the first two demo sites from `demo_web_projects`
      2. Generate tasks_per_project = ceil(NUMBER_OF_PROMPTS_PER_FORWARD / 2)
      3. Alternate tasks [web1, web2, web1, …] until NUMBER_OF_PROMPTS_PER_FORWARD tasks
         have been processed (or lists exhaust)
      4. Update stats, occasionally broadcast operator endpoint, sleep
    """
    try:
        # ------------------------------------------------------------------ stats
        init_validator_performance_stats(self)
        self.forward_count += 1

        bt.logging.info(
            f"[Forward #{self.forward_count}] Starting (version {__version__})"
        )
        t_forward_start = time.time()

        # ------------------------------------------------------------- pick sites
        if len(demo_web_projects) < 2:
            raise RuntimeError(
                "Need at least two demo web projects in `demo_web_projects`."
            )

        web1, web2 = demo_web_projects[0], demo_web_projects[1]
        bt.logging.info(
            f"Demo sites selected:\n"
            f"  • web1 → {web1.frontend_url}\n"
            f"  • web2 → {web2.frontend_url}"
        )

        # ----------------------------------------------------- task generation
        tasks_per_project = NUMBER_OF_PROMPTS_PER_FORWARD

        t_gen_start = time.time()
        tasks_web1 = await generate_tasks_for_web_project(
            web1,
            total_prompts=tasks_per_project,
            prompts_per_use_case=PROMPTS_PER_USECASE,
        )
        tasks_web2 = await generate_tasks_for_web_project(
            web2,
            total_prompts=tasks_per_project,
            prompts_per_use_case=PROMPTS_PER_USECASE,
        )
        t_gen = time.time() - t_gen_start

        # trim in case more were generated than needed
        tasks_web1 = tasks_web1[:tasks_per_project]
        tasks_web2 = tasks_web2[:tasks_per_project]

        # 🆕 Shuffle so the order inside each project is random
        random.shuffle(tasks_web1)
        random.shuffle(tasks_web2)

        total_tasks_generated = len(tasks_web1) + len(tasks_web2)

        self.validator_performance_stats[
            "total_tasks_generated"
        ] += total_tasks_generated
        self.validator_performance_stats["total_generated_tasks_time"] += t_gen

        if total_tasks_generated == 0:
            bt.logging.warning("No tasks generated – skipping forward step.")
            return

        # ----------------------------------------------------- interleave + run
        t_proc_start = time.time()
        processed = 0

        for task in _interleave(tasks_web1, tasks_web2):
            if processed >= NUMBER_OF_PROMPTS_PER_FORWARD:
                break  # honour the hyper-param hard cap

            project = web1 if task in tasks_web1 else web2
            await process_tasks(self, project, [task])
            processed += 1

        t_proc = time.time() - t_proc_start
        self.validator_performance_stats["total_processing_tasks_time"] += t_proc

        # ------------------------------------------------------ housekeeping
        if self.forward_count % SET_OPERATOR_ENDPOINT_FORWARDS_INTERVAL == 0:
            await broadcast_and_save_operator_endpoints(self)

        # -------------------------------------------------------- final stats
        forward_time = time.time() - t_forward_start
        self.validator_performance_stats["total_forwards_time"] += forward_time
        self.validator_performance_stats["total_forwards_count"] += 1

        print_validator_performance_stats(self)

        bt.logging.success("Forward cycle completed!")
        bt.logging.info(f"Sleeping for {FORWARD_SLEEP_SECONDS}s…")
        await asyncio.sleep(FORWARD_SLEEP_SECONDS)

    except Exception as err:
        bt.logging.error(f"Error in forward: {err}")
