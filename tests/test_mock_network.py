import asyncio
from types import SimpleNamespace

import pytest

from autoppia_web_agents_subnet.base.miner import BaseMinerNeuron
from autoppia_web_agents_subnet.base.validator import BaseValidatorNeuron
from autoppia_web_agents_subnet.protocol import StartRoundSynapse, TaskSynapse, TaskFeedbackSynapse
from autoppia_web_agents_subnet.validator.evaluation.synapse_handlers import (
    send_start_round_synapse_to_miners,
    send_task_synapse_to_miners,
)


VALIDATOR_HOTKEY = "5MockValidator1111111111111111111111111"
MINER_HOTKEY = "5MockMiner1111111111111111111111111111"


class SimpleValidator(BaseValidatorNeuron):
    async def forward(self):
        return None

    def resync_metagraph(self):
        self.metagraph.sync(self.subtensor)

    def set_weights(self):
        return None


class SimpleMiner(BaseMinerNeuron):
    async def forward(self, synapse: TaskSynapse):
        return TaskSynapse(
            version=self.version,
            prompt=synapse.prompt,
            url=synapse.url,
            actions=[],
        )

    async def forward_feedback(self, synapse: TaskFeedbackSynapse):
        return synapse

    async def forward_start_round(self, synapse: StartRoundSynapse):
        synapse.agent_name = "MockMiner"
        synapse.agent_version = "0.1"
        return synapse


def _make_validator_config():
    cfg = SimpleValidator.config()
    cfg.mock = True
    cfg.mock_hotkey = VALIDATOR_HOTKEY
    cfg.mock_uid = 0
    cfg.mock_peer_hotkeys = f"{VALIDATOR_HOTKEY},{MINER_HOTKEY}"
    cfg.mock_metagraph_size = 2
    cfg.blacklist = SimpleNamespace(
        force_validator_permit=False,
        allow_non_registered=True,
        minimum_stake_requirement=0,
    )
    cfg.neuron.axon_off = True
    cfg.neuron.disable_set_weights = True
    cfg.neuron.num_concurrent_forwards = 1
    return cfg


def _make_miner_config():
    cfg = SimpleMiner.config()
    cfg.mock = True
    cfg.mock_hotkey = MINER_HOTKEY
    cfg.mock_uid = 1
    cfg.mock_peer_hotkeys = f"{VALIDATOR_HOTKEY},{MINER_HOTKEY}"
    cfg.mock_metagraph_size = 2
    cfg.blacklist = SimpleNamespace(
        force_validator_permit=False,
        allow_non_registered=True,
        minimum_stake_requirement=0,
    )
    return cfg


@pytest.mark.asyncio
async def test_mock_dendrite_round_trip():
    miner = SimpleMiner(config=_make_miner_config())
    miner.axon.serve(netuid=miner.config.netuid, subtensor=miner.subtensor)
    miner.axon.start()

    validator = SimpleValidator(config=_make_validator_config())

    miner_axons = [
        axon for axon in validator.metagraph.axons if axon.hotkey == MINER_HOTKEY
    ]
    assert miner_axons, "expected mock metagraph to include miner axon"

    start_synapse = StartRoundSynapse(
        version=validator.version,
        round_id="mock-round",
        validator_id=str(validator.uid),
        total_prompts=1,
        prompts_per_use_case=1,
        note="integration-test",
    )

    start_responses = await send_start_round_synapse_to_miners(
        validator=validator,
        miner_axons=miner_axons,
        start_synapse=start_synapse,
        timeout=5,
    )

    assert len(start_responses) == 1
    assert start_responses[0] is not None
    assert start_responses[0].agent_name == "MockMiner"

    task_synapse = TaskSynapse(
        version=validator.version,
        prompt="Click the button",
        url="https://example.com",
    )

    task_responses = await send_task_synapse_to_miners(
        validator=validator,
        miner_axons=miner_axons,
        task_synapse=task_synapse,
        timeout=5,
    )

    assert len(task_responses) == 1
    assert isinstance(task_responses[0], TaskSynapse)
    assert task_responses[0].prompt == "Click the button"
