from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from autoppia_web_agents_subnet.platform.mixin import ValidatorPlatformMixin


def _bind_platform_helpers(validator):
    validator._extract_round_numbers_from_round_id = ValidatorPlatformMixin._extract_round_numbers_from_round_id
    validator._round_metrics_payload_from_stats = ValidatorPlatformMixin._round_metrics_payload_from_stats
    validator._current_round_numbers = ValidatorPlatformMixin._current_round_numbers.__get__(validator, type(validator))
    validator._evaluation_context_payload = ValidatorPlatformMixin._evaluation_context_payload.__get__(validator, type(validator))
    validator._current_round_run_payload = ValidatorPlatformMixin._current_round_run_payload.__get__(validator, type(validator))
    validator._best_run_payload_for_miner = ValidatorPlatformMixin._best_run_payload_for_miner.__get__(validator, type(validator))
    return validator


@pytest.mark.integration
def test_best_run_promotes_current_run_when_current_is_better():
    """
    Scenario:
    The validator already has a historical best run for a miner.
    In the current round, the miner performs better than that historical best.

    What this test proves:
    the exported `best_run` must become the current run.
    We should never publish a stale lower `best_run` when the current round is strictly better.
    """
    validator = _bind_platform_helpers(Mock())
    validator.current_round_id = "validator_round_1_2_best_run"
    validator.round_manager = SimpleNamespace(round_rewards={48: [0.8, 0.8]}, round_eval_scores={}, round_times={})
    validator.season_manager = SimpleNamespace(season_number=1)
    validator.agent_run_accumulators = {
        48: {
            "tasks": 2,
            "reward": 1.6,
            "eval_score": 1.6,
            "execution_time": 20.0,
            "cost": 0.04,
        }
    }
    validator.current_agent_runs = {
        48: SimpleNamespace(
            total_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
            average_reward=0.0,
            average_score=0.0,
            average_execution_time=0.0,
            zero_reason=None,
            metadata={},
        )
    }
    validator.agents_dict = {
        48: SimpleNamespace(
            github_url="https://github.com/example/miner/tree/main",
            normalized_repo="https://github.com/example/miner",
            git_commit="deadbeef",
        )
    }
    validator._evaluated_commits_by_miner = {
        48: {
            "old-best": {
                "agent_run_id": "old-run",
                "average_reward": 0.4,
                "average_score": 0.4,
                "average_execution_time": 15.0,
                "average_cost": 0.02,
                "total_tasks": 2,
                "success_tasks": 1,
                "evaluation_context": {"evaluation_context_hash": "sha256:old"},
            }
        }
    }

    best_payload = validator._best_run_payload_for_miner(48)

    assert best_payload is not None
    assert best_payload["reward"] == pytest.approx(0.8)
    assert best_payload["score"] == pytest.approx(0.8)
    assert best_payload["tasks_received"] == 2
    assert best_payload["tasks_success"] == 2


@pytest.mark.integration
def test_best_run_keeps_historical_best_when_current_is_worse():
    """
    Scenario:
    The validator already has a strong historical best run for a miner.
    In the current round, the miner performs worse than that historical best.

    What this test proves:
    the exported `best_run` must stay on the historical best.
    We should never downgrade `best_run` just because the current round is worse.
    """
    validator = _bind_platform_helpers(Mock())
    validator.current_round_id = "validator_round_1_2_best_run"
    validator.round_manager = SimpleNamespace(round_rewards={48: [0.2, 0.2]}, round_eval_scores={}, round_times={})
    validator.season_manager = SimpleNamespace(season_number=1)
    validator.agent_run_accumulators = {
        48: {
            "tasks": 2,
            "reward": 0.4,
            "eval_score": 0.4,
            "execution_time": 20.0,
            "cost": 0.04,
        }
    }
    validator.current_agent_runs = {
        48: SimpleNamespace(
            total_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
            average_reward=0.0,
            average_score=0.0,
            average_execution_time=0.0,
            zero_reason=None,
            metadata={},
        )
    }
    validator.agents_dict = {
        48: SimpleNamespace(
            github_url="https://github.com/example/miner/tree/main",
            normalized_repo="https://github.com/example/miner",
            git_commit="deadbeef",
        )
    }
    validator._evaluated_commits_by_miner = {
        48: {
            "old-best": {
                "agent_run_id": "old-run",
                "average_reward": 0.7,
                "average_score": 0.7,
                "average_execution_time": 12.0,
                "average_cost": 0.02,
                "total_tasks": 2,
                "success_tasks": 2,
                "evaluation_context": {"evaluation_context_hash": "sha256:old"},
            }
        }
    }

    best_payload = validator._best_run_payload_for_miner(48)

    assert best_payload is not None
    assert best_payload["reward"] == pytest.approx(0.7)
    assert best_payload["score"] == pytest.approx(0.7)
    assert best_payload["tasks_received"] == 2
    assert best_payload["tasks_success"] == 2
