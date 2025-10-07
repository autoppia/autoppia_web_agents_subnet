# file: autoppia_web_agents_subnet/validator/communication.py
"""
Communication utilities for validator.
Handles sending/receiving synapses to/from miners.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple, Union, TypeVar

import bittensor as bt
from bittensor import AxonInfo

from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.synapses import (
    TaskSynapse,
    TaskFeedbackSynapse,
    StartRoundSynapse,
)
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_web_agents_subnet.config import MAX_ACTIONS_LENGTH, FEEDBACK_TIMEOUT, TIMEOUT
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries 

T = TypeVar("T")


# ─────────────────────────────────────────────────────────────────────────────
# Responses → solutions + times
# ─────────────────────────────────────────────────────────────────────────────
def get_task_solution_from_synapse(
    task_id: str,
    synapse: TaskSynapse,
    web_agent_id: str,
    max_actions_length: int = MAX_ACTIONS_LENGTH,
) -> TaskSolution:
    """
    Safely extract actions from a TaskSynapse response and limit their length.
    NOTE: correct slicing is [:max], not [max].
    """
    actions = []
    if synapse and hasattr(synapse, "actions") and isinstance(synapse.actions, list):
        actions = synapse.actions[:max_actions_length]
    return TaskSolution(task_id=task_id, actions=actions, web_agent_id=web_agent_id)


def collect_task_solutions_and_execution_times(
    task: Task,
    responses: List[TaskSynapse],
    miner_uids: List[int],
) -> Tuple[List[TaskSolution], List[float]]:
    """
    Convert miner responses into TaskSolution and gather process times.
    """
    task_solutions: List[TaskSolution] = []
    execution_times: List[float] = []

    for miner_uid, response in zip(miner_uids, responses):
        try:
            task_solutions.append(
                get_task_solution_from_synapse(
                    task_id=task.id,
                    synapse=response,
                    web_agent_id=str(miner_uid),
                )
            )
        except Exception as e:
            bt.logging.error(f"Miner response format error: {e}")
            task_solutions.append(
                TaskSolution(task_id=task.id, actions=[], web_agent_id=str(miner_uid))
            )

        if (
            response
            and hasattr(response, "dendrite")
            and hasattr(response.dendrite, "process_time")
            and response.dendrite.process_time is not None
        ):
            execution_times.append(response.dendrite.process_time)
            bt.logging.info(
                f"[TIME] uid={miner_uid} process_time={response.dendrite.process_time:.3f}s (taken)"
            )
        else:
            execution_times.append(TIMEOUT)
            bt.logging.info(
                f"[TIME] uid={miner_uid} process_time=None -> using TIMEOUT={TIMEOUT:.3f}s"
            )

    return task_solutions, execution_times


# ─────────────────────────────────────────────────────────────────────────────
# Synapse sending
# ─────────────────────────────────────────────────────────────────────────────
async def send_synapse_to_miners_generic(
    validator,
    miner_axons: List[AxonInfo],
    synapse: Union[TaskSynapse, StartRoundSynapse],
    timeout: int,
    retries: int = 1,
) -> List[Optional[T]]:
    """
    Deterministic, typed sender:
      - Sets synapse.version = validator.version (if present)
      - Uses a single retry wrapper for all queries
      - Returns a list aligned with miner_axons order (Optional for failures)
    """
    if hasattr(synapse, "version"):
        setattr(synapse, "version", getattr(validator, "version", ""))

    responses: List[Optional[T]] = await dendrite_with_retries(
        dendrite=validator.dendrite,
        axons=miner_axons,
        synapse=synapse,
        deserialize=True,
        timeout=timeout,
        retries=retries,
    )
    bt.logging.info(
        f"Received {sum(1 for r in responses if r is not None)}/{len(miner_axons)} responses."
    )
    return responses


async def send_task_synapse_to_miners(
    validator,
    miner_axons: List[AxonInfo],
    task_synapse: TaskSynapse,
    timeout: int,
) -> List[TaskSynapse]:
    """
    Send a TaskSynapse (with correct version) and return the responses.
    """
    task_synapse.version = validator.version
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
    miner_axons: List[AxonInfo],
    miner_uids: List[int],
    task: Task,
    rewards: List[float],
    execution_times: List[float],
    task_solutions: List[TaskSolution],
    test_results_matrices: List[List[List[Any]]],
    evaluation_results: List[Dict[str, Any]],
) -> None:
    """
    Build and send a TaskFeedbackSynapse to each miner with their evaluation details.
    """
    feedback_list: List[TaskFeedbackSynapse] = []
    for i, miner_uid in enumerate(miner_uids):
        feedback_list.append(
            TaskFeedbackSynapse(
                version=__version__,
                miner_id=str(miner_uid),
                validator_id=str(getattr(validator, "uid", "unknown")),
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
        )

    ColoredLogger.info(
        f"Sending TaskFeedbackSynapse to {len(miner_axons)} miners in parallel",
        ColoredLogger.BLUE,
    )

    tasks = [
        asyncio.create_task(
            validator.dendrite(
                axons=[axon],
                synapse=fb,
                deserialize=True,
                timeout=FEEDBACK_TIMEOUT,
            )
        )
        for axon, fb in zip(miner_axons, feedback_list)
    ]
    await asyncio.gather(*tasks)
    ColoredLogger.info("Feedback responses received from miners", ColoredLogger.BLUE)
