from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from autoppia_web_agents_subnet.validator.settlement.consensus import aggregate_scores_from_commitments


def _payload_for_miner(
    *,
    uid: int,
    validator_version: str,
    best_run: dict | None,
    current_run: dict | None = None,
) -> dict:
    return {
        "validator_version": validator_version,
        "miners": [
            {
                "uid": uid,
                "best_run": best_run,
                "current_run": current_run,
            }
        ],
    }


def _best_run(
    *,
    reward: float,
    score: float,
    time_s: float,
    cost: float,
    tasks_received: int,
    tasks_success: int,
) -> dict:
    return {
        "reward": reward,
        "score": score,
        "time": time_s,
        "cost": cost,
        "tasks_received": tasks_received,
        "tasks_success": tasks_success,
    }


def _configure_consensus_validator(validator, *, version: str, hotkeys: list[str], stakes: list[float]) -> None:
    validator.version = version
    validator.current_round_id = "validator_round_1_1_post_consensus"
    validator._current_round_number = 1
    validator.metagraph.hotkeys = hotkeys
    validator.metagraph.n = len(hotkeys)
    validator.metagraph.stake = stakes


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_consensus_stake_weights_best_run_metrics(dummy_validator):
    """
    Scenario:
    We simulate two validators evaluating the same miner with different metrics and different stake.

    What this test proves:
    - reward is aggregated stake-weighted
    - score is aggregated stake-weighted
    - time is aggregated stake-weighted
    - cost is aggregated stake-weighted
    - tasks_received/tasks_success are summed in the post-consensus details
    """
    validator = dummy_validator
    _configure_consensus_validator(
        validator,
        version="16.0.0",
        hotkeys=["hk1", "hk2"],
        stakes=[10000.0, 20000.0],
    )

    commits = {
        "hk1": {"v": 1, "s": 1, "r": 1, "c": "cid-1"},
        "hk2": {"v": 1, "s": 1, "r": 1, "c": "cid-2"},
    }
    payload_1 = _payload_for_miner(
        uid=48,
        validator_version="16.0.1",
        best_run=_best_run(
            reward=0.2,
            score=0.3,
            time_s=80.0,
            cost=0.05,
            tasks_received=100,
            tasks_success=20,
        ),
    )
    payload_2 = _payload_for_miner(
        uid=48,
        validator_version="16.0.3",
        best_run=_best_run(
            reward=0.5,
            score=0.6,
            time_s=20.0,
            cost=0.01,
            tasks_received=100,
            tasks_success=50,
        ),
    )

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments", new=AsyncMock(return_value=commits)),
        patch(
            "autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async",
            new=AsyncMock(side_effect=[(payload_1, None, None), (payload_2, None, None)]),
        ),
    ):
        consensus_rewards, details = await aggregate_scores_from_commitments(validator, st=Mock())

    assert consensus_rewards[48] == pytest.approx((10000.0 * 0.2 + 20000.0 * 0.5) / 30000.0)
    assert details["stats_by_miner"][48]["avg_reward"] == pytest.approx(0.4)
    assert details["stats_by_miner"][48]["avg_eval_score"] == pytest.approx(0.5)
    assert details["stats_by_miner"][48]["avg_eval_time"] == pytest.approx(40.0)
    assert details["stats_by_miner"][48]["avg_cost"] == pytest.approx((10000.0 * 0.05 + 20000.0 * 0.01) / 30000.0)
    assert details["stats_by_miner"][48]["tasks_sent"] == 200
    assert details["stats_by_miner"][48]["tasks_success"] == 70


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_consensus_accepts_patch_updates_but_skips_minor_and_major_mismatch(dummy_validator):
    """
    Scenario:
    The local validator runs `16.0.x`.
    Three remote validators publish payloads:
    - one in `16.0.5` -> should be accepted
    - one in `16.1.0` -> should be skipped
    - one in `17.0.0` -> should be skipped

    What this test proves:
    consensus compatibility is based on `major.minor`, not exact patch.
    """
    validator = dummy_validator
    _configure_consensus_validator(
        validator,
        version="16.0.0",
        hotkeys=["hk1", "hk2", "hk3"],
        stakes=[15000.0, 15000.0, 15000.0],
    )

    commits = {
        "hk1": {"v": 1, "s": 1, "r": 1, "c": "cid-1"},
        "hk2": {"v": 1, "s": 1, "r": 1, "c": "cid-2"},
        "hk3": {"v": 1, "s": 1, "r": 1, "c": "cid-3"},
    }

    accepted_payload = _payload_for_miner(
        uid=48,
        validator_version="16.0.5",
        best_run=_best_run(reward=0.3, score=0.3, time_s=30.0, cost=0.02, tasks_received=100, tasks_success=30),
    )
    wrong_minor_payload = _payload_for_miner(
        uid=48,
        validator_version="16.1.0",
        best_run=_best_run(reward=0.9, score=0.9, time_s=5.0, cost=0.01, tasks_received=100, tasks_success=90),
    )
    wrong_major_payload = _payload_for_miner(
        uid=48,
        validator_version="17.0.0",
        best_run=_best_run(reward=0.95, score=0.95, time_s=4.0, cost=0.01, tasks_received=100, tasks_success=95),
    )

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments", new=AsyncMock(return_value=commits)),
        patch(
            "autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async",
            new=AsyncMock(
                side_effect=[
                    (accepted_payload, None, None),
                    (wrong_minor_payload, None, None),
                    (wrong_major_payload, None, None),
                ]
            ),
        ),
    ):
        consensus_rewards, details = await aggregate_scores_from_commitments(validator, st=Mock())

    assert consensus_rewards == {48: pytest.approx(0.3)}
    assert details["stats_by_miner"][48]["avg_reward"] == pytest.approx(0.3)
    assert details["skips"]["wrong_validator_version"] == [("hk2", "16.1.0"), ("hk3", "17.0.0")]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_consensus_two_validators_two_miners_and_one_high_stake_incompatible_validator(dummy_validator):
    """
    Scenario:
    We have three validators and two miners.

    Validators:
    - A stake 10k, compatible version
    - B stake 20k, compatible version
    - C stake 50k, incompatible version

    Miners:
    - miner 48
    - miner 127

    What this test proves:
    - validator C is completely excluded even though it has the highest stake
    - validators A and B still form consensus normally
    - the reward for each miner is computed independently with only A and B
    """
    validator = dummy_validator
    _configure_consensus_validator(
        validator,
        version="16.0.0",
        hotkeys=["hk1", "hk2", "hk3"],
        stakes=[10000.0, 20000.0, 50000.0],
    )

    commits = {
        "hk1": {"v": 1, "s": 1, "r": 1, "c": "cid-1"},
        "hk2": {"v": 1, "s": 1, "r": 1, "c": "cid-2"},
        "hk3": {"v": 1, "s": 1, "r": 1, "c": "cid-3"},
    }

    payload_a = {
        "validator_version": "16.0.1",
        "miners": [
            {"uid": 48, "best_run": _best_run(reward=0.2, score=0.2, time_s=20.0, cost=0.01, tasks_received=100, tasks_success=20), "current_run": None},
            {"uid": 127, "best_run": _best_run(reward=0.6, score=0.6, time_s=60.0, cost=0.03, tasks_received=100, tasks_success=60), "current_run": None},
        ],
    }
    payload_b = {
        "validator_version": "16.0.5",
        "miners": [
            {"uid": 48, "best_run": _best_run(reward=0.5, score=0.5, time_s=50.0, cost=0.02, tasks_received=100, tasks_success=50), "current_run": None},
            {"uid": 127, "best_run": _best_run(reward=0.3, score=0.3, time_s=30.0, cost=0.015, tasks_received=100, tasks_success=30), "current_run": None},
        ],
    }
    payload_c = {
        "validator_version": "16.1.0",
        "miners": [
            {"uid": 48, "best_run": _best_run(reward=0.99, score=0.99, time_s=1.0, cost=0.001, tasks_received=100, tasks_success=99), "current_run": None},
            {"uid": 127, "best_run": _best_run(reward=0.99, score=0.99, time_s=1.0, cost=0.001, tasks_received=100, tasks_success=99), "current_run": None},
        ],
    }

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments", new=AsyncMock(return_value=commits)),
        patch(
            "autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async",
            new=AsyncMock(side_effect=[(payload_a, None, None), (payload_b, None, None), (payload_c, None, None)]),
        ),
    ):
        consensus_rewards, details = await aggregate_scores_from_commitments(validator, st=Mock())

    assert consensus_rewards[48] == pytest.approx((10000.0 * 0.2 + 20000.0 * 0.5) / 30000.0)
    assert consensus_rewards[127] == pytest.approx((10000.0 * 0.6 + 20000.0 * 0.3) / 30000.0)
    assert details["stats_by_miner"][48]["avg_reward"] == pytest.approx(0.4)
    assert details["stats_by_miner"][127]["avg_reward"] == pytest.approx(0.4)
    assert details["validators"] == [
        {"hotkey": "hk1", "uid": 0, "stake": 10000.0, "cid": "cid-1"},
        {"hotkey": "hk2", "uid": 1, "stake": 20000.0, "cid": "cid-2"},
    ]
    assert details["skips"]["wrong_validator_version"] == [("hk3", "16.1.0")]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_consensus_uses_best_run_when_current_run_is_null(dummy_validator):
    """
    Scenario:
    A validator does not re-evaluate in the current round, so `current_run` is null.
    It still publishes a valid `best_run`.

    What this test proves:
    post-consensus must use `best_run` and must not zero out that validator just because `current_run` is absent.
    """
    validator = dummy_validator
    _configure_consensus_validator(
        validator,
        version="16.0.0",
        hotkeys=["hk1"],
        stakes=[18000.0],
    )

    commits = {"hk1": {"v": 1, "s": 1, "r": 1, "c": "cid-1"}}
    payload = _payload_for_miner(
        uid=48,
        validator_version="16.0.9",
        best_run=_best_run(
            reward=0.3155677995,
            score=0.07,
            time_s=94.711490646,
            cost=0.038233545,
            tasks_received=100,
            tasks_success=7,
        ),
        current_run=None,
    )

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments", new=AsyncMock(return_value=commits)),
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async", new=AsyncMock(return_value=(payload, None, None))),
    ):
        consensus_rewards, details = await aggregate_scores_from_commitments(validator, st=Mock())

    assert consensus_rewards[48] == pytest.approx(0.3155677995)
    assert details["stats_by_miner"][48]["avg_eval_score"] == pytest.approx(0.07)
    assert details["stats_by_miner"][48]["tasks_sent"] == 100
    assert details["current_stats_by_miner"] == {}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_consensus_keeps_best_run_stats_separate_from_current_run_stats(dummy_validator):
    """
    Scenario:
    Two compatible validators publish both `best_run` and `current_run` for the same miner.

    What this test proves:
    - `stats_by_miner` is built from `best_run`
    - `current_stats_by_miner` is built from `current_run`
    - both blocks stay separate and both are stake-weighted correctly
    """
    validator = dummy_validator
    _configure_consensus_validator(
        validator,
        version="16.0.0",
        hotkeys=["hk1", "hk2"],
        stakes=[10000.0, 20000.0],
    )

    commits = {
        "hk1": {"v": 1, "s": 1, "r": 1, "c": "cid-1"},
        "hk2": {"v": 1, "s": 1, "r": 1, "c": "cid-2"},
    }
    payload_1 = _payload_for_miner(
        uid=48,
        validator_version="16.0.2",
        best_run=_best_run(reward=0.8, score=0.8, time_s=8.0, cost=0.08, tasks_received=100, tasks_success=80),
        current_run=_best_run(reward=0.2, score=0.2, time_s=20.0, cost=0.02, tasks_received=100, tasks_success=20),
    )
    payload_2 = _payload_for_miner(
        uid=48,
        validator_version="16.0.4",
        best_run=_best_run(reward=0.5, score=0.5, time_s=5.0, cost=0.05, tasks_received=100, tasks_success=50),
        current_run=_best_run(reward=0.1, score=0.1, time_s=10.0, cost=0.01, tasks_received=100, tasks_success=10),
    )

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments", new=AsyncMock(return_value=commits)),
        patch(
            "autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async",
            new=AsyncMock(side_effect=[(payload_1, None, None), (payload_2, None, None)]),
        ),
    ):
        consensus_rewards, details = await aggregate_scores_from_commitments(validator, st=Mock())

    assert consensus_rewards[48] == pytest.approx((10000.0 * 0.8 + 20000.0 * 0.5) / 30000.0)

    assert details["stats_by_miner"][48]["avg_reward"] == pytest.approx((10000.0 * 0.8 + 20000.0 * 0.5) / 30000.0)
    assert details["stats_by_miner"][48]["avg_eval_score"] == pytest.approx((10000.0 * 0.8 + 20000.0 * 0.5) / 30000.0)
    assert details["stats_by_miner"][48]["avg_eval_time"] == pytest.approx((10000.0 * 8.0 + 20000.0 * 5.0) / 30000.0)
    assert details["stats_by_miner"][48]["avg_cost"] == pytest.approx((10000.0 * 0.08 + 20000.0 * 0.05) / 30000.0)
    assert details["stats_by_miner"][48]["tasks_sent"] == 200
    assert details["stats_by_miner"][48]["tasks_success"] == 130

    assert details["current_stats_by_miner"][48]["avg_reward"] == pytest.approx((10000.0 * 0.2 + 20000.0 * 0.1) / 30000.0)
    assert details["current_stats_by_miner"][48]["avg_eval_score"] == pytest.approx((10000.0 * 0.2 + 20000.0 * 0.1) / 30000.0)
    assert details["current_stats_by_miner"][48]["avg_eval_time"] == pytest.approx((10000.0 * 20.0 + 20000.0 * 10.0) / 30000.0)
    assert details["current_stats_by_miner"][48]["avg_cost"] == pytest.approx((10000.0 * 0.02 + 20000.0 * 0.01) / 30000.0)
    assert details["current_stats_by_miner"][48]["tasks_sent"] == 200
    assert details["current_stats_by_miner"][48]["tasks_success"] == 30


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_consensus_null_best_run_contributes_zero_for_that_miner_when_validator_has_other_signal(dummy_validator):
    """
    Scenario:
    Two validators participate.
    One publishes a valid `best_run` for miner 48.
    The other validator publishes `best_run = null` for miner 48, but still has a positive best run for miner 127.

    What this test proves:
    a validator is not excluded just because one miner is null.
    For that specific miner, `best_run = null` contributes no signal at all, so the
    miner consensus only uses validators that actually published a best run.
    """
    validator = dummy_validator
    _configure_consensus_validator(
        validator,
        version="16.0.0",
        hotkeys=["hk1", "hk2"],
        stakes=[10000.0, 10000.0],
    )

    commits = {
        "hk1": {"v": 1, "s": 1, "r": 1, "c": "cid-1"},
        "hk2": {"v": 1, "s": 1, "r": 1, "c": "cid-2"},
    }
    payload_ok = _payload_for_miner(
        uid=48,
        validator_version="16.0.0",
        best_run=_best_run(reward=0.4, score=0.4, time_s=40.0, cost=0.02, tasks_received=100, tasks_success=40),
    )
    payload_zero = _payload_for_miner(
        validator_version="16.0.0",
        uid=48,
        best_run=None,
    )
    payload_zero["miners"].append(
        {
            "uid": 127,
            "best_run": _best_run(reward=0.5, score=0.5, time_s=50.0, cost=0.03, tasks_received=100, tasks_success=50),
            "current_run": None,
        }
    )

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments", new=AsyncMock(return_value=commits)),
        patch(
            "autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async",
            new=AsyncMock(side_effect=[(payload_ok, None, None), (payload_zero, None, None)]),
        ),
    ):
        consensus_rewards, details = await aggregate_scores_from_commitments(validator, st=Mock())

    assert consensus_rewards[48] == pytest.approx(0.4)
    assert details["stats_by_miner"][48]["avg_reward"] == pytest.approx(0.4)
    assert details["stats_by_miner"][48]["tasks_sent"] == 100
    assert details["stats_by_miner"][48]["tasks_success"] == 40
    assert details["skips"]["all_zero_when_others_positive"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_consensus_excludes_all_zero_validator_when_others_have_positive_signal(dummy_validator):
    """
    Scenario:
    Two healthy validators publish non-zero `best_run` for a miner.
    A new validator with much higher stake publishes only zeros/nulls for every miner.

    What this test proves:
    if one validator is all-zero while others clearly have positive signal, that validator is excluded
    from post-consensus instead of dragging down the global result.
    """
    validator = dummy_validator
    _configure_consensus_validator(
        validator,
        version="16.0.0",
        hotkeys=["hk-old-1", "hk-old-2", "hk-new-big"],
        stakes=[10000.0, 10000.0, 50000.0],
    )

    commits = {
        "hk-old-1": {"v": 1, "s": 1, "r": 1, "c": "cid-1"},
        "hk-old-2": {"v": 1, "s": 1, "r": 1, "c": "cid-2"},
        "hk-new-big": {"v": 1, "s": 1, "r": 1, "c": "cid-3"},
    }
    payload_old_1 = _payload_for_miner(
        uid=48,
        validator_version="16.0.1",
        best_run=_best_run(reward=0.23, score=0.23, time_s=23.0, cost=0.02, tasks_received=100, tasks_success=23),
    )
    payload_old_2 = _payload_for_miner(
        uid=48,
        validator_version="16.0.2",
        best_run=_best_run(reward=0.23, score=0.23, time_s=23.0, cost=0.02, tasks_received=100, tasks_success=23),
    )
    payload_new_big = _payload_for_miner(
        uid=48,
        validator_version="16.0.3",
        best_run=None,
    )
    payload_new_big["summary"] = {"validator_all_best_runs_zero": True}

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments", new=AsyncMock(return_value=commits)),
        patch(
            "autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async",
            new=AsyncMock(side_effect=[(payload_old_1, None, None), (payload_old_2, None, None), (payload_new_big, None, None)]),
        ),
    ):
        consensus_rewards, details = await aggregate_scores_from_commitments(validator, st=Mock())

    expected = 0.23
    assert consensus_rewards[48] == pytest.approx(expected)
    assert details["stats_by_miner"][48]["avg_reward"] == pytest.approx(expected)
    assert details["stats_by_miner"][48]["tasks_sent"] == 200
    assert details["stats_by_miner"][48]["tasks_success"] == 46
    assert details["validators"] == [
        {"hotkey": "hk-old-1", "uid": 0, "stake": 10000.0, "cid": "cid-1"},
        {"hotkey": "hk-old-2", "uid": 1, "stake": 10000.0, "cid": "cid-2"},
    ]
    assert details["skips"]["all_zero_when_others_positive"] == [("hk-new-big", "cid-3")]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_consensus_keeps_validator_with_positive_best_run_even_if_summary_claims_all_zero(dummy_validator):
    """
    Scenario:
    A validator had no fresh current-round evaluations because miners were in cooldown, so its payload
    summary incorrectly says `validator_all_best_runs_zero=true`, but it still carries a positive `best_run`.

    What this test proves:
    consensus must keep that validator, because the effective signal it publishes is still positive.
    """
    validator = dummy_validator
    _configure_consensus_validator(
        validator,
        version="16.0.0",
        hotkeys=["hk-old", "hk-cooldown"],
        stakes=[10000.0, 20000.0],
    )

    commits = {
        "hk-old": {"v": 1, "s": 1, "r": 1, "c": "cid-1"},
        "hk-cooldown": {"v": 1, "s": 1, "r": 1, "c": "cid-2"},
    }
    payload_old = _payload_for_miner(
        uid=48,
        validator_version="16.0.1",
        best_run=_best_run(reward=0.20, score=0.20, time_s=20.0, cost=0.02, tasks_received=100, tasks_success=20),
    )
    payload_cooldown = _payload_for_miner(
        uid=48,
        validator_version="16.0.2",
        best_run=_best_run(reward=0.22, score=0.22, time_s=22.0, cost=0.02, tasks_received=100, tasks_success=22),
        current_run={"reward": 0.0, "score": 0.0, "time": 0.0, "cost": 0.0, "tasks_received": 0, "tasks_success": 0},
    )
    payload_cooldown["summary"] = {"validator_all_best_runs_zero": True}

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments", new=AsyncMock(return_value=commits)),
        patch(
            "autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async",
            new=AsyncMock(side_effect=[(payload_old, None, None), (payload_cooldown, None, None)]),
        ),
    ):
        consensus_rewards, details = await aggregate_scores_from_commitments(validator, st=Mock())

    expected = (10000.0 * 0.20 + 20000.0 * 0.22) / 30000.0
    assert consensus_rewards[48] == pytest.approx(expected)
    assert details["stats_by_miner"][48]["avg_reward"] == pytest.approx(expected)
    assert details["validators"] == [
        {"hotkey": "hk-old", "uid": 0, "stake": 10000.0, "cid": "cid-1"},
        {"hotkey": "hk-cooldown", "uid": 1, "stake": 20000.0, "cid": "cid-2"},
    ]
    assert details["skips"]["all_zero_when_others_positive"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_consensus_keeps_all_zero_validators_when_everyone_is_all_zero(dummy_validator):
    """
    Scenario:
    Every compatible validator publishes only zero/null `best_run` values.

    What this test proves:
    the all-zero exclusion rule only kicks in when other validators have positive signal.
    If the whole validator set is all-zero, nobody is auto-excluded.
    """
    validator = dummy_validator
    _configure_consensus_validator(
        validator,
        version="16.0.0",
        hotkeys=["hk1", "hk2"],
        stakes=[10000.0, 20000.0],
    )

    commits = {
        "hk1": {"v": 1, "s": 1, "r": 1, "c": "cid-1"},
        "hk2": {"v": 1, "s": 1, "r": 1, "c": "cid-2"},
    }
    payload_1 = _payload_for_miner(uid=48, validator_version="16.0.1", best_run=None)
    payload_2 = _payload_for_miner(uid=48, validator_version="16.0.2", best_run=_best_run(reward=0.0, score=0.0, time_s=0.0, cost=0.0, tasks_received=100, tasks_success=0))
    payload_1["summary"] = {"validator_all_best_runs_zero": True}
    payload_2["summary"] = {"validator_all_best_runs_zero": True}

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments", new=AsyncMock(return_value=commits)),
        patch(
            "autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async",
            new=AsyncMock(side_effect=[(payload_1, None, None), (payload_2, None, None)]),
        ),
    ):
        consensus_rewards, details = await aggregate_scores_from_commitments(validator, st=Mock())

    assert consensus_rewards[48] == pytest.approx(0.0)
    assert details["stats_by_miner"][48]["avg_reward"] == pytest.approx(0.0)
    assert details["skips"]["all_zero_when_others_positive"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_consensus_does_not_dilute_single_positive_validator_with_empty_payloads(dummy_validator):
    """
    Scenario:
    One validator publishes a valid best run for a miner.
    The other validators publish miner lists with no best/current run payloads at all.

    What this test proves:
    empty payloads are treated as "no signal", not as zero votes, so they must not dilute
    the only validator that actually produced a best run.
    """
    validator = dummy_validator
    _configure_consensus_validator(
        validator,
        version="16.0.0",
        hotkeys=["hk-a", "hk-b", "hk-c", "hk-d"],
        stakes=[1500000.0, 80000.0, 220000.0, 580000.0],
    )

    commits = {
        "hk-a": {"v": 1, "s": 1, "r": 1, "c": "cid-a"},
        "hk-b": {"v": 1, "s": 1, "r": 1, "c": "cid-b"},
        "hk-c": {"v": 1, "s": 1, "r": 1, "c": "cid-c"},
        "hk-d": {"v": 1, "s": 1, "r": 1, "c": "cid-d"},
    }
    payload_signal = {
        "validator_version": "16.0.0",
        "miners": [
            {"uid": 168, "best_run": _best_run(reward=0.2765, score=0.28, time_s=87.0, cost=0.0034, tasks_received=25, tasks_success=7), "current_run": None},
            {"uid": 196, "best_run": _best_run(reward=0.2761, score=0.28, time_s=90.8, cost=0.0025, tasks_received=25, tasks_success=7), "current_run": None},
        ],
        "summary": {"validator_all_best_runs_zero": False},
    }
    payload_empty_1 = {
        "validator_version": "16.0.0",
        "miners": [{"uid": 168}, {"uid": 196}],
        "summary": {"validator_all_best_runs_zero": True},
    }
    payload_empty_2 = {
        "validator_version": "16.0.0",
        "miners": [{"uid": 168}, {"uid": 196}],
        "summary": {"validator_all_best_runs_zero": True},
    }
    payload_empty_3 = {
        "validator_version": "16.0.0",
        "miners": [{"uid": 168}, {"uid": 196}],
        "summary": {"validator_all_best_runs_zero": True},
    }

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments", new=AsyncMock(return_value=commits)),
        patch(
            "autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async",
            new=AsyncMock(side_effect=[(payload_signal, None, None), (payload_empty_1, None, None), (payload_empty_2, None, None), (payload_empty_3, None, None)]),
        ),
    ):
        consensus_rewards, details = await aggregate_scores_from_commitments(validator, st=Mock())

    assert consensus_rewards[168] == pytest.approx(0.2765)
    assert consensus_rewards[196] == pytest.approx(0.2761)
    assert details["validators"] == [{"hotkey": "hk-a", "uid": 0, "stake": 1500000.0, "cid": "cid-a"}]
    assert details["skips"]["all_zero_when_others_positive"] == [
        ("hk-b", "cid-b"),
        ("hk-c", "cid-c"),
        ("hk-d", "cid-d"),
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_consensus_tasks_are_summed_not_stake_weighted(dummy_validator):
    """
    Scenario:
    Two validators publish different `tasks_received` and `tasks_success` for the same miner.

    What this test proves:
    in the current implementation, tasks in `stats_by_miner` are summed, not averaged and not stake-weighted.
    This is important because it fixes the contract explicitly.
    """
    validator = dummy_validator
    _configure_consensus_validator(
        validator,
        version="16.0.0",
        hotkeys=["hk1", "hk2"],
        stakes=[5000.0, 25000.0],
    )

    commits = {
        "hk1": {"v": 1, "s": 1, "r": 1, "c": "cid-1"},
        "hk2": {"v": 1, "s": 1, "r": 1, "c": "cid-2"},
    }
    payload_1 = _payload_for_miner(
        uid=48,
        validator_version="16.0.2",
        best_run=_best_run(reward=0.1, score=0.1, time_s=10.0, cost=0.01, tasks_received=20, tasks_success=7),
    )
    payload_2 = _payload_for_miner(
        uid=48,
        validator_version="16.0.4",
        best_run=_best_run(reward=0.9, score=0.9, time_s=20.0, cost=0.02, tasks_received=100, tasks_success=50),
    )

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments", new=AsyncMock(return_value=commits)),
        patch(
            "autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async",
            new=AsyncMock(side_effect=[(payload_1, None, None), (payload_2, None, None)]),
        ),
    ):
        _consensus_rewards, details = await aggregate_scores_from_commitments(validator, st=Mock())

    assert details["stats_by_miner"][48]["tasks_sent"] == 120
    assert details["stats_by_miner"][48]["tasks_success"] == 57


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_consensus_mixed_20_vs_100_semantics_are_visible(dummy_validator):
    """
    Scenario:
    We reproduce the confusing prod shape explicitly:
    - validator A publishes an old-style run with `7/20` and score `0.35`
    - validator B publishes a normalized run with `7/100` and score `0.07`

    What this test proves:
    if those two payloads enter the same consensus, the system mixes them exactly as published.
    The point of this test is not to bless that behavior as ideal, but to make it visible and prevent silent regressions.
    """
    validator = dummy_validator
    _configure_consensus_validator(
        validator,
        version="16.0.0",
        hotkeys=["hk1", "hk2"],
        stakes=[10000.0, 10000.0],
    )

    commits = {
        "hk1": {"v": 1, "s": 1, "r": 1, "c": "cid-1"},
        "hk2": {"v": 1, "s": 1, "r": 1, "c": "cid-2"},
    }
    old_style_payload = _payload_for_miner(
        uid=48,
        validator_version="16.0.0",
        best_run=_best_run(
            reward=0.3155677995,
            score=0.35,
            time_s=94.711490646,
            cost=0.038233545,
            tasks_received=20,
            tasks_success=7,
        ),
    )
    normalized_payload = _payload_for_miner(
        uid=48,
        validator_version="16.0.0",
        best_run=_best_run(
            reward=0.0631135599,
            score=0.07,
            time_s=94.711490646,
            cost=0.038233545,
            tasks_received=100,
            tasks_success=7,
        ),
    )

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments", new=AsyncMock(return_value=commits)),
        patch(
            "autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async",
            new=AsyncMock(side_effect=[(old_style_payload, None, None), (normalized_payload, None, None)]),
        ),
    ):
        consensus_rewards, details = await aggregate_scores_from_commitments(validator, st=Mock())

    assert consensus_rewards[48] == pytest.approx((0.3155677995 + 0.0631135599) / 2.0)
    assert details["stats_by_miner"][48]["avg_reward"] == pytest.approx((0.3155677995 + 0.0631135599) / 2.0)
    assert details["stats_by_miner"][48]["avg_eval_score"] == pytest.approx(0.21)
    assert details["stats_by_miner"][48]["avg_eval_time"] == pytest.approx(94.711490646)
    assert details["stats_by_miner"][48]["avg_cost"] == pytest.approx(0.038233545)
    assert details["stats_by_miner"][48]["tasks_sent"] == 120
    assert details["stats_by_miner"][48]["tasks_success"] == 14
