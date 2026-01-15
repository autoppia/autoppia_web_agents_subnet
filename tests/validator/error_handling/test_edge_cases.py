"""
Edge case tests for validator workflow.

Tests handling of unusual but valid scenarios.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.unit
class TestStakeEdgeCases:
    """Test edge cases related to stake filtering."""

    @pytest.mark.asyncio
    async def test_handshake_when_no_miners_meet_minimum_stake(
        self, validator_with_agents, mock_metagraph
    ):
        """Test handshake when no miners meet minimum stake requirement."""
        # Setup metagraph with all low-stake miners
        mock_metagraph.S = [50.0] * 10  # All below MIN_MINER_STAKE_TAO (100)
        mock_metagraph.n = 10
        
        validator_with_agents.metagraph = mock_metagraph
        validator_with_agents.uid = 0
        
        # Mock dendrite
        async def mock_query(*args, **kwargs):
            return []
        
        validator_with_agents.dendrite.query = mock_query
        
        # Should not crash
        await validator_with_agents._perform_handshake()
        
        # No agents should be added
        assert len(validator_with_agents.agents_dict) == 0
        assert validator_with_agents.agents_queue.empty()

    @pytest.mark.asyncio
    async def test_consensus_when_all_validators_have_zero_stake(
        self, mock_ipfs_client, mock_async_subtensor
    ):
        """Test consensus aggregation when all validators have zero stake."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            aggregate_scores_from_commitments
        )
        
        # Setup validators with zero stake
        round_number = 100
        
        for validator_uid in range(3):
            scores = {1: 0.8, 2: 0.6}
            payload = {"round_number": round_number, "scores": scores}
            cid = await mock_ipfs_client.add_json_async(payload)
            
            mock_async_subtensor.commitments[validator_uid] = {
                "round_number": round_number,
                "cid": cid[0],
                "block": 1000
            }
        
        # All validators have zero stake
        mock_async_subtensor.stakes = {0: 0.0, 1: 0.0, 2: 0.0}
        
        # Should use simple average
        result = await aggregate_scores_from_commitments(
            async_subtensor=mock_async_subtensor,
            ipfs_client=mock_ipfs_client,
            round_number=round_number,
            min_stake=0.0  # Allow zero stake
        )
        
        # Should still aggregate scores
        assert len(result) > 0, "Should aggregate scores even with zero stake"
        assert result[1] == pytest.approx(0.8, abs=0.01)
        assert result[2] == pytest.approx(0.6, abs=0.01)

    @pytest.mark.asyncio
    async def test_settlement_when_no_validators_committed(
        self, validator_with_agents
    ):
        """Test settlement when no validators committed scores."""
        # Setup agents with scores
        validator_with_agents.agents_dict = {
            1: MagicMock(uid=1, score=0.8),
            2: MagicMock(uid=2, score=0.6)
        }
        
        # Mock consensus to return empty dict
        with patch(
            'autoppia_web_agents_subnet.validator.settlement.consensus.aggregate_scores_from_commitments',
            new=AsyncMock(return_value={})
        ):
            validator_with_agents.update_scores = MagicMock()
            validator_with_agents.set_weights = AsyncMock()
            validator_with_agents.round_manager.enter_phase = MagicMock()
            
            # Should not crash
            await validator_with_agents._calculate_final_weights()
            
            # Should still set weights (using local scores)
            validator_with_agents.set_weights.assert_called()


@pytest.mark.unit
class TestEmptyDataEdgeCases:
    """Test edge cases with empty or missing data."""

    @pytest.mark.asyncio
    async def test_evaluation_with_no_agents(self, validator_with_agents):
        """Test evaluation phase with no agents."""
        # Clear agents
        validator_with_agents.agents_dict = {}
        validator_with_agents.agents_queue.queue.clear()
        
        # Should not crash
        await validator_with_agents._run_evaluation_phase()
        
        # Should complete without errors
        assert len(validator_with_agents.agents_dict) == 0

    @pytest.mark.asyncio
    async def test_evaluation_with_no_tasks(self, validator_with_agents):
        """Test evaluation with no tasks available."""
        # Setup agent
        agent = MagicMock()
        agent.uid = 1
        agent.agent_name = "TestAgent"
        agent.github_url = "https://github.com/test/agent"
        agent.score = 0.0
        
        validator_with_agents.agents_dict = {1: agent}
        validator_with_agents.agents_queue.queue.clear()
        validator_with_agents.agents_queue.put(agent)
        
        # Mock season manager to return empty tasks
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(
            return_value=[]
        )
        
        validator_with_agents.sandbox_manager.deploy_agent = AsyncMock(return_value=True)
        validator_with_agents.sandbox_manager.cleanup_agent = AsyncMock()
        
        # Should not crash
        await validator_with_agents._run_evaluation_phase()
        
        # Agent score should remain 0 (no tasks to evaluate)
        assert agent.score == 0.0

    @pytest.mark.asyncio
    async def test_settlement_with_no_scores(self, validator_with_agents):
        """Test settlement when no agents have scores."""
        # Setup agents with zero scores
        validator_with_agents.agents_dict = {
            1: MagicMock(uid=1, score=0.0),
            2: MagicMock(uid=2, score=0.0)
        }
        
        validator_with_agents.update_scores = MagicMock()
        validator_with_agents.set_weights = AsyncMock()
        validator_with_agents.round_manager.enter_phase = MagicMock()
        
        # Should trigger burn logic
        await validator_with_agents._calculate_final_weights()
        
        # Should still call set_weights (with burn)
        validator_with_agents.set_weights.assert_called()

    @pytest.mark.asyncio
    async def test_consensus_with_no_commitments(
        self, mock_ipfs_client, mock_async_subtensor
    ):
        """Test consensus when no validators have commitments."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            aggregate_scores_from_commitments
        )
        
        # No commitments
        mock_async_subtensor.commitments = {}
        mock_async_subtensor.stakes = {}
        
        # Should return empty dict
        result = await aggregate_scores_from_commitments(
            async_subtensor=mock_async_subtensor,
            ipfs_client=mock_ipfs_client,
            round_number=100,
            min_stake=100.0
        )
        
        assert result == {}, "Should return empty dict with no commitments"


@pytest.mark.unit
class TestRoundBoundaryEdgeCases:
    """Test edge cases at round boundaries."""

    def test_round_start_at_exact_boundary(self, round_manager):
        """Test round start at exact round boundary."""
        # Start at exact boundary
        round_manager.sync_boundaries(current_block=1000)
        round_manager.start_new_round(current_block=1000)
        
        boundaries = round_manager.get_round_boundaries(current_block=1000)
        
        assert boundaries["round_start_block"] == 1000
        assert boundaries["fraction_elapsed"] == 0.0

    def test_round_end_at_exact_boundary(self, round_manager):
        """Test round at exact end boundary."""
        round_manager.sync_boundaries(current_block=1000)
        round_manager.start_new_round(current_block=1000)
        
        # Move to exact end
        target_block = round_manager.get_round_boundaries(1000)["target_block"]
        boundaries = round_manager.get_round_boundaries(target_block)
        
        assert boundaries["fraction_elapsed"] == pytest.approx(1.0, abs=0.01)

    def test_fraction_elapsed_beyond_round_end(self, round_manager):
        """Test fraction_elapsed when beyond round end."""
        round_manager.sync_boundaries(current_block=1000)
        round_manager.start_new_round(current_block=1000)
        
        # Move way beyond end
        target_block = round_manager.get_round_boundaries(1000)["target_block"]
        boundaries = round_manager.get_round_boundaries(target_block + 1000)
        
        # Should be capped at 1.0 or slightly above
        assert boundaries["fraction_elapsed"] >= 1.0


@pytest.mark.unit
class TestSeasonTransitionEdgeCases:
    """Test edge cases during season transitions."""

    @pytest.mark.asyncio
    async def test_season_transition_at_exact_boundary(
        self, season_manager, mock_validator_config
    ):
        """Test season transition at exact season boundary."""
        # Calculate exact season boundary
        season_size = mock_validator_config.SEASON_SIZE_EPOCHS
        epoch_length = mock_validator_config.EPOCH_LENGTH
        minimum_start_block = mock_validator_config.MINIMUM_START_BLOCK
        
        season_boundary = minimum_start_block + (season_size * epoch_length)
        
        # Should detect transition
        assert season_manager.should_start_new_season(season_boundary)
        
        # Generate tasks for new season
        tasks = await season_manager.generate_season_tasks(season_boundary)
        assert len(tasks) > 0

    @pytest.mark.asyncio
    async def test_multiple_season_transitions_in_sequence(
        self, season_manager, mock_validator_config
    ):
        """Test multiple consecutive season transitions."""
        season_size = mock_validator_config.SEASON_SIZE_EPOCHS
        epoch_length = mock_validator_config.EPOCH_LENGTH
        minimum_start_block = mock_validator_config.MINIMUM_START_BLOCK
        
        season_numbers = []
        
        # Simulate 3 seasons
        for i in range(3):
            block = minimum_start_block + (i * season_size * epoch_length)
            season_num = season_manager.get_season_number(block)
            season_numbers.append(season_num)
            
            # Generate tasks
            tasks = await season_manager.generate_season_tasks(block)
            assert len(tasks) > 0
        
        # Season numbers should increment
        assert season_numbers[1] > season_numbers[0]
        assert season_numbers[2] > season_numbers[1]


@pytest.mark.unit
class TestMetagraphEdgeCases:
    """Test edge cases related to metagraph state."""

    @pytest.mark.asyncio
    async def test_handshake_with_single_validator(
        self, validator_with_agents
    ):
        """Test handshake when validator is the only node."""
        # Setup metagraph with only validator
        mock_metagraph = MagicMock()
        mock_metagraph.n = 1
        mock_metagraph.S = [1000.0]  # Only validator
        
        validator_with_agents.metagraph = mock_metagraph
        validator_with_agents.uid = 0
        
        # Mock dendrite
        async def mock_query(*args, **kwargs):
            return []
        
        validator_with_agents.dendrite.query = mock_query
        
        # Should not crash
        await validator_with_agents._perform_handshake()
        
        # No agents (validator excludes itself)
        assert len(validator_with_agents.agents_dict) == 0

    @pytest.mark.asyncio
    async def test_handshake_with_large_metagraph(
        self, validator_with_agents
    ):
        """Test handshake with very large metagraph."""
        # Setup large metagraph (1000 nodes)
        mock_metagraph = MagicMock()
        mock_metagraph.n = 1000
        mock_metagraph.S = [1000.0] * 1000  # All high stake
        
        validator_with_agents.metagraph = mock_metagraph
        validator_with_agents.uid = 0
        
        # Mock dendrite to return many responses
        async def mock_query(*args, **kwargs):
            responses = []
            for i in range(1, 100):  # Return 99 responses
                response = MagicMock()
                response.agent_name = f"Agent{i}"
                response.github_url = f"https://github.com/test/agent{i}"
                response.axon = MagicMock()
                response.axon.hotkey = f"hotkey{i}"
                responses.append(response)
            return responses
        
        validator_with_agents.dendrite.query = mock_query
        
        # Should not crash
        await validator_with_agents._perform_handshake()
        
        # Should have added agents
        assert len(validator_with_agents.agents_dict) > 0


@pytest.mark.unit
class TestConcurrencyEdgeCases:
    """Test edge cases related to concurrent operations."""

    @pytest.mark.asyncio
    async def test_evaluation_with_queue_modifications(
        self, validator_with_agents, season_tasks
    ):
        """Test evaluation when queue is modified during processing."""
        # Setup initial agents
        for i in range(3):
            agent = MagicMock()
            agent.uid = i
            agent.agent_name = f"Agent{i}"
            agent.github_url = f"https://github.com/test/agent{i}"
            agent.score = 0.0
            
            validator_with_agents.agents_dict[i] = agent
            validator_with_agents.agents_queue.put(agent)
        
        validator_with_agents.sandbox_manager.deploy_agent = AsyncMock(return_value=True)
        validator_with_agents.sandbox_manager.cleanup_agent = AsyncMock()
        
        # Mock evaluation
        async def mock_evaluate(*args, **kwargs):
            return 0.8
        
        with patch(
            'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
            new=mock_evaluate
        ):
            # Should handle gracefully
            await validator_with_agents._run_evaluation_phase()
        
        # Should have evaluated agents
        evaluated = sum(1 for a in validator_with_agents.agents_dict.values() if a.score > 0)
        assert evaluated > 0
