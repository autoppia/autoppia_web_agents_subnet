from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from rich.console import Console

from autoppia_web_agents_subnet.miner.cli import payment as payment_mod
from autoppia_web_agents_subnet.miner.cli import _common as common_mod


class _DummyWallet:
    def __init__(self, name: str, hotkey: str):
        self.name = name
        self.hotkey_str = hotkey
        self.hotkey = SimpleNamespace(ss58_address=f"{hotkey}_ss58")
        self.coldkeypub = SimpleNamespace(ss58_address="miner_coldkey_ss58")


class _DummySubtensor:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_current_block(self):
        return common_mod._DEFAULT_MINIMUM_START_BLOCK + common_mod._round_block_length() * 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_payment_cli_shows_all_matching_validators():
    args = SimpleNamespace(
        wallet_name="default",
        wallet_hotkey="default",
        subtensor_network="finney",
        subtensor_chain_endpoint=None,
        netuid=36,
        validator="",
        payment_round=None,
        payment_season=1,
    )

    all_commits = {
        "validator_hotkey_a": {"c": "cid-a", "s": 1, "r": 1},
        "validator_hotkey_b": {"c": "cid-b", "s": 1, "r": 2},
    }

    payloads = {
        "cid-a": ({
            "validator_uid": 10,
            "consumed_evals_by_coldkey": {"miner_coldkey_ss58": 1},
            "paid_rao_by_coldkey": {"miner_coldkey_ss58": 2_000_000_000},
            "payment_config": {
                "alpha_per_eval": 1.0,
                "payment_wallet_ss58": "pay_wallet",
                "last_scanned_block": 1234,
                "cache_updated_at_unix": 1_700_000_000,
            },
        }, None, None),
        "cid-b": ({
            "validator_uid": 11,
            "consumed_evals_by_coldkey": {"miner_coldkey_ss58": 3},
            "paid_rao_by_coldkey": {"miner_coldkey_ss58": 5_000_000_000},
            "payment_config": {
                "alpha_per_eval": 1.0,
                "payment_wallet_ss58": "pay_wallet",
                "last_scanned_block": 1235,
                "cache_updated_at_unix": 1_700_000_001,
            },
        }, None, None),
    }

    async def fake_get_json_async(cid, api_url=None):
        return payloads[cid]

    record_console = Console(record=True, width=120)

    with patch("builtins.input", return_value=""):
        with patch("bittensor.Wallet", _DummyWallet):
            with patch("bittensor.AsyncSubtensor", return_value=_DummySubtensor()):
                with patch(
                    "autoppia_web_agents_subnet.utils.commitments.read_all_plain_commitments",
                    AsyncMock(return_value=all_commits),
                ):
                    with patch(
                        "autoppia_web_agents_subnet.utils.ipfs_client.get_json_async",
                        side_effect=fake_get_json_async,
                    ):
                        with patch.object(common_mod, "_get_console", return_value=record_console):
                            with patch.object(common_mod, "_get_err_console", return_value=record_console):
                                await payment_mod.run(args)

    rendered = record_console.export_text()
    assert "Payment Status for miner_coldkey_ss" in rendered
    assert rendered.count("Validator validator_hotkey") == 2
    assert "Round               1" in rendered
    assert "Round               2" in rendered
    assert "Last scanned block" in rendered
    assert "Cache updated" in rendered
