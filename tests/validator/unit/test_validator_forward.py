from unittest.mock import AsyncMock

import pytest

from autoppia_web_agents_subnet.validator.round_start.types import RoundStartResult
from neurons.validator import Validator


@pytest.mark.unit
@pytest.mark.asyncio
async def test_forward_uploads_round_log_checkpoint_when_evaluation_raises(dummy_validator):
    """
    Scenario:
    The validator has already opened the round in IWAP and registered miners, but
    evaluation crashes before settlement.

    What this test proves:
    the forward loop forces a round-log upload checkpoint before re-raising, so
    IWAP/S3 still gets the latest log context instead of silently losing the round.
    """
    validator = dummy_validator
    validator.forward = Validator.forward.__get__(validator, type(validator))
    validator._wait_for_minimum_start_block = AsyncMock(return_value=False)
    validator._start_round = AsyncMock(return_value=RoundStartResult(continue_forward=True))
    validator._perform_handshake = AsyncMock(return_value=None)
    validator._iwap_start_round = AsyncMock(return_value=None)
    validator._iwap_register_miners = AsyncMock(return_value=None)
    validator._run_evaluation_phase = AsyncMock(side_effect=RuntimeError("evaluation exploded"))
    validator._run_settlement_phase = AsyncMock(return_value=None)
    validator._try_upload_round_log_checkpoint = AsyncMock(return_value="https://logs.example/round.log")
    validator.round_manager.get_round_tasks = AsyncMock(return_value=[])
    validator.current_round_id = "validator_round_1_1_test"
    validator.block = 1000

    with pytest.raises(RuntimeError, match="evaluation exploded"):
        await validator.forward()

    reasons = [call.kwargs["reason"] for call in validator._try_upload_round_log_checkpoint.await_args_list]
    assert "forward_round_started" in reasons
    assert "forward_miners_registered" in reasons
    assert reasons[-1] == "forward_exception:RuntimeError"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_forward_uploads_round_log_checkpoint_when_settlement_raises(dummy_validator):
    """
    Scenario:
    Evaluation completed, but settlement crashes before finish_round can run.

    What this test proves:
    the validator still forces a final checkpoint upload on the exception path,
    which is the critical observability gap we saw in prod.
    """
    validator = dummy_validator
    validator.forward = Validator.forward.__get__(validator, type(validator))
    validator._wait_for_minimum_start_block = AsyncMock(return_value=False)
    validator._start_round = AsyncMock(return_value=RoundStartResult(continue_forward=True))
    validator._perform_handshake = AsyncMock(return_value=None)
    validator._iwap_start_round = AsyncMock(return_value=None)
    validator._iwap_register_miners = AsyncMock(return_value=None)
    validator._run_evaluation_phase = AsyncMock(return_value=4)
    validator._run_settlement_phase = AsyncMock(side_effect=RuntimeError("settlement exploded"))
    validator._try_upload_round_log_checkpoint = AsyncMock(return_value="https://logs.example/round.log")
    validator.round_manager.get_round_tasks = AsyncMock(return_value=[])
    validator.current_round_id = "validator_round_1_1_test"
    validator.block = 1000

    with pytest.raises(RuntimeError, match="settlement exploded"):
        await validator.forward()

    reasons = [call.kwargs["reason"] for call in validator._try_upload_round_log_checkpoint.await_args_list]
    assert reasons[-1] == "forward_exception:RuntimeError"
