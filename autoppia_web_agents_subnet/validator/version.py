import random
import bittensor as bt
from typing import List
from autoppia_web_agents_subnet.utils.weights_version import generate_random_version
from autoppia_web_agents_subnet.protocol import TaskSynapse
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries


async def check_miner_not_responding_to_invalid_version(self, task_synapse:TaskSynapse, miner_axons, timeout):
    CHECK_VERSION_PROBABILITY = 0.25
    do_check_versions = random.random() < CHECK_VERSION_PROBABILITY

    version_responses = []
    if do_check_versions:
        bt.logging.info("Sending Check Version Synapses To Miners")
        random_version = generate_random_version(
            self.version, self.least_acceptable_version)
        task_synapse.version = random_version

        responses: List[TaskSynapse] = await dendrite_with_retries(
            dendrite=self.dendrite,
            axons=miner_axons,
            synapse=task_synapse,
            deserialize=True,
            timeout=timeout,
        )
        version_responses.extend(responses)
    else:
        version_responses.extend([TaskSynapse(prompt="", url="", actions=[]) for _ in range(len(miner_axons))])
    return version_responses
