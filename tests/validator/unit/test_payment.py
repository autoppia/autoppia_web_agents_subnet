"""
Unit tests for payment module: AlphaScanner (scanner.py), helpers (helpers.py),
get_alpha_sent_by_miner, get_paid_alpha_per_coldkey_async.
Tests focus on functionality only — no validator handshake behavior.
"""

import random
import string

import pytest

from autoppia_web_agents_subnet.validator.payment import (
    RAO_PER_ALPHA,
    AlphaScanner,
    allowed_evaluations_from_paid_rao,
    get_alpha_sent_by_miner,
    get_paid_alpha_per_coldkey_async,
)


def _random_ss58_like(prefix: str = "5", length: int = 44) -> str:
    """Return a random string resembling an SS58 address for parameterized tests."""
    chars = string.ascii_letters + string.digits
    return prefix + "".join(random.choices(chars, k=min(length - 1, 43)))


@pytest.mark.unit
class TestAllowedEvaluationsFromPaidRao:
    """Test allowed_evaluations_from_paid_rao helper."""

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
class TestAlphaScanner:
    """Test AlphaScanner.scan contract and block range / netuid."""

    async def test_scan_empty_payment_address_returns_zero(self):
        scanner = AlphaScanner(subtensor=object())
        out = await scanner.scan("", "5Coldkey", netuid=36, from_block=1, to_block=100)
        assert out == 0

    async def test_scan_empty_coldkey_returns_zero(self):
        scanner = AlphaScanner(subtensor=object())
        out = await scanner.scan("5Payment", "", netuid=36, from_block=1, to_block=100)
        assert out == 0

    async def test_scan_explicit_block_range_returns_sum_for_coldkey(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        payment_addr = _random_ss58_like("5Pay")
        coldkey_addr = _random_ss58_like("5Ck")
        netuid = 36
        from_b, to_b = 100, 200
        ten_rao = 10 * RAO_PER_ALPHA
        fake_events = [
            MagicMock(src_coldkey=coldkey_addr, amount_rao=ten_rao),
            MagicMock(src_coldkey=coldkey_addr, amount_rao=5 * RAO_PER_ALPHA),
            MagicMock(src_coldkey="5Other", amount_rao=ten_rao),
        ]
        mock_backend = MagicMock()
        mock_backend.scan = AsyncMock(return_value=fake_events)
        MockClass = MagicMock(return_value=mock_backend)
        with patch.dict(
            "sys.modules",
            {
                "metahash": MagicMock(),
                "metahash.validator": MagicMock(),
                "metahash.validator.alpha_transfers": MagicMock(AlphaTransfersScanner=MockClass),
            },
        ):
            scanner = AlphaScanner(subtensor=MagicMock())
            result = await scanner.scan(payment_addr, coldkey_addr, netuid=netuid, from_block=from_b, to_block=to_b)
        assert result == 15 * RAO_PER_ALPHA

    async def test_scan_netuid_custom_completes(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        payment_addr = _random_ss58_like("5P")
        coldkey_addr = _random_ss58_like("5C")
        with patch.dict(
            "sys.modules",
            {
                "metahash": MagicMock(),
                "metahash.validator": MagicMock(),
                "metahash.validator.alpha_transfers": MagicMock(
                    AlphaTransfersScanner=MagicMock(return_value=MagicMock(scan=AsyncMock(return_value=[])))
                ),
            },
        ):
            scanner = AlphaScanner(subtensor=MagicMock())
            result = await scanner.scan(payment_addr, coldkey_addr, netuid=73, from_block=1, to_block=50)
        assert result == 0

    @pytest.mark.parametrize("netuid", [36, 73, 1])
    async def test_scan_netuid_param_coverage(self, netuid):
        from unittest.mock import AsyncMock, MagicMock, patch

        pay = _random_ss58_like()
        ck = _random_ss58_like()
        with patch.dict(
            "sys.modules",
            {
                "metahash": MagicMock(),
                "metahash.validator": MagicMock(),
                "metahash.validator.alpha_transfers": MagicMock(
                    AlphaTransfersScanner=MagicMock(return_value=MagicMock(scan=AsyncMock(return_value=[])))
                ),
            },
        ):
            scanner = AlphaScanner(subtensor=MagicMock())
            result = await scanner.scan(pay, ck, netuid=netuid, from_block=10, to_block=20)
        assert result == 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetAlphaSentByMiner:
    """Test get_alpha_sent_by_miner service with randomized wallet/coldkey."""

    async def test_returns_zero_when_subtensor_none(self):
        result = await get_alpha_sent_by_miner(_random_ss58_like(), subtensor=None)
        assert result == 0

    async def test_returns_zero_when_payment_address_and_config_empty(self):
        from unittest.mock import patch

        with patch("autoppia_web_agents_subnet.validator.payment.helpers.PAYMENT_WALLET_SS58", ""):
            result = await get_alpha_sent_by_miner("5SomeColdkey", payment_address="", subtensor=object())
        assert result == 0

    async def test_uses_scanner_and_returns_result_with_randomized_args(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        pay = _random_ss58_like("5Pay")
        ck = _random_ss58_like("5Ck")
        with patch.object(AlphaScanner, "scan", new_callable=AsyncMock, return_value=7 * RAO_PER_ALPHA):
            result = await get_alpha_sent_by_miner(
                ck, payment_address=pay, netuid=36, from_block=1, to_block=100, subtensor=MagicMock()
            )
        assert result == 7 * RAO_PER_ALPHA

    @pytest.mark.parametrize("from_b,to_b", [(None, 500), (100, 200), (1, 100)])
    async def test_block_range_optional_coverage(self, from_b, to_b):
        from unittest.mock import AsyncMock, MagicMock, patch

        st = MagicMock()
        mock_scan = AsyncMock(return_value=0)
        with patch.object(AlphaScanner, "scan", mock_scan):
            result = await get_alpha_sent_by_miner(
                _random_ss58_like(), payment_address=_random_ss58_like(), from_block=from_b, to_block=to_b, subtensor=st
            )
        assert result == 0
        assert mock_scan.called


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetPaidAlphaPerColdkeyAsync:
    """Test get_paid_alpha_per_coldkey_async boundary conditions."""

    async def test_from_block_gt_to_block_returns_empty(self):
        result = await get_paid_alpha_per_coldkey_async(
            subtensor=object(), from_block=100, to_block=50, dest_coldkey="5SomeWallet", target_subnet_id=36
        )
        assert result == {}

    async def test_empty_dest_coldkey_returns_empty(self):
        result = await get_paid_alpha_per_coldkey_async(
            subtensor=object(), from_block=1, to_block=100, dest_coldkey="", target_subnet_id=36
        )
        assert result == {}

    async def test_whitespace_dest_coldkey_returns_empty(self):
        result = await get_paid_alpha_per_coldkey_async(
            subtensor=object(), from_block=1, to_block=100, dest_coldkey="   ", target_subnet_id=36
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
                subtensor=MagicMock(), from_block=1, to_block=100, dest_coldkey="5Treasury", target_subnet_id=36
            )
        assert result["5Alice"] == 15 * RAO_PER_ALPHA
        assert result["5Bob"] == ten_alpha_rao
        assert allowed_evaluations_from_paid_rao(result["5Alice"], 10.0) == 1
        assert allowed_evaluations_from_paid_rao(result["5Bob"], 10.0) == 1
