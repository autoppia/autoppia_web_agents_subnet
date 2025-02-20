from typing import List, Optional
import bittensor as bt


async def dendrite_with_retries(
    dendrite: bt.dendrite,
    axons: List,
    synapses: List,
    deserialize: bool,
    timeout: float,
    cnt_attempts: int = 3
) -> List:
    res: List[Optional] = [None] * len(axons)
    idx = list(range(len(axons)))
    axons_copy = axons.copy()
    synapses_copy = synapses.copy()

    for attempt in range(cnt_attempts):
        responses: List = await dendrite(
            axons=axons_copy,
            synapses=synapses_copy,
            deserialize=deserialize,
            timeout=timeout
        )

        new_idx = []
        new_axons = []
        new_synapses = []
        for i, syn_rsp in enumerate(responses):
            if syn_rsp.dendrite.status_code is not None and int(syn_rsp.dendrite.status_code) == 422:
                if attempt == cnt_attempts - 1:
                    res[idx[i]] = syn_rsp
                    bt.logging.info(
                        f"Could not get answer from axon {axons_copy[i]} after {cnt_attempts} attempts"
                    )
                else:
                    new_idx.append(idx[i])
                    new_axons.append(axons_copy[i])
                    new_synapses.append(synapses_copy[i])
            else:
                res[idx[i]] = syn_rsp

        if new_idx:
            bt.logging.info(f"Retrying {len(new_idx)} miners with broken pipe")
            idx = new_idx
            axons_copy = new_axons
            synapses_copy = new_synapses
        else:
            break

    assert all(el is not None for el in res)
    return res  # type: ignore
