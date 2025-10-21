# file: autoppia_web_agents_subnet/validator/synapse_handlers.py
"""
Synapse handling utilities for validator.
Handles sending/receiving synapses to/from miners.

Each synapse type has its own dedicated handler:
- StartRoundSynapse  → send_start_round_synapse_to_miners
- TaskSynapse        → send_task_synapse_to_miners
- TaskFeedbackSynapse → send_feedback_synapse_to_miners
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

import bittensor as bt
from bittensor import AxonInfo

from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.protocol import (
    TaskSynapse,
    TaskFeedbackSynapse,
    StartRoundSynapse,
)
from autoppia_web_agents_subnet.validator.config import FEEDBACK_TIMEOUT, TIMEOUT
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries


# ═══════════════════════════════════════════════════════════════════════════════
# 1. START ROUND SYNAPSE HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

async def send_start_round_synapse_to_miners(
    validator,
    miner_axons: List[AxonInfo],
    start_synapse: StartRoundSynapse,
    timeout: int = 30,
) -> List[Optional[StartRoundSynapse]]:
    """
    Send StartRoundSynapse to miners for round handshake.

    Args:
        validator: Validator instance
        miner_axons: List of miner axons to send to
        start_synapse: StartRoundSynapse to send
        timeout: Timeout in seconds

    Returns:
        List of responses (None for failed responses)
    """
    start_synapse.version = validator.version

    bt.logging.info(f"Sending StartRoundSynapse to {len(miner_axons)} miners...")
    responses: List[Optional[StartRoundSynapse]] = await dendrite_with_retries(
        dendrite=validator.dendrite,
        axons=miner_axons,
        synapse=start_synapse,
        deserialize=True,
        timeout=timeout,
        retries=1,
    )

    # DEBUG: Log all responses with detailed status codes
    successful_responses = []
    failed_responses = []
    status_422_responses = []

    for i, response in enumerate(responses):
        if response is not None:
            status_code = getattr(response.dendrite, 'status_code', None)
            agent_name = getattr(response, 'agent_name', None)

            if status_code == 422:
                # Log 422 errors with full details
                status_422_responses.append({
                    'uid': i,
                    'hotkey': miner_axons[i].hotkey[:10] if i < len(miner_axons) else 'unknown',
                    'status': status_code,
                    'agent_name': agent_name,
                })
            elif agent_name:
                successful_responses.append(f"  UID {i}: agent_name='{agent_name}' status={status_code}")
            else:
                failed_responses.append(f"  UID {i}: status={status_code}")

    if successful_responses:
        bt.logging.info(f"🔍 DEBUG: Successful handshake responses ({len(successful_responses)}):")
        for response_log in successful_responses[:5]:  # Show first 5
            bt.logging.info(response_log)

    if status_422_responses:
        bt.logging.warning(f"⚠️  DEBUG: Miners returning 422 ({len(status_422_responses)}):")
        for r in status_422_responses[:5]:  # Show first 5
            bt.logging.warning(f"  UID {r['uid']}: hotkey={r['hotkey']}... agent_name={r['agent_name']}")

    if not successful_responses and not status_422_responses:
        bt.logging.info(f"🔍 DEBUG: No successful handshake responses")

    successful = sum(1 for r in responses if r is not None and hasattr(r, 'agent_name') and r.agent_name)
    bt.logging.info(f"✅ Handshake complete: {successful}/{len(miner_axons)} miners responded")

    return responses


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TASK SYNAPSE HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

async def send_task_synapse_to_miners(
    validator,
    miner_axons: List[AxonInfo],
    task_synapse: TaskSynapse,
    timeout: int = 60,
) -> List[Optional[TaskSynapse]]:
    """
    Send a TaskSynapse to miners and return the responses.

    Args:
        validator: Validator instance
        miner_axons: List of miner axons to send to
        task_synapse: TaskSynapse to send
        timeout: Timeout in seconds

    Returns:
        List of responses (None for failed responses)
    """
    task_synapse.version = validator.version

    bt.logging.info(f"Sending TaskSynapse to {len(miner_axons)} miners...")
    responses: List[Optional[TaskSynapse]] = await dendrite_with_retries(
        dendrite=validator.dendrite,
        axons=miner_axons,
        synapse=task_synapse,
        deserialize=True,
        timeout=timeout,
        retries=1,
    )

    successful = sum(1 for r in responses if r is not None)
    bt.logging.info(f"Received {successful}/{len(miner_axons)} task responses.")

    return responses


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TASK FEEDBACK SYNAPSE HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

async def send_feedback_synapse_to_miners(
    validator,
    miner_axons: List[AxonInfo],
    miner_uids: List[int],
    task,
    rewards: List[float],
    execution_times: List[float],
    task_solutions,
    test_results_list: List[List],
    evaluation_results: List[dict],
    web_project_name: str = "Unknown",
) -> None:
    """
    Build and send a TaskFeedbackSynapse to each miner with their evaluation details.

    Args:
        validator: Validator instance
        miner_axons: List of miner axons
        miner_uids: List of miner UIDs
        task: Task object
        rewards: List of reward scores
        execution_times: List of execution times
        task_solutions: List of solutions from miners
        test_results_list: Test results for each miner (list of dicts)
        evaluation_results: Evaluation results for each miner
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
                test_results=(
                    test_results_list[i] if i < len(test_results_list) else []
                ),
                evaluation_result=(
                    evaluation_results[i] if i < len(evaluation_results) else None
                ),
                # 🔍 DEBUG: Add web project name
                web_project_name=web_project_name,
            )
        )

    # DEBUG: Log detailed TaskFeedbackSynapse content being sent
    ColoredLogger.info(f"🔍 DEBUG Sending TaskFeedbackSynapse content of the first miner:", ColoredLogger.YELLOW)
    if feedback_list:
        fb = feedback_list[0]  # Log first feedback as example
        ColoredLogger.info(f"  - task_id: {fb.task_id}", ColoredLogger.CYAN)
        ColoredLogger.info(f"  - tests: {fb.tests}", ColoredLogger.CYAN)
        ColoredLogger.info(f"  - score: {fb.score}", ColoredLogger.CYAN)
        ColoredLogger.info(f"  - execution_time: {fb.execution_time}", ColoredLogger.CYAN)

        # Show evaluation_result but replace GIF content with just its length
        eval_result_display = None
        if fb.evaluation_result:
            eval_result_display = fb.evaluation_result.copy() if isinstance(fb.evaluation_result, dict) else fb.evaluation_result
            if isinstance(eval_result_display, dict) and 'gif_recording' in eval_result_display and eval_result_display['gif_recording']:
                eval_result_display['gif_recording'] = f"<length: {len(eval_result_display['gif_recording'])}>"

        ColoredLogger.info(f"  - evaluation_result: {eval_result_display}", ColoredLogger.CYAN)
        ColoredLogger.info(f"  - actions: {len(fb.actions) if fb.actions else 0} actions", ColoredLogger.CYAN)
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
