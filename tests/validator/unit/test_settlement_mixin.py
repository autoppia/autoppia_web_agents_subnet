"""
Unit tests for ValidatorSettlementMixin.

Tests settlement phase, consensus, and weight finalization.
"""

from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pytest

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

    async def test_settlement_disables_next_round_reuse_when_own_all_zero_payload_is_excluded(self, dummy_validator):
        from autoppia_web_agents_subnet.platform.mixin import ValidatorPlatformMixin
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)
        dummy_validator._extract_round_numbers_from_round_id = ValidatorPlatformMixin._extract_round_numbers_from_round_id
        dummy_validator._current_round_numbers = ValidatorPlatformMixin._current_round_numbers.__get__(dummy_validator, type(dummy_validator))
        dummy_validator._current_round_run_payload = ValidatorPlatformMixin._current_round_run_payload.__get__(dummy_validator, type(dummy_validator))
        dummy_validator._current_round_all_runs_zero = ValidatorPlatformMixin._current_round_all_runs_zero.__get__(dummy_validator, type(dummy_validator))
        dummy_validator._purge_evaluated_commits_for_round = ValidatorPlatformMixin._purge_evaluated_commits_for_round.__get__(dummy_validator, type(dummy_validator))
        dummy_validator._mark_all_zero_round_for_re_evaluation = ValidatorPlatformMixin._mark_all_zero_round_for_re_evaluation.__get__(dummy_validator, type(dummy_validator))
        dummy_validator._apply_post_consensus_reuse_policy = ValidatorPlatformMixin._apply_post_consensus_reuse_policy.__get__(dummy_validator, type(dummy_validator))
        dummy_validator.current_round_id = "validator_round_1_1_reuse_guard"
        dummy_validator.season_manager = Mock(season_number=1)
        dummy_validator.current_agent_runs = {
            48: Mock(
                total_tasks=25,
                completed_tasks=0,
                failed_tasks=25,
                average_reward=0.0,
                average_score=0.0,
                average_execution_time=180.0,
                zero_reason="task_failed",
                metadata={"average_cost": 0.0},
            )
        }
        dummy_validator.agent_run_accumulators = {
            48: {"tasks": 25, "reward": 0.0, "eval_score": 0.0, "execution_time": 4500.0, "cost": 0.0},
        }
        dummy_validator.miners_reused_this_round = set()
        dummy_validator._evaluated_commits_by_miner = {
            48: {
                "https://github.com/example/miner48|deadbeef": {
                    "agent_run_id": "agent-run-48-old",
                    "total_tasks": 25,
                    "evaluated_season": 1,
                    "evaluated_round": 1,
                }
            }
        }
        assert dummy_validator._mark_all_zero_round_for_re_evaluation() is True

        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator._wait_until_specific_block = AsyncMock()
        dummy_validator._calculate_final_weights = AsyncMock()

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot"):
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments") as mock_aggregate:
                mock_aggregate.return_value = (
                    {},
                    {"skips": {"all_zero_when_others_positive": [("test_hotkey_address", "cid-ours")]}},
                )

                await dummy_validator._run_settlement_phase(agents_evaluated=1)

        assert dummy_validator._disable_reuse_until == {
            "season": 1,
            "round": 2,
            "reason": "all_zero_excluded_by_consensus",
            "miner_uids": [48],
        }
        assert dummy_validator._last_all_zero_round_policy["reuse_preserved"] is False

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
                assert call_args[1]["consensus_rewards"] == mock_scores

    async def test_settlement_uploads_round_log_checkpoints_across_snapshot_consensus_and_weights(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator._wait_until_specific_block = AsyncMock()
        dummy_validator._calculate_final_weights = AsyncMock()
        dummy_validator._try_upload_round_log_checkpoint = AsyncMock()

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot"):
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments") as mock_aggregate:
                mock_aggregate.return_value = ({48: 0.42}, {"source": "test"})

                await dummy_validator._run_settlement_phase(agents_evaluated=1)

        reasons = [call.kwargs["reason"] for call in dummy_validator._try_upload_round_log_checkpoint.await_args_list]
        assert "settlement_snapshot_published" in reasons
        assert "settlement_fetch_block_reached" in reasons
        assert "settlement_consensus_aggregated" in reasons
        assert "settlement_weights_finalized" in reasons

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

        """Test that publish_round_snapshot is called during settlement."""
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

                # Settlement should publish a snapshot. The payload is built inside
                # publish_round_snapshot from current/best run data, so the helper
                # no longer depends on the deprecated `scores` argument.
                mock_publish.assert_called_once()
                call_args = mock_publish.call_args
                scores = call_args[1]["scores"]
                assert scores == {}


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

                await dummy_validator._calculate_final_weights(consensus_rewards=scores)

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

                await dummy_validator._calculate_final_weights(consensus_rewards=scores)

                # Should have called wta_rewards
                mock_wta.assert_called_once()

    async def test_weight_calculation_keeps_reigning_winner_until_threshold_is_beaten(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Winner should persist if challenger does not exceed required +% threshold."""
        dummy_validator.season_manager.season_number = 7
        dummy_validator.round_manager.round_number = 1

        with patch("autoppia_web_agents_subnet.validator.config.LAST_WINNER_BONUS_PCT", 0.05):
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"):
                await dummy_validator._calculate_final_weights(consensus_rewards={1: 0.9, 2: 0.8})
                assert dummy_validator._last_round_winner_uid == 1

                # Round 2: miner 2 improves, but not enough (> 0.9 * 1.05 = 0.945 required)
                dummy_validator.round_manager.round_number = 2
                await dummy_validator._calculate_final_weights(consensus_rewards={1: 0.7, 2: 0.93})
                assert dummy_validator._last_round_winner_uid == 1

                # Confirm rewards still point to UID 1 in last update
                rewards = dummy_validator.update_scores.call_args[1]["rewards"]
                assert float(rewards[1]) == pytest.approx(1.0)
                assert float(rewards[2]) == pytest.approx(0.0)

    async def test_weight_calculation_switches_winner_when_threshold_is_beaten(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Winner should switch when challenger beats reigning best by required threshold."""
        dummy_validator.season_manager.season_number = 8
        dummy_validator.round_manager.round_number = 1

        with patch("autoppia_web_agents_subnet.validator.config.LAST_WINNER_BONUS_PCT", 0.05):
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"):
                await dummy_validator._calculate_final_weights(consensus_rewards={1: 0.9, 2: 0.8})
                assert dummy_validator._last_round_winner_uid == 1

                # Round 2: 0.96 > 0.945, so UID 2 dethrones UID 1
                dummy_validator.round_manager.round_number = 2
                await dummy_validator._calculate_final_weights(consensus_rewards={1: 0.7, 2: 0.96})
                assert dummy_validator._last_round_winner_uid == 2

                rewards = dummy_validator.update_scores.call_args[1]["rewards"]
                assert float(rewards[2]) == pytest.approx(1.0)
                assert float(rewards[1]) == pytest.approx(0.0)

    async def test_weight_calculation_requires_eligibility_for_active_leader(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)
        dummy_validator.season_manager.season_number = 9
        dummy_validator.round_manager.round_number = 1

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"):
            dummy_validator.eligibility_status_by_uid = {1: "evaluated", 2: "evaluated"}
            await dummy_validator._calculate_final_weights(consensus_rewards={1: 0.9, 2: 0.8})
            assert dummy_validator._last_round_winner_uid == 1

            dummy_validator.round_manager.round_number = 2
            dummy_validator.eligibility_status_by_uid = {2: "evaluated"}
            await dummy_validator._calculate_final_weights(consensus_rewards={1: 0.0, 2: 0.7})
            assert dummy_validator._last_round_winner_uid == 2

            rewards = dummy_validator.update_scores.call_args[1]["rewards"]
            assert float(rewards[2]) == pytest.approx(1.0)
            assert float(rewards[1]) == pytest.approx(0.0)

    async def test_weight_calculation_restores_best_score_when_miner_becomes_eligible_again(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)
        dummy_validator.season_manager.season_number = 10
        dummy_validator.round_manager.round_number = 1

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"):
            dummy_validator.eligibility_status_by_uid = {1: "evaluated", 2: "evaluated"}
            await dummy_validator._calculate_final_weights(consensus_rewards={1: 0.9, 2: 0.8})
            assert dummy_validator._last_round_winner_uid == 1

            dummy_validator.round_manager.round_number = 2
            dummy_validator.eligibility_status_by_uid = {2: "evaluated"}
            await dummy_validator._calculate_final_weights(consensus_rewards={1: 0.0, 2: 0.7})
            assert dummy_validator._last_round_winner_uid == 2

            dummy_validator.round_manager.round_number = 3
            dummy_validator.eligibility_status_by_uid = {1: "evaluated", 2: "evaluated"}
            await dummy_validator._calculate_final_weights(consensus_rewards={1: 0.6, 2: 0.5})
            assert dummy_validator._last_round_winner_uid == 1

    async def test_weight_calculation_records_season_history_and_round_winners(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Settlement should store per-season round history and round winners."""
        dummy_validator.season_manager.season_number = 9
        dummy_validator.round_manager.round_number = 1

        with patch("autoppia_web_agents_subnet.validator.config.LAST_WINNER_BONUS_PCT", 0.05):
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"):
                await dummy_validator._calculate_final_weights(consensus_rewards={1: 0.91, 2: 0.82})
                dummy_validator.round_manager.round_number = 2
                await dummy_validator._calculate_final_weights(consensus_rewards={1: 0.55, 2: 0.86})

        season_state = dummy_validator._season_competition_history[9]
        assert season_state["summary"]["best_by_miner"][1] == pytest.approx(0.91)
        assert season_state["rounds"][1]["miner_scores"][1] == pytest.approx(0.91)
        assert season_state["rounds"][2]["miner_scores"][1] == pytest.approx(0.55)
        assert season_state["rounds"][1]["winner"]["miner_uid"] == 1
        assert season_state["rounds"][2]["winner"]["miner_uid"] == 1

    async def test_weight_calculation_calls_update_scores_and_set_weights(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that weight calculation calls update_scores and set_weights."""
        scores = {1: 0.8}

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.wta_rewards") as mock_wta:
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"):
                mock_wta.return_value = np.zeros(10, dtype=np.float32)

                await dummy_validator._calculate_final_weights(consensus_rewards=scores)

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

        await dummy_validator._calculate_final_weights(consensus_rewards=scores)

        # Should have called _burn_all
        dummy_validator._burn_all.assert_called_once()

    async def test_burn_all_when_burn_amount_percentage_is_one(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin

        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that weights are burned when BURN_AMOUNT_PERCENTAGE=1."""
        scores = {1: 0.8}

        with patch("autoppia_web_agents_subnet.validator.config.BURN_AMOUNT_PERCENTAGE", 1.0):
            await dummy_validator._calculate_final_weights(consensus_rewards=scores)

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

    async def test_wait_uploads_round_log_checkpoints_during_progress_logs(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin_with_wait

        dummy_validator = _bind_settlement_mixin_with_wait(dummy_validator)
        dummy_validator.block = 1000
        dummy_validator.subtensor.get_current_block = Mock(side_effect=[1000, 1010, 1030])
        dummy_validator._try_upload_round_log_checkpoint = AsyncMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("time.time", side_effect=[0, 13, 26]):
                await dummy_validator._wait_until_specific_block(target_block=1030, target_description="test block")

        reasons = [call.kwargs["reason"] for call in dummy_validator._try_upload_round_log_checkpoint.await_args_list]
        assert reasons == ["wait_progress:test block", "wait_progress:test block"]

    async def test_wait_uploads_round_log_checkpoint_before_timeout(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin_with_wait

        dummy_validator = _bind_settlement_mixin_with_wait(dummy_validator)
        dummy_validator.block = 1000
        dummy_validator._try_upload_round_log_checkpoint = AsyncMock()

        with patch("time.monotonic", side_effect=[0.0, 721.0]):
            with pytest.raises(TimeoutError):
                await dummy_validator._wait_until_specific_block(target_block=1020, target_description="test block")

        dummy_validator._try_upload_round_log_checkpoint.assert_awaited_once()
        assert dummy_validator._try_upload_round_log_checkpoint.await_args.kwargs["reason"] == "wait_timeout:test block"

    async def test_wait_uploads_round_log_checkpoint_before_block_read_failure_raises(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin_with_wait

        dummy_validator = _bind_settlement_mixin_with_wait(dummy_validator)
        dummy_validator.block = 1000
        dummy_validator.subtensor.get_current_block = Mock(side_effect=[RuntimeError("rpc down")] * 5)
        dummy_validator._try_upload_round_log_checkpoint = AsyncMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="Failed to read current block 5 times"):
                await dummy_validator._wait_until_specific_block(target_block=1020, target_description="test block")

        dummy_validator._try_upload_round_log_checkpoint.assert_awaited_once()
        assert dummy_validator._try_upload_round_log_checkpoint.await_args.kwargs["reason"] == "wait_block_read_failure:test block"


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

        await dummy_validator._calculate_final_weights(consensus_rewards=scores)

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

                await dummy_validator._calculate_final_weights(consensus_rewards=scores)

                # Should have filtered out negative score
                call_args = mock_wta.call_args[0][0]
                assert call_args[2] == 0.0  # Negative score should be filtered
