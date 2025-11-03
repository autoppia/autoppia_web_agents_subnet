import asyncio
from types import SimpleNamespace

import pytest

from autoppia_web_agents_subnet.base.miner import BaseMinerNeuron
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from neurons.validator import Validator

VALIDATOR_HOTKEY = "5MockValidatorRound11111111111111111111111"
MINER_HOTKEY = "5MockMinerRound11111111111111111111111"


class MockMiner(BaseMinerNeuron):
    async def forward(self, synapse):
        return synapse.__class__(
            version=self.version,
            prompt=synapse.prompt,
            url=synapse.url,
            actions=[],
        )

    async def forward_feedback(self, synapse):
        return synapse

    async def forward_start_round(self, synapse):
        synapse.agent_name = "MockMiner"
        synapse.agent_version = "0.1"
        synapse.github_url = "https://example.com/mock"
        return synapse


def _mk_validator_config():
    cfg = Validator.config()
    cfg.mock = True
    cfg.mock_hotkey = VALIDATOR_HOTKEY
    cfg.mock_uid = 0
    cfg.mock_peer_hotkeys = f"{VALIDATOR_HOTKEY},{MINER_HOTKEY}"
    cfg.mock_metagraph_size = 2
    cfg.neuron.axon_off = True
    cfg.neuron.disable_set_weights = True
    cfg.neuron.num_concurrent_forwards = 1
    return cfg


def _mk_miner_config():
    cfg = MockMiner.config()
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


class DummyIWAPClient:
    async def auth_check(self):
        return {"status": "ok"}

    async def start_round(self, **_):
        return {"validator_round_id": "mock-round-id"}

    async def set_tasks(self, **_):
        return {"status": "ok"}

    async def start_agent_run(self, **_):
        return {"agent_run_id": "mock-agent-run"}

    async def add_evaluation(self, **_):
        return {"evaluation_id": "mock-eval"}

    async def upload_evaluation_gif(self, evaluation_id, gif_bytes):  # noqa: ARG002
        return "https://example.com/gif"

    async def finish_round(self, **_):
        return {"status": "ok"}


@pytest.mark.asyncio
async def test_validator_forward_end_to_end(monkeypatch):
    # Minimal env for validator config
    monkeypatch.setenv("VALIDATOR_NAME", "Mock Validator")
    monkeypatch.setenv("VALIDATOR_IMAGE", "https://example.com/avatar.png")
    monkeypatch.setenv("TESTING", "true")

    # Disable consensus/external heavy steps
    import autoppia_web_agents_subnet.validator.config as validator_config

    validator_config.ENABLE_DISTRIBUTED_CONSENSUS = False
    validator_config.SHOULD_RECORD_GIF = False
    validator_config.CONSENSUS_VERIFICATION_ENABLED = False
    validator_config.PRE_GENERATED_TASKS = 1
    validator_config.VALIDATOR_NAME = "Mock Validator"
    validator_config.VALIDATOR_IMAGE = "https://example.com/avatar.png"

    import neurons.validator as validator_module
    validator_module.VALIDATOR_NAME = "Mock Validator"
    validator_module.VALIDATOR_IMAGE = "https://example.com/avatar.png"

    # Provide deterministic task generation & evaluation
    from autoppia_web_agents_subnet.validator.evaluation import tasks as tasks_module
    from autoppia_web_agents_subnet.validator.evaluation import eval as eval_module
    from autoppia_web_agents_subnet.validator.models import TaskWithProject
    from autoppia_iwa.src.data_generation.domain.classes import Task
    from autoppia_iwa.src.demo_webs.config import demo_web_projects

    project = demo_web_projects[0]

    async def fake_get_tasks(*_, **__):
        return [
            TaskWithProject(
                project=project,
                task=Task(url="https://demo", prompt="Click button", tests=[]),
            )
        ]

    class DummyEvaluator:
        def __init__(self, *_, **__):
            pass

        async def evaluate_task_solutions(self, *, task, task_solutions):  # noqa: ARG002
            return [
                SimpleNamespace(
                    final_score=1.0,
                    test_results=[],
                    gif_recording=None,
                    stats=SimpleNamespace(error_message=""),
                    version_ok=True,
                    notes="",
                )
                for _ in task_solutions
            ]

    monkeypatch.setattr(tasks_module, "get_task_collection_interleaved", fake_get_tasks)
    monkeypatch.setattr(eval_module, "ConcurrentEvaluator", DummyEvaluator)

    # Boot mock miner and register on mock network
    miner = MockMiner(config=_mk_miner_config())
    miner.axon.serve(netuid=miner.config.netuid, subtensor=miner.subtensor)
    miner.axon.start()

    validator = Validator(config=_mk_validator_config())
    validator.iwap_client = DummyIWAPClient()

    try:
        await validator.forward()

        assert validator.round_manager.current_phase == RoundPhase.COMPLETE
        assert validator._finalized_this_round is True
        assert MINER_HOTKEY in validator.metagraph.hotkeys
        miner_uid = validator.metagraph.hotkeys.index(MINER_HOTKEY)
        rewards = validator.round_manager.round_rewards.get(miner_uid)
        assert rewards, "expected miner rewards recorded"
        assert rewards[0] >= 0.0
    finally:
        miner.axon.stop()
