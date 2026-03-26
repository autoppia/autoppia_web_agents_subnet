from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from autoppia_web_agents_subnet.platform.mixin import ValidatorPlatformMixin
from autoppia_web_agents_subnet.validator.settlement.consensus import publish_round_snapshot


def _bind_platform_helpers(validator):
    validator._extract_round_numbers_from_round_id = ValidatorPlatformMixin._extract_round_numbers_from_round_id
    validator._round_metrics_payload_from_stats = ValidatorPlatformMixin._round_metrics_payload_from_stats
    validator._current_round_numbers = ValidatorPlatformMixin._current_round_numbers.__get__(validator, type(validator))
    validator._evaluation_context_payload = ValidatorPlatformMixin._evaluation_context_payload.__get__(validator, type(validator))
    validator._is_same_evaluation_context = ValidatorPlatformMixin._is_same_evaluation_context.__get__(validator, type(validator))
    validator._find_reusable_commit_stats = ValidatorPlatformMixin._find_reusable_commit_stats.__get__(validator, type(validator))
    validator._current_round_all_runs_zero = ValidatorPlatformMixin._current_round_all_runs_zero.__get__(validator, type(validator))
    validator._effective_signal_all_runs_zero = ValidatorPlatformMixin._effective_signal_all_runs_zero.__get__(validator, type(validator))
    validator._purge_evaluated_commits_for_round = ValidatorPlatformMixin._purge_evaluated_commits_for_round.__get__(validator, type(validator))
    validator._mark_all_zero_round_for_re_evaluation = ValidatorPlatformMixin._mark_all_zero_round_for_re_evaluation.__get__(validator, type(validator))
    validator._apply_post_consensus_reuse_policy = ValidatorPlatformMixin._apply_post_consensus_reuse_policy.__get__(validator, type(validator))
    validator._current_round_run_payload = ValidatorPlatformMixin._current_round_run_payload.__get__(validator, type(validator))
    validator._best_run_payload_for_miner = ValidatorPlatformMixin._best_run_payload_for_miner.__get__(validator, type(validator))
    return validator


@pytest.mark.integration
def test_reuse_same_commit_and_same_conditions_reuses_previous_run(dummy_validator):
    """
    Scenario:
    A miner submits the same repo and the same commit again.
    The validator conditions have not changed, so the evaluation-context hash stays the same.

    What this test proves:
    the validator must detect that the old run is reusable and avoid re-evaluating that commit.
    """
    validator = _bind_platform_helpers(dummy_validator)
    validator.current_round_id = "validator_round_1_2_reuse"
    validator.round_manager.round_size_epochs = 5.0
    validator.round_manager.BLOCKS_PER_EPOCH = 360
    validator.season_manager.season_size_epochs = 100.0
    validator.season_manager.season_number = 1
    validator.version = "16.0.0"

    matching_context = validator._evaluation_context_payload()
    validator._evaluated_commits_by_miner = {
        48: {
            "https://github.com/example/miner|deadbeef": {
                "agent_run_id": "agent-run-48-old",
                "total_tasks": 100,
                "average_reward": 0.42,
                "average_score": 0.42,
                "average_execution_time": 22.0,
                "average_cost": 0.02,
                "success_tasks": 42,
                "evaluation_context": matching_context,
            }
        }
    }

    reusable = validator._find_reusable_commit_stats(
        uid=48,
        github_url="https://github.com/example/miner/commit/deadbeef",
        normalized_repo="https://github.com/example/miner",
        commit_sha="deadbeef",
    )

    assert reusable is not None
    assert reusable["agent_run_id"] == "agent-run-48-old"


@pytest.mark.integration
def test_evaluation_context_hash_changes_when_conditions_change(dummy_validator):
    """
    Scenario:
    We build the evaluation-context hash once, then change a real validator condition:
    `minimum_start_block`.

    What this test proves:
    the context hash must change when validator conditions change, so reuse cannot silently cross incompatible setups.
    """
    validator = _bind_platform_helpers(dummy_validator)
    validator.current_round_id = "validator_round_1_2_reuse"
    validator.round_manager.round_size_epochs = 5.0
    validator.round_manager.BLOCKS_PER_EPOCH = 360
    validator.season_manager.season_size_epochs = 100.0
    validator.season_manager.season_number = 1
    validator.version = "16.0.0"

    first_context = validator._evaluation_context_payload()

    with patch("autoppia_web_agents_subnet.platform.mixin.validator_config.MINIMUM_START_BLOCK", 9999999):
        second_context = validator._evaluation_context_payload()

    assert first_context["evaluation_context_hash"] != second_context["evaluation_context_hash"]


@pytest.mark.integration
def test_reuse_is_blocked_when_evaluation_context_hash_changes(dummy_validator):
    """
    Scenario:
    A miner resubmits the same commit, but the validator conditions changed since the previous run.

    What this test proves:
    if the evaluation-context hash is different, the old run must not be reused.
    """
    validator = _bind_platform_helpers(dummy_validator)
    validator.current_round_id = "validator_round_1_2_reuse"
    validator.round_manager.round_size_epochs = 5.0
    validator.round_manager.BLOCKS_PER_EPOCH = 360
    validator.season_manager.season_size_epochs = 100.0
    validator.season_manager.season_number = 1
    validator.version = "16.0.0"

    validator._evaluated_commits_by_miner = {
        48: {
            "https://github.com/example/miner|deadbeef": {
                "agent_run_id": "agent-run-48-old",
                "total_tasks": 100,
                "evaluation_context": {"evaluation_context_hash": "sha256:stale"},
            }
        }
    }

    reusable = validator._find_reusable_commit_stats(
        uid=48,
        github_url="https://github.com/example/miner/commit/deadbeef",
        normalized_repo="https://github.com/example/miner",
        commit_sha="deadbeef",
    )

    assert reusable is None


@pytest.mark.integration
def test_best_run_persists_into_next_round_when_commit_does_not_change(dummy_validator):
    """
    Scenario:
    A miner had a strong best run in a previous round.
    In the next round the commit does not change and there is no current run yet.

    What this test proves:
    the exported `best_run` must persist across rounds even when `current_run` is absent.
    """
    validator = _bind_platform_helpers(dummy_validator)
    validator.current_round_id = "validator_round_1_3_reuse"
    validator.round_manager = SimpleNamespace(round_rewards={})
    validator.season_manager = SimpleNamespace(season_number=1)
    validator.current_agent_runs = {}
    validator.agent_run_accumulators = {}
    validator.agents_dict = {}
    validator._evaluated_commits_by_miner = {
        48: {
            "old-best": {
                "agent_run_id": "agent-run-48-old",
                "average_reward": 0.63,
                "average_score": 0.63,
                "average_execution_time": 18.0,
                "average_cost": 0.03,
                "total_tasks": 100,
                "success_tasks": 63,
                "evaluated_season": 1,
                "evaluated_round": 2,
                "evaluation_context": {"evaluation_context_hash": "sha256:old"},
            }
        }
    }

    best_payload = validator._best_run_payload_for_miner(48)

    assert best_payload is not None
    assert best_payload["reward"] == pytest.approx(0.63)
    assert best_payload["tasks_received"] == 100
    assert best_payload["tasks_success"] == 63


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ipfs_snapshot_matches_local_best_and_current_run_payloads(dummy_validator):
    """
    Scenario:
    The validator has local state for one miner:
    - a historical `best_run`
    - a current round run

    What this test proves:
    the payload uploaded to IPFS must contain exactly what the validator has locally for `best_run` and `current_run`.
    """
    validator = _bind_platform_helpers(dummy_validator)
    validator.uid = 83
    validator.version = "16.0.0"
    validator.current_round_id = "validator_round_1_1_payload"
    validator.wallet.hotkey.ss58_address = "5FValidator"
    validator.active_miner_uids = {48}
    validator.round_manager.sync_boundaries(validator.block)
    validator.round_manager.round_number = 1
    validator.season_manager.season_number = 1
    validator.agents_dict = {
        48: SimpleNamespace(
            agent_name="miner-48",
            github_url="https://github.com/example/miner/tree/main",
            normalized_repo="https://github.com/example/miner",
            git_commit="deadbeef",
        )
    }
    validator.agent_run_accumulators = {
        48: {
            "tasks": 100,
            "reward": 50.0,
            "eval_score": 50.0,
            "execution_time": 1000.0,
            "cost": 5.0,
        }
    }
    validator.current_agent_runs = {
        48: SimpleNamespace(
            total_tasks=100,
            completed_tasks=50,
            failed_tasks=50,
            average_reward=0.5,
            average_score=0.5,
            average_execution_time=10.0,
            zero_reason=None,
            metadata={"average_cost": 0.05},
        )
    }
    validator._evaluated_commits_by_miner = {
        48: {
            "old-best": {
                "agent_run_id": "agent-run-48-old",
                "average_reward": 0.7,
                "average_score": 0.7,
                "average_execution_time": 9.0,
                "average_cost": 0.04,
                "total_tasks": 100,
                "success_tasks": 70,
                "evaluated_season": 1,
                "evaluated_round": 0,
                "evaluation_context": {"evaluation_context_hash": "sha256:old"},
            }
        }
    }
    validator._get_async_subtensor = AsyncMock(return_value=Mock())

    captured_payloads: list[dict] = []

    async def _capture_add_json(payload, **_kwargs):
        captured_payloads.append(payload)
        return ("QmCID", "sha256", 123)

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.add_json_async", new=_capture_add_json),
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.write_plain_commitment_json", new=AsyncMock(return_value=True)),
    ):
        cid = await publish_round_snapshot(validator, st=Mock(), scores={48: 0.5})

    assert cid == "QmCID"
    assert len(captured_payloads) == 1
    payload = captured_payloads[0]
    miner_payload = payload["miners"][0]

    assert miner_payload["best_run"]["reward"] == pytest.approx(0.7)
    assert miner_payload["best_run"]["tasks_received"] == 100
    assert "subnet_version" not in payload
    assert payload["summary"]["validator_all_best_runs_zero"] is False
    assert payload["summary"]["validator_all_current_runs_zero"] is False
    assert "validator_all_runs_zero" not in payload["summary"]
    assert "validator_all_runs_zero_current_round" not in payload["summary"]
    assert "validator_all_runs_zero_effective_signal" not in payload["summary"]


@pytest.mark.integration
def test_effective_signal_all_runs_zero_is_true_when_active_miners_have_no_best_signal(dummy_validator):
    validator = _bind_platform_helpers(dummy_validator)
    validator.active_miner_uids = {48, 127}
    validator.current_agent_runs = {}
    validator.agent_run_accumulators = {}
    validator.agents_dict = {}
    validator._evaluated_commits_by_miner = {}

    assert validator._effective_signal_all_runs_zero() is True


@pytest.mark.integration
def test_current_run_payload_keeps_reward_normalized_by_total_tasks_after_early_stop(dummy_validator):
    """
    Scenario:
    A miner was only evaluated on 20 tasks before the validator stopped early, but the season still
    has 100 total tasks. The miner solved 7 of those attempted tasks, while shaped reward ended slightly
    lower than score as usual after time/cost effects.

    What this test proves:
    the exported `current_run` payload must keep reward/score normalized by the full season task count,
    while time/cost stay averaged over attempted tasks only. The payload must also keep
    `tasks_received=100` so downstream consumers do not accidentally reinterpret the run as `7/20`.
    """
    validator = _bind_platform_helpers(dummy_validator)
    validator.current_round_id = "validator_round_1_1_partial_payload"
    validator.round_manager = SimpleNamespace(round_rewards={48: [1.0] * 7 + [0.0] * 13}, round_number=1)
    validator.season_manager = SimpleNamespace(season_number=1)
    validator.agents_dict = {
        48: SimpleNamespace(
            github_url="https://github.com/example/miner/tree/main",
            normalized_repo="https://github.com/example/miner",
            git_commit="deadbeef",
        )
    }
    validator.agent_run_accumulators = {
        48: {
            "tasks": 20,
            "reward": 6.3,
            "eval_score": 7.0,
            "execution_time": 1600.0,
            "cost": 0.8,
        }
    }
    validator.current_agent_runs = {
        48: SimpleNamespace(
            total_tasks=100,
            completed_tasks=7,
            failed_tasks=93,
            average_reward=0.063,
            average_score=0.07,
            average_execution_time=80.0,
            zero_reason="over_cost_limit",
            metadata={"average_cost": 0.04},
        )
    }

    payload = validator._current_round_run_payload(48)

    assert payload is not None
    assert payload["reward"] == pytest.approx(0.063)
    assert payload["score"] == pytest.approx(0.07)
    assert payload["time"] == pytest.approx(80.0)
    assert payload["cost"] == pytest.approx(0.04)
    assert payload["tasks_received"] == 100
    assert payload["tasks_attempted"] == 20
    assert payload["tasks_success"] == 7
    assert payload["failed_tasks"] == 93
    assert payload["zero_reason"] == "over_cost_limit"
    assert payload["early_stop_reason"] == "over_cost_limit"
    assert "20/100" in payload["early_stop_message"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ipfs_snapshot_does_not_regress_to_partial_task_denominator_after_early_stop(dummy_validator):
    """
    Scenario:
    A miner stopped early after 20 attempted tasks because of over-cost, but the validator still has
    a 100-task season. Score came from 7 successes, while shaped reward ended slightly lower.
    We publish the round snapshot immediately after that partial run.

    What this test proves:
    the snapshot must publish the same semantics as the local run:
    - reward/score normalized by 100
    - time/cost averaged over 20 attempted tasks
    - `tasks_received=100`, never `20`
    This is the exact regression guard against accidentally reintroducing `7/20` style payloads.
    """
    validator = _bind_platform_helpers(dummy_validator)
    validator.uid = 83
    validator.version = "16.0.0"
    validator.current_round_id = "validator_round_1_1_partial_snapshot"
    validator.wallet.hotkey.ss58_address = "5FValidator"
    validator.active_miner_uids = {48}
    validator.round_manager.sync_boundaries(validator.block)
    validator.round_manager.round_number = 1
    validator.round_manager.round_rewards = {48: [1.0] * 7 + [0.0] * 13}
    validator.season_manager.season_number = 1
    validator.agents_dict = {
        48: SimpleNamespace(
            agent_name="miner-48",
            github_url="https://github.com/example/miner/tree/main",
            normalized_repo="https://github.com/example/miner",
            git_commit="deadbeef",
        )
    }
    validator.agent_run_accumulators = {
        48: {
            "tasks": 20,
            "reward": 6.3,
            "eval_score": 7.0,
            "execution_time": 1600.0,
            "cost": 0.8,
        }
    }
    validator.current_agent_runs = {
        48: SimpleNamespace(
            total_tasks=100,
            completed_tasks=7,
            failed_tasks=93,
            average_reward=0.063,
            average_score=0.07,
            average_execution_time=80.0,
            zero_reason="over_cost_limit",
            metadata={"average_cost": 0.04},
        )
    }
    validator._evaluated_commits_by_miner = {}
    validator._get_async_subtensor = AsyncMock(return_value=Mock())

    captured_payloads: list[dict] = []

    async def _capture_add_json(payload, **_kwargs):
        captured_payloads.append(payload)
        return ("QmCID", "sha256", 123)

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.add_json_async", new=_capture_add_json),
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.write_plain_commitment_json", new=AsyncMock(return_value=True)),
    ):
        cid = await publish_round_snapshot(validator, st=Mock(), scores={48: 0.063})

    assert cid == "QmCID"
    miner_payload = captured_payloads[0]["miners"][0]
    assert miner_payload["current_run"]["reward"] == pytest.approx(0.063)
    assert miner_payload["current_run"]["score"] == pytest.approx(0.07)
    assert miner_payload["current_run"]["time"] == pytest.approx(80.0)
    assert miner_payload["current_run"]["cost"] == pytest.approx(0.04)
    assert miner_payload["current_run"]["tasks_received"] == 100
    assert miner_payload["current_run"]["tasks_attempted"] == 20
    assert miner_payload["current_run"]["tasks_success"] == 7
    assert miner_payload["current_run"]["zero_reason"] == "over_cost_limit"
    assert miner_payload["best_run"]["reward"] == pytest.approx(0.063)
    assert miner_payload["best_run"]["score"] == pytest.approx(0.07)
    assert miner_payload["best_run"]["tasks_received"] == 100
    assert miner_payload["best_run"]["tasks_success"] == 7


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ipfs_snapshot_marks_summary_all_runs_zero_when_every_local_run_is_zero(dummy_validator):
    """
    Scenario:
    The validator is about to publish a round snapshot where every local miner run ended at zero.

    What this test proves:
    the snapshot summary carries explicit current-round and best-run all-zero flags so other validators
    can exclude this payload from consensus when they still have positive signal.
    """
    validator = _bind_platform_helpers(dummy_validator)
    validator.uid = 83
    validator.version = "16.0.0"
    validator.current_round_id = "validator_round_1_1_payload_zero"
    validator.wallet.hotkey.ss58_address = "5FValidator"
    validator.active_miner_uids = {48, 127}
    validator.round_manager.sync_boundaries(validator.block)
    validator.round_manager.round_number = 1
    validator.season_manager.season_number = 1
    validator.agents_dict = {
        48: SimpleNamespace(agent_name="miner-48", github_url="https://github.com/example/miner48/commit/deadbeef", normalized_repo="https://github.com/example/miner48", git_commit="deadbeef"),
        127: SimpleNamespace(agent_name="miner-127", github_url="https://github.com/example/miner127/commit/cafebabe", normalized_repo="https://github.com/example/miner127", git_commit="cafebabe"),
    }
    validator.agent_run_accumulators = {
        48: {"tasks": 100, "reward": 0.0, "eval_score": 0.0, "execution_time": 1000.0, "cost": 1.0},
        127: {"tasks": 100, "reward": 0.0, "eval_score": 0.0, "execution_time": 1500.0, "cost": 2.0},
    }
    validator.current_agent_runs = {
        48: SimpleNamespace(
            total_tasks=100, completed_tasks=0, failed_tasks=100, average_reward=0.0, average_score=0.0, average_execution_time=10.0, zero_reason="task_failed", metadata={"average_cost": 0.01}
        ),
        127: SimpleNamespace(
            total_tasks=100, completed_tasks=0, failed_tasks=100, average_reward=0.0, average_score=0.0, average_execution_time=15.0, zero_reason="task_failed", metadata={"average_cost": 0.02}
        ),
    }
    validator.round_manager.round_rewards = {48: [0.0] * 100, 127: [0.0] * 100}
    validator._evaluated_commits_by_miner = {}
    validator._get_async_subtensor = AsyncMock(return_value=Mock())

    captured_payloads: list[dict] = []

    async def _capture_add_json(payload, **_kwargs):
        captured_payloads.append(payload)
        return ("QmCID", "sha256", 123)

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.add_json_async", new=_capture_add_json),
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.write_plain_commitment_json", new=AsyncMock(return_value=True)),
    ):
        cid = await publish_round_snapshot(validator, st=Mock(), scores={48: 0.0, 127: 0.0})

    assert cid == "QmCID"
    assert captured_payloads[0]["summary"]["validator_all_current_runs_zero"] is True
    assert captured_payloads[0]["summary"]["validator_all_best_runs_zero"] is True
    assert "validator_all_runs_zero" not in captured_payloads[0]["summary"]
    assert "validator_all_runs_zero_current_round" not in captured_payloads[0]["summary"]
    assert "validator_all_runs_zero_effective_signal" not in captured_payloads[0]["summary"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ipfs_snapshot_does_not_mark_all_zero_when_best_run_remains_positive_during_cooldown(dummy_validator):
    """
    Scenario:
    The current round produced only zero current_run payloads because no fresh evaluation happened,
    but the validator still carries a positive best historical run for that same miner.

    What this test proves:
    the published snapshot must not declare `validator_all_best_runs_zero=true` in this case, because the
    validator still has effective positive signal that consensus should keep.
    """
    validator = _bind_platform_helpers(dummy_validator)
    validator.uid = 83
    validator.version = "16.0.0"
    validator.current_round_id = "validator_round_1_2_payload_cooldown"
    validator.wallet.hotkey.ss58_address = "5FValidator"
    validator.active_miner_uids = {48}
    validator.round_manager.sync_boundaries(validator.block)
    validator.round_manager.round_number = 2
    validator.season_manager.season_number = 1
    validator.agents_dict = {
        48: SimpleNamespace(
            agent_name="miner-48",
            github_url="https://github.com/example/miner48/commit/newsha",
            normalized_repo="https://github.com/example/miner48",
            git_commit="newsha",
        )
    }
    validator.current_agent_runs = {
        48: SimpleNamespace(
            total_tasks=100,
            completed_tasks=0,
            failed_tasks=100,
            average_reward=0.0,
            average_score=0.0,
            average_execution_time=0.0,
            zero_reason="cooldown_pending",
            metadata={"average_cost": 0.0},
        )
    }
    validator.round_manager.round_rewards = {48: [0.0] * 100}
    validator.agent_run_accumulators = {48: {"tasks": 0, "reward": 0.0, "eval_score": 0.0, "execution_time": 0.0, "cost": 0.0}}
    validator._evaluated_commits_by_miner = {
        48: {
            "https://github.com/example/miner48|oldsha": {
                "agent_run_id": "agent-run-48-old",
                "total_tasks": 100,
                "average_reward": 0.22,
                "average_score": 0.22,
                "average_execution_time": 22.0,
                "average_cost": 0.02,
                "success_tasks": 22,
                "evaluated_season": 1,
                "evaluated_round": 1,
                "evaluation_context": validator._evaluation_context_payload(),
            }
        }
    }
    validator._get_async_subtensor = AsyncMock(return_value=Mock())

    captured_payloads: list[dict] = []

    async def _capture_add_json(payload, **_kwargs):
        captured_payloads.append(payload)
        return ("QmCID", "sha256", 123)

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.add_json_async", new=_capture_add_json),
        patch("autoppia_web_agents_subnet.validator.settlement.consensus.write_plain_commitment_json", new=AsyncMock(return_value=True)),
    ):
        cid = await publish_round_snapshot(validator, st=Mock(), scores={48: 0.22})

    assert cid == "QmCID"
    assert captured_payloads[0]["summary"]["validator_all_current_runs_zero"] is True
    assert captured_payloads[0]["summary"]["validator_all_best_runs_zero"] is False
    assert "validator_all_runs_zero" not in captured_payloads[0]["summary"]
    assert "validator_all_runs_zero_current_round" not in captured_payloads[0]["summary"]
    assert "validator_all_runs_zero_effective_signal" not in captured_payloads[0]["summary"]


@pytest.mark.integration
def test_all_zero_round_preserves_reuse_when_consensus_does_not_exclude_validator(dummy_validator):
    """
    Scenario:
    A validator finishes a round where every freshly evaluated miner ended with reward 0.
    This is the suspicious validator-wide failure pattern we want to protect against.

    What this test proves:
    - an all-zero round is only a pending signal during evaluation
    - if post-consensus does not exclude this validator, reuse is preserved
    - the next round still reuses when commit + evaluation context match
    """
    validator = _bind_platform_helpers(dummy_validator)
    validator.current_round_id = "validator_round_1_1_all_zero"
    validator.round_manager = SimpleNamespace(round_rewards={48: [0.0] * 100, 127: [0.0] * 100})
    validator.season_manager = SimpleNamespace(season_number=1)
    validator.current_agent_runs = {
        48: SimpleNamespace(
            total_tasks=100, completed_tasks=0, failed_tasks=100, average_reward=0.0, average_score=0.0, average_execution_time=30.0, zero_reason="task_failed", metadata={"average_cost": 0.01}
        ),
        127: SimpleNamespace(
            total_tasks=100, completed_tasks=0, failed_tasks=100, average_reward=0.0, average_score=0.0, average_execution_time=25.0, zero_reason="task_failed", metadata={"average_cost": 0.02}
        ),
    }
    validator.agent_run_accumulators = {
        48: {"tasks": 100, "reward": 0.0, "eval_score": 0.0, "execution_time": 3000.0, "cost": 1.0},
        127: {"tasks": 100, "reward": 0.0, "eval_score": 0.0, "execution_time": 2500.0, "cost": 2.0},
    }
    validator.miners_reused_this_round = set()
    validator._disable_reuse_until = None
    validator.agents_dict = {
        48: SimpleNamespace(github_url="https://github.com/example/miner48/commit/deadbeef", normalized_repo="https://github.com/example/miner48", git_commit="deadbeef"),
        127: SimpleNamespace(github_url="https://github.com/example/miner127/commit/cafebabe", normalized_repo="https://github.com/example/miner127", git_commit="cafebabe"),
    }
    matching_context = validator._evaluation_context_payload()
    validator._evaluated_commits_by_miner = {
        48: {
            "https://github.com/example/miner48|deadbeef": {
                "agent_run_id": "agent-run-48-old",
                "total_tasks": 100,
                "average_reward": 0.42,
                "average_score": 0.42,
                "average_execution_time": 22.0,
                "average_cost": 0.02,
                "success_tasks": 42,
                "normalized_repo": "https://github.com/example/miner48",
                "commit_sha": "deadbeef",
                "github_url": "https://github.com/example/miner48/commit/deadbeef",
                "evaluated_season": 0,
                "evaluated_round": 9,
                "evaluation_context": matching_context,
            },
            "https://github.com/example/miner48/commit/deadbeef": {
                "agent_run_id": "agent-run-48-zero",
                "total_tasks": 100,
                "average_reward": 0.0,
                "average_score": 0.0,
                "average_execution_time": 30.0,
                "average_cost": 0.01,
                "success_tasks": 0,
                "normalized_repo": "https://github.com/example/miner48",
                "commit_sha": "deadbeef",
                "github_url": "https://github.com/example/miner48/commit/deadbeef",
                "evaluated_season": 1,
                "evaluated_round": 1,
                "evaluation_context": matching_context,
            },
        }
    }

    applied = validator._mark_all_zero_round_for_re_evaluation()

    assert applied is True
    assert validator._disable_reuse_until is None
    assert validator._pending_all_zero_round_policy["miner_uids"] == [48, 127]
    assert validator._last_all_zero_round_policy["status"] == "pending_consensus"

    excluded = validator._apply_post_consensus_reuse_policy({"skips": {"all_zero_when_others_positive": []}})

    assert excluded is False
    assert validator._disable_reuse_until is None
    assert validator._pending_all_zero_round_policy is None
    assert validator._last_all_zero_round_policy["miner_uids"] == [48, 127]
    assert validator._last_all_zero_round_policy["reuse_preserved"] is True
    assert "https://github.com/example/miner48|deadbeef" in validator._evaluated_commits_by_miner[48]
    assert "https://github.com/example/miner48/commit/deadbeef" in validator._evaluated_commits_by_miner[48]

    validator.current_round_id = "validator_round_1_2_all_zero"
    reusable = validator._find_reusable_commit_stats(
        uid=48,
        github_url="https://github.com/example/miner48/commit/deadbeef",
        normalized_repo="https://github.com/example/miner48",
        commit_sha="deadbeef",
    )
    assert reusable is not None
    assert reusable["agent_run_id"] == "agent-run-48-old"


@pytest.mark.integration
def test_all_zero_round_disables_reuse_next_round_when_consensus_excludes_validator(dummy_validator):
    """
    Scenario:
    The validator published only zero scores, but other validators produced positive signal, so
    consensus excludes this validator from the aggregate.

    What this test proves:
    - the validator records the all-zero round locally
    - post-consensus exclusion disables reuse for the next round
    - the next round will force a local re-evaluation even if commit + context match
    """
    validator = _bind_platform_helpers(dummy_validator)
    validator.wallet.hotkey.ss58_address = "validator-hotkey-83"
    validator.current_round_id = "validator_round_1_2_all_zero"
    validator.round_manager = SimpleNamespace(round_rewards={48: [0.0] * 25})
    validator.season_manager = SimpleNamespace(season_number=1)
    validator.current_agent_runs = {
        48: SimpleNamespace(
            total_tasks=25,
            completed_tasks=0,
            failed_tasks=25,
            average_reward=0.0,
            average_score=0.0,
            average_execution_time=180.0,
            zero_reason="task_failed",
            metadata={"average_cost": 0.0},
        ),
    }
    validator.agent_run_accumulators = {
        48: {"tasks": 25, "reward": 0.0, "eval_score": 0.0, "execution_time": 4500.0, "cost": 0.0},
    }
    validator.miners_reused_this_round = set()
    validator._disable_reuse_until = None
    matching_context = validator._evaluation_context_payload()
    validator._evaluated_commits_by_miner = {
        48: {
            "https://github.com/example/miner48|deadbeef": {
                "agent_run_id": "agent-run-48-old",
                "total_tasks": 25,
                "average_reward": 0.42,
                "average_score": 0.42,
                "average_execution_time": 22.0,
                "average_cost": 0.02,
                "success_tasks": 8,
                "normalized_repo": "https://github.com/example/miner48",
                "commit_sha": "deadbeef",
                "github_url": "https://github.com/example/miner48/commit/deadbeef",
                "evaluated_season": 1,
                "evaluated_round": 1,
                "evaluation_context": matching_context,
            }
        }
    }

    applied = validator._mark_all_zero_round_for_re_evaluation()

    assert applied is True
    excluded = validator._apply_post_consensus_reuse_policy({"skips": {"all_zero_when_others_positive": [("validator-hotkey-83", "cid-ours")]}})

    assert excluded is True
    assert validator._disable_reuse_until == {
        "season": 1,
        "round": 3,
        "reason": "all_zero_excluded_by_consensus",
        "miner_uids": [48],
    }
    assert validator._last_all_zero_round_policy["reuse_preserved"] is False
    assert validator._last_all_zero_round_policy["status"] == "excluded_by_consensus"

    validator.current_round_id = "validator_round_1_3_all_zero_follow_up"
    reusable = validator._find_reusable_commit_stats(
        uid=48,
        github_url="https://github.com/example/miner48/commit/deadbeef",
        normalized_repo="https://github.com/example/miner48",
        commit_sha="deadbeef",
    )
    assert reusable is None


@pytest.mark.integration
def test_round_window_exceeded_only_does_not_disable_reuse_next_round(dummy_validator):
    """
    Scenario:
    The validator did not fail; it simply reached the round stop window and marked pending miners
    with `round_window_exceeded`.

    What this test proves:
    an early round cutoff must not be treated as a validator-wide all-zero failure and must not
    disable reuse for the following round.
    """
    validator = _bind_platform_helpers(dummy_validator)
    validator.current_round_id = "validator_round_1_1_cutoff"
    validator.round_manager = SimpleNamespace(round_rewards={48: [0.0] * 100})
    validator.season_manager = SimpleNamespace(season_number=1)
    validator.current_agent_runs = {
        48: SimpleNamespace(
            total_tasks=100,
            completed_tasks=0,
            failed_tasks=100,
            average_reward=0.0,
            average_score=0.0,
            average_execution_time=180.0,
            zero_reason="round_window_exceeded",
            metadata={"average_cost": 0.0},
        ),
    }
    validator.agent_run_accumulators = {
        48: {"tasks": 100, "reward": 0.0, "eval_score": 0.0, "execution_time": 18000.0, "cost": 0.0},
    }
    validator.miners_reused_this_round = set()
    validator._disable_reuse_until = None

    applied = validator._mark_all_zero_round_for_re_evaluation()

    assert applied is False
    assert validator._disable_reuse_until is None
