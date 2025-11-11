import asyncio
from types import SimpleNamespace

import pytest

from autoppia_web_agents_subnet.validator import consensus as consensus_mod


class DummyRoundManager:
    BLOCKS_PER_EPOCH = 360

    def __init__(self):
        self.round_rewards = {1: [1.0]}

    def get_current_boundaries(self):
        return {
            "round_start_epoch": 10.0,
            "target_epoch": 11.0,
            "round_start_block": 3600,
            "target_block": 3960,
        }

    def get_average_rewards(self):
        return {1: 0.75}

    @classmethod
    def block_to_epoch(cls, block: int) -> float:
        return block / cls.BLOCKS_PER_EPOCH


class DummySubtensor:
    def __init__(self):
        self.commits = {}

    async def commit(self, *, wallet, netuid, data, period=None):  # noqa: ARG002
        self.commits[(wallet.hotkey.ss58_address, netuid)] = data
        return True

    async def get_uid_for_hotkey_on_subnet(self, hotkey_ss58, netuid):  # noqa: ARG002
        return 0

    async def get_commitment(self, *, netuid, uid, block=None):  # noqa: ARG002
        return self.commits.get(("hk", netuid))

    async def get_all_commitments(self, *, netuid, block=None, reuse_block=False):  # noqa: ARG002
        return {}


@pytest.mark.asyncio
async def test_publish_round_snapshot_records_commit(monkeypatch):
    monkeypatch.setattr(consensus_mod, "ENABLE_DISTRIBUTED_CONSENSUS", True, raising=False)
    monkeypatch.setattr(consensus_mod, "CONSENSUS_DATASET_EMBED", False, raising=False)

    recorded_payloads = []

    async def fake_aadd_json(payload, filename, api_url, pin, sort_keys):  # noqa: ARG005
        recorded_payloads.append((payload, filename))
        return ("cid123", "sha123", 42)

    async def fake_write_plain_commitment_json(st, wallet, data, netuid, period=None):  # noqa: ARG005
        st.commits[(wallet.hotkey.ss58_address, netuid)] = data
        return True

    monkeypatch.setattr(consensus_mod, "aadd_json", fake_aadd_json)
    monkeypatch.setattr(consensus_mod, "write_plain_commitment_json", fake_write_plain_commitment_json)

    validator = SimpleNamespace(
        wallet=SimpleNamespace(hotkey=SimpleNamespace(ss58_address="hk")),
        uid=0,
        config=SimpleNamespace(netuid=1),
        round_manager=DummyRoundManager(),
        dataset_collector=None,
        subtensor=SimpleNamespace(get_current_block=lambda: 4000),
    )

    st = DummySubtensor()
    cid = await consensus_mod.publish_round_snapshot(
        validator=validator,
        st=st,
        round_number=5,
        tasks_completed=3,
    )

    assert cid == "cid123"
    assert recorded_payloads, "expected payload upload"
    payload, filename = recorded_payloads[0]
    assert filename.endswith("_mid.json")
    assert payload["phase"] == "mid"


@pytest.mark.asyncio
async def test_aggregate_scores_from_commitments_with_blocks(monkeypatch):
    monkeypatch.setattr(consensus_mod, "ENABLE_DISTRIBUTED_CONSENSUS", True, raising=False)
    monkeypatch.setattr(consensus_mod, "MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO", 0.0, raising=False)
    monkeypatch.setattr(consensus_mod, "CONSENSUS_VERIFICATION_ENABLED", False, raising=False)

    async def fake_read_all_plain_commitments(st, netuid, block=None):  # noqa: ARG002
        return {
            "val1": {"e": 99, "pe": 100, "c": "cid1", "stake": 1.0},
            "val2": {"e": 99, "pe": 100, "c": "cid2", "stake": 3.0},
        }

    async def fake_aget_json(cid, api_url=None, expected_sha256_hex=None):  # noqa: ARG002
        scores = {"1": 0.2, "2": 0.8} if cid == "cid1" else {"1": 1.0, "2": 0.4}
        return {"scores": scores}, None, None

    async def fake_verify_payload_sample(*args, **kwargs):
        return True, None

    monkeypatch.setattr(consensus_mod, "read_all_plain_commitments", fake_read_all_plain_commitments)
    monkeypatch.setattr(consensus_mod, "aget_json", fake_aget_json)
    monkeypatch.setattr(consensus_mod, "_verify_payload_sample", fake_verify_payload_sample)

    validator = SimpleNamespace(
        wallet=SimpleNamespace(hotkey=SimpleNamespace(ss58_address="hk")),
        uid=0,
        config=SimpleNamespace(netuid=1),
        metagraph=SimpleNamespace(
            hotkeys=["val1", "val2"],
            stake=[1.0, 3.0],
            axons=[SimpleNamespace(hotkey="val1"), SimpleNamespace(hotkey="val2")],
        ),
        round_manager=DummyRoundManager(),
    )

    st = SimpleNamespace()
    scores, details = await consensus_mod.aggregate_scores_from_commitments(
        validator=validator,
        st=st,
        start_block=360 * 99,
        target_block=360 * 100,
    )

    assert scores  # weighted average should exist
    assert pytest.approx(scores[1], rel=1e-6) == (0.2 * 1 + 1.0 * 3) / 4
    assert details["round_target_epoch"] == pytest.approx(100.0)
