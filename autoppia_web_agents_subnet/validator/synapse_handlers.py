# file: autoppia_web_agents_subnet/validator/synapse_handlers.py
"""
Synapse handling utilities for validator.
Handles sending/receiving synapses to/from miners.
"""
from __future__ import annotations

import asyncio
from typing import List, Union

import bittensor as bt
from bittensor import AxonInfo

from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.synapses import (
    TaskSynapse,
    TaskFeedbackSynapse,
    StartRoundSynapse,
)
from autoppia_web_agents_subnet.config import FEEDBACK_TIMEOUT, TIMEOUT
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries


# ═══════════════════════════════════════════════════════════════════════════════
# SYNAPSE SENDING - Send synapses to miners
# ═══════════════════════════════════════════════════════════════════════════════

async def send_synapse_to_miners_generic(
    validator,
    miner_axons: List[AxonInfo],
    synapse: Union[TaskSynapse, StartRoundSynapse],
    timeout: int,
    retries: int = 1,
) -> List[Optional[T]]:
    """
    Generic synapse sender for validator.
    Sets synapse.version = validator.version (if present)
    Uses a single retry wrapper for all queries
    Returns a list aligned with miner_axons order (Optional for failures)
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
    task,
    rewards: List[float],
    execution_times: List[float],
    task_solutions,
    test_results_matrices: List[List[List]],
    evaluation_results: List[dict],
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
