from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from httpx import HTTPStatusError, Request, Response

os.environ.setdefault("TESTING", "True")
os.environ.setdefault("VALIDATOR_NAME", "Test Validator")
os.environ.setdefault("VALIDATOR_IMAGE", "https://example.com/validator.png")

from autoppia_web_agents_subnet.platform.utils.round_flow import finish_round_flow, start_round_flow
from autoppia_web_agents_subnet.validator import config as validator_config


def _http_error(status_code: int, detail):
    payload = detail if isinstance(detail, dict) and "detail" in detail else {"detail": detail}
    response = Response(status_code=status_code, json=payload, request=Request("POST", "https://iwap.test/finish"))
    return HTTPStatusError(f"HTTP {status_code}", request=response.request, response=response)


def _make_agent_run(agent_run_id: str):
    return SimpleNamespace(agent_run_id=agent_run_id, started_at=1000.0, ended_at=None, elapsed_sec=None)


def _make_finish_ctx(tmp_path: Path):
    ctx = SimpleNamespace()
    ctx.current_round_id = "validator_round_1_5_finish"
    ctx.uid = 83
    ctx.version = "20.0.0"
    ctx.round_start_time = 1000.0
    ctx.round_start_timestamp = 1000.0
    ctx.active_miner_uids = {48}
    ctx.current_agent_runs = {48: _make_agent_run("run-48")}
    ctx.current_miner_snapshots = {}
    ctx.current_round_tasks = {}
    ctx.agent_run_accumulators = {}
    ctx._agg_scores_cache = {}
    ctx._agg_meta_cache = {}
    ctx._best_runs = {}
    ctx._current_runs = {
        48: {
            "reward": 0.4,
            "score": 0.4,
            "time": 10.0,
            "cost": 0.02,
            "tasks_received": 100,
            "tasks_attempted": 67,
            "tasks_success": 40,
            "failed_tasks": 60,
            "early_stop_reason": "over_cost_limit",
            "early_stop_message": "Stopped early after 67/100 tasks: 10 tasks exceeded the per-task cost limit of $0.05.",
        }
    }
    ctx._best_run_payload_for_miner = lambda uid: ctx._best_runs.get(uid)
    ctx._current_round_run_payload = lambda uid: ctx._current_runs.get(uid)
    ctx._ipfs_uploaded_payload = None
    ctx._ipfs_upload_cid = None
    ctx._consensus_commit_cid = None
    ctx._consensus_publish_timestamp = None
    ctx._consensus_reveal_round = 0
    ctx._iwap_offline_mode = False
    ctx._state_summary_root = Mock(return_value=tmp_path / "state")
    ctx._reset_iwap_round_state = Mock()
    ctx._upload_round_log_snapshot = AsyncMock(return_value="https://logs.example/round.log")
    ctx._persist_round_checkpoint = Mock()
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
        round_number=5,
        round_rewards={},
        round_eval_scores={},
        round_times={},
        round_size_epochs=5.0,
        season_size_epochs=100.0,
        minimum_start_block=7736300,
        BLOCKS_PER_EPOCH=360,
        block_to_epoch=Mock(side_effect=lambda block: float(block) / 360.0),
        get_current_boundaries=Mock(
            return_value={
                "round_start_block": 7747761,
                "target_block": 7749561,
                "round_start_epoch": 21521.56,
                "target_epoch": 21526.56,
            }
        ),
    )
    ctx.agents_dict = {48: SimpleNamespace(agent_name="Miner 48")}
    ctx.handshake_results = {"48": "ok"}
    ctx.eligibility_status_by_uid = {48: "evaluated"}
    return ctx


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_round_offline_mode_cleans_up_locally_and_returns_true(tmp_path):
    ctx = _make_finish_ctx(tmp_path)
    ctx._iwap_offline_mode = True

    success = await finish_round_flow(ctx, avg_rewards={48: 0.4}, final_weights={48: 1.0}, tasks_completed=40)

    assert success is True
    ctx.iwap_client.finish_round.assert_not_called()
    ctx._reset_iwap_round_state.assert_called_once()
    ctx._persist_round_checkpoint.assert_called_once_with(reason="finish_round_offline", status="completed")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_round_main_success_persists_completed_checkpoint(tmp_path):
    ctx = _make_finish_ctx(tmp_path)

    success = await finish_round_flow(ctx, avg_rewards={48: 0.4}, final_weights={48: 1.0}, tasks_completed=40)

    assert success is True
    ctx.iwap_client.finish_round.assert_awaited_once()
    ctx._persist_round_checkpoint.assert_called_once_with(reason="finish_round_completed", status="completed")
    ctx._reset_iwap_round_state.assert_called_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_round_authority_grace_retries_then_succeeds(tmp_path):
    ctx = _make_finish_ctx(tmp_path)
    grace_error = _http_error(409, "main validator still within finish grace")
    ctx.iwap_client.finish_round = AsyncMock(side_effect=[grace_error, grace_error, None])

    with (
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.FINISH_ROUND_MAX_RETRIES", 2),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.FINISH_ROUND_RETRY_SECONDS", 10),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.asyncio.sleep", new=AsyncMock()),
    ):
        success = await finish_round_flow(ctx, avg_rewards={48: 0.4}, final_weights={48: 1.0}, tasks_completed=40)

    assert success is True
    assert ctx.iwap_client.finish_round.await_count == 3
    ctx._persist_round_checkpoint.assert_called_once_with(reason="finish_round_completed", status="completed")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_round_generic_failure_uses_fallback_payload_and_completes(tmp_path):
    ctx = _make_finish_ctx(tmp_path)
    primary_error = _http_error(500, "backend exploded")
    ctx.iwap_client.finish_round = AsyncMock(side_effect=[primary_error, None])

    success = await finish_round_flow(ctx, avg_rewards={48: 0.4}, final_weights={48: 1.0}, tasks_completed=40)

    assert success is True
    assert ctx.iwap_client.finish_round.await_count == 2
    fallback_request = ctx.iwap_client.finish_round.await_args_list[1].kwargs["finish_request"]
    assert fallback_request.summary["round_closure_error"]["status"] == "failed_on_finish_round"
    ctx._persist_round_checkpoint.assert_called_once_with(reason="finish_round_fallback_completed", status="completed")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_round_shadow_persists_pending_payload_when_main_grace_never_clears(tmp_path):
    ctx = _make_finish_ctx(tmp_path)
    ctx.uid = 55
    grace_error = _http_error(409, "main validator still within finish grace")
    ctx.iwap_client.finish_round = AsyncMock(side_effect=[grace_error, grace_error, grace_error])

    with (
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.FINISH_ROUND_MAX_RETRIES", 2),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.FINISH_ROUND_RETRY_SECONDS", 10),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.asyncio.sleep", new=AsyncMock()),
    ):
        success = await finish_round_flow(ctx, avg_rewards={48: 0.4}, final_weights={48: 1.0}, tasks_completed=40)

    assert success is False
    pending_file = tmp_path / "state" / "pending_finish" / "validator_round_1_5_finish.json"
    assert pending_file.exists()
    payload = json.loads(pending_file.read_text(encoding="utf-8"))
    assert payload["validator_round_id"] == "validator_round_1_5_finish"
    ctx._persist_round_checkpoint.assert_called_once_with(reason="finish_round_pending", status="pending_finish")
    ctx._reset_iwap_round_state.assert_called_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_round_primary_and_fallback_failure_persist_pending_payload(tmp_path):
    ctx = _make_finish_ctx(tmp_path)
    primary_error = _http_error(500, "backend exploded")
    fallback_error = _http_error(500, "fallback exploded")
    ctx.iwap_client.finish_round = AsyncMock(side_effect=[primary_error, fallback_error])

    success = await finish_round_flow(ctx, avg_rewards={48: 0.4}, final_weights={48: 1.0}, tasks_completed=40)

    assert success is False
    pending_file = tmp_path / "state" / "pending_finish" / "validator_round_1_5_finish.json"
    assert pending_file.exists()
    payload = json.loads(pending_file.read_text(encoding="utf-8"))
    assert payload["validator_round_id"] == "validator_round_1_5_finish"
    assert ctx.iwap_client.finish_round.await_count == 2
    ctx._reset_iwap_round_state.assert_called_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_replays_pending_finish_before_registering_new_round(tmp_path):
    pending_dir = tmp_path / "state" / "pending_finish"
    pending_dir.mkdir(parents=True, exist_ok=True)
    pending_file = pending_dir / "validator_round_1_4_shadow.json"
    pending_file.write_text(
        json.dumps(
            {
                "validator_round_id": "validator_round_1_4_shadow",
                "finish_request": {
                    "status": "completed",
                    "ended_at": 1234.5,
                    "summary": {"winner_uid": 48},
                    "agent_runs": [],
                    "round_metadata": None,
                    "local_evaluation": {"miners": [{"miner_uid": 48}]},
                    "post_consensus_evaluation": None,
                    "validator_summary": {"round": {"season_number": 1, "round_number": 4}},
                    "ipfs_uploaded": None,
                    "ipfs_downloaded": None,
                    "s3_logs_url": None,
                    "validator_state": None,
                },
                "persisted_at": 1234.0,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    round_blocks = 1800
    round_number = 5
    start_block = int(validator_config.MINIMUM_START_BLOCK) + ((round_number - 1) * round_blocks)
    call_order: list[str] = []

    ctx = SimpleNamespace()
    ctx.current_round_id = "validator_round_1_5_test"
    ctx.uid = 55
    ctx.version = "20.0.0"
    ctx.round_start_timestamp = 1234567890.0
    ctx.active_miner_uids = {48}
    ctx.current_round_tasks = {"task-1": object()}
    ctx._iwap_offline_mode = False
    ctx._iwap_shadow_mode = False
    ctx._iwap_round_ready = False
    ctx._s3_task_log_urls = []
    ctx._reset_iwap_round_state = Mock()
    ctx._state_summary_root = Mock(return_value=tmp_path / "state")
    ctx.get_current_block = Mock(return_value=start_block)
    ctx.wallet = SimpleNamespace(
        hotkey=SimpleNamespace(ss58_address="5DLDdEfwnjGuHPnjZAE56mxWgSXp6CH54GgLFGSWDUGuJjst"),
        coldkeypub=SimpleNamespace(ss58_address="5FColdkeyValidator"),
    )
    ctx.metagraph = SimpleNamespace(
        hotkeys=["5Fdummy"] * 300,
        coldkeys=["5Cdummy"] * 300,
        S=[0.0] * 300,
        validator_trust=[0.0] * 300,
    )
    ctx.metagraph.S[55] = 1_500_000_000_000.0
    ctx.metagraph.validator_trust[55] = 1.0
    ctx.config = SimpleNamespace(neuron=SimpleNamespace(full_path=str(tmp_path / "validator")))
    Path(ctx.config.neuron.full_path).mkdir(parents=True, exist_ok=True)
    ctx.season_manager = SimpleNamespace(season_number=1, season_size_epochs=100.0)
    ctx.round_manager = SimpleNamespace(
        round_number=round_number,
        round_size_epochs=5.0,
        season_size_epochs=100.0,
        minimum_start_block=int(validator_config.MINIMUM_START_BLOCK),
        BLOCKS_PER_EPOCH=360,
        round_block_length=round_blocks,
        get_round_boundaries=Mock(
            return_value={
                "round_start_block": start_block,
                "target_block": start_block + round_blocks,
                "round_start_epoch": float(start_block) / 360.0,
                "target_epoch": float(start_block + round_blocks) / 360.0,
            }
        ),
    )

    async def _finish_round_replay(**kwargs):
        call_order.append("finish_round")
        return None

    async def _start_round_call(**kwargs):
        call_order.append("start_round")
        return {"validator_round_id": ctx.current_round_id}

    async def _set_tasks_call(**kwargs):
        call_order.append("set_tasks")
        return None

    ctx.iwap_client = SimpleNamespace(
        auth_check=AsyncMock(return_value=None),
        sync_runtime_config=AsyncMock(return_value={"updated": False}),
        finish_round=AsyncMock(side_effect=_finish_round_replay),
        start_round=AsyncMock(side_effect=_start_round_call),
        set_tasks=AsyncMock(side_effect=_set_tasks_call),
    )

    await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert call_order[:3] == ["finish_round", "start_round", "set_tasks"]
    assert not pending_file.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_replays_multiple_pending_finishes_and_keeps_grace_blocked_file(tmp_path):
    pending_dir = tmp_path / "state" / "pending_finish"
    pending_dir.mkdir(parents=True, exist_ok=True)
    blocked_file = pending_dir / "validator_round_1_3_blocked.json"
    success_file = pending_dir / "validator_round_1_4_success.json"

    blocked_file.write_text(
        json.dumps(
            {
                "validator_round_id": "validator_round_1_3_blocked",
                "finish_request": {"status": "completed", "summary": {"winner_uid": 48}},
                "persisted_at": 1000.0,
            }
        ),
        encoding="utf-8",
    )
    success_file.write_text(
        json.dumps(
            {
                "validator_round_id": "validator_round_1_4_success",
                "finish_request": {"status": "completed", "summary": {"winner_uid": 48}},
                "persisted_at": 1001.0,
            }
        ),
        encoding="utf-8",
    )

    round_blocks = 1800
    round_number = 5
    start_block = int(validator_config.MINIMUM_START_BLOCK) + ((round_number - 1) * round_blocks)
    flushed_ids: list[str] = []

    ctx = _make_finish_ctx(tmp_path)
    ctx.current_round_id = "validator_round_1_5_test"
    ctx.round_manager.round_number = round_number
    ctx.round_manager.round_block_length = round_blocks
    ctx.get_current_block = Mock(return_value=start_block)
    ctx.round_manager.get_round_boundaries = Mock(
        return_value={
            "round_start_block": start_block,
            "target_block": start_block + round_blocks,
            "round_start_epoch": float(start_block) / 360.0,
            "target_epoch": float(start_block + round_blocks) / 360.0,
        }
    )
    ctx.current_round_tasks = {"task-1": object()}
    ctx.active_miner_uids = {48}
    ctx._state_summary_root = Mock(return_value=tmp_path / "state")

    async def _finish_round_replay(**kwargs):
        validator_round_id = kwargs["validator_round_id"]
        flushed_ids.append(validator_round_id)
        if validator_round_id == "validator_round_1_3_blocked":
            raise _http_error(409, "main validator still within finish grace")
        return None

    ctx.iwap_client = SimpleNamespace(
        auth_check=AsyncMock(return_value=None),
        sync_runtime_config=AsyncMock(return_value={"updated": False}),
        finish_round=AsyncMock(side_effect=_finish_round_replay),
        start_round=AsyncMock(return_value={"validator_round_id": ctx.current_round_id}),
        set_tasks=AsyncMock(return_value=None),
    )

    await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert flushed_ids[:2] == ["validator_round_1_3_blocked", "validator_round_1_4_success"]
    assert blocked_file.exists()
    assert not success_file.exists()
    ctx.iwap_client.start_round.assert_awaited_once()
    ctx.iwap_client.set_tasks.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_replays_invalid_pending_finish_payload_and_deletes_it(tmp_path):
    pending_dir = tmp_path / "state" / "pending_finish"
    pending_dir.mkdir(parents=True, exist_ok=True)
    invalid_file = pending_dir / "validator_round_invalid.json"
    invalid_file.write_text(
        json.dumps(
            {
                "validator_round_id": "",
                "finish_request": None,
                "persisted_at": 1002.0,
            }
        ),
        encoding="utf-8",
    )

    round_blocks = 1800
    round_number = 5
    start_block = int(validator_config.MINIMUM_START_BLOCK) + ((round_number - 1) * round_blocks)

    ctx = _make_finish_ctx(tmp_path)
    ctx.current_round_id = "validator_round_1_5_test"
    ctx.round_manager.round_number = round_number
    ctx.round_manager.round_block_length = round_blocks
    ctx.get_current_block = Mock(return_value=start_block)
    ctx.round_manager.get_round_boundaries = Mock(
        return_value={
            "round_start_block": start_block,
            "target_block": start_block + round_blocks,
            "round_start_epoch": float(start_block) / 360.0,
            "target_epoch": float(start_block + round_blocks) / 360.0,
        }
    )
    ctx.current_round_tasks = {"task-1": object()}
    ctx.active_miner_uids = {48}
    ctx._state_summary_root = Mock(return_value=tmp_path / "state")
    ctx.iwap_client = SimpleNamespace(
        auth_check=AsyncMock(return_value=None),
        sync_runtime_config=AsyncMock(return_value={"updated": False}),
        finish_round=AsyncMock(return_value=None),
        start_round=AsyncMock(return_value={"validator_round_id": ctx.current_round_id}),
        set_tasks=AsyncMock(return_value=None),
    )

    await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert not invalid_file.exists()
    ctx.iwap_client.finish_round.assert_not_called()
    ctx.iwap_client.start_round.assert_awaited_once()
    ctx.iwap_client.set_tasks.assert_awaited_once()
