"""
Integration tests for multi-round scenarios.

Tests validator behavior across multiple rounds.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch


@pytest.mark.integration
@pytest.mark.asyncio
class TestMultiRound:
    """Test multi-round scenarios."""

    async def test_multiple_rounds_maintain_state_correctly(self, dummy_validator, season_tasks):
        from tests.conftest import _bind_settlement_mixin, _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that multiple rounds maintain state correctly."""
        validator = dummy_validator
        validator.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator._get_async_subtensor = AsyncMock(return_value=Mock())
        validator._calculate_final_weights = AsyncMock()

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot"):
            with patch("autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments") as mock_aggregate:
                mock_aggregate.return_value = ({}, None)

                # Run first round
                validator.block = 1100
                await validator._start_round()
                await validator._run_settlement_phase(agents_evaluated=0)
                round1_number = validator.round_manager.round_number

                # Run second round
                validator.block = 1820  # Next round
                await validator._start_round()
                await validator._run_settlement_phase(agents_evaluated=0)
                round2_number = validator.round_manager.round_number

                # Round numbers should increment
                assert round2_number == round1_number + 1

    async def test_season_transition_regenerates_tasks(self, dummy_validator):
        """Test that season transition triggers task regeneration."""
        # Set up the mocks BEFORE binding
        dummy_validator.season_manager.task_generated_season = 1
        dummy_validator.season_manager.should_start_new_season = Mock(return_value=True)
        dummy_validator.season_manager.generate_season_tasks = AsyncMock(return_value=[])

        from tests.conftest import _bind_settlement_mixin, _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator = _bind_settlement_mixin(dummy_validator)

        validator = dummy_validator

        # Move to new season - use a block early in the round to avoid waiting
        validator.block = 4620  # Season 2, early in round (< 20% through)

        await validator._start_round()

        # Should have regenerated tasks
        validator.season_manager.generate_season_tasks.assert_called_once()

    async def test_season_winner_persists_across_rounds_until_threshold(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin, _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Winner should persist across rounds unless another beats by configured threshold."""
        validator = dummy_validator
        validator.season_manager.season_number = 12

        with patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"):
            with patch("autoppia_web_agents_subnet.validator.config.LAST_WINNER_BONUS_PCT", 0.05):
                validator.round_manager.round_number = 1
                await validator._calculate_final_weights(scores={1: 0.9, 2: 0.8})
                assert validator._last_round_winner_uid == 1

                # 0.93 does not beat 0.9 by >5% (needs >0.945)
                validator.round_manager.round_number = 2
                await validator._calculate_final_weights(scores={1: 0.6, 2: 0.93})
                assert validator._last_round_winner_uid == 1

                # 0.96 beats 0.9 by >5%
                validator.round_manager.round_number = 3
                await validator._calculate_final_weights(scores={1: 0.7, 2: 0.96})
                assert validator._last_round_winner_uid == 2

    async def test_state_resets_between_rounds(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin, _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that state resets properly between rounds."""
        from autoppia_web_agents_subnet.validator.round_manager import RoundPhase

        validator = dummy_validator

        # Run first round
        validator.block = 1100
        await validator._start_round()

        # Add some phase history
        validator.round_manager.enter_phase(RoundPhase.EVALUATION, block=1200)
        phase_count_1 = len(validator.round_manager.phase_history)

        # Start new round
        validator.block = 1820
        await validator._start_round()

        # Phase history should be reset
        phase_count_2 = len(validator.round_manager.phase_history)
        assert phase_count_2 < phase_count_1  # Should have reset


@pytest.mark.integration
@pytest.mark.asyncio
class TestSeasonTransitions:
    """Test season transition behavior."""

    async def test_season_transition_clears_agent_queue(self, dummy_validator):
        """Test that season transition clears the agent queue."""
        # Set up the mocks BEFORE binding
        dummy_validator.season_manager.task_generated_season = 1
        dummy_validator.season_manager.generate_season_tasks = AsyncMock(return_value=[])
        dummy_validator.season_manager.should_start_new_season = Mock(return_value=True)

        from tests.conftest import _bind_settlement_mixin, _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator = _bind_settlement_mixin(dummy_validator)

        validator = dummy_validator

        # Add agents to queue
        from autoppia_web_agents_subnet.validator.models import AgentInfo

        for uid in [1, 2, 3]:
            agent = AgentInfo(uid=uid, agent_name=f"agent{uid}", github_url="https://test.com")
            validator.agents_dict[uid] = agent
            validator.agents_queue.put(agent)

        # Move to new season - use early block
        validator.block = 4620
        await validator._start_round()

        # Agents should be cleared
        assert len(validator.agents_dict) == 0

    async def test_season_transition_clears_agent_dict(self, dummy_validator):
        """Test that season transition clears the agent dictionary."""
        # Set up the mocks BEFORE binding
        dummy_validator.season_manager.task_generated_season = 1
        dummy_validator.season_manager.generate_season_tasks = AsyncMock(return_value=[])
        dummy_validator.season_manager.should_start_new_season = Mock(return_value=True)

        from tests.conftest import _bind_settlement_mixin, _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator = _bind_settlement_mixin(dummy_validator)

        validator = dummy_validator

        # Add agents
        from autoppia_web_agents_subnet.validator.models import AgentInfo

        validator.agents_dict = {
            1: AgentInfo(uid=1, agent_name="agent1", github_url="https://test.com"),
            2: AgentInfo(uid=2, agent_name="agent2", github_url="https://test.com"),
        }

        # Move to new season - use early block
        validator.block = 4620
        await validator._start_round()

        # Agents dict should be cleared
        assert len(validator.agents_dict) == 0


@pytest.mark.integration
@pytest.mark.asyncio
class TestRoundBoundaries:
    """Test round boundary behavior."""

    async def test_late_round_start_waits_for_next_boundary(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin, _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that starting late in round waits for next boundary."""
        validator = dummy_validator
        validator.block = 1650  # Late in round (90% through)
        validator._wait_until_specific_block = AsyncMock()

        with patch("autoppia_web_agents_subnet.validator.round_start.mixin.SKIP_ROUND_IF_STARTED_AFTER_FRACTION", 0.2):
            result = await validator._start_round()

            # Should wait for next boundary
            assert result.continue_forward is False
            validator._wait_until_specific_block.assert_called_once()

    async def test_early_round_start_continues_forward(self, dummy_validator):
        from tests.conftest import _bind_settlement_mixin, _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator = _bind_settlement_mixin(dummy_validator)

        """Test that starting early in round continues forward."""
        validator = dummy_validator
        validator.block = 1050  # Early in round (7% through)

        with patch("autoppia_web_agents_subnet.validator.round_start.mixin.SKIP_ROUND_IF_STARTED_AFTER_FRACTION", 0.2):
            result = await validator._start_round()

            # Should continue forward
            assert result.continue_forward is True
