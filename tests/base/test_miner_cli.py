from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner


@pytest.mark.unit
def test_resolve_common_options_uses_persistent_config(monkeypatch, tmp_path):
    from autoppia_web_agents_subnet.miner.config import load_config, update_config
    from autoppia_web_agents_subnet.miner.service import CommonOptions, resolve_common_options

    config_path = tmp_path / "miner-cli.json"
    monkeypatch.setenv("AUTOPPIA_MINER_CLI_CONFIG", str(config_path))

    update_config(
        {
            "wallet_name": "miner",
            "wallet_hotkey": "default",
            "subtensor_network": "finney",
            "netuid": 36,
            "consensus_version": 1,
        }
    )

    resolved = resolve_common_options(
        CommonOptions(
            wallet_name=None,
            wallet_hotkey=None,
            inspect_hotkey_ss58=None,
            inspect_round=None,
            inspect_season=None,
            consensus_version=None,
            subtensor_network=None,
            subtensor_chain_endpoint=None,
            netuid=None,
        )
    )

    assert load_config()["wallet_name"] == "miner"
    assert resolved.wallet_name == "miner"
    assert resolved.wallet_hotkey == "default"
    assert resolved.subtensor_network == "finney"
    assert resolved.netuid == 36
    assert resolved.consensus_version == 1


@pytest.mark.unit
def test_normalize_requested_round_for_snapshot_uses_previous_internal_round():
    from autoppia_web_agents_subnet.miner.service import _normalize_requested_round_for_snapshot

    assert _normalize_requested_round_for_snapshot(None) is None
    assert _normalize_requested_round_for_snapshot(1) == 1
    assert _normalize_requested_round_for_snapshot(2) == 2
    assert _normalize_requested_round_for_snapshot(10) == 10


@pytest.mark.unit
def test_target_round_for_status_display_prefers_requested_round():
    from autoppia_web_agents_subnet.miner.service import _target_round_for_status_display

    assert _target_round_for_status_display(inspect_round=10, next_round=11) == 10
    assert _target_round_for_status_display(inspect_round=1, next_round=11) == 1
    assert _target_round_for_status_display(inspect_round=None, next_round=11) == 11


@pytest.mark.unit
def test_rank_candidate_season_round_pairs_prefers_highest_aggregate_stake():
    from autoppia_web_agents_subnet.miner.service import _rank_candidate_season_round_pairs

    rows = [
        {"season": 180, "round_number": 5, "stake": 1.0},
        {"season": 1, "round_number": 13, "stake": 100.0},
        {"season": 1, "round_number": 13, "stake": 50.0},
        {"season": 124, "round_number": 10, "stake": 2.0},
    ]

    assert _rank_candidate_season_round_pairs(rows) == [(1, 13), (124, 10), (180, 5)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_latest_consensus_snapshot_selects_latest_round_and_aggregates(monkeypatch):
    from autoppia_web_agents_subnet.miner.service import _load_latest_consensus_snapshot

    metagraph = SimpleNamespace(
        hotkeys=["validator-a", "validator-b", "miner-1"],
        stake=[10.0, 20.0, 0.0],
    )
    commitments = {
        "validator-a": {"v": 1, "s": 1, "r": 2, "c": "cid-a-old"},
        "validator-b": {"v": 1, "s": 1, "r": 2, "c": "cid-b-old"},
        "validator-a-latest": {"v": 1, "s": 1, "r": 3, "c": "cid-a-new"},
        "validator-b-latest": {"v": 1, "s": 1, "r": 3, "c": "cid-b-new"},
        "miner-1": {"t": "m", "s": 1, "r": 3, "g": "https://github.com/test/agent/tree/main", "n": "agent"},
    }
    # expose latest validator hotkeys in metagraph only
    metagraph.hotkeys = ["validator-a-latest", "validator-b-latest", "miner-1"]

    payloads = {
        "cid-a-new": {
            "s": 1,
            "r": 3,
            "miners": [
                {
                    "uid": 2,
                    "best_run": {
                        "reward": 1.0,
                        "score": 0.8,
                        "time": 3.0,
                        "cost": 0.1,
                        "penalty": 0.25,
                        "tasks_received": 1,
                        "tasks_success": 1,
                    },
                }
            ],
        },
        "cid-b-new": {
            "s": 1,
            "r": 3,
            "miners": [
                {
                    "uid": 2,
                    "best_run": {
                        "reward": 0.5,
                        "score": 0.4,
                        "time": 5.0,
                        "cost": 0.3,
                        "penalty": 0.0,
                        "tasks_received": 1,
                        "tasks_success": 0,
                    },
                }
            ],
        },
    }

    async def fake_get_json(cid: str, **_: object):
        return payloads[cid], b"{}", "sha"

    with (
        patch("autoppia_web_agents_subnet.miner.service.read_all_plain_commitments", new=AsyncMock(return_value=commitments)),
        patch("autoppia_web_agents_subnet.miner.service.get_json_async", new=AsyncMock(side_effect=fake_get_json)),
        patch("autoppia_web_agents_subnet.miner.service.MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO", 0),
    ):
        snapshot = await _load_latest_consensus_snapshot(st=object(), netuid=36, metagraph=metagraph, consensus_version=1)

    assert snapshot is not None
    assert snapshot.source == "chain"
    assert snapshot.season == 1
    assert snapshot.round_number == 3
    assert len(snapshot.validators) == 2
    assert snapshot.aggregated_scores[2] == pytest.approx((10.0 * 1.0 + 20.0 * 0.5) / 30.0)
    assert snapshot.stats_by_miner[2]["avg_penalty"] == pytest.approx((10.0 * 0.25 + 20.0 * 0.0) / 30.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_latest_consensus_snapshot_round_filter_prefers_season_where_target_miner_exists():
    from autoppia_web_agents_subnet.miner.service import _load_latest_consensus_snapshot

    metagraph = SimpleNamespace(
        hotkeys=["validator-season1", "validator-season124", "miner-target"],
        stake=[15.0, 25.0, 0.0],
    )
    commitments = {
        "validator-season1": {"v": 1, "s": 1, "r": 10, "c": "cid-season1-round10"},
        "validator-season124": {"v": 1, "s": 124, "r": 10, "c": "cid-season124-round10"},
        "miner-target": {"t": "m", "s": 1, "r": 10, "g": "https://github.com/test/agent/tree/main", "n": "agent"},
    }
    payloads = {
        "cid-season1-round10": {
            "s": 1,
            "r": 10,
            "miners": [
                {
                    "uid": 2,
                    "best_run": {
                        "reward": 0.7,
                        "score": 0.6,
                        "time": 12.0,
                        "cost": 0.2,
                        "penalty": 0.0,
                        "tasks_received": 10,
                        "tasks_success": 7,
                    },
                }
            ],
        },
        "cid-season124-round10": {
            "s": 124,
            "r": 10,
            "miners": [
                {
                    "uid": 999,
                    "best_run": {
                        "reward": 0.9,
                        "score": 0.9,
                        "time": 5.0,
                        "cost": 0.1,
                        "penalty": 0.0,
                        "tasks_received": 10,
                        "tasks_success": 9,
                    },
                }
            ],
        },
    }

    async def fake_get_json(cid: str, **_: object):
        return payloads[cid], b"{}", "sha"

    with (
        patch("autoppia_web_agents_subnet.miner.service.read_all_plain_commitments", new=AsyncMock(return_value=commitments)),
        patch("autoppia_web_agents_subnet.miner.service.get_json_async", new=AsyncMock(side_effect=fake_get_json)),
        patch("autoppia_web_agents_subnet.miner.service.MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO", 0),
    ):
        snapshot = await _load_latest_consensus_snapshot(
            st=object(),
            netuid=36,
            metagraph=metagraph,
            consensus_version=1,
            requested_round=10,
            target_miner_uid=2,
        )

    assert snapshot is not None
    assert snapshot.season == 1
    assert snapshot.round_number == 10
    assert 2 in snapshot.aggregated_scores


@pytest.mark.unit
def test_is_missing_commitment_treats_blank_string_as_missing():
    from autoppia_web_agents_subnet.miner.service import _is_missing_commitment

    assert _is_missing_commitment(None) is True
    assert _is_missing_commitment("") is True
    assert _is_missing_commitment("   ") is True
    assert _is_missing_commitment({}) is False


@pytest.mark.unit
def test_config_set_preserves_existing_keys(monkeypatch, tmp_path):
    from autoppia_web_agents_subnet.miner.cli import cli
    from autoppia_web_agents_subnet.miner.config import load_config, update_config

    config_path = tmp_path / "miner-cli.json"
    monkeypatch.setenv("AUTOPPIA_MINER_CLI_CONFIG", str(config_path))

    update_config(
        {
            "wallet_name": "miner",
            "github": "https://github.com/autoppia/autoppia_operator/tree/main",
        }
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["config", "set", "--consensus-version", "1"])

    assert result.exit_code == 0
    config = load_config()
    assert config["wallet_name"] == "miner"
    assert config["github"] == "https://github.com/autoppia/autoppia_operator/tree/main"
    assert config["consensus_version"] == 1


@pytest.mark.unit
def test_load_miner_season_history_from_backup_dir_filters_and_sorts(monkeypatch, tmp_path):
    from autoppia_web_agents_subnet.miner.service import _load_miner_season_history_from_backup_dir

    backup_root = tmp_path / "data"
    monkeypatch.setenv("IWAP_BACKUP_DIR", str(backup_root))

    season_1_round_2 = backup_root / "season_1" / "round_2"
    season_1_round_3 = backup_root / "season_1" / "round_3"
    season_2_round_1 = backup_root / "season_2" / "round_1"
    season_1_round_2.mkdir(parents=True)
    season_1_round_3.mkdir(parents=True)
    season_2_round_1.mkdir(parents=True)

    target_hotkey = "miner-hotkey-1"
    other_hotkey = "miner-hotkey-2"

    (season_1_round_2 / "post_consensus.json").write_text(
        json.dumps(
            {
                "season": 1,
                "round": 2,
                "miners": [
                    {
                        "hotkey": target_hotkey,
                        "github_url": "https://github.com/example/repo/commit/aaa",
                        "best_run_consensus": {
                            "commit_sha": "aaa",
                            "normalized_repo": "https://github.com/example/repo",
                            "reward": 0.4,
                            "score": 0.5,
                            "time": 10.0,
                            "cost": 0.01,
                            "penalty": 0.0,
                            "rank": 3,
                            "tasks_received": 10,
                            "tasks_success": 4,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (season_1_round_3 / "post_consensus.json").write_text(
        json.dumps(
            {
                "season": 1,
                "round": 3,
                "miners": [
                    {
                        "hotkey": target_hotkey,
                        "github_url": "https://github.com/example/repo/commit/bbb",
                        "best_run_consensus": {
                            "commit_sha": "bbb",
                            "normalized_repo": "https://github.com/example/repo",
                            "reward": 0.6,
                            "score": 0.7,
                            "time": 8.0,
                            "cost": 0.02,
                            "penalty": 0.0,
                            "rank": 1,
                            "tasks_received": 10,
                            "tasks_success": 6,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (season_2_round_1 / "post_consensus.json").write_text(
        json.dumps(
            {
                "season": 2,
                "round": 1,
                "miners": [
                    {
                        "hotkey": other_hotkey,
                        "github_url": "https://github.com/example/repo/commit/ccc",
                        "best_run_consensus": {"commit_sha": "ccc", "reward": 0.1, "score": 0.1},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    entries = _load_miner_season_history_from_backup_dir(target_hotkey_ss58=target_hotkey, requested_season=1)

    assert [(entry.season, entry.round_number) for entry in entries] == [(1, 2), (1, 3)]
    assert entries[-1].commit_sha == "bbb"
    assert entries[-1].rank == 1


@pytest.mark.unit
def test_load_validator_round_history_from_backup_dir_extracts_reward_and_eval(monkeypatch, tmp_path):
    from autoppia_web_agents_subnet.miner.service import _load_validator_round_history_from_backup_dir

    backup_root = tmp_path / "data"
    monkeypatch.setenv("IWAP_BACKUP_DIR", str(backup_root))
    round_dir = backup_root / "season_1" / "round_3"
    round_dir.mkdir(parents=True)

    target_hotkey = "miner-hotkey-1"
    (round_dir / "ipfs_downloaded.json").write_text(
        json.dumps(
            {
                "payloads": [
                    {
                        "validator_uid": 71,
                        "validator_hotkey": "validator-hotkey-71",
                        "payload": {
                            "payload": {
                                "s": 1,
                                "r": 3,
                                "miners": [
                                    {
                                        "hotkey": target_hotkey,
                                        "best_run": {"reward": 0.42, "score": 0.6},
                                        "current_run": {"tasks_received": 10, "score": 0.55},
                                    },
                                    {
                                        "hotkey": "other-miner",
                                        "best_run": {"reward": 0.90, "score": 0.95},
                                    },
                                ],
                            }
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    entries = _load_validator_round_history_from_backup_dir(target_hotkey_ss58=target_hotkey, requested_season=1)

    assert len(entries) == 1
    assert entries[0].validator_uid == 71
    assert entries[0].round_number == 3
    assert entries[0].present is True
    assert entries[0].reward == pytest.approx(0.42)
    assert entries[0].evaluated is True
    assert entries[0].best_score_in_validator == pytest.approx(0.95)


@pytest.mark.unit
def test_validator_history_from_snapshot_extracts_single_round():
    from autoppia_web_agents_subnet.miner.service import LatestConsensusSnapshot, _validator_history_from_snapshot

    snapshot = LatestConsensusSnapshot(
        source="chain",
        season=1,
        round_number=13,
        aggregated_scores={},
        stats_by_miner={},
        validators=[],
        downloaded_payloads=[
            {
                "uid": 83,
                "validator_hotkey": "validator-hotkey-83",
                "payload": {
                    "miners": [
                        {
                            "hotkey": "miner-hotkey-1",
                            "best_run": {"reward": 0.11, "score": 0.2},
                            "current_run": {"tasks_received": 0, "score": 0.0},
                        }
                    ]
                },
            }
        ],
    )

    entries = _validator_history_from_snapshot(snapshot=snapshot, target_hotkey_ss58="miner-hotkey-1")

    assert len(entries) == 1
    assert entries[0].validator_uid == 83
    assert entries[0].round_number == 13
    assert entries[0].present is True
    assert entries[0].reward == pytest.approx(0.11)
    assert entries[0].evaluated is False


@pytest.mark.unit
def test_validator_history_from_snapshot_keeps_absent_miner_as_blankable_entry():
    from autoppia_web_agents_subnet.miner.service import LatestConsensusSnapshot, _validator_history_from_snapshot

    snapshot = LatestConsensusSnapshot(
        source="chain",
        season=1,
        round_number=13,
        aggregated_scores={},
        stats_by_miner={},
        validators=[],
        downloaded_payloads=[
            {
                "uid": 83,
                "validator_hotkey": "validator-hotkey-83",
                "payload": {
                    "miners": [
                        {
                            "hotkey": "other-miner",
                            "best_run": {"reward": 0.11, "score": 0.2},
                            "current_run": {"tasks_received": 10, "score": 0.2},
                        }
                    ]
                },
            }
        ],
    )

    entries = _validator_history_from_snapshot(snapshot=snapshot, target_hotkey_ss58="miner-hotkey-1")

    assert len(entries) == 1
    assert entries[0].validator_uid == 83
    assert entries[0].round_number == 13
    assert entries[0].present is False
    assert entries[0].reward == pytest.approx(0.0)
    assert entries[0].evaluated is False


@pytest.mark.unit
def test_validator_history_from_snapshot_uses_summary_leader_when_miner_absent_from_miners():
    from autoppia_web_agents_subnet.miner.service import LatestConsensusSnapshot, _validator_history_from_snapshot

    snapshot = LatestConsensusSnapshot(
        source="chain",
        season=1,
        round_number=13,
        aggregated_scores={},
        stats_by_miner={},
        validators=[],
        downloaded_payloads=[
            {
                "uid": 83,
                "validator_hotkey": "validator-hotkey-83",
                "payload": {
                    "summary": {
                        "leader_before_round": {"uid": 219, "reward": 0.3047, "score": 0.3079},
                        "leader_after_round": {"uid": 203, "reward": 0.3372, "score": 0.34},
                    },
                    "miners": [
                        {
                            "hotkey": "other-miner",
                            "best_run": {"reward": 0.11, "score": 0.2},
                            "current_run": {"tasks_received": 10, "score": 0.2},
                        }
                    ],
                },
            }
        ],
    )

    entries = _validator_history_from_snapshot(
        snapshot=snapshot,
        target_hotkey_ss58="miner-hotkey-1",
        target_miner_uid=219,
    )

    assert len(entries) == 1
    assert entries[0].validator_uid == 83
    assert entries[0].present is True
    assert entries[0].reward == pytest.approx(0.3047)
    assert entries[0].miner_score == pytest.approx(0.3079)
    assert entries[0].evaluated is False


@pytest.mark.unit
def test_round_scan_block_map_anchors_past_rounds_to_start_of_next_round():
    from autoppia_web_agents_subnet.miner.service import _round_scan_block_map

    blocks = _round_scan_block_map(
        current_block=10_500,
        minimum_start_block=1_000,
        round_block_span=500,
        latest_round_number=4,
    )

    assert blocks == {
        1: 1499,
        2: 1999,
        3: 2499,
        4: 10500,
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_validator_history_from_chain_scan_uses_current_block_anchored_round_blocks():
    from autoppia_web_agents_subnet.miner.service import LatestConsensusSnapshot, _validator_history_from_chain_scan

    snapshot = LatestConsensusSnapshot(
        source="chain",
        season=1,
        round_number=3,
        aggregated_scores={},
        stats_by_miner={},
        validators=[{"uid": 83, "hotkey": "validator-hotkey-83", "stake": 1.0}],
        downloaded_payloads=[
            {
                "uid": 83,
                "validator_hotkey": "validator-hotkey-83",
                "payload": {
                    "miners": [
                        {
                            "uid": 219,
                            "hotkey": "miner-hotkey-1",
                            "best_run": {
                                "reward": 0.11,
                                "score": 0.2,
                                "evaluation_context": {
                                    "minimum_start_block": 1_000,
                                    "blocks_per_epoch": 100,
                                    "round_size_epochs": 5,
                                },
                            },
                        }
                    ]
                },
            }
        ],
    )

    block_calls: list[int] = []

    async def fake_read_all_plain_commitments(_st, *, netuid, block=None):
        assert netuid == 36
        block_calls.append(int(block))
        round_by_block = {
            1499: {"validator-hotkey-83": {"v": 1, "s": 1, "r": 1, "c": "cid-r1"}},
            1999: {"validator-hotkey-83": {"v": 1, "s": 1, "r": 2, "c": "cid-r2"}},
            2500: {"validator-hotkey-83": {"v": 1, "s": 1, "r": 3, "c": "cid-r3"}},
        }
        return round_by_block.get(int(block), {})

    async def fake_get_json(cid: str, **_: object):
        payloads = {
            "cid-r1": {"miners": [{"hotkey": "miner-hotkey-1", "best_run": {"reward": 0.1, "score": 0.1}}]},
            "cid-r2": {"miners": [{"hotkey": "miner-hotkey-1", "best_run": {"reward": 0.2, "score": 0.2}}]},
            "cid-r3": {"miners": [{"hotkey": "miner-hotkey-1", "best_run": {"reward": 0.3, "score": 0.3}}]},
        }
        return payloads[cid], b"{}", "sha"

    with (
        patch("autoppia_web_agents_subnet.miner.service.read_all_plain_commitments", new=AsyncMock(side_effect=fake_read_all_plain_commitments)),
        patch("autoppia_web_agents_subnet.miner.service.get_json_async", new=AsyncMock(side_effect=fake_get_json)),
    ):
        entries = await _validator_history_from_chain_scan(
            st=object(),
            netuid=36,
            current_block=2500,
            snapshot=snapshot,
            target_hotkey_ss58="miner-hotkey-1",
            target_miner_uid=219,
            consensus_version=1,
        )

    assert block_calls == [1499, 1999, 2500]
    assert [entry.round_number for entry in entries] == [1, 2, 3]
    assert [entry.reward for entry in entries] == [pytest.approx(0.1), pytest.approx(0.2), pytest.approx(0.3)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_validator_history_from_chain_scan_raises_archive_required_on_state_discarded():
    from autoppia_web_agents_subnet.miner.service import (
        HistoricalCommitmentArchiveRequired,
        LatestConsensusSnapshot,
        _validator_history_from_chain_scan,
    )

    snapshot = LatestConsensusSnapshot(
        source="chain",
        season=1,
        round_number=3,
        aggregated_scores={},
        stats_by_miner={},
        validators=[{"uid": 83, "hotkey": "validator-hotkey-83", "stake": 1.0}],
        downloaded_payloads=[
            {
                "uid": 83,
                "validator_hotkey": "validator-hotkey-83",
                "payload": {
                    "miners": [
                        {
                            "uid": 219,
                            "hotkey": "miner-hotkey-1",
                            "best_run": {
                                "reward": 0.11,
                                "score": 0.2,
                                "evaluation_context": {
                                    "minimum_start_block": 1_000,
                                    "blocks_per_epoch": 100,
                                    "round_size_epochs": 5,
                                },
                            },
                        }
                    ]
                },
            }
        ],
    )

    class FakeStateDiscardedError(Exception):
        pass

    async def fake_read_all_plain_commitments(_st, *, netuid, block=None):
        raise FakeStateDiscardedError(f"state discarded at {block}")

    with (
        patch("autoppia_web_agents_subnet.miner.service.StateDiscardedError", FakeStateDiscardedError),
        patch("autoppia_web_agents_subnet.miner.service.read_all_plain_commitments", new=AsyncMock(side_effect=fake_read_all_plain_commitments)),
    ):
        with pytest.raises(HistoricalCommitmentArchiveRequired):
            await _validator_history_from_chain_scan(
                st=object(),
                netuid=36,
                current_block=2500,
                snapshot=snapshot,
                target_hotkey_ss58="miner-hotkey-1",
                target_miner_uid=219,
                consensus_version=1,
            )
