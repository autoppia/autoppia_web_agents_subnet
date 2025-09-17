import bittensor as bt
from typing import List
from autoppia_web_agents_subnet.utils.weights_version import generate_random_version
from autoppia_web_agents_subnet.protocol import TaskSynapse
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries
from autoppia_web_agents_subnet.utils.logging import ColoredLogger


import random
import bittensor as bt
from typing import List
from autoppia_web_agents_subnet.utils.weights_version import generate_random_version
from autoppia_web_agents_subnet.protocol import TaskSynapse
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries
from autoppia_web_agents_subnet.utils.logging import ColoredLogger


async def check_miner_not_responding_to_invalid_version(
    self,
    task_synapse: TaskSynapse,
    miner_axons,
    probability: float,
    timeout: int,
) -> List[TaskSynapse]:
    """
    Optionally send a 'wrong version' synapse to detect miners that respond when they shouldn't.
    Returns a list aligned with miner_axons (one response per axon, possibly stub/None-like).
    """
    try:
        do_check_versions = False

        # do_check_versions = random.random() < probability
        version_responses: List[TaskSynapse] = []
        if do_check_versions:
            # Make a shallow copy so we don't mutate the original synapse
            syn_for_check = TaskSynapse(**task_synapse.model_dump())
            syn_for_check.version = generate_random_version(
                self.version, self.least_acceptable_version
            )
            ColoredLogger.info(
                f"Sending check version synapses with random version {syn_for_check.version}",
                "yellow",
            )
            responses = await dendrite_with_retries(
                dendrite=self.dendrite,
                axons=miner_axons,
                synapse=syn_for_check,
                deserialize=True,
                timeout=timeout,
                retries=1,
            )
            version_responses.extend(responses if responses is not None else [])
        else:
            # Return aligned stubs (same length as miner_axons)
            version_responses.extend(
                [
                    TaskSynapse(prompt="", url="", actions=[])
                    for _ in range(len(miner_axons))
                ]
            )
        return version_responses
    except Exception as e:
        bt.logging.error(f"Error while sending version synapses: {e}")
        # Fallback: keep alignment with empty stubs
        return [
            TaskSynapse(prompt="", url="", actions=[]) for _ in range(len(miner_axons))
        ]
