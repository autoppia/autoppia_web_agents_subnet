from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import HTTPStatusError, Request, Response

from autoppia_web_agents_subnet.platform.mixin import ValidatorPlatformMixin


def _bind_platform_helpers(validator):
    validator._extract_round_numbers_from_round_id = ValidatorPlatformMixin._extract_round_numbers_from_round_id
    validator._round_metrics_payload_from_stats = ValidatorPlatformMixin._round_metrics_payload_from_stats
    validator._current_round_numbers = ValidatorPlatformMixin._current_round_numbers.__get__(validator, type(validator))
    validator._evaluation_context_payload = ValidatorPlatformMixin._evaluation_context_payload.__get__(validator, type(validator))
    validator._is_same_evaluation_context = ValidatorPlatformMixin._is_same_evaluation_context.__get__(validator, type(validator))
    validator._find_reusable_commit_stats = ValidatorPlatformMixin._find_reusable_commit_stats.__get__(validator, type(validator))
    validator._current_round_run_payload = ValidatorPlatformMixin._current_round_run_payload.__get__(validator, type(validator))
    validator._best_run_payload_for_miner = ValidatorPlatformMixin._best_run_payload_for_miner.__get__(validator, type(validator))
    validator._upload_round_log_snapshot = ValidatorPlatformMixin._upload_round_log_snapshot.__get__(validator, type(validator))
    return validator


@pytest.mark.unit
def test_extract_round_numbers_from_round_id_valid_and_invalid():
    assert ValidatorPlatformMixin._extract_round_numbers_from_round_id("validator_round_12_3_hash") == (12, 3)
    assert ValidatorPlatformMixin._extract_round_numbers_from_round_id("1/2") == (None, None)
    assert ValidatorPlatformMixin._extract_round_numbers_from_round_id(None) == (None, None)


@pytest.mark.unit
def test_current_round_numbers_prefers_round_id_then_falls_back():
    validator = _bind_platform_helpers(Mock())
    validator.current_round_id = "validator_round_7_9_hash"
    validator.season_manager = SimpleNamespace(season_number=111)
    validator.round_manager = SimpleNamespace(round_number=222)

    assert validator._current_round_numbers() == (7, 9)

    validator.current_round_id = "not_a_validator_round_id"
    assert validator._current_round_numbers() == (111, 222)


@pytest.mark.unit
def test_evaluation_context_payload_and_context_match():
    validator = _bind_platform_helpers(Mock())
    validator.current_round_id = "validator_round_2_4_hash"
    validator.round_manager = SimpleNamespace(round_size_epochs=0.5, BLOCKS_PER_EPOCH=360)
    validator.season_manager = SimpleNamespace(season_size_epochs=1.5, season_number=2)
    validator.version = "9.9.9"

    payload = validator._evaluation_context_payload()
    assert payload["season_number"] == 2
    assert payload["round_size_epochs"] == 0.5
    assert payload["season_size_epochs"] == 1.5
    assert str(payload["evaluation_context_hash"]).startswith("sha256:")
    assert validator._is_same_evaluation_context({"evaluation_context": payload})
    assert not validator._is_same_evaluation_context({"evaluation_context": {"evaluation_context_hash": "sha256:different"}})


@pytest.mark.unit
def test_find_reusable_commit_stats_requires_matching_context_and_tasks():
    validator = _bind_platform_helpers(Mock())
    validator.current_round_id = "validator_round_3_1_hash"
    validator.round_manager = SimpleNamespace(round_size_epochs=1.0, BLOCKS_PER_EPOCH=360)
    validator.season_manager = SimpleNamespace(season_size_epochs=2.0, season_number=3)
    validator.version = "1.0.0"

    matching_context = validator._evaluation_context_payload()
    validator._evaluated_commits_by_miner = {
        5: {
            "https://github.com/example/repo/commit/abc": {
                "agent_run_id": "run-1",
                "total_tasks": 3,
                "evaluation_context": matching_context,
            },
            "https://github.com/example/repo|abc": {
                "agent_run_id": "run-2",
                "total_tasks": 0,
                "evaluation_context": matching_context,
            },
        }
    }

    reused = validator._find_reusable_commit_stats(
        uid=5,
        github_url="https://github.com/example/repo/commit/abc",
        normalized_repo="https://github.com/example/repo",
        commit_sha="abc",
    )
    assert reused is not None
    assert reused["agent_run_id"] == "run-1"


@pytest.mark.unit
def test_round_metrics_payload_from_stats_invalid_and_valid():
    assert ValidatorPlatformMixin._round_metrics_payload_from_stats(None) is None
    assert ValidatorPlatformMixin._round_metrics_payload_from_stats({"average_reward": "bad"}) is None

    payload = ValidatorPlatformMixin._round_metrics_payload_from_stats(
        {
            "average_reward": 0.7,
            "average_score": 0.8,
            "average_execution_time": 3.2,
            "average_cost": 0.1,
            "total_tasks": 4,
            "success_tasks": 3,
            "github_url": "https://github.com/example/repo/commit/abc",
            "normalized_repo": "https://github.com/example/repo",
            "commit_sha": "abc",
            "evaluated_season": 2,
            "evaluated_round": 5,
            "evaluation_context": {"evaluation_context_hash": "sha256:test"},
        }
    )
    assert payload is not None
    assert payload["reward"] == pytest.approx(0.7)
    assert payload["tasks_received"] == 4
    assert payload["tasks_success"] == 3
    assert payload["season"] == 2
    assert payload["round"] == 5
    assert payload["evaluation_context"]["evaluation_context_hash"] == "sha256:test"


@pytest.mark.unit
def test_current_round_run_payload_and_best_run_selection():
    validator = _bind_platform_helpers(Mock())
    validator.current_round_id = "validator_round_1_2_hash"
    validator.round_manager = SimpleNamespace(round_rewards={1: [0.8, 0.2]})
    validator.season_manager = SimpleNamespace(season_number=1)
    validator.current_agent_runs = {
        1: SimpleNamespace(
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
    validator.agent_run_accumulators = {
        1: {
            "tasks": 2,
            "reward": 1.0,
            "eval_score": 1.2,
            "execution_time": 6.0,
            "cost": 0.4,
        }
    }
    validator.agents_dict = {
        1: SimpleNamespace(
            github_url="https://github.com/example/repo/commit/abc",
            normalized_repo="https://github.com/example/repo",
            git_commit="abc",
        )
    }
    validator._evaluated_commits_by_miner = {
        1: {
            "older": {
                "agent_run_id": "old-run",
                "average_reward": 0.4,
                "average_score": 0.4,
                "average_execution_time": 12.0,
                "average_cost": 0.2,
                "total_tasks": 2,
                "success_tasks": 1,
            }
        }
    }

    current_payload = validator._current_round_run_payload(1)
    assert current_payload is not None
    assert current_payload["reward"] == pytest.approx(0.5)
    assert current_payload["score"] == pytest.approx(0.6)
    assert current_payload["time"] == pytest.approx(3.0)
    assert current_payload["cost"] == pytest.approx(0.2)
    assert current_payload["tasks_received"] == 2
    assert current_payload["tasks_success"] == 1

    best_payload = validator._best_run_payload_for_miner(1)
    assert best_payload is not None
    assert best_payload["reward"] == pytest.approx(0.5)
    # _best_run_payload_for_miner strips transient failure fields when sourcing current run.
    assert "failed_tasks" not in best_payload
    assert "zero_reason" not in best_payload


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upload_round_log_snapshot_retries_with_truncated_tail_after_413(tmp_path):
    """
    Scenario:
    The full round log is too large for the gateway and IWAP returns 413.

    What this test proves:
    the validator retries with a truncated tail payload so it still gets an S3 URL
    instead of losing the round log entirely.
    """
    from autoppia_web_agents_subnet.utils.logging import ColoredLogger

    validator = _bind_platform_helpers(Mock())
    validator.current_round_id = "validator_round_1_1_biglog"
    validator._iwap_offline_mode = False
    validator._round_log_last_upload_round_id = None
    validator._round_log_last_upload_ts = 0.0
    validator._round_log_last_uploaded_size = -1
    validator._round_log_last_uploaded_url = None
    validator._log_iwap_phase = Mock()
    validator.uid = 83
    validator.wallet = SimpleNamespace(hotkey=SimpleNamespace(ss58_address="5FValidator"))
    validator.season_manager = SimpleNamespace(season_number=1)
    validator.round_manager = SimpleNamespace(round_number=1)

    request = Request("POST", "https://api.example/round-log")
    response = Response(413, request=request)
    attempts: list[str] = []

    async def _upload(*, content: str, **_kwargs):
        attempts.append(content)
        if len(attempts) == 1:
            raise HTTPStatusError("payload too large", request=request, response=response)
        return "https://logs.example/truncated.log"

    validator.iwap_client = SimpleNamespace(upload_round_log=AsyncMock(side_effect=_upload))

    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        ColoredLogger.clear_round_log_file()
        ColoredLogger.set_round_log_file("validator_round_1_1_biglog")
        path = ColoredLogger.get_round_log_file()
        assert path is not None
        Path(path).write_text(("x" * 2_500_000) + "\nfinal line\n", encoding="utf-8")

        url = await validator._upload_round_log_snapshot(reason="test", force=True, min_interval_seconds=0.0)
    finally:
        os.chdir(orig_cwd)
        ColoredLogger.clear_round_log_file()

    assert url == "https://logs.example/truncated.log"
    assert len(attempts) == 2
    assert len(attempts[1].encode("utf-8")) < len(attempts[0].encode("utf-8"))
    assert "[AUTOPPIA ROUND LOG TRUNCATED FOR S3 UPLOAD]" in attempts[1]
    assert "final line" in attempts[1]
