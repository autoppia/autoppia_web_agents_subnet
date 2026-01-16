from __future__ import annotations

from typing import List, Optional

import bittensor as bt
from bittensor import AxonInfo

from autoppia_web_agents_subnet.protocol import StartRoundSynapse
from autoppia_web_agents_subnet.utils.dendrite import dendrite_with_retries


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
