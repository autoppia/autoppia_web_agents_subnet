from __future__ import annotations

from typing import List, Tuple

from autoppia_web_agents_subnet.protocol import TaskSynapse
from autoppia_web_agents_subnet.validator.synapse_handlers import (
    send_task_synapse_to_http_endpoints,
    collect_task_solutions_and_execution_times_http,
)
from autoppia_iwa.src.data_generation.domain.classes import Task as IWATask  # type: ignore
from autoppia_iwa.src.demo_webs.classes import WebProject  # type: ignore


class FinalPhase:
    """
    Encapsulates FINAL phase operations: send via HTTP local endpoints and collect results.

    Inputs:
      - project, task
      - target_uids: list of Top-S miner UIDs
      - endpoints: base URLs aligned with target_uids
      - task_synapse
      - timeout

    Output:
      - (task_solutions, execution_times) aligned with target_uids
    """

    async def send_and_collect(
        self,
        *,
        project: WebProject,
        task: IWATask,
        target_uids: List[int],
        endpoints: List[str],
        task_synapse: TaskSynapse,
        timeout: int,
    ) -> Tuple[list, list]:
        http_responses, measured_times = await send_task_synapse_to_http_endpoints(
            endpoints=endpoints,
            task_synapse=task_synapse,
            timeout=timeout,
        )
        task_solutions, execution_times = collect_task_solutions_and_execution_times_http(
            task=task,
            http_responses=http_responses,
            measured_times=measured_times,
            miner_uids=target_uids,
        )
        return task_solutions, execution_times

