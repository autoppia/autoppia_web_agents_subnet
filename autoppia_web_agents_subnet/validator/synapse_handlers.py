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
from autoppia_web_agents_subnet.validator.tasks import (
    get_task_solution_from_synapse,
)
from autoppia_iwa.src.web_agents.classes import TaskSolution  # type: ignore
from autoppia_iwa.src.data_generation.domain.classes import Task as IWATask  # type: ignore


# ═══════════════════════════════════════════════════════════════════════════════
# 1. START ROUND SYNAPSE HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

async def send_start_round_synapse_to_miners(
    validator,
    miner_axons: List[AxonInfo],
    start_synapse: StartRoundSynapse,
    timeout: int = 60,
) -> List[Optional[StartRoundSynapse]]:
    """
    Send StartRoundSynapse to miners for round handshake.

    Args:
        validator: Validator instance
        miner_axons: List of miner axons to send to
        start_synapse: StartRoundSynapse to send
        timeout: Timeout in seconds (default: 60s, increased for better reliability)

    Returns:
        List of responses (None for failed responses)
    """
    start_synapse.version = validator.version

    bt.logging.info(f"Sending StartRoundSynapse to {len(miner_axons)} miners with {timeout}s timeout and 3 retries...")
    responses: List[Optional[StartRoundSynapse]] = await dendrite_with_retries(
        dendrite=validator.dendrite,
        axons=miner_axons,
        synapse=start_synapse,
        deserialize=True,
        timeout=timeout,
        retries=3,
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

    # Summary only (detailed table is shown in validator.py)
    successful = sum(1 for r in responses if r is not None and hasattr(r, 'agent_name') and r.agent_name)
    if successful > 0:
        bt.logging.success(f"✅ Handshake complete: {successful}/{len(miner_axons)} miners responded")
    else:
        bt.logging.warning(f"⚠️ Handshake complete: 0/{len(miner_axons)} miners responded")

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

    # Send feedback to miners
    bt.logging.info(f"Sending feedback to {len(miner_axons)} miners...")

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


# ═══════════════════════════════════════════════════════════════════════════════
# 4. HTTP helpers for FINAL PHASE (local deployed miners)
# ═══════════════════════════════════════════════════════════════════════════════

async def send_task_synapse_to_http_endpoints(
    *,
    endpoints: list[str],
    task_synapse: TaskSynapse,
    timeout: int,
) -> tuple[list[TaskSynapse | None], list[float]]:
    """
    Send TaskSynapse as JSON over HTTP to each base endpoint.

    Returns:
      - responses: list aligned with endpoints; None for failures
      - times: per-request measured elapsed seconds
    """
    import httpx
    out: list[TaskSynapse | None] = []
    times: list[float] = []

    payload = {
        "prompt": task_synapse.prompt,
        "url": task_synapse.url,
        "html": task_synapse.html or "",
        "screenshot": task_synapse.screenshot or "",
        "actions": task_synapse.actions or [],
        "version": getattr(task_synapse, "version", ""),
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        for base in endpoints:
            base = (base or "").rstrip("/")
            url = f"{base}/api/task"
            start = asyncio.get_event_loop().time()
            try:
                resp = await client.post(url, json=payload)
                elapsed = asyncio.get_event_loop().time() - start
                times.append(float(elapsed))
                if resp.status_code == 200:
                    data = resp.json()
                    ts = TaskSynapse(
                        prompt=payload["prompt"],
                        url=payload["url"],
                        html=payload["html"],
                        screenshot=payload["screenshot"],
                        actions=data.get("actions", []) or [],
                        version=payload.get("version", ""),
                    )
                    out.append(ts)
                else:
                    out.append(None)
            except Exception:
                elapsed = asyncio.get_event_loop().time() - start
                times.append(float(elapsed))
                out.append(None)

    # Pad times if needed
    if len(times) < len(endpoints):
        times.extend([float(timeout)] * (len(endpoints) - len(times)))
    return out, times


def collect_task_solutions_and_execution_times_http(
    *,
    task: IWATask,
    http_responses: list[TaskSynapse | None],
    measured_times: list[float],
    miner_uids: list[int],
) -> tuple[list[TaskSolution], list[float]]:
    """
    Convert HTTP responses into TaskSolution list aligned with miner_uids and
    use client-side measured times as execution_times.
    """
    task_solutions: list[TaskSolution] = []
    execution_times: list[float] = []

    for miner_uid, resp, t in zip(miner_uids, http_responses, measured_times):
        try:
            if resp is not None:
                task_solutions.append(
                    get_task_solution_from_synapse(
                        task_id=task.id,
                        synapse=resp,
                        web_agent_id=str(miner_uid),
                    )
                )
            else:
                task_solutions.append(TaskSolution(task_id=task.id, actions=[], web_agent_id=str(miner_uid)))
        except Exception:
            task_solutions.append(TaskSolution(task_id=task.id, actions=[], web_agent_id=str(miner_uid)))

        try:
            execution_times.append(float(t))
        except Exception:
            execution_times.append(float(TIMEOUT))

    # Pad to miner_uids length if needed
    n = len(miner_uids)
    if len(task_solutions) < n:
        pad = n - len(task_solutions)
        task_solutions.extend([TaskSolution(task_id=task.id, actions=[], web_agent_id="0")] * pad)
        execution_times.extend([float(TIMEOUT)] * pad)

    return task_solutions, execution_times
