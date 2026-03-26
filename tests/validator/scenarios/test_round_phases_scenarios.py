from __future__ import annotations

import queue
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from autoppia_web_agents_subnet.validator.models import AgentInfo


def _make_agent(uid: int) -> AgentInfo:
    return AgentInfo(
        uid=uid,
        agent_name=f"miner-{uid}",
        github_url=f"https://github.com/example/miner-{uid}/tree/main",
        normalized_repo=f"https://github.com/example/miner-{uid}",
        git_commit="deadbeef",
        score=0.0,
    )


def _make_agent_run(agent_run_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        agent_run_id=agent_run_id,
        started_at=1000.0,
        total_tasks=0,
        completed_tasks=0,
        failed_tasks=0,
        total_reward=0.0,
        average_reward=0.0,
        average_score=0.0,
        average_execution_time=0.0,
        zero_reason=None,
        metadata={},
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_round_phase_skips_start_when_validator_joins_too_late(dummy_validator):
    """
    Scenario:
    The validator tries to start a round after the configured "too late to start cleanly" fraction.

    What this test proves:
    - the round must not continue forward
    - the validator must wait for the next boundary instead of starting a dirty late round
    """
    from tests.conftest import _bind_round_start_mixin

    validator = _bind_round_start_mixin(dummy_validator)
    validator.round_manager.target_block = 2222
    validator.round_manager.fraction_elapsed = Mock(return_value=0.31)
    validator.season_manager.get_season_start_block = Mock(return_value=1000)
    validator.season_manager.get_season_number = Mock(return_value=1)

    with patch("autoppia_web_agents_subnet.validator.round_start.mixin.SKIP_ROUND_IF_STARTED_AFTER_FRACTION", 0.30):
        result = await validator._start_round()

    assert result.continue_forward is False
    assert result.reason == "late in round"
    validator._wait_until_specific_block.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_round_phase_stop_fraction_marks_all_pending_miners_as_round_window_exceeded(dummy_validator, season_tasks):
    """
    Scenario:
    The evaluation phase begins, but the round is already at or beyond the stop fraction before any miner starts.

    What this test proves:
    - queued miners are not evaluated
    - they are materialized with deterministic zeroed runs
    - the reason is `round_window_exceeded`, not a generic missing placeholder
    """
    from tests.conftest import _bind_evaluation_mixin

    validator = _bind_evaluation_mixin(dummy_validator)
    validator.agents_queue = queue.Queue()
    validator.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
    validator.round_manager.fraction_elapsed = Mock(return_value=0.95)
    validator.round_manager.round_rewards = {}
    validator.round_manager.round_eval_scores = {}
    validator.round_manager.round_times = {}

    agent_1 = _make_agent(1)
    agent_2 = _make_agent(2)
    validator.agents_queue.put(agent_1)
    validator.agents_queue.put(agent_2)
    validator.agents_dict = {1: agent_1, 2: agent_2}
    validator.current_agent_runs = {
        1: _make_agent_run("run-1"),
        2: _make_agent_run("run-2"),
    }

    with patch(
        "autoppia_web_agents_subnet.validator.config.STOP_TASK_EVALUATION_AND_UPLOAD_IPFS_AT_ROUND_FRACTION",
        0.94,
    ):
        agents_evaluated = await validator._run_evaluation_phase()

    assert agents_evaluated == 0

    for uid in (1, 2):
        run = validator.current_agent_runs[uid]
        assert run.total_tasks == len(season_tasks)
        assert run.completed_tasks == 0
        assert run.failed_tasks == len(season_tasks)
        assert run.average_reward == 0.0
        assert run.average_score == 0.0
        assert run.zero_reason == "round_window_exceeded"
        assert validator.agents_dict[uid].zero_reason == "round_window_exceeded"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_round_phase_finishes_current_miner_but_zeroes_remaining_pending_miners_after_stop_fraction(dummy_validator, season_tasks):
    """
    Scenario:
    The round starts with enough time to evaluate one miner.
    After that miner finishes, the round reaches the stop fraction before the next miner starts.

    What this test proves:
    - the miner already in progress keeps its real evaluation
    - the next queued miner is not started
    - the pending miner is recorded as `round_window_exceeded` with zeroed stats

    Important:
    this documents the current contract: the stop-fraction check happens between miners,
    not in the middle of an active miner run.
    """
    from tests.conftest import _bind_evaluation_mixin

    validator = _bind_evaluation_mixin(dummy_validator)
    validator.agents_queue = queue.Queue()
    validator.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
    validator.round_manager.fraction_elapsed = Mock(side_effect=[0.10, 0.95])
    validator.round_manager.round_rewards = {}
    validator.round_manager.round_eval_scores = {}
    validator.round_manager.round_times = {}
    validator.sandbox_manager = Mock()
    validator.sandbox_manager.deploy_agent = Mock(return_value=SimpleNamespace(base_url="http://localhost:8001"))
    validator.sandbox_manager.cleanup_agent = Mock()
    validator.sandbox_manager.get_usage_for_task = Mock(return_value=None)

    agent_1 = _make_agent(1)
    agent_2 = _make_agent(2)
    validator.agents_queue.put(agent_1)
    validator.agents_queue.put(agent_2)
    validator.agents_dict = {1: agent_1, 2: agent_2}
    validator.current_agent_runs = {
        1: _make_agent_run("run-1"),
        2: _make_agent_run("run-2"),
    }

    with (
        patch("autoppia_web_agents_subnet.validator.config.STOP_TASK_EVALUATION_AND_UPLOAD_IPFS_AT_ROUND_FRACTION", 0.94),
        patch("autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url", return_value=("https://github.com/example/miner-1", "main")),
        patch("autoppia_web_agents_subnet.validator.evaluation.mixin.resolve_remote_ref_commit", return_value="deadbeef"),
        patch("autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua", new=AsyncMock(return_value=(1.0, 3.0, None))),
        patch("autoppia_web_agents_subnet.validator.evaluation.mixin.calculate_reward_for_task", return_value=0.9),
    ):
        agents_evaluated = await validator._run_evaluation_phase()

    assert agents_evaluated == 1

    run_1 = validator.current_agent_runs[1]
    assert run_1.completed_tasks == len(season_tasks)
    assert run_1.failed_tasks == 0
    assert run_1.average_reward > 0.0
    assert run_1.zero_reason is None

    run_2 = validator.current_agent_runs[2]
    assert run_2.total_tasks == len(season_tasks)
    assert run_2.completed_tasks == 0
    assert run_2.failed_tasks == len(season_tasks)
    assert run_2.average_reward == 0.0
    assert run_2.average_score == 0.0
    assert run_2.zero_reason == "round_window_exceeded"
