from __future__ import annotations

from typing import List, Tuple

from autoppia_web_agents_subnet.protocol import TaskSynapse
from autoppia_web_agents_subnet.validator.synapse_handlers import (
    send_task_synapse_to_miners,
)
from autoppia_web_agents_subnet.validator.tasks import (
    collect_task_solutions_and_execution_times,
)
from autoppia_iwa.src.data_generation.domain.classes import Task as IWATask  # type: ignore
from autoppia_iwa.src.demo_webs.classes import WebProject  # type: ignore


class ScreeningPhase:
    """
    Encapsulates SCREENING phase operations: send via dendrite and collect results.

    Inputs:
      - validator: Validator instance (provides dendrite and metagraph)
      - project: IWA WebProject
      - task: IWA Task
      - target_uids: list of miner UIDs to query (screening = active set)
      - axons: axon infos aligned with target_uids
      - task_synapse: fully built TaskSynapse
      - timeout: request timeout

    Output:
      - (task_solutions, execution_times) aligned with target_uids
    """

    async def send_and_collect(
        self,
        *,
        validator,
        project: WebProject,
        task: IWATask,
        target_uids: List[int],
        axons: List,
        task_synapse: TaskSynapse,
        timeout: int,
    ) -> Tuple[list, list]:
        responses = await send_task_synapse_to_miners(
            validator=validator,
            miner_axons=axons,
            task_synapse=task_synapse,
            timeout=timeout,
        )
        task_solutions, execution_times = collect_task_solutions_and_execution_times(
            task=task,
            responses=responses,
            miner_uids=target_uids,
        )
        return task_solutions, execution_times

