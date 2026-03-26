from __future__ import annotations

import queue
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from autoppia_web_agents_subnet.validator.evaluation import mixin as evaluation_mixin_module
from autoppia_web_agents_subnet.validator.models import AgentInfo, TaskWithProject
from autoppia_web_agents_subnet.validator.settlement.consensus import aggregate_scores_from_commitments


def _task_with_id(task_id: str) -> TaskWithProject:
    task = Mock()
    task.id = task_id
    task.url = f"https://example.com/{task_id}"
    task.prompt = f"Prompt for {task_id}"
    task.tests = []
    return TaskWithProject(project=None, task=task)


def _consensus_payload(
    *,
    uid: int,
    validator_version: str,
    reward: float,
    score: float,
    time_s: float,
    cost: float,
    tasks_received: int,
    tasks_success: int,
    current_run: dict | None = None,
) -> dict:
    return {
        "validator_version": validator_version,
        "miners": [
            {
                "uid": uid,
                "best_run": {
                    "reward": reward,
                    "score": score,
                    "time": time_s,
                    "cost": cost,
                    "tasks_received": tasks_received,
                    "tasks_success": tasks_success,
                },
                "current_run": current_run,
            }
        ],
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_over_cost_stop_keeps_reward_normalized_by_total_tasks(dummy_validator):
    from tests.conftest import _bind_evaluation_mixin

    validator = _bind_evaluation_mixin(dummy_validator)
    validator.current_round_id = "validator_round_1_1_regression"
    validator.season_manager.season_number = 1
    validator.round_manager.round_number = 1
    validator.round_manager.sync_boundaries(validator.block)
    validator.agents_queue = queue.Queue()
    validator.agent_run_accumulators = {}
    validator.round_manager.round_rewards = {}
    validator.round_manager.round_eval_scores = {}
    validator.round_manager.round_times = {}

    agent = AgentInfo(
        uid=48,
        agent_name="miner-48",
        github_url="https://github.com/example/miner/tree/main",
        score=0.0,
    )
    validator.agents_dict = {48: agent}
    validator.agents_queue.put(agent)

    season_tasks = [_task_with_id(f"task-{index}") for index in range(56)]
    validator.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
    validator.current_agent_runs = {
        48: SimpleNamespace(
            agent_run_id="agent-run-48",
            total_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
            total_reward=0.0,
            average_reward=0.0,
            average_score=0.0,
            average_execution_time=0.0,
            metadata={},
            zero_reason=None,
        )
    }

    validator.sandbox_manager = Mock()
    validator.sandbox_manager.deploy_agent = Mock(return_value=SimpleNamespace(base_url="http://localhost:8001", git_commit="deadbeef"))
    validator.sandbox_manager.cleanup_agent = Mock()
    validator.sandbox_manager.get_usage_for_task = Mock(
        return_value={
            "total_cost": 0.06,
            "total_tokens": 120,
            "usage_details": {"tokens": {"openai": {"gpt-4.1": 120}}, "cost": {"openai": {"gpt-4.1": 0.06}}},
        }
    )
    submitted_batches: list[dict] = []

    async def _capture_batch(*, agent_uid, batch_eval_data):
        submitted_batches.append({"agent_uid": agent_uid, "batch_eval_data": batch_eval_data})
        return True

    validator._submit_batch_evaluations_to_iwap = AsyncMock(side_effect=_capture_batch)

    with (
        patch.object(evaluation_mixin_module.ColoredLogger, "info"),
        patch.object(evaluation_mixin_module.ColoredLogger, "warning"),
        patch.object(evaluation_mixin_module.ColoredLogger, "debug"),
        patch.object(evaluation_mixin_module.ColoredLogger, "error"),
        patch.object(evaluation_mixin_module.validator_config, "CONCURRENT_EVALUATION_NUM", 1),
        patch.object(evaluation_mixin_module.validator_config, "MAX_OVER_COST_TASKS_BEFORE_FORCED_ZERO_SCORE", 34),
        patch.object(evaluation_mixin_module.validator_config, "MAX_TASK_DOLLAR_COST_USD", 0.05),
        patch.object(evaluation_mixin_module.validator_config, "TASK_TIMEOUT_SECONDS", 180.0),
        patch("autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url", return_value=("https://github.com/example/miner", "main")),
        patch("autoppia_web_agents_subnet.validator.evaluation.mixin.resolve_remote_ref_commit", return_value="deadbeef"),
        patch(
            "autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua",
            new=AsyncMock(return_value=(1.0, 10.0, {"actions": [], "recording": {"execution_history": []}})),
        ) as mock_eval,
        patch("autoppia_web_agents_subnet.validator.evaluation.mixin.calculate_reward_for_task", return_value=0.0),
    ):
        agents_evaluated = await validator._run_evaluation_phase()

    run = validator.current_agent_runs[48]
    assert agents_evaluated == 1
    assert mock_eval.await_count == 34
    assert run.total_tasks == 56
    assert run.completed_tasks == 0
    assert run.failed_tasks == 56
    assert run.average_reward == pytest.approx(0.0)
    assert run.average_score == pytest.approx(34 / 56)
    assert run.average_execution_time == pytest.approx(10.0)
    assert run.metadata["average_cost"] == pytest.approx(0.06)
    assert run.zero_reason == "over_cost_limit"
    assert submitted_batches
    zero_reason_values = {item["zero_reason"] for batch in submitted_batches for item in batch["batch_eval_data"] if (item.get("score", 0.0) <= 0.0 or item.get("reward", 0.0) <= 0.0)}
    assert zero_reason_values == {"over_cost_limit"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_consensus_stake_weights_best_run_metrics_even_when_current_run_is_missing(dummy_validator):
    validator = dummy_validator
    validator.version = "16.0.0"
    validator.current_round_id = "validator_round_1_1_regression"
    validator._current_round_number = 1
    validator.metagraph.hotkeys = ["hk1", "hk2"]
    validator.metagraph.n = 2
    validator.metagraph.stake = [10000.0, 20000.0]

    commits = {
        "hk1": {"v": 1, "s": 1, "r": 1, "c": "cid-1"},
        "hk2": {"v": 1, "s": 1, "r": 1, "c": "cid-2"},
    }

    payload_1 = _consensus_payload(
        uid=48,
        validator_version="16.0.1",
        reward=0.2,
        score=0.3,
        time_s=80.0,
        cost=0.05,
        tasks_received=100,
        tasks_success=20,
        current_run=None,
    )
    payload_2 = _consensus_payload(
        uid=48,
        validator_version="16.0.3",
        reward=0.5,
        score=0.6,
        time_s=20.0,
        cost=0.01,
        tasks_received=100,
        tasks_success=50,
        current_run=None,
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
    assert details["current_stats_by_miner"] == {}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_consensus_accepts_patch_updates_but_skips_minor_or_major_version_mismatches(dummy_validator):
    validator = dummy_validator
    validator.version = "16.0.0"
    validator.current_round_id = "validator_round_1_1_regression"
    validator._current_round_number = 1
    validator.metagraph.hotkeys = ["hk1", "hk2", "hk3"]
    validator.metagraph.n = 3
    validator.metagraph.stake = [15000.0, 15000.0, 15000.0]

    commits = {
        "hk1": {"v": 1, "s": 1, "r": 1, "c": "cid-1"},
        "hk2": {"v": 1, "s": 1, "r": 1, "c": "cid-2"},
        "hk3": {"v": 1, "s": 1, "r": 1, "c": "cid-3"},
    }

    accepted_payload = _consensus_payload(
        uid=48,
        validator_version="16.0.5",
        reward=0.3,
        score=0.3,
        time_s=30.0,
        cost=0.02,
        tasks_received=100,
        tasks_success=30,
    )
    wrong_minor_payload = _consensus_payload(
        uid=48,
        validator_version="16.1.0",
        reward=0.9,
        score=0.9,
        time_s=5.0,
        cost=0.01,
        tasks_received=100,
        tasks_success=90,
    )
    wrong_major_payload = _consensus_payload(
        uid=48,
        validator_version="17.0.0",
        reward=0.95,
        score=0.95,
        time_s=4.0,
        cost=0.01,
        tasks_received=100,
        tasks_success=95,
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
