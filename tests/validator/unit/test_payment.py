"""
Unit tests for payment-per-eval: allowed_evaluations_from_paid_rao and get_paid_alpha_per_coldkey_async.

How to verify the implementation is correct:
  1. Unit tests (this file): run `pytest tests/validator/unit/test_payment.py -v`
     - allowed_evaluations_from_paid_rao: rao/alpha math and edge cases
     - get_paid_alpha_per_coldkey_async: empty/invalid args return {}; mock scanner aggregates by coldkey
  2. Gating off (default): ENABLE_PAYMENT_GATING=false or unset → no payment logic; handshake unchanged
  3. Gating on, no metahash: set ENABLE_PAYMENT_GATING=true, PAYMENT_WALLET_SS58=<addr>; without metahash
     installed, get_paid_alpha_per_coldkey_async returns {} → all candidates get 0 allowed evals → all
     filtered out (payment_skip = N). Check logs for "[payment] AlphaTransfersScanner not available"
  4. Gating on, with metahash: install metahash, point PAYMENT_WALLET_SS58 at sn36 payments wallet;
     run validator, confirm only miners whose coldkey has paid >= ALPHA_PER_EVAL appear in handshake
  5. Chain check (manual): on testnet, send α to the payments wallet from a coldkey, run scanner for
     that block range, confirm coldkey appears in aggregated paid with correct amount_rao
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

    async def test_aggregates_events_by_src_coldkey_when_scanner_available(self):
        """With scanner mocked, paid amounts are summed per coldkey."""
        from unittest.mock import AsyncMock, MagicMock, patch

        ten_alpha_rao = 10 * RAO_PER_ALPHA
        fake_events = [
            MagicMock(src_coldkey="5Alice", amount_rao=ten_alpha_rao),
            MagicMock(src_coldkey="5Bob", amount_rao=ten_alpha_rao),
            MagicMock(src_coldkey="5Alice", amount_rao=5 * RAO_PER_ALPHA),
        ]
        mock_scanner = MagicMock()
        mock_scanner.scan = AsyncMock(return_value=fake_events)
        MockScannerClass = MagicMock(return_value=mock_scanner)

        with patch.dict(
            "sys.modules",
            {
                "metahash": MagicMock(),
                "metahash.validator": MagicMock(),
                "metahash.validator.alpha_transfers": MagicMock(AlphaTransfersScanner=MockScannerClass),
            },
        ):
            result = await get_paid_alpha_per_coldkey_async(
                subtensor=MagicMock(),
                from_block=1,
                to_block=100,
                dest_coldkey="5Treasury",
                target_subnet_id=36,
            )
        assert result["5Alice"] == 15 * RAO_PER_ALPHA
        assert result["5Bob"] == ten_alpha_rao
        assert allowed_evaluations_from_paid_rao(result["5Alice"], 10.0) == 1
        assert allowed_evaluations_from_paid_rao(result["5Bob"], 10.0) == 1
