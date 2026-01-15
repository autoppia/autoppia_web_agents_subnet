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
        """Test that multiple rounds maintain state correctly."""
        validator = dummy_validator
        validator.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator._get_async_subtensor = AsyncMock(return_value=Mock())
        validator._calculate_final_weights = AsyncMock()
        
        with patch('autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot'):
            with patch('autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments') as mock_aggregate:
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
        validator = dummy_validator
        validator.season_manager.generate_season_tasks = AsyncMock(return_value=[])
        validator.season_manager.task_generated_season = 1
        
        # Move to new season
        validator.block = 5000  # Season 2
        
        await validator._start_round()
        
        # Should have regenerated tasks
        validator.season_manager.generate_season_tasks.assert_called_once()

    async def test_winner_bonus_applies_across_rounds(self, dummy_validator):
        """Test that winner bonus applies to previous round winner."""
        validator = dummy_validator
        validator._last_round_winner_uid = 1  # UID 1 won last round
        
        scores = {1: 0.8, 2: 0.6}
        
        with patch('autoppia_web_agents_subnet.validator.settlement.mixin.wta_rewards') as mock_wta:
            with patch('autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table'):
                with patch('autoppia_web_agents_subnet.validator.config.LAST_WINNER_BONUS_PCT', 0.1):
                    mock_wta.return_value = __import__('numpy').zeros(10, dtype=__import__('numpy').float32)
                    
                    await validator._calculate_final_weights(scores=scores)
                    
                    # Should have applied bonus to UID 1
                    call_args = mock_wta.call_args[0][0]
                    # UID 1 should have bonus applied (0.8 * 1.1 = 0.88)
                    assert call_args[1] > 0.8

    async def test_state_resets_between_rounds(self, dummy_validator):
        """Test that state resets properly between rounds."""
        validator = dummy_validator
        
        # Run first round
        validator.block = 1100
        await validator._start_round()
        
        # Add some phase history
        validator.round_manager.enter_phase(validator.round_manager.RoundPhase.EVALUATION, block=1200)
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
        validator = dummy_validator
        validator.season_manager.task_generated_season = 1
        validator.season_manager.generate_season_tasks = AsyncMock(return_value=[])
        
        # Add agents to queue
        from autoppia_web_agents_subnet.validator.models import AgentInfo
        for uid in [1, 2, 3]:
            agent = AgentInfo(uid=uid, agent_name=f"agent{uid}", github_url="https://test.com")
            validator.agents_dict[uid] = agent
            validator.agents_queue.put(agent)
        
        # Move to new season
        validator.block = 5000
        await validator._start_round()
        
        # Agents should be cleared
        assert len(validator.agents_dict) == 0

    async def test_season_transition_clears_agent_dict(self, dummy_validator):
        """Test that season transition clears the agent dictionary."""
        validator = dummy_validator
        validator.season_manager.task_generated_season = 1
        validator.season_manager.generate_season_tasks = AsyncMock(return_value=[])
        
        # Add agents
        from autoppia_web_agents_subnet.validator.models import AgentInfo
        validator.agents_dict = {
            1: AgentInfo(uid=1, agent_name="agent1", github_url="https://test.com"),
            2: AgentInfo(uid=2, agent_name="agent2", github_url="https://test.com"),
        }
        
        # Move to new season
        validator.block = 5000
        await validator._start_round()
        
        # Agents dict should be cleared
        assert len(validator.agents_dict) == 0


@pytest.mark.integration
@pytest.mark.asyncio
class TestRoundBoundaries:
    """Test round boundary behavior."""

    async def test_late_round_start_waits_for_next_boundary(self, dummy_validator):
        """Test that starting late in round waits for next boundary."""
        validator = dummy_validator
        validator.block = 1650  # Late in round (90% through)
        validator._wait_until_specific_block = AsyncMock()
        
        with patch('autoppia_web_agents_subnet.validator.config.ROUND_START_UNTIL_FRACTION', 0.2):
            result = await validator._start_round()
            
            # Should wait for next boundary
            assert result.continue_forward is False
            validator._wait_until_specific_block.assert_called_once()

    async def test_early_round_start_continues_forward(self, dummy_validator):
        """Test that starting early in round continues forward."""
        validator = dummy_validator
        validator.block = 1050  # Early in round (7% through)
        
        with patch('autoppia_web_agents_subnet.validator.config.ROUND_START_UNTIL_FRACTION', 0.2):
            result = await validator._start_round()
            
            # Should continue forward
            assert result.continue_forward is True
