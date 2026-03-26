from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from httpx import HTTPStatusError, Request, Response

os.environ.setdefault("TESTING", "True")
os.environ.setdefault("VALIDATOR_NAME", "Test Validator")
os.environ.setdefault("VALIDATOR_IMAGE", "https://example.com/validator.png")

from autoppia_web_agents_subnet.platform.utils.round_flow import start_round_flow
from autoppia_web_agents_subnet.validator import config as validator_config


def _http_error(status_code: int, detail):
    payload = detail if isinstance(detail, dict) and "detail" in detail else {"detail": detail}
    response = Response(status_code=status_code, json=payload, request=Request("POST", "https://iwap.test"))
    return HTTPStatusError(f"HTTP {status_code}", request=response.request, response=response)


def _make_start_ctx(tmp_path: Path, *, round_number: int = 1, current_block: int | None = None):
    round_blocks = 1800
    start_block = int(validator_config.MINIMUM_START_BLOCK) + ((round_number - 1) * round_blocks)
    if current_block is None:
        current_block = start_block

    ctx = SimpleNamespace()
    ctx.current_round_id = f"validator_round_1_{round_number}_test"
    ctx.uid = 83
    ctx.version = "20.0.0"
    ctx.round_start_timestamp = 1234567890.0
    ctx.active_miner_uids = {48, 127}
    ctx.current_round_tasks = {"task-1": object(), "task-2": object()}
    ctx._iwap_offline_mode = False
    ctx._iwap_shadow_mode = False
    ctx._iwap_round_ready = False
    ctx._s3_task_log_urls = []
    ctx._reset_iwap_round_state = Mock()
    ctx._state_summary_root = Mock(return_value=tmp_path / "state")
    ctx.get_current_block = Mock(return_value=int(current_block))
    ctx.wallet = SimpleNamespace(
        hotkey=SimpleNamespace(ss58_address="5DUmbxsTWuMxefEk36BYX8qNsF18BbUeTgBPuefBN6gSDe8j"),
        coldkeypub=SimpleNamespace(ss58_address="5FColdkeyValidator"),
    )
    ctx.metagraph = SimpleNamespace(
        hotkeys=["5Fdummy"] * 300,
        coldkeys=["5Cdummy"] * 300,
        S=[0.0] * 300,
        validator_trust=[0.0] * 300,
    )
    ctx.metagraph.S[83] = 1_500_000_000_000.0
    ctx.metagraph.validator_trust[83] = 1.0
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
    ctx.iwap_client = SimpleNamespace(
        auth_check=AsyncMock(return_value=None),
        sync_runtime_config=AsyncMock(return_value={"updated": True}),
        start_round=AsyncMock(return_value={"validator_round_id": ctx.current_round_id}),
        set_tasks=AsyncMock(return_value=None),
    )
    return ctx


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_main_success_marks_round_ready_and_sets_tasks(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=5)

    await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is False
    assert ctx._iwap_shadow_mode is False
    assert ctx._iwap_round_ready is True
    ctx.iwap_client.start_round.assert_awaited_once()
    ctx.iwap_client.set_tasks.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_main_authority_guard_enables_shadow_mode_without_offline(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=5)
    ctx.iwap_client.start_round = AsyncMock(
        side_effect=_http_error(
            409,
            "Only main validator can open a new season/round before fallback grace elapses (current_block=7747761, planned_start_block=7747761, grace_blocks=25)",
        )
    )

    with (
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_MAX_RETRIES", 0),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_RETRY_SECONDS", 1),
    ):
        await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is False
    assert ctx._iwap_shadow_mode is True
    assert ctx._iwap_round_ready is False
    ctx.iwap_client.set_tasks.assert_not_called()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_duplicate_is_treated_as_idempotent_and_continues(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=5)
    ctx.iwap_client.start_round = AsyncMock(side_effect=_http_error(409, "validator round already exists"))

    await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is False
    assert ctx._iwap_round_ready is True
    ctx.iwap_client.set_tasks.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_round_number_mismatch_forces_offline_mode(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=6)
    ctx.iwap_client.start_round = AsyncMock(
        side_effect=_http_error(
            400,
            {"detail": {"error": "round_number mismatch", "expectedRoundNumber": 7, "got": 6}},
        )
    )

    await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is True
    assert ctx._iwap_round_ready is False
    ctx.iwap_client.set_tasks.assert_not_called()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_window_not_active_keeps_validator_online_and_not_ready(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=7)
    ctx.iwap_client.start_round = AsyncMock(
        side_effect=_http_error(
            409,
            {
                "detail": {
                    "error": "round window not active",
                    "currentBlock": 7751361,
                    "startBlock": 7751361,
                    "endBlock": 7753161,
                }
            },
        )
    )

    with (
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_MAX_RETRIES", 0),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_RETRY_SECONDS", 1),
    ):
        await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is False
    assert ctx._iwap_shadow_mode is False
    assert ctx._iwap_round_ready is False
    ctx.iwap_client.set_tasks.assert_not_called()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_window_not_active_retries_until_main_window_is_open(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=7)
    not_ready_error = _http_error(
        409,
        {
            "detail": {
                "error": "round window not active",
                "currentBlock": 7751358,
                "startBlock": 7751361,
                "endBlock": 7753161,
            }
        },
    )
    ctx.iwap_client.start_round = AsyncMock(side_effect=[not_ready_error, {"validator_round_id": ctx.current_round_id}])

    with (
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_MAX_RETRIES", 2),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_RETRY_SECONDS", 1),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.asyncio.sleep", new=AsyncMock()),
    ):
        await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is False
    assert ctx._iwap_round_ready is True
    assert ctx.iwap_client.start_round.await_count == 2
    ctx.iwap_client.set_tasks.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_shadow_response_updates_round_id_and_continues_set_tasks(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=5)
    ctx.iwap_client.start_round = AsyncMock(
        return_value={
            "validator_round_id": "validator_round_1_5_shadow",
            "shadow_mode": True,
        }
    )

    await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx.current_round_id == "validator_round_1_5_shadow"
    assert ctx._iwap_shadow_mode is True
    assert ctx._iwap_round_ready is True
    assert ctx.iwap_client.set_tasks.await_args.kwargs["validator_round_id"] == "validator_round_1_5_shadow"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_set_tasks_duplicate_keeps_round_ready(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=5)
    ctx.iwap_client.set_tasks = AsyncMock(side_effect=_http_error(409, "duplicate key value violates unique constraint"))

    await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is False
    assert ctx._iwap_round_ready is True
    ctx.iwap_client.start_round.assert_awaited_once()
    ctx.iwap_client.set_tasks.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_generic_http_failure_forces_offline_mode(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=5)
    ctx.iwap_client.start_round = AsyncMock(side_effect=_http_error(500, "backend exploded"))

    await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is True
    assert ctx._iwap_shadow_mode is False
    assert ctx._iwap_round_ready is False
    ctx.iwap_client.set_tasks.assert_not_called()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_authority_guard_then_shadow_attach_response_marks_round_ready(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=5)
    authority_error = _http_error(
        409,
        "Only main validator can open a new season/round before fallback grace elapses (current_block=7747762, planned_start_block=7747761, grace_blocks=25)",
    )
    ctx.iwap_client.start_round = AsyncMock(
        side_effect=[
            authority_error,
            {
                "validator_round_id": "validator_round_1_5_shadow_attach",
                "shadow_mode": True,
                "attach_mode": "attached_to_main_round",
                "canonical_round_id": 501,
            },
        ]
    )

    with (
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_MAX_RETRIES", 2),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_RETRY_SECONDS", 1),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.asyncio.sleep", new=AsyncMock()),
    ):
        await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is False
    assert ctx._iwap_shadow_mode is True
    assert ctx._iwap_round_ready is True
    assert ctx.current_round_id == "validator_round_1_5_shadow_attach"
    assert ctx.iwap_client.start_round.await_count == 2
    ctx.iwap_client.set_tasks.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_authority_guard_then_duplicate_retry_continues_idempotently(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=5)
    authority_error = _http_error(
        409,
        "Only main validator can open a new season/round before fallback grace elapses (current_block=7747762, planned_start_block=7747761, grace_blocks=25)",
    )
    duplicate_error = _http_error(409, "validator round already exists")
    ctx.iwap_client.start_round = AsyncMock(side_effect=[authority_error, duplicate_error])

    with (
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_MAX_RETRIES", 2),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_RETRY_SECONDS", 1),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.asyncio.sleep", new=AsyncMock()),
    ):
        await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is False
    assert ctx._iwap_shadow_mode is False
    assert ctx._iwap_round_ready is True
    assert ctx.iwap_client.start_round.await_count == 2
    ctx.iwap_client.set_tasks.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_window_not_active_then_nonrecoverable_error_forces_offline_mode(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=7)
    not_ready_error = _http_error(
        409,
        {
            "detail": {
                "error": "round window not active",
                "currentBlock": 7751359,
                "startBlock": 7751361,
                "endBlock": 7753161,
            }
        },
    )
    generic_error = _http_error(500, "backend exploded")
    ctx.iwap_client.start_round = AsyncMock(side_effect=[not_ready_error, generic_error])

    with (
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_MAX_RETRIES", 2),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_RETRY_SECONDS", 1),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.asyncio.sleep", new=AsyncMock()),
    ):
        await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is True
    assert ctx._iwap_round_ready is False
    assert ctx.iwap_client.start_round.await_count == 2
    ctx.iwap_client.set_tasks.assert_not_called()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_set_tasks_generic_failure_keeps_validator_online_but_not_ready(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=5)
    ctx.iwap_client.set_tasks = AsyncMock(side_effect=_http_error(500, "set_tasks failed"))

    await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is False
    assert ctx._iwap_shadow_mode is False
    assert ctx._iwap_round_ready is False
    ctx.iwap_client.start_round.assert_awaited_once()
    ctx.iwap_client.set_tasks.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_backup_can_retry_after_main_opens_round(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=5)
    ctx.uid = 55
    ctx.wallet.hotkey.ss58_address = "5DLDdEfwnjGuHPnjZAE56mxWgSXp6CH54GgLFGSWDUGuJjst"
    authority_error = _http_error(
        409,
        "Only main validator can open a new season/round before fallback grace elapses (current_block=7747765, planned_start_block=7747761, grace_blocks=25)",
    )
    ctx.iwap_client.start_round = AsyncMock(side_effect=[authority_error, {"validator_round_id": ctx.current_round_id}])

    with (
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_MAX_RETRIES", 2),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_RETRY_SECONDS", 1),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.asyncio.sleep", new=AsyncMock()),
    ):
        await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is False
    assert ctx._iwap_round_ready is True
    assert ctx.iwap_client.start_round.await_count == 2
    ctx.iwap_client.set_tasks.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_backup_after_main_is_already_active_attaches_cleanly(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=5)
    ctx.uid = 55
    ctx.wallet.hotkey.ss58_address = "5DLDdEfwnjGuHPnjZAE56mxWgSXp6CH54GgLFGSWDUGuJjst"

    await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is False
    assert ctx._iwap_shadow_mode is False
    assert ctx._iwap_round_ready is True
    ctx.iwap_client.start_round.assert_awaited_once()
    ctx.iwap_client.set_tasks.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_round_backup_far_before_main_stays_not_ready_across_retries(tmp_path):
    ctx = _make_start_ctx(tmp_path, round_number=5)
    ctx.uid = 55
    ctx.wallet.hotkey.ss58_address = "5DLDdEfwnjGuHPnjZAE56mxWgSXp6CH54GgLFGSWDUGuJjst"
    authority_error = _http_error(
        409,
        "Only main validator can open a new season/round before fallback grace elapses (current_block=7747700, planned_start_block=7747761, grace_blocks=25)",
    )
    ctx.iwap_client.start_round = AsyncMock(side_effect=[authority_error, authority_error, authority_error])

    with (
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_MAX_RETRIES", 0),
        patch("autoppia_web_agents_subnet.platform.utils.round_flow.validator_config.START_ROUND_RETRY_SECONDS", 1),
    ):
        for _ in range(3):
            await start_round_flow(ctx, current_block=ctx.get_current_block(), n_tasks=100)

    assert ctx._iwap_offline_mode is False
    assert ctx._iwap_shadow_mode is True
    assert ctx._iwap_round_ready is False
    assert ctx.iwap_client.start_round.await_count == 3
    ctx.iwap_client.set_tasks.assert_not_called()
