"""
Unit tests for payment module: AlphaScanner (scanner.py), helpers (helpers.py),
get_alpha_sent_by_miner, get_paid_alpha_per_coldkey_async.
Tests focus on functionality only — no validator handshake behavior.
"""

import random
import string
import json

import pytest

from autoppia_web_agents_subnet.validator.payment import (
    RAO_PER_ALPHA,
    AlphaScanner,
    allowed_evaluations_from_paid_rao,
    get_coldkey_balance,
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

    async def test_scan_returns_correct_alpha_as_rao(self):
        """Scanner returns total amount_rao; rao / RAO_PER_ALPHA equals expected alpha."""
        from unittest.mock import AsyncMock, MagicMock, patch

        payment_addr = _random_ss58_like("5Pay")
        coldkey_addr = _random_ss58_like("5Ck")
        # 10 α + 5 α = 15 α total
        events = [
            MagicMock(src_coldkey=coldkey_addr, amount_rao=10 * RAO_PER_ALPHA),
            MagicMock(src_coldkey=coldkey_addr, amount_rao=5 * RAO_PER_ALPHA),
        ]
        mock_backend = MagicMock()
        mock_backend.scan = AsyncMock(return_value=events)
        with patch.dict(
            "sys.modules",
            {
                "metahash": MagicMock(),
                "metahash.validator": MagicMock(),
                "metahash.validator.alpha_transfers": MagicMock(
                    AlphaTransfersScanner=MagicMock(return_value=mock_backend)
                ),
            },
        ):
            scanner = AlphaScanner(subtensor=MagicMock())
            paid_rao = await scanner.scan(
                payment_addr, coldkey_addr, netuid=36, from_block=1, to_block=100
            )
        expected_alpha = 15.0
        assert paid_rao == int(expected_alpha * RAO_PER_ALPHA)
        assert paid_rao / RAO_PER_ALPHA == expected_alpha
        assert allowed_evaluations_from_paid_rao(paid_rao, 10.0) == 1
        assert allowed_evaluations_from_paid_rao(paid_rao, 5.0) == 3

    async def test_scan_aggregates_across_multiple_chunks(self):
        """When backend.scan is called multiple times (chunked blocks), returned rao is sum of all events."""
        from unittest.mock import AsyncMock, MagicMock, patch

        payment_addr = _random_ss58_like("5Pay")
        coldkey_addr = _random_ss58_like("5Ck")
        chunk1_events = [
            MagicMock(src_coldkey=coldkey_addr, amount_rao=10 * RAO_PER_ALPHA),
        ]
        chunk2_events = [
            MagicMock(src_coldkey=coldkey_addr, amount_rao=5 * RAO_PER_ALPHA),
        ]
        mock_backend = MagicMock()
        mock_backend.scan = AsyncMock(side_effect=[chunk1_events, chunk2_events])
        with patch.dict(
            "sys.modules",
            {
                "metahash": MagicMock(),
                "metahash.validator": MagicMock(),
                "metahash.validator.alpha_transfers": MagicMock(
                    AlphaTransfersScanner=MagicMock(return_value=mock_backend)
                ),
            },
        ):
            scanner = AlphaScanner(subtensor=MagicMock())
            paid_rao = await scanner.scan(
                payment_addr, coldkey_addr, netuid=36, from_block=1, to_block=600
            )
        assert paid_rao == 15 * RAO_PER_ALPHA
        assert paid_rao / RAO_PER_ALPHA == 15.0

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

    async def test_scan_fallback_when_target_subnet_id_not_supported(self):
        """When metahash AlphaTransfersScanner does not accept target_subnet_id, we init without it and filter by subnet_id."""
        from unittest.mock import AsyncMock, MagicMock, patch

        payment_addr = _random_ss58_like("5Pay")
        coldkey_addr = _random_ss58_like("5Ck")
        netuid = 36
        from_b, to_b = 1, 100
        ten_rao = 10 * RAO_PER_ALPHA
        # Events: one for our subnet, one for other subnet; only our subnet should be counted
        fake_events = [
            MagicMock(src_coldkey=coldkey_addr, amount_rao=ten_rao, subnet_id=36),
            MagicMock(src_coldkey=coldkey_addr, amount_rao=5 * RAO_PER_ALPHA, subnet_id=73),
        ]
        mock_backend = MagicMock()
        mock_backend.scan = AsyncMock(return_value=fake_events)

        def scanner_side_effect(*args, **kwargs):
            if "target_subnet_id" in kwargs:
                raise TypeError("unexpected keyword argument 'target_subnet_id'")
            return mock_backend

        MockClass = MagicMock(side_effect=scanner_side_effect)
        with patch.dict(
            "sys.modules",
            {
                "metahash": MagicMock(),
                "metahash.validator": MagicMock(),
                "metahash.validator.alpha_transfers": MagicMock(AlphaTransfersScanner=MockClass),
            },
        ):
            scanner = AlphaScanner(subtensor=MagicMock())
            result = await scanner.scan(
                payment_addr, coldkey_addr, netuid=netuid, from_block=from_b, to_block=to_b
            )
        assert result == ten_rao


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

    async def test_get_alpha_sent_by_miner_returned_rao_gives_correct_alpha_and_evals(self):
        """get_alpha_sent_by_miner returns rao that converts to correct alpha and allowed evals."""
        from unittest.mock import AsyncMock, MagicMock, patch

        pay = _random_ss58_like("5Pay")
        ck = _random_ss58_like("5Ck")
        paid_rao = 25 * RAO_PER_ALPHA
        with patch.object(AlphaScanner, "scan", new_callable=AsyncMock, return_value=paid_rao):
            result_rao = await get_alpha_sent_by_miner(
                ck, payment_address=pay, netuid=36, from_block=1, to_block=100, subtensor=MagicMock()
            )
        assert result_rao == paid_rao
        assert result_rao / RAO_PER_ALPHA == 25.0
        assert allowed_evaluations_from_paid_rao(result_rao, 10.0) == 2
        assert allowed_evaluations_from_paid_rao(result_rao, 5.0) == 5

    async def test_season_cache_backfills_then_only_scans_new_blocks(self, tmp_path):
        from unittest.mock import AsyncMock, MagicMock, patch

        cache_path = str(tmp_path / "payment_cache.json")
        coldkey = _random_ss58_like("5Ck")
        payment_address = _random_ss58_like("5Pay")
        subtensor = MagicMock()
        subtensor.get_current_block = AsyncMock(side_effect=[120, 130])
        scan_mock = AsyncMock(side_effect=[{coldkey: 3 * RAO_PER_ALPHA}, {coldkey: 2 * RAO_PER_ALPHA}])

        with patch(
            "autoppia_web_agents_subnet.validator.payment.helpers.get_paid_alpha_per_coldkey_async",
            scan_mock,
        ):
            first = await get_alpha_sent_by_miner(
                coldkey,
                payment_address=payment_address,
                netuid=36,
                subtensor=subtensor,
                season_start_block=100,
                season_duration_blocks=1000,
                cache_path=cache_path,
            )
            second = await get_alpha_sent_by_miner(
                coldkey,
                payment_address=payment_address,
                netuid=36,
                subtensor=subtensor,
                season_start_block=100,
                season_duration_blocks=1000,
                cache_path=cache_path,
            )

        assert first == 3 * RAO_PER_ALPHA
        assert second == 5 * RAO_PER_ALPHA
        assert scan_mock.await_count == 2

        first_kwargs = scan_mock.await_args_list[0].kwargs
        second_kwargs = scan_mock.await_args_list[1].kwargs
        assert first_kwargs["from_block"] == 100
        assert first_kwargs["to_block"] == 120
        assert second_kwargs["from_block"] == 121
        assert second_kwargs["to_block"] == 130

        with open(cache_path, "r", encoding="utf-8") as infile:
            cache = json.load(infile)
        assert isinstance(cache.get("entries"), dict)
        only_entry = next(iter(cache["entries"].values()))
        assert only_entry["last_processed_block"] == 130
        assert only_entry["totals_by_coldkey"][coldkey] == 5 * RAO_PER_ALPHA

    async def test_season_cache_no_new_blocks_does_not_rescan(self, tmp_path):
        from unittest.mock import AsyncMock, MagicMock, patch

        cache_path = str(tmp_path / "payment_cache.json")
        coldkey = _random_ss58_like("5Ck")
        payment_address = _random_ss58_like("5Pay")
        subtensor = MagicMock()
        subtensor.get_current_block = AsyncMock(side_effect=[220, 220])
        scan_mock = AsyncMock(return_value={coldkey: 7 * RAO_PER_ALPHA})

        with patch(
            "autoppia_web_agents_subnet.validator.payment.helpers.get_paid_alpha_per_coldkey_async",
            scan_mock,
        ):
            first = await get_alpha_sent_by_miner(
                coldkey,
                payment_address=payment_address,
                netuid=36,
                subtensor=subtensor,
                season_start_block=200,
                season_duration_blocks=500,
                cache_path=cache_path,
            )
            second = await get_alpha_sent_by_miner(
                coldkey,
                payment_address=payment_address,
                netuid=36,
                subtensor=subtensor,
                season_start_block=200,
                season_duration_blocks=500,
                cache_path=cache_path,
            )

        assert first == 7 * RAO_PER_ALPHA
        assert second == 7 * RAO_PER_ALPHA
        assert scan_mock.await_count == 1

    async def test_season_cache_respects_season_end(self, tmp_path):
        from unittest.mock import AsyncMock, MagicMock, patch

        cache_path = str(tmp_path / "payment_cache.json")
        coldkey = _random_ss58_like("5Ck")
        payment_address = _random_ss58_like("5Pay")
        subtensor = MagicMock()
        subtensor.get_current_block = AsyncMock(return_value=1200)
        scan_mock = AsyncMock(return_value={coldkey: RAO_PER_ALPHA})

        with patch(
            "autoppia_web_agents_subnet.validator.payment.helpers.get_paid_alpha_per_coldkey_async",
            scan_mock,
        ):
            result = await get_alpha_sent_by_miner(
                coldkey,
                payment_address=payment_address,
                netuid=36,
                subtensor=subtensor,
                season_start_block=1000,
                season_duration_blocks=100,
                cache_path=cache_path,
            )
        assert result == RAO_PER_ALPHA
        assert scan_mock.await_count == 1
        scan_kwargs = scan_mock.await_args_list[0].kwargs
        assert scan_kwargs["from_block"] == 1000
        assert scan_kwargs["to_block"] == 1099

    async def test_get_coldkey_balance_wrapper_uses_same_result(self, tmp_path):
        from unittest.mock import AsyncMock, MagicMock, patch

        cache_path = str(tmp_path / "payment_cache.json")
        coldkey = _random_ss58_like("5Ck")
        payment_address = _random_ss58_like("5Pay")
        subtensor = MagicMock()
        subtensor.get_current_block = AsyncMock(return_value=500)
        scan_mock = AsyncMock(return_value={coldkey: 11 * RAO_PER_ALPHA})

        with patch(
            "autoppia_web_agents_subnet.validator.payment.helpers.get_paid_alpha_per_coldkey_async",
            scan_mock,
        ):
            result = await get_coldkey_balance(
                coldkey,
                payment_address=payment_address,
                netuid=36,
                subtensor=subtensor,
                season_start_block=400,
                season_duration_blocks=200,
                cache_path=cache_path,
            )
        assert result == 11 * RAO_PER_ALPHA

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

    async def test_get_paid_returns_correct_alpha_per_coldkey_and_evals(self):
        """get_paid_alpha_per_coldkey_async returns rao that converts to correct alpha and evals per coldkey."""
        from unittest.mock import AsyncMock, MagicMock, patch

        alice_rao = 30 * RAO_PER_ALPHA
        bob_rao = 10 * RAO_PER_ALPHA
        fake_events = [
            MagicMock(src_coldkey="5Alice", amount_rao=alice_rao),
            MagicMock(src_coldkey="5Bob", amount_rao=bob_rao),
        ]
        mock_scanner = MagicMock()
        mock_scanner.scan = AsyncMock(return_value=fake_events)
        with patch.dict(
            "sys.modules",
            {
                "metahash": MagicMock(),
                "metahash.validator": MagicMock(),
                "metahash.validator.alpha_transfers": MagicMock(
                    AlphaTransfersScanner=MagicMock(return_value=mock_scanner)
                ),
            },
        ):
            result = await get_paid_alpha_per_coldkey_async(
                subtensor=MagicMock(), from_block=1, to_block=100, dest_coldkey="5Treasury", target_subnet_id=36
            )
        assert result["5Alice"] == alice_rao
        assert result["5Bob"] == bob_rao
        assert result["5Alice"] / RAO_PER_ALPHA == 30.0
        assert result["5Bob"] / RAO_PER_ALPHA == 10.0
        assert allowed_evaluations_from_paid_rao(result["5Alice"], 10.0) == 3
        assert allowed_evaluations_from_paid_rao(result["5Bob"], 10.0) == 1

    async def test_get_paid_fallback_filters_by_subnet_id_when_target_subnet_id_not_supported(self):
        """When AlphaTransfersScanner rejects target_subnet_id, we filter events by subnet_id."""
        from unittest.mock import AsyncMock, MagicMock, patch

        ten_alpha_rao = 10 * RAO_PER_ALPHA
        fake_events = [
            MagicMock(src_coldkey="5Alice", amount_rao=ten_alpha_rao, subnet_id=36),
            MagicMock(src_coldkey="5Bob", amount_rao=ten_alpha_rao, subnet_id=73),
        ]
        mock_scanner = MagicMock()
        mock_scanner.scan = AsyncMock(return_value=fake_events)

        def scanner_side_effect(*args, **kwargs):
            if "target_subnet_id" in kwargs:
                raise TypeError("unexpected keyword argument 'target_subnet_id'")
            return mock_scanner

        MockScannerClass = MagicMock(side_effect=scanner_side_effect)
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
        assert result["5Alice"] == ten_alpha_rao
        assert "5Bob" not in result
