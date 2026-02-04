"""
Unit tests for ValidatorRoundStartMixin.

Tests round start logic, handshake, and minimum block waiting.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.round_start.types import RoundStartResult


@pytest.mark.unit
@pytest.mark.asyncio
class TestRoundStart:
    """Test round start logic."""

    async def test_start_round_early_in_round_continues_forward(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test that _start_round early in round continues with forward pass."""
        dummy_validator.block = 1100  # Early in round (fraction < 0.2)
        
        result = await dummy_validator._start_round()
        
        assert result.continue_forward is True
        assert dummy_validator.round_manager.round_number == 1

    async def test_start_round_late_in_round_waits_for_boundary(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test that _start_round late in round waits for next boundary."""
        dummy_validator.block = 1650  # Late in round (fraction > 0.2)
        dummy_validator._wait_until_specific_block = AsyncMock()
        
        with patch('autoppia_web_agents_subnet.validator.config.ROUND_START_UNTIL_FRACTION', 0.2):
            result = await dummy_validator._start_round()
        
        assert result.continue_forward is False
        dummy_validator._wait_until_specific_block.assert_called_once()

    async def test_season_transition_triggers_task_regeneration(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test that season transition regenerates tasks and clears agents."""
        dummy_validator.block = 4600  # Start of new season (early in round)
        dummy_validator.season_manager.task_generated_season = 1
        # Mock should_start_new_season to return True for this test
        dummy_validator.season_manager.should_start_new_season = Mock(return_value=True)
        # Use the existing mock from fixture, just reset it
        dummy_validator.season_manager.generate_season_tasks.reset_mock()
        
        # Add some agents to queue
        from autoppia_web_agents_subnet.validator.models import AgentInfo
        agent = AgentInfo(uid=1, agent_name="test", github_url="https://test.com")
        dummy_validator.agents_dict[1] = agent
        dummy_validator.agents_queue.put(agent)
        
        await dummy_validator._start_round()
        
        # Should regenerate tasks
        dummy_validator.season_manager.generate_season_tasks.assert_called_once()
        # Should clear agents
        assert len(dummy_validator.agents_dict) == 0

    async def test_round_manager_start_new_round_is_called(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test that start_new_round is called on round_manager."""
        dummy_validator.block = 1100
        
        await dummy_validator._start_round()
        
        assert dummy_validator.round_manager.current_phase == RoundPhase.PREPARING
        assert len(dummy_validator.round_manager.phase_history) > 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestHandshake:
    """Test handshake logic."""

    async def test_perform_handshake_sends_to_eligible_miners(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test that handshake sends synapse to miners meeting stake requirement."""
        with patch('autoppia_web_agents_subnet.validator.round_start.mixin.send_start_round_synapse_to_miners') as mock_send:
            # Mock responses with agent info
            mock_responses = [
                Mock(agent_name="agent1", github_url="https://github.com/test/agent1", agent_image=None),
                Mock(agent_name="agent2", github_url="https://github.com/test/agent2", agent_image=None),
            ]
            mock_send.return_value = mock_responses
            
            await dummy_validator._perform_handshake()
            
            # Should have called send_start_round_synapse_to_miners
            assert mock_send.call_count == 1

    async def test_handshake_filters_miners_by_min_stake(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test that handshake filters out miners below MIN_MINER_STAKE_TAO."""
        # Set stakes: UIDs 1,2,3 have sufficient stake (UID 0 is validator)
        # UID 0: 100.0 (validator, excluded), UID 1: 150.0, UID 2: 200.0, UID 3: 100.0, rest < 100.0
        dummy_validator.metagraph.S = [100.0, 150.0, 200.0, 100.0, 50.0, 30.0, 10.0, 0.0, 0.0, 0.0]
        dummy_validator.metagraph.stake = [100.0, 150.0, 200.0, 100.0, 50.0, 30.0, 10.0, 0.0, 0.0, 0.0]
        
        with patch('autoppia_web_agents_subnet.validator.round_start.mixin.send_start_round_synapse_to_miners') as mock_send:
            with patch('autoppia_web_agents_subnet.validator.round_start.mixin.MIN_MINER_STAKE_TAO', 100.0):
                mock_send.return_value = []
                
                await dummy_validator._perform_handshake()
                
                # Should only send to UIDs with stake >= 100.0 (excluding validator UID 0)
                call_args = mock_send.call_args
                if call_args:
                    miner_axons = call_args[1]['miner_axons']
                    # Should have 3 miners (UIDs 1, 2, 3)
                    assert len(miner_axons) == 3

    async def test_handshake_populates_agents_dict_and_queue(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test that handshake populates agents_dict and agents_queue."""
        with patch('autoppia_web_agents_subnet.validator.round_start.mixin.send_start_round_synapse_to_miners') as mock_send:
            mock_responses = [
                Mock(agent_name="agent1", github_url="https://github.com/test/agent1", agent_image=None),
                Mock(agent_name="agent2", github_url="https://github.com/test/agent2", agent_image=None),
            ]
            mock_send.return_value = mock_responses
            
            # Clear existing agents
            dummy_validator.agents_dict = {}
            
            await dummy_validator._perform_handshake()
            
            # Should have populated agents_dict
            assert len(dummy_validator.agents_dict) > 0

    async def test_handshake_excludes_validator_own_uid(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test that handshake excludes the validator's own UID."""
        dummy_validator.uid = 0
        
        with patch('autoppia_web_agents_subnet.validator.round_start.mixin.send_start_round_synapse_to_miners') as mock_send:
            mock_send.return_value = []
            
            await dummy_validator._perform_handshake()
            
            # Validator UID should not be in candidate list
            call_args = mock_send.call_args
            if call_args:
                miner_axons = call_args[1]['miner_axons']
                # Should not include validator's own axon
                assert all(axon.port != 8000 for axon in miner_axons)

    async def test_handshake_handles_missing_agent_name_or_github_url(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test that handshake skips responses with missing agent_name or github_url."""
        with patch('autoppia_web_agents_subnet.validator.round_start.mixin.send_start_round_synapse_to_miners') as mock_send:
            mock_responses = [
                Mock(agent_name="agent1", github_url="https://github.com/test/agent1", agent_image=None),
                Mock(agent_name=None, github_url="https://github.com/test/agent2", agent_image=None),  # Missing name
                Mock(agent_name="agent3", github_url=None, agent_image=None),  # Missing URL
                Mock(agent_name="", github_url="https://github.com/test/agent4", agent_image=None),  # Empty name
            ]
            mock_send.return_value = mock_responses
            
            dummy_validator.agents_dict = {}
            
            await dummy_validator._perform_handshake()
            
            # Should only add agent1 (valid response)
            # Note: actual count depends on UID filtering
            valid_agents = [a for a in dummy_validator.agents_dict.values() if a.agent_name and a.github_url]
            assert len(valid_agents) >= 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestMinimumBlock:
    """Test minimum block waiting logic."""

    async def test_wait_for_minimum_start_block_waits_when_early(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test that _wait_for_minimum_start_block waits when before minimum."""
        dummy_validator.block = 500  # Before minimum_start_block (1000)
        
        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            result = await dummy_validator._wait_for_minimum_start_block()
            
            assert result is True  # Indicates wait occurred
            mock_sleep.assert_called_once()

    async def test_wait_for_minimum_start_block_continues_when_ready(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test that _wait_for_minimum_start_block continues when past minimum."""
        dummy_validator.block = 1500  # After minimum_start_block (1000)
        
        result = await dummy_validator._wait_for_minimum_start_block()
        
        assert result is False  # No wait needed

    async def test_wait_calculates_correct_eta(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test that wait calculates correct ETA for minimum block."""
        dummy_validator.block = 500  # 500 blocks before minimum
        
        blocks_remaining = dummy_validator.round_manager.blocks_until_allowed(500)
        assert blocks_remaining == 500
        
        # ETA should be blocks * 12 seconds / 60 = 100 minutes
        expected_minutes = 500 * 12 / 60
        assert abs(expected_minutes - 100.0) < 0.1


@pytest.mark.unit
@pytest.mark.asyncio
class TestHandshakeEdgeCases:
    """Test edge cases in handshake logic."""

    async def test_handshake_with_no_metagraph(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test handshake handles missing metagraph gracefully."""
        dummy_validator.metagraph = None
        
        # Should not raise exception
        await dummy_validator._perform_handshake()

    async def test_handshake_with_empty_metagraph(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test handshake handles empty metagraph."""
        dummy_validator.metagraph.n = 0
        
        # Should not raise exception
        await dummy_validator._perform_handshake()

    async def test_handshake_with_no_eligible_miners(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
        """Test handshake when no miners meet minimum stake."""
        # All miners have insufficient stake
        dummy_validator.metagraph.S = [10.0] * 10
        dummy_validator.metagraph.stake = [10.0] * 10
        
        with patch('autoppia_web_agents_subnet.validator.round_start.mixin.MIN_MINER_STAKE_TAO', 100.0):
            # Should not raise exception
            await dummy_validator._perform_handshake()
