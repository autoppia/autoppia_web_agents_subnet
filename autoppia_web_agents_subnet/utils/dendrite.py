import bittensor as bt
from typing import List
from autoppia_web_agents_subnet.protocol import TaskSynapse, SetOperatorEndpointSynapse

import bittensor as bt
from typing import List, Union
from autoppia_web_agents_subnet.protocol import TaskSynapse, SetOperatorEndpointSynapse

SynapseT = Union[TaskSynapse, SetOperatorEndpointSynapse]


async def dendrite_with_retries(
    dendrite: bt.dendrite,
    axons: list,
    synapse: SynapseT,
    deserialize: bool,
    timeout: float,
    retries: int = 3,
) -> List[SynapseT | None]:
    """
    Sends the same synapse to a list of axons. Preserves order and returns
    one slot per axon (either a response or None) after up to `retries` attempts.
    Retries only for responses with status_code == 422 or None-like responses.
    """
    res: List[SynapseT | None] = [None] * len(axons)
    idx = list(range(len(axons)))
    axons_pending = axons.copy()

    try:
        for attempt in range(retries):
            responses = await dendrite(
                axons=axons_pending,
                synapse=synapse,
                deserialize=deserialize,
                timeout=timeout,
            )

            # If some backends return fewer responses than axons, guard against it
            if len(responses) != len(axons_pending):
                bt.logging.warning(
                    f"dendrite returned {len(responses)} responses for {len(axons_pending)} axons; aligning conservatively."
                )

            new_idx: List[int] = []
            new_axons: List = []

            for i in range(len(axons_pending)):
                resp = responses[i] if i < len(responses) else None

                # Normalize None/malformed cases
                code = None
                if resp is not None and getattr(resp, "dendrite", None) is not None:
                    code = getattr(resp.dendrite, "status_code", None)

                if resp is None or (code is not None and int(code) == 422):
                    # retry condition
                    if attempt == retries - 1:
                        res[idx[i]] = resp  # keep None or the last bad response
                        bt.logging.info(
                            f"Wasn't able to get a valid answer from axon {axons_pending[i]} after {retries} attempts"
                        )
                    else:
                        new_idx.append(idx[i])
                        new_axons.append(axons_pending[i])
                else:
                    # success path
                    res[idx[i]] = resp

            if new_idx:
                bt.logging.info(
                    f"Found {len(new_idx)} synapses to retry (broken pipe/None), retrying them"
                )
                idx = new_idx
                axons_pending = new_axons
            else:
                break

        # Keep length and order; may still contain None if unresponsive after retries
        return res

    except Exception as e:
        bt.logging.error(f"Error while sending synapse with dendrite_with_retries: {e}")
        # Preserve alignment on error
        return [None] * len(axons)
