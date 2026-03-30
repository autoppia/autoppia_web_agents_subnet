from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from httpx import HTTPStatusError, Request, Response

from autoppia_web_agents_subnet.platform.utils.round_flow import (
    _flush_pending_finish_requests,
    _flush_pending_round_log_replays,
    finish_round_flow,
)


def _make_finish_ctx(tmp_path: Path):
    ctx = SimpleNamespace()
    ctx.current_round_id = "validator_round_1_1_finish"
    ctx.uid = 83
    ctx.version = "16.0.0"
    ctx.round_start_time = 1000.0
    ctx.active_miner_uids = {48, 127}
    ctx.current_agent_runs = {}
    ctx.current_miner_snapshots = {}
    ctx.current_round_tasks = {}
    ctx.agent_run_accumulators = {}
    ctx._agg_scores_cache = {}
    ctx._agg_meta_cache = {}
    ctx._ipfs_uploaded_payload = None
    ctx._ipfs_upload_cid = None
    ctx._consensus_commit_cid = None
    ctx._consensus_publish_timestamp = None
    ctx._consensus_reveal_round = 0
    ctx._iwap_offline_mode = False
    ctx.handshake_results = {"48": "ok", "127": "ok"}
    ctx.eligibility_status_by_uid = {48: "evaluated", 127: "evaluated"}
    ctx._state_summary_root = Mock(return_value=tmp_path / "state")
    ctx._reset_iwap_round_state = Mock()
    ctx._upload_round_log_snapshot = AsyncMock(return_value="https://logs.example/round.log")
    ctx.iwap_client = SimpleNamespace(finish_round=AsyncMock(return_value=None))
    ctx.wallet = SimpleNamespace(
        hotkey=SimpleNamespace(ss58_address="5FValidator"),
        coldkeypub=SimpleNamespace(ss58_address="5FColdkey"),
    )
    ctx.metagraph = SimpleNamespace(
        hotkeys=["hotkey0"] * 300,
        coldkeys=["coldkey0"] * 300,
    )
    ctx.config = SimpleNamespace(neuron=SimpleNamespace(full_path=str(tmp_path / "validator")))
    Path(ctx.config.neuron.full_path).mkdir(parents=True, exist_ok=True)
    ctx.season_manager = SimpleNamespace(season_number=1)
    ctx.round_manager = SimpleNamespace(
        round_number=1,
        round_rewards={},
        round_eval_scores={},
        round_times={},
        round_size_epochs=5.0,
        season_size_epochs=100.0,
        minimum_start_block=7736300,
        BLOCKS_PER_EPOCH=360,
        get_current_boundaries=Mock(
            return_value={
                "round_start_block": 7736300,
                "target_block": 7738100,
                "round_start_epoch": 21489.72,
                "target_epoch": 21494.72,
            }
        ),
        block_to_epoch=Mock(side_effect=lambda block: float(block) / 360.0),
    )
    ctx.agents_dict = {
        48: SimpleNamespace(agent_name="Miner 48"),
        127: SimpleNamespace(agent_name="Miner 127"),
    }
    ctx._best_runs = {}
    ctx._current_runs = {}
    ctx._best_run_payload_for_miner = lambda uid: ctx._best_runs.get(uid)
    ctx._current_round_run_payload = lambda uid: ctx._current_runs.get(uid)
    return ctx


def _make_agent_run(agent_run_id: str):
    return SimpleNamespace(
        agent_run_id=agent_run_id,
        started_at=1000.0,
        ended_at=None,
        elapsed_sec=None,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_round_serializes_partial_round_window_exceeded_run_into_iwap_payload(tmp_path):
    """
    Scenario:
    A miner was partially evaluated and then the round window closed.
    The current run is therefore partial and tagged with `zero_reason=round_window_exceeded`.

    What this test proves:
    the IWAP finish payload must preserve that partial state exactly instead of silently
    pretending the miner was either fully evaluated or never seen.
    """
    ctx = _make_finish_ctx(tmp_path)
    ctx.active_miner_uids = {48}
    ctx.current_agent_runs = {48: _make_agent_run("run-48")}
    ctx._current_runs = {
        48: {
            "reward": 0.41,
            "score": 0.41,
            "time": 12.5,
            "cost": 0.03,
            "tasks_received": 67,
            "tasks_success": 56,
            "failed_tasks": 11,
            "zero_reason": "round_window_exceeded",
        }
    }

    await finish_round_flow(ctx, avg_rewards={48: 0.41}, final_weights={48: 1.0}, tasks_completed=56)

    ctx.iwap_client.finish_round.assert_awaited_once()
    finish_request = ctx.iwap_client.finish_round.await_args.kwargs["finish_request"]

    local_miner = finish_request.local_evaluation["miners"][0]
    assert local_miner["miner_uid"] == 48
    assert local_miner["tasks_attempted"] == 67
    assert local_miner["tasks_completed"] == 56
    assert local_miner["tasks_failed"] == 11
    assert local_miner["zero_reason"] == "round_window_exceeded"
    assert local_miner["current_run"]["tasks_received"] == 67
    assert local_miner["current_run"]["tasks_success"] == 56

    agent_run_summary = finish_request.agent_runs[0]
    assert agent_run_summary.agent_run_id == "run-48"
    assert agent_run_summary.tasks_attempted == 67
    assert agent_run_summary.tasks_completed == 56
    assert agent_run_summary.tasks_failed == 11
    assert agent_run_summary.zero_reason == "round_window_exceeded"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_round_includes_zeroed_pending_miner_and_keeps_round_metadata_consistent(tmp_path):
    """
    Scenario:
    One miner finished normally.
    Another miner was queued but got zeroed because the round stop window was reached.

    What this test proves:
    - both miners still appear in the finish payload
    - the zeroed miner is not dropped
    - round metadata totals are computed from the current runs that will be persisted
    """
    ctx = _make_finish_ctx(tmp_path)
    ctx.current_agent_runs = {
        48: _make_agent_run("run-48"),
        127: _make_agent_run("run-127"),
    }
    ctx._current_runs = {
        48: {
            "reward": 0.60,
            "score": 0.60,
            "time": 9.0,
            "cost": 0.02,
            "tasks_received": 100,
            "tasks_success": 60,
            "failed_tasks": 40,
        },
        127: {
            "reward": 0.0,
            "score": 0.0,
            "time": 180.0,
            "cost": 0.0,
            "tasks_received": 100,
            "tasks_success": 0,
            "failed_tasks": 100,
            "zero_reason": "round_window_exceeded",
        },
    }

    await finish_round_flow(
        ctx,
        avg_rewards={48: 0.60, 127: 0.0},
        final_weights={48: 0.9, 127: 0.1},
        tasks_completed=60,
    )

    finish_request = ctx.iwap_client.finish_round.await_args.kwargs["finish_request"]
    miners = {miner["miner_uid"]: miner for miner in finish_request.local_evaluation["miners"]}

    assert set(miners) == {48, 127}
    assert miners[127]["zero_reason"] == "round_window_exceeded"
    assert miners[127]["tasks_attempted"] == 100
    assert miners[127]["tasks_completed"] == 0
    assert miners[127]["tasks_failed"] == 100

    assert finish_request.round_metadata.tasks_total == 200
    assert finish_request.round_metadata.tasks_completed == 60
    assert finish_request.summary["tasks_completed"] == 60
    assert finish_request.summary["active_miners"] == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_round_retries_main_authority_grace_and_exits_cleanly(tmp_path):
    """
    Scenario:
    This validator tries to close the round, but the backend says the main validator
    is still inside the finish grace window.

    What this test proves:
    - finish_round retries instead of crashing
    - after exhausting retries, the validator resets local round state cleanly
    - the function returns `False` rather than throwing
    """
    ctx = _make_finish_ctx(tmp_path)
    ctx.active_miner_uids = {48}
    ctx.current_agent_runs = {48: _make_agent_run("run-48")}
    ctx._current_runs = {
        48: {
            "reward": 0.4,
            "score": 0.4,
            "time": 10.0,
            "cost": 0.02,
            "tasks_received": 100,
            "tasks_success": 40,
            "failed_tasks": 60,
        }
    }

    error_payload = {"detail": "main validator still within finish grace"}
    response = Response(status_code=409, json=error_payload, request=Request("POST", "https://iwap.test/finish"))
    grace_error = HTTPStatusError("grace", request=response.request, response=response)
    ctx.iwap_client.finish_round = AsyncMock(side_effect=[grace_error, grace_error, grace_error])

    with (
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.FINISH_ROUND_MAX_RETRIES", 2),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.FINISH_ROUND_RETRY_SECONDS", 10),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.asyncio.sleep", new=AsyncMock()),
    ):
        success = await finish_round_flow(ctx, avg_rewards={48: 0.4}, final_weights={48: 1.0}, tasks_completed=40)

    assert success is False
    assert ctx.iwap_client.finish_round.await_count == 3
    ctx._reset_iwap_round_state.assert_called_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_round_persists_pending_payload_when_grace_blocks_iwap_close(tmp_path):
    """
    Scenario:
    A validator finishes locally, but IWAP keeps rejecting the close because the
    main validator is still inside the finish grace window.

    What this test proves:
    - the validator persists a pending finish payload to disk
    - the local payload is not lost just because IWAP is temporarily blocked
    """
    ctx = _make_finish_ctx(tmp_path)
    ctx.active_miner_uids = {48}
    ctx.current_agent_runs = {48: _make_agent_run("run-48")}
    ctx._current_runs = {
        48: {
            "reward": 0.4,
            "score": 0.4,
            "time": 10.0,
            "cost": 0.02,
            "tasks_received": 100,
            "tasks_success": 40,
            "failed_tasks": 60,
        }
    }

    error_payload = {"detail": "main validator still within finish grace"}
    response = Response(status_code=409, json=error_payload, request=Request("POST", "https://iwap.test/finish"))
    grace_error = HTTPStatusError("grace", request=response.request, response=response)
    ctx.iwap_client.finish_round = AsyncMock(side_effect=[grace_error, grace_error, grace_error])

    with (
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.FINISH_ROUND_MAX_RETRIES", 2),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.FINISH_ROUND_RETRY_SECONDS", 10),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.asyncio.sleep", new=AsyncMock()),
    ):
        success = await finish_round_flow(ctx, avg_rewards={48: 0.4}, final_weights={48: 1.0}, tasks_completed=40)

    assert success is False
    pending_file = tmp_path / "state" / "pending_finish" / "validator_round_1_1_finish.json"
    assert pending_file.exists()
    payload = json.loads(pending_file.read_text(encoding="utf-8"))
    assert payload["validator_round_id"] == "validator_round_1_1_finish"
    assert payload["finish_request"]["local_evaluation"]["miners"][0]["miner_uid"] == 48


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pending_finish_payload_is_replayed_successfully_on_next_round_start(tmp_path):
    """
    Scenario:
    A previous round left behind a persisted pending finish payload.

    What this test proves:
    - the replay helper resubmits that finish payload to IWAP
    - after a successful replay, the pending file is deleted
    """
    ctx = _make_finish_ctx(tmp_path)
    pending_dir = tmp_path / "state" / "pending_finish"
    pending_dir.mkdir(parents=True, exist_ok=True)
    pending_payload = {
        "validator_round_id": "validator_round_1_1_finish",
        "finish_request": {
            "status": "completed",
            "ended_at": 1234.5,
            "summary": {"winner_uid": 48},
            "agent_runs": [],
            "round_metadata": None,
            "local_evaluation": {"miners": [{"miner_uid": 48, "current_run": {"reward": 0.4}}]},
            "post_consensus_evaluation": {"miners": [{"uid": 48, "best_run_consensus": {"reward": 0.4}}]},
            "validator_summary": {"round": {"season_number": 1, "round_number": 1}},
            "ipfs_uploaded": {"cid": "bafy-test"},
            "ipfs_downloaded": {"payloads": []},
            "s3_logs_url": "https://logs.example/round.log",
            "validator_state": None,
        },
        "persisted_at": 1234.0,
    }
    pending_file = pending_dir / "validator_round_1_1_finish.json"
    pending_file.write_text(json.dumps(pending_payload, indent=2, sort_keys=True), encoding="utf-8")

    ctx.iwap_client.finish_round = AsyncMock(return_value=None)

    await _flush_pending_finish_requests(ctx)

    ctx.iwap_client.finish_round.assert_awaited_once()
    assert not pending_file.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pending_round_log_is_replayed_successfully_on_next_round_start(tmp_path):
    """
    Scenario:
    The validator crashed before settlement completed, so only the round log and a
    non-completed round checkpoint survived on disk.

    What this test proves:
    - the next startup replays that stale round log to IWAP/S3
    - the checkpoint is updated with the replayed upload metadata
    """
    ctx = _make_finish_ctx(tmp_path)
    ctx.iwap_client.upload_round_log = AsyncMock(return_value="https://logs.example/replayed-round.log")

    round_dir = tmp_path / "state" / "season_1" / "round_2"
    round_dir.mkdir(parents=True, exist_ok=True)
    round_log_path = round_dir / "round.log"
    round_log_path.write_text("round log survived crash\n", encoding="utf-8")
    checkpoint_path = round_dir / "round_checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "validator_round_id": "validator_round_1_2_crash",
                "season_number": 1,
                "round_number_in_season": 2,
                "validator_uid": 71,
                "validator_hotkey": "5C5hkvYV...",
                "status": "registering_miners",
                "round_log_file": str(round_log_path),
                "last_round_log_uploaded_size": -1,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    await _flush_pending_round_log_replays(ctx)

    ctx.iwap_client.upload_round_log.assert_awaited_once()
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert payload["last_round_log_upload_url"] == "https://logs.example/replayed-round.log"
    assert payload["replayed_from_startup"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_completed_round_checkpoint_is_not_replayed_again(tmp_path):
    """
    Scenario:
    A finished round left behind its checkpoint on disk.

    What this test proves:
    completed checkpoints are ignored by the startup replay helper, so we do not
    keep re-uploading old round logs forever.
    """
    ctx = _make_finish_ctx(tmp_path)
    ctx.iwap_client.upload_round_log = AsyncMock(return_value="https://logs.example/should-not-upload.log")

    round_dir = tmp_path / "state" / "season_1" / "round_1"
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "round.log").write_text("finished round log\n", encoding="utf-8")
    (round_dir / "round_checkpoint.json").write_text(
        json.dumps(
            {
                "validator_round_id": "validator_round_1_1_done",
                "season_number": 1,
                "round_number_in_season": 1,
                "validator_uid": 83,
                "status": "completed",
                "round_log_file": str(round_dir / "round.log"),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    await _flush_pending_round_log_replays(ctx)

    ctx.iwap_client.upload_round_log.assert_not_called()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_round_canonicalizes_summary_snapshots_from_best_run_consensus(tmp_path):
    """
    Scenario:
    The stored post-consensus summary already has the correct UIDs for leader/candidate,
    but stale score/time/cost values.

    What this test proves:
    finish_round rewrites those snapshots from the canonical miner entries that are actually
    being sent in `post_consensus_evaluation`.

    Important:
    current code keeps `reward/weight` from the best-run consensus entry, but `score/time/cost`
    can still reflect current-round aggregated stats when those are preferred upstream.
    """
    ctx = _make_finish_ctx(tmp_path)
    ctx.current_round_id = "validator_round_1_2_finish"
    ctx.round_manager.round_number = 2
    ctx.active_miner_uids = {48, 127}
    ctx.current_agent_runs = {
        48: _make_agent_run("run-48"),
        127: _make_agent_run("run-127"),
    }
    ctx._best_runs = {
        48: {
            "reward": 0.90,
            "score": 0.90,
            "time": 9.0,
            "cost": 0.02,
            "tasks_received": 100,
            "tasks_success": 90,
            "github_url": "https://github.com/example/leader",
            "normalized_repo": "https://github.com/example/leader",
            "commit_sha": "leader-sha",
        },
        127: {
            "reward": 0.96,
            "score": 0.96,
            "time": 8.0,
            "cost": 0.01,
            "tasks_received": 100,
            "tasks_success": 96,
            "github_url": "https://github.com/example/challenger",
            "normalized_repo": "https://github.com/example/challenger",
            "commit_sha": "challenger-sha",
        },
    }
    ctx._current_runs = {
        48: {
            "reward": 0.70,
            "score": 0.70,
            "time": 11.0,
            "cost": 0.03,
            "tasks_received": 100,
            "tasks_success": 70,
        },
        127: {
            "reward": 0.96,
            "score": 0.96,
            "time": 8.0,
            "cost": 0.01,
            "tasks_received": 100,
            "tasks_success": 96,
        },
    }
    ctx._agg_scores_cache = {48: 0.90, 127: 0.96}
    ctx._agg_meta_cache = {
        "stats_by_miner": {
            48: {"avg_reward": 0.90, "avg_eval_score": 0.90, "avg_eval_time": 9.0, "avg_cost": 0.02, "tasks_sent": 100, "tasks_success": 90},
            127: {"avg_reward": 0.96, "avg_eval_score": 0.96, "avg_eval_time": 8.0, "avg_cost": 0.01, "tasks_sent": 100, "tasks_success": 96},
        },
        "current_stats_by_miner": {
            48: {"avg_reward": 0.70, "avg_eval_score": 0.70, "avg_eval_time": 11.0, "avg_cost": 0.03, "tasks_sent": 100, "tasks_success": 70},
            127: {"avg_reward": 0.96, "avg_eval_score": 0.96, "avg_eval_time": 8.0, "avg_cost": 0.01, "tasks_sent": 100, "tasks_success": 96},
        },
        "downloaded_payloads": [
            {"uid": 71, "validator_hotkey": "hk71", "stake": 10000.0, "cid": "cid-71", "payload": {"miners": []}},
            {"uid": 83, "validator_hotkey": "hk83", "stake": 20000.0, "cid": "cid-83", "payload": {"miners": []}},
        ],
    }
    ctx._season_competition_history = {
        1: {
            "rounds": {
                1: {
                    "post_consensus_json": {
                        "summary": {
                            "season": 1,
                            "round": 1,
                            "percentage_to_dethrone": 0.05,
                            "dethroned": False,
                            "leader_before_round": None,
                            "candidate_this_round": {"uid": 48, "reward": 0.90, "score": 0.70, "time": 11.0, "cost": 0.03},
                            "leader_after_round": {"uid": 48, "reward": 0.90, "score": 0.70, "time": 11.0, "cost": 0.03},
                        }
                    }
                },
                2: {
                    "post_consensus_json": {
                        "summary": {
                            "season": 1,
                            "round": 2,
                            "percentage_to_dethrone": 0.05,
                            "dethroned": True,
                            "leader_before_round": {"uid": 48, "reward": 999.0, "score": 999.0, "time": 999.0, "cost": 999.0},
                            "candidate_this_round": {"uid": 127, "reward": 888.0, "score": 888.0, "time": 888.0, "cost": 888.0},
                            "leader_after_round": {"uid": 127, "reward": 777.0, "score": 777.0, "time": 777.0, "cost": 777.0},
                        }
                    }
                },
            }
        }
    }

    await finish_round_flow(
        ctx,
        avg_rewards={48: 0.70, 127: 0.96},
        final_weights={127: 0.075, 5: 0.925},
        tasks_completed=166,
    )

    finish_request = ctx.iwap_client.finish_round.await_args.kwargs["finish_request"]
    summary = finish_request.post_consensus_evaluation["summary"]

    assert summary["leader_before_round"]["uid"] == 48
    assert summary["leader_before_round"]["reward"] == pytest.approx(0.90)
    assert summary["leader_before_round"]["score"] == pytest.approx(0.70)
    assert summary["leader_before_round"]["time"] == pytest.approx(11.0)
    assert summary["leader_before_round"]["cost"] == pytest.approx(0.03)
    assert summary["candidate_this_round"]["uid"] == 127
    assert summary["candidate_this_round"]["reward"] == pytest.approx(0.96)
    assert summary["candidate_this_round"]["score"] == pytest.approx(0.96)
    assert summary["leader_after_round"]["uid"] == 127
    assert summary["leader_after_round"]["reward"] == pytest.approx(0.96)
    assert summary["leader_after_round"]["weight"] == pytest.approx(0.075)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_round_uses_current_round_task_counts_for_post_consensus_snapshot(tmp_path):
    """
    Scenario:
    A miner has a historical best run with much larger task counters than the
    current round's run.

    What this test proves:
    the post-consensus snapshot for the current round must keep the current
    round task counters and commit metadata instead of leaking the historical
    best-run payload into `best_run_consensus`.
    """
    ctx = _make_finish_ctx(tmp_path)
    ctx.active_miner_uids = {48}
    ctx.current_agent_runs = {48: _make_agent_run("run-48")}
    ctx._best_runs = {
        48: {
            "reward": 0.80,
            "score": 0.80,
            "time": 22.0,
            "cost": 0.02,
            "tasks_received": 325,
            "tasks_success": 200,
            "github_url": "https://github.com/example/repo/commit/historical",
            "normalized_repo": "https://github.com/example/repo",
            "commit_sha": "historical",
        }
    }
    ctx._current_runs = {
        48: {
            "reward": 0.10,
            "score": 0.10,
            "time": 58.0,
            "cost": 0.01,
            "tasks_received": 25,
            "tasks_success": 0,
            "github_url": "https://github.com/example/repo/commit/current",
            "normalized_repo": "https://github.com/example/repo",
            "commit_sha": "current",
        }
    }
    ctx._agg_scores_cache = {48: 0.0}
    ctx._agg_meta_cache = {
        "stats_by_miner": {48: {"avg_reward": 0.0, "avg_eval_score": 0.0, "avg_eval_time": 58.28, "avg_cost": 0.001, "tasks_sent": 25, "tasks_success": 0}},
        "current_stats_by_miner": {48: {"avg_reward": 0.0, "avg_eval_score": 0.0, "avg_eval_time": 58.28, "avg_cost": 0.001, "tasks_sent": 25, "tasks_success": 0}},
    }

    await finish_round_flow(
        ctx,
        avg_rewards={48: 0.0},
        final_weights={48: 1.0},
        tasks_completed=0,
    )

    finish_request = ctx.iwap_client.finish_round.await_args.kwargs["finish_request"]
    miner_payload = finish_request.post_consensus_evaluation["miners"][0]["best_run_consensus"]

    assert miner_payload["tasks_received"] == 25
    assert miner_payload["tasks_success"] == 0
    assert miner_payload["commit_sha"] == "current"
    assert miner_payload["github_url"] == "https://github.com/example/repo/commit/current"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_round_first_round_cannot_keep_different_leader_after_when_no_leader_before(tmp_path):
    """
    Scenario:
    A first-round summary arrives corrupted:
    - there is no `leader_before_round`
    - `candidate_this_round` points to the actual winner
    - `leader_after_round` points to a different stale miner

    What this test proves:
    finish_round must repair this impossible state. Without a reigning leader, the only valid
    `leader_after_round` is the current round winner/candidate.
    """
    ctx = _make_finish_ctx(tmp_path)
    ctx.current_round_id = "validator_round_1_1_finish"
    ctx.round_manager.round_number = 1
    ctx.active_miner_uids = {48, 127}
    ctx.current_agent_runs = {
        48: _make_agent_run("run-48"),
        127: _make_agent_run("run-127"),
    }
    ctx._best_runs = {
        48: {
            "reward": 0.153927,
            "score": 0.169214,
            "time": 87.60756,
            "cost": 0.033605,
            "tasks_received": 100,
            "tasks_success": 7,
        },
        127: {
            "reward": 0.0,
            "score": 0.0,
            "time": 0.0,
            "cost": 0.0,
            "tasks_received": 100,
            "tasks_success": 0,
        },
    }
    ctx._current_runs = {
        48: {
            "reward": 0.153927,
            "score": 0.169214,
            "time": 87.60756,
            "cost": 0.033605,
            "tasks_received": 100,
            "tasks_success": 7,
        },
        127: {
            "reward": 0.0,
            "score": 0.0,
            "time": 0.0,
            "cost": 0.0,
            "tasks_received": 100,
            "tasks_success": 0,
        },
    }
    ctx._agg_scores_cache = {48: 0.153927, 127: 0.0}
    ctx._agg_meta_cache = {
        "stats_by_miner": {
            48: {"avg_reward": 0.153927, "avg_eval_score": 0.169214, "avg_eval_time": 87.60756, "avg_cost": 0.033605, "tasks_sent": 100, "tasks_success": 7},
            127: {"avg_reward": 0.0, "avg_eval_score": 0.0, "avg_eval_time": 0.0, "avg_cost": 0.0, "tasks_sent": 100, "tasks_success": 0},
        },
        "current_stats_by_miner": {
            48: {"avg_reward": 0.153927, "avg_eval_score": 0.169214, "avg_eval_time": 87.60756, "avg_cost": 0.033605, "tasks_sent": 100, "tasks_success": 7},
            127: {"avg_reward": 0.0, "avg_eval_score": 0.0, "avg_eval_time": 0.0, "avg_cost": 0.0, "tasks_sent": 100, "tasks_success": 0},
        },
        "downloaded_payloads": [],
    }
    ctx._season_competition_history = {
        1: {
            "rounds": {
                1: {
                    "post_consensus_json": {
                        "summary": {
                            "season": 1,
                            "round": 1,
                            "percentage_to_dethrone": 0.05,
                            "dethroned": False,
                            "leader_before_round": None,
                            "candidate_this_round": {"uid": 48, "reward": 999.0, "score": 999.0, "time": 999.0, "cost": 999.0},
                            "leader_after_round": {"uid": 127, "reward": 777.0, "score": 777.0, "time": 777.0, "cost": 777.0},
                        }
                    }
                }
            }
        }
    }

    await finish_round_flow(ctx, avg_rewards={48: 0.153927, 127: 0.0}, final_weights={48: 0.075, 5: 0.925}, tasks_completed=100)

    summary = ctx.iwap_client.finish_round.await_args.kwargs["finish_request"].post_consensus_evaluation["summary"]
    assert summary["leader_before_round"] is None
    assert summary["candidate_this_round"]["uid"] == 48
    assert summary["leader_after_round"]["uid"] == 48
    assert summary["leader_after_round"]["reward"] == pytest.approx(0.153927)
    assert summary["dethroned"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_round_repairs_dethrone_when_candidate_beats_threshold_but_summary_says_otherwise(tmp_path):
    """
    Scenario:
    A later-round summary arrives corrupted:
    - a real reigning leader exists
    - the candidate reward beats the dethrone threshold
    - but stale summary data says `dethroned=false` and keeps the old leader after the round

    What this test proves:
    finish_round must not preserve that impossible state. If candidate reward beats the threshold,
    `dethroned` must become true and `leader_after_round` must become the candidate.
    """
    ctx = _make_finish_ctx(tmp_path)
    ctx.current_round_id = "validator_round_1_2_finish"
    ctx.round_manager.round_number = 2
    ctx.active_miner_uids = {48, 127}
    ctx.current_agent_runs = {
        48: _make_agent_run("run-48"),
        127: _make_agent_run("run-127"),
    }
    ctx._best_runs = {
        48: {
            "reward": 0.90,
            "score": 0.70,
            "time": 11.0,
            "cost": 0.03,
            "tasks_received": 100,
            "tasks_success": 70,
        },
        127: {
            "reward": 0.96,
            "score": 0.96,
            "time": 8.0,
            "cost": 0.01,
            "tasks_received": 100,
            "tasks_success": 96,
        },
    }
    ctx._current_runs = {
        48: {
            "reward": 0.70,
            "score": 0.70,
            "time": 11.0,
            "cost": 0.03,
            "tasks_received": 100,
            "tasks_success": 70,
        },
        127: {
            "reward": 0.96,
            "score": 0.96,
            "time": 8.0,
            "cost": 0.01,
            "tasks_received": 100,
            "tasks_success": 96,
        },
    }
    ctx._agg_scores_cache = {48: 0.90, 127: 0.96}
    ctx._agg_meta_cache = {
        "stats_by_miner": {
            48: {"avg_reward": 0.90, "avg_eval_score": 0.70, "avg_eval_time": 11.0, "avg_cost": 0.03, "tasks_sent": 100, "tasks_success": 70},
            127: {"avg_reward": 0.96, "avg_eval_score": 0.96, "avg_eval_time": 8.0, "avg_cost": 0.01, "tasks_sent": 100, "tasks_success": 96},
        },
        "current_stats_by_miner": {
            48: {"avg_reward": 0.70, "avg_eval_score": 0.70, "avg_eval_time": 11.0, "avg_cost": 0.03, "tasks_sent": 100, "tasks_success": 70},
            127: {"avg_reward": 0.96, "avg_eval_score": 0.96, "avg_eval_time": 8.0, "avg_cost": 0.01, "tasks_sent": 100, "tasks_success": 96},
        },
        "downloaded_payloads": [],
    }
    ctx._season_competition_history = {
        1: {
            "rounds": {
                1: {
                    "post_consensus_json": {
                        "summary": {
                            "season": 1,
                            "round": 1,
                            "percentage_to_dethrone": 0.05,
                            "dethroned": False,
                            "leader_before_round": None,
                            "candidate_this_round": {"uid": 48, "reward": 0.90, "score": 0.70, "time": 11.0, "cost": 0.03},
                            "leader_after_round": {"uid": 48, "reward": 0.90, "score": 0.70, "time": 11.0, "cost": 0.03},
                        }
                    }
                },
                2: {
                    "post_consensus_json": {
                        "summary": {
                            "season": 1,
                            "round": 2,
                            "percentage_to_dethrone": 0.05,
                            "dethroned": False,
                            "leader_before_round": {"uid": 48, "reward": 999.0, "score": 999.0, "time": 999.0, "cost": 999.0},
                            "candidate_this_round": {"uid": 127, "reward": 888.0, "score": 888.0, "time": 888.0, "cost": 888.0},
                            "leader_after_round": {"uid": 48, "reward": 777.0, "score": 777.0, "time": 777.0, "cost": 777.0},
                        }
                    }
                },
            }
        }
    }

    await finish_round_flow(ctx, avg_rewards={48: 0.70, 127: 0.96}, final_weights={127: 0.075, 5: 0.925}, tasks_completed=200)

    summary = ctx.iwap_client.finish_round.await_args.kwargs["finish_request"].post_consensus_evaluation["summary"]
    assert summary["leader_before_round"]["uid"] == 48
    assert summary["candidate_this_round"]["uid"] == 127
    assert summary["candidate_this_round"]["reward"] == pytest.approx(0.96)
    assert summary["dethroned"] is True
    assert summary["leader_after_round"]["uid"] == 127
    assert summary["leader_after_round"]["reward"] == pytest.approx(0.96)
