"""
Unit tests for ValidatorSettlementMixin.

Tests settlement phase, consensus, and weight finalization.
"""

import pytest
import numpy as np
from unittest.mock import Mock, AsyncMock, patch
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase


@pytest.mark.unit
@pytest.mark.asyncio
class TestSettlementPhase:
    """Test settlement phase logic."""

    async def test_run_settlement_phase_publishes_snapshot(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that settlement phase publishes round snapshot."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator._wait_until_specific_block = AsyncMock()
        dummy_validator._calculate_final_weights = AsyncMock()

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot") as mock_publish:
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments") as mock_aggregate:
                mock_aggregate.return_value = ({}, None)

                await dummy_validator._run_settlement_phase(agents_evaluated=3)

                # Should have called publish_round_snapshot
                mock_publish.assert_called_once()

    async def test_settlement_waits_for_consensus_fetch_block(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that settlement waits until configured fetch fraction block is reached."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator._wait_until_specific_block = AsyncMock()
        dummy_validator._calculate_final_weights = AsyncMock()

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot"):
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments") as mock_aggregate:
                mock_aggregate.return_value = ({}, None)

                with patch(
                    "autoppia_web_agents_subnet.validator.config.FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION",
                    0.80,
                ):
                    await dummy_validator._run_settlement_phase(agents_evaluated=3)

                assert dummy_validator._wait_until_specific_block.call_count >= 1
                first_call = dummy_validator._wait_until_specific_block.call_args_list[0]
                expected_fetch_block = int(dummy_validator.round_manager.start_block + int(dummy_validator.round_manager.round_block_length * 0.80))
                assert first_call[1]["target_block"] == expected_fetch_block

    async def test_settlement_aggregates_scores_from_commitments(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that settlement aggregates scores from validator commitments."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator._wait_until_specific_block = AsyncMock()
        dummy_validator._calculate_final_weights = AsyncMock()

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot"):
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments") as mock_aggregate:
                mock_scores = {1: 0.8, 2: 0.6, 3: 0.9}
                mock_aggregate.return_value = (mock_scores, None)

                await dummy_validator._run_settlement_phase(agents_evaluated=3)

                # Should have called aggregate_scores_from_commitments
                mock_aggregate.assert_called_once()

    async def test_settlement_calls_calculate_final_weights(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that settlement calls _calculate_final_weights with aggregated scores."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator._wait_until_specific_block = AsyncMock()
        dummy_validator._calculate_final_weights = AsyncMock()

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot"):
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments") as mock_aggregate:
                mock_scores = {1: 0.8, 2: 0.6}
                mock_aggregate.return_value = (mock_scores, None)

                await dummy_validator._run_settlement_phase(agents_evaluated=2)

                # Should have called _calculate_final_weights with scores
                dummy_validator._calculate_final_weights.assert_called_once()
                call_args = dummy_validator._calculate_final_weights.call_args
                assert call_args[1]["scores"] == mock_scores

    async def test_settlement_enters_complete_phase(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that settlement enters COMPLETE phase after finalization."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator._wait_until_specific_block = AsyncMock()
        dummy_validator._calculate_final_weights = AsyncMock()

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot"):
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments") as mock_aggregate:
                mock_aggregate.return_value = ({}, None)

                await dummy_validator._run_settlement_phase(agents_evaluated=0)

                # Should be in COMPLETE phase
                assert dummy_validator.round_manager.current_phase == RoundPhase.COMPLETE


@pytest.mark.unit
@pytest.mark.asyncio
class TestConsensusPublishing:
    """Test consensus snapshot publishing."""

    async def test_publish_round_snapshot_uploads_to_ipfs(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that publish_round_snapshot is called with correct scores."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator._wait_until_specific_block = AsyncMock()
        dummy_validator._calculate_final_weights = AsyncMock()

        # Add agents with scores
        from autoppia_web_agents_subnet.validator.models import AgentInfo

        dummy_validator.agents_dict = {
            1: AgentInfo(uid=1, agent_name="agent1", github_url="https://test.com", score=0.8),
            2: AgentInfo(uid=2, agent_name="agent2", github_url="https://test.com", score=0.6),
        }

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot") as mock_publish:
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments") as mock_aggregate:
                mock_aggregate.return_value = ({}, None)

                await dummy_validator._run_settlement_phase(agents_evaluated=2)

                # Should have called publish with scores
                mock_publish.assert_called_once()
                call_args = mock_publish.call_args
                scores = call_args[1]["scores"]
                assert "1" in scores
                assert "2" in scores
                assert scores["1"] == 0.8
                assert scores["2"] == 0.6


@pytest.mark.unit
@pytest.mark.asyncio
class TestWeightCalculation:
    """Test weight calculation logic."""

    async def test_calculate_final_weights_with_valid_scores(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that _calculate_final_weights processes valid scores."""
        scores = {1: 0.8, 2: 0.6, 3: 0.9}

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.wta_rewards") as mock_wta:
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"):
                # Mock WTA to return winner-takes-all rewards
                mock_rewards = np.zeros(10, dtype=np.float32)
                mock_rewards[3] = 1.0  # UID 3 wins
                mock_wta.return_value = mock_rewards

                await dummy_validator._calculate_final_weights(scores=scores)

                # Should have called update_scores and set_weights
                dummy_validator.update_scores.assert_called_once()
                dummy_validator.set_weights.assert_called_once()

    async def test_weight_calculation_applies_wta_rewards(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that weight calculation applies winner-takes-all rewards."""
        scores = {1: 0.5, 2: 0.8, 3: 0.3}

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.wta_rewards") as mock_wta:
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"):
                mock_rewards = np.zeros(10, dtype=np.float32)
                mock_rewards[2] = 1.0  # UID 2 wins (highest score)
                mock_wta.return_value = mock_rewards

                await dummy_validator._calculate_final_weights(scores=scores)

                # Should have called wta_rewards
                mock_wta.assert_called_once()

    async def test_weight_calculation_applies_winner_bonus(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that weight calculation applies previous winner bonus."""
        scores = {1: 0.8, 2: 0.6}
        dummy_validator._last_round_winner_uid = 1  # UID 1 won last round

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.wta_rewards") as mock_wta:
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"):
                with patch("autoppia_web_agents_subnet.validator.config.LAST_WINNER_BONUS_PCT", 0.1):
                    mock_wta.return_value = np.zeros(10, dtype=np.float32)

                    await dummy_validator._calculate_final_weights(scores=scores)

                    # Should have applied bonus to UID 1
                    call_args = mock_wta.call_args[0][0]
                    # UID 1 should have bonus applied (0.8 * 1.1 = 0.88)
                    assert call_args[1] > 0.8

    async def test_weight_calculation_calls_update_scores_and_set_weights(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that weight calculation calls update_scores and set_weights."""
        scores = {1: 0.8}

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.wta_rewards") as mock_wta:
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"):
                mock_wta.return_value = np.zeros(10, dtype=np.float32)

                await dummy_validator._calculate_final_weights(scores=scores)

                # Should have called both methods
                dummy_validator.update_scores.assert_called_once()
                dummy_validator.set_weights.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
class TestBurnLogic:
    """Test burn logic for edge cases."""

    async def test_calculate_final_weights_burns_when_no_scores(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that _calculate_final_weights burns when no valid scores."""
        scores = {}  # No scores
        dummy_validator._burn_all = AsyncMock()

        await dummy_validator._calculate_final_weights(scores=scores)

        # Should have called _burn_all
        dummy_validator._burn_all.assert_called_once()

    async def test_burn_all_when_burn_amount_percentage_is_one(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that weights are burned when BURN_AMOUNT_PERCENTAGE=1."""
        scores = {1: 0.8}

        with patch("autoppia_web_agents_subnet.validator.config.BURN_AMOUNT_PERCENTAGE", 1.0):
            await dummy_validator._calculate_final_weights(scores=scores)

            # Should have called update_scores (which happens in _burn_all)
            dummy_validator.update_scores.assert_called_once()
            # Should have called set_weights
            dummy_validator.set_weights.assert_called_once()

    async def test_burn_sets_weight_to_burn_uid(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that _burn_all sets weight to BURN_UID."""
        with patch("autoppia_web_agents_subnet.validator.config.BURN_UID", 5):
            await dummy_validator._burn_all(reason="test burn")

            # Should have called update_scores with burn weights
            dummy_validator.update_scores.assert_called_once()
            call_args = dummy_validator.update_scores.call_args
            rewards = call_args[1]["rewards"]

            # Only BURN_UID should have weight
            assert rewards[5] == 1.0
            assert np.sum(rewards) == 1.0

    async def test_burn_handles_custom_weights_array(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that _burn_all can accept custom weights array."""
        custom_weights = np.array([0.0, 0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)

        await dummy_validator._burn_all(reason="custom burn", weights=custom_weights)

        # Should have used custom weights
        dummy_validator.update_scores.assert_called_once()
        call_args = dummy_validator.update_scores.call_args
        rewards = call_args[1]["rewards"]

        assert rewards[1] == 0.5
        assert rewards[2] == 0.5


@pytest.mark.unit
@pytest.mark.asyncio
class TestWaitLogic:
    """Test wait logic for specific blocks."""

    async def test_wait_until_specific_block_waits_correctly(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin_with_wait

        dummy_validator = _bind_settlement_mixin_with_wait(dummy_validator)

        """Test that _wait_until_specific_block waits until target is reached."""
        dummy_validator.block = 1000
        dummy_validator.subtensor.get_current_block = Mock(side_effect=[1000, 1010, 1020, 1030])

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await dummy_validator._wait_until_specific_block(target_block=1030, target_description="test block")

            # Should have waited (called sleep multiple times)
            assert mock_sleep.call_count >= 2

    async def test_wait_returns_immediately_when_already_past_target(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin_with_wait

        dummy_validator = _bind_settlement_mixin_with_wait(dummy_validator)

        """Test that wait returns immediately when already past target block."""
        dummy_validator.block = 1500

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await dummy_validator._wait_until_specific_block(target_block=1000, target_description="test block")

            # Should not have waited
            mock_sleep.assert_not_called()

    async def test_wait_logs_progress_periodically(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin_with_wait

        dummy_validator = _bind_settlement_mixin_with_wait(dummy_validator)

        """Test that wait logs progress during waiting."""
        dummy_validator.block = 1000
        dummy_validator.subtensor.get_current_block = Mock(side_effect=[1000, 1010, 1020])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("time.time", side_effect=[0, 13, 26, 39]):  # Simulate time passing
                await dummy_validator._wait_until_specific_block(target_block=1020, target_description="test block")

                # Should have entered WAITING phase
                assert RoundPhase.WAITING in [t.phase for t in dummy_validator.round_manager.phase_history]


@pytest.mark.unit
@pytest.mark.asyncio
class TestSettlementEdgeCases:
    """Test edge cases in settlement logic."""

    async def test_settlement_handles_empty_agents_dict(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test settlement handles empty agents_dict gracefully."""
        dummy_validator.agents_dict = {}
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator._wait_until_specific_block = AsyncMock()
        dummy_validator._calculate_final_weights = AsyncMock()

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot"):
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments") as mock_aggregate:
                mock_aggregate.return_value = ({}, None)

                # Should not raise exception
                await dummy_validator._run_settlement_phase(agents_evaluated=0)

    async def test_calculate_final_weights_with_zero_scores(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test weight calculation with all zero scores."""
        scores = {1: 0.0, 2: 0.0, 3: 0.0}
        dummy_validator._burn_all = AsyncMock()

        await dummy_validator._calculate_final_weights(scores=scores)

        # Should burn when all scores are zero
        dummy_validator._burn_all.assert_called_once()

    async def test_calculate_final_weights_with_negative_scores(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test weight calculation filters out negative scores."""
        scores = {1: 0.8, 2: -0.5, 3: 0.6}  # UID 2 has negative score

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.wta_rewards") as mock_wta:
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"):
                mock_wta.return_value = np.zeros(10, dtype=np.float32)

                await dummy_validator._calculate_final_weights(scores=scores)

                # Should have filtered out negative score
                call_args = mock_wta.call_args[0][0]
                assert call_args[2] == 0.0  # Negative score should be filtered
