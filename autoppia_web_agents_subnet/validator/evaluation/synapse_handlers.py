from __future__ import annotations

import asyncio
from typing import List, Optional, Tuple

import bittensor as bt
from bittensor import AxonInfo

from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.protocol import (
    StartRoundSynapse,
    TaskFeedbackSynapse,
    TaskSynapse,
)
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries
from autoppia_web_agents_subnet.validator.config import FEEDBACK_TIMEOUT


async def send_start_round_synapse_to_miners(
    validator,
    miner_axons: List[AxonInfo],
    start_synapse: StartRoundSynapse,
    timeout: int = 60,
) -> List[Optional[StartRoundSynapse]]:
    """Broadcast StartRoundSynapse and collect responses."""
    start_synapse.version = validator.version

    bt.logging.info(
        f"Sending StartRoundSynapse to {len(miner_axons)} miners with {timeout}s timeout and 3 retries..."
    )
    responses: List[Optional[StartRoundSynapse]] = await dendrite_with_retries(
        dendrite=validator.dendrite,
        axons=miner_axons,
        synapse=start_synapse,
        deserialize=True,
        timeout=timeout,
        retries=3,
    )

    successful = sum(
        1 for r in responses if r is not None and getattr(r, "agent_name", None)
    )
    if successful:
        bt.logging.success(
            f"✅ Handshake complete: {successful}/{len(miner_axons)} miners responded"
        )
    else:
        bt.logging.warning(
            f"⚠️ Handshake complete: 0/{len(miner_axons)} miners responded"
        )
    return responses


async def send_task_synapse_to_miners(
    validator,
    miner_axons: List[AxonInfo],
    task_synapse: TaskSynapse,
    timeout: int = 60,
) -> List[Optional[TaskSynapse]]:
    """Send a TaskSynapse to miners and return responses."""
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
    """Send feedback payloads to miners with task results."""
    bt.logging.info(f"Sending feedback to {len(miner_axons)} miners...")

    feedback_messages: List[TaskFeedbackSynapse] = []
    for idx, miner_uid in enumerate(miner_uids):
        feedback_messages.append(
            TaskFeedbackSynapse(
                version=__version__,
                miner_id=str(miner_uid),
                validator_id=str(getattr(validator, "uid", "unknown")),
                task_id=task.id,
                task_url=task.url,
                prompt=task.prompt,
                score=rewards[idx],
                execution_time=execution_times[idx],
                tests=task.tests,
                actions=task_solutions[idx].actions if idx < len(task_solutions) else [],
                test_results=test_results_list[idx] if idx < len(test_results_list) else [],
                evaluation_result=evaluation_results[idx] if idx < len(evaluation_results) else None,
                web_project_name=web_project_name,
            )
        )

    send_tasks = []
    for axon, feedback in zip(miner_axons, feedback_messages):
        send_tasks.append(
            asyncio.create_task(
                validator.dendrite(
                    axons=[axon],
                    synapse=feedback,
                    deserialize=True,
                    timeout=FEEDBACK_TIMEOUT,
                    retry=False,
                )
            )
        )

    if not send_tasks:
        return

    try:
        await asyncio.gather(*send_tasks)
    except Exception as exc:  # noqa: BLE001
        bt.logging.warning(f"Failed to send feedback synapses: {exc}")


async def send_task_synapse_to_http_endpoints(
    *,
    endpoints: List[str],
    task_synapse: TaskSynapse,
    timeout: int,
) -> Tuple[List[TaskSynapse | None], List[float]]:
    """Send TaskSynapse payloads over HTTP to miner endpoints."""
    import asyncio
    import httpx

    responses: List[TaskSynapse | None] = []
    elapsed_times: List[float] = []

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
                response = await client.post(url, json=payload)
                elapsed = asyncio.get_event_loop().time() - start
                elapsed_times.append(float(elapsed))
                if response.status_code == 200:
                    data = response.json()
                    responses.append(
                        TaskSynapse(
                            prompt=payload["prompt"],
                            url=payload["url"],
                            html=payload["html"],
                            screenshot=payload["screenshot"],
                            actions=data.get("actions", []) or [],
                            version=payload.get("version", ""),
                        )
                    )
                else:
                    responses.append(None)
            except Exception:
                elapsed = asyncio.get_event_loop().time() - start
                elapsed_times.append(float(elapsed))
                responses.append(None)

    if len(elapsed_times) < len(endpoints):
        elapsed_times.extend([float(timeout)] * (len(endpoints) - len(elapsed_times)))

    return responses, elapsed_times


def collect_task_solutions_and_execution_times_http(
    *,
    task: IWATask,
    http_responses: List[TaskSynapse | None],
    measured_times: List[float],
    miner_uids: List[int],
) -> Tuple[List[TaskSolution], List[float]]:
    """Convert HTTP responses into TaskSolutions and align timing info."""
    task_solutions: List[TaskSolution] = []
    execution_times: List[float] = []

    for miner_uid, response, measured in zip(miner_uids, http_responses, measured_times):
        try:
            if response is not None:
                task_solutions.append(
                    get_task_solution_from_synapse(
                        task_id=task.id,
                        synapse=response,
                        web_agent_id=str(miner_uid),
                    )
                )
            else:
                task_solutions.append(
                    TaskSolution(task_id=task.id, actions=[], web_agent_id=str(miner_uid))
                )
        except Exception:
            task_solutions.append(TaskSolution(task_id=task.id, actions=[], web_agent_id=str(miner_uid)))

        try:
            execution_times.append(float(measured))
        except Exception:
            execution_times.append(float(TIMEOUT))

    if len(task_solutions) < len(miner_uids):
        for uid in miner_uids[len(task_solutions):]:
            task_solutions.append(TaskSolution(task_id=task.id, actions=[], web_agent_id=str(uid)))
            execution_times.append(float(TIMEOUT))

    return task_solutions, execution_times


__all__ = [
    "send_start_round_synapse_to_miners",
    "send_task_synapse_to_miners",
    "send_feedback_synapse_to_miners",
    "send_task_synapse_to_http_endpoints",
    "collect_task_solutions_and_execution_times_http",
]
