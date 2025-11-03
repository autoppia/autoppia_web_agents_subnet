from types import SimpleNamespace

import numpy as np
import pytest

from autoppia_web_agents_subnet.validator.round_manager import RoundManager
from autoppia_web_agents_subnet.validator.settlement import mixin as settlement_mixin
from autoppia_web_agents_subnet.validator.settlement import consensus as consensus_module


class SettlementHarness(settlement_mixin.SettlementMixin):
    def __init__(self):
        self.block = 0
        self.round_manager = RoundManager(
            round_size_epochs=0.2,
            avg_task_duration_seconds=30,
            safety_buffer_epochs=0.02,
            minimum_start_block=0,
        )
        self.round_manager.start_new_round(0)
        self.metagraph = SimpleNamespace(
            n=3,
            hotkeys=['hk0', 'hk1', 'hk2'],
            coldkeys=['ck0', 'ck1', 'ck2'],
        )
        self.active_miner_uids = [0, 1]
        self.subtensor = SimpleNamespace(get_current_block=lambda: 10)
        self._consensus_last_details = {}
        self.wallet = SimpleNamespace(hotkey=SimpleNamespace(ss58_address='5mock'))
        self.config = SimpleNamespace(netuid=0)
        self._agg_scores_cache = None
        self._consensus_published = False
        self._consensus_mid_fetched = False
        self._finalized_this_round = False
        self._current_round_number = 1
        self.update_calls = []
        self.weights = None

    def update_scores(self, rewards, uids):
        self.update_calls.append((np.asarray(rewards), list(uids)))

    def set_weights(self):
        self.weights = self.update_calls[-1][0]

    async def _get_async_subtensor(self):
        return SimpleNamespace()

    async def _finish_iwap_round(self, *_, **__):
        return True


@pytest.mark.asyncio
async def test_calculate_final_weights_uses_aggregated_scores(monkeypatch):
    harness = SettlementHarness()
    harness.round_manager.round_rewards = {0: [1.0], 1: [0.5]}

    async def fake_aggregate(**_):
        return {0: 0.7, 1: 0.3}, {"validators": 1}

    monkeypatch.setattr(
        consensus_module, "aggregate_scores_from_commitments", fake_aggregate
    )
    async def fake_read_all_plain_commitments(*_, **__):
        return []

    monkeypatch.setattr(
        consensus_module, "read_all_plain_commitments", fake_read_all_plain_commitments
    )

    await harness._calculate_final_weights(tasks_completed=2)

    assert harness.weights is not None
    assert np.argmax(harness.weights) == 0


@pytest.mark.asyncio
async def test_burn_all_when_no_active_miners():
    harness = SettlementHarness()
    harness.active_miner_uids = []
    await harness._calculate_final_weights(tasks_completed=0)
    assert harness.weights is not None
    assert harness.weights.sum() == pytest.approx(1.0)
