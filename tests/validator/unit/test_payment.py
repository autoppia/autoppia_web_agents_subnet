"""
Unit tests for payment-per-eval: allowed_evaluations_from_paid_rao and get_paid_alpha_per_coldkey_async.
"""

import pytest

from autoppia_web_agents_subnet.validator.payment.paid_alpha import (
    RAO_PER_ALPHA,
    allowed_evaluations_from_paid_rao,
    get_paid_alpha_per_coldkey_async,
)


@pytest.mark.unit
class TestAllowedEvaluationsFromPaidRao:
    """Test allowed_evaluations_from_paid_rao."""

    def test_zero_paid_returns_zero(self):
        assert allowed_evaluations_from_paid_rao(0, 10.0) == 0

    def test_zero_alpha_per_eval_returns_zero(self):
        assert allowed_evaluations_from_paid_rao(10 * RAO_PER_ALPHA, 0.0) == 0

    def test_one_eval_exact(self):
        assert allowed_evaluations_from_paid_rao(10 * RAO_PER_ALPHA, 10.0) == 1

    def test_one_eval_under_pays_zero(self):
        assert allowed_evaluations_from_paid_rao(10 * RAO_PER_ALPHA - 1, 10.0) == 0

    def test_two_evals_exact(self):
        assert allowed_evaluations_from_paid_rao(20 * RAO_PER_ALPHA, 10.0) == 2

    def test_fractional_alpha_per_eval(self):
        assert allowed_evaluations_from_paid_rao(5 * RAO_PER_ALPHA, 5.0) == 1
        assert allowed_evaluations_from_paid_rao(15 * RAO_PER_ALPHA, 5.0) == 3

    def test_negative_paid_returns_zero(self):
        assert allowed_evaluations_from_paid_rao(-1, 10.0) == 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetPaidAlphaPerColdkeyAsync:
    """Test get_paid_alpha_per_coldkey_async boundary conditions."""

    async def test_from_block_gt_to_block_returns_empty(self):
        result = await get_paid_alpha_per_coldkey_async(
            subtensor=object(),
            from_block=100,
            to_block=50,
            dest_coldkey="5SomeWallet",
            target_subnet_id=36,
        )
        assert result == {}

    async def test_empty_dest_coldkey_returns_empty(self):
        result = await get_paid_alpha_per_coldkey_async(
            subtensor=object(),
            from_block=1,
            to_block=100,
            dest_coldkey="",
            target_subnet_id=36,
        )
        assert result == {}

    async def test_whitespace_dest_coldkey_returns_empty(self):
        result = await get_paid_alpha_per_coldkey_async(
            subtensor=object(),
            from_block=1,
            to_block=100,
            dest_coldkey="   ",
            target_subnet_id=36,
        )
        assert result == {}
