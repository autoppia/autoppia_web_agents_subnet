"""
Edge case tests for validator workflow.

Tests handling of unusual but valid scenarios.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch


@pytest.mark.unit
class TestStakeEdgeCases:
    """Test edge cases related to stake filtering."""

    @pytest.mark.asyncio
    async def test_handshake_when_no_miners_meet_minimum_stake(
        self, dummy_validator, mock_metagraph
    ):
        """Test handshake when no miners meet minimum stake requirement."""
        # Setup metagraph with all low-stake miners
        mock_metagraph.S = [50.0] * 10  # All below MIN_MINER_STAKE_TAO (100)
        mock_metagraph.n = 10
        
        dummy_validator.metagraph = mock_metagraph
        dummy_validator.uid = 0
        
        # Mock dendrite
        async def mock_query(*args, **kwargs):
            return []
        
        dummy_validator.dendrite.query = mock_query
        
        # Should not crash
        await dummy_validator._perform_handshake()
        
        # No agents should be added
        assert len(dummy_validator.agents_dict) == 0
        assert dummy_validator.agents_queue.empty()

    @pytest.mark.asyncio
    async def test_consensus_when_all_validators_have_zero_stake(
        self, mock_ipfs_client, mock_async_subtensor, dummy_validator
    ):
        """Test consensus aggregation when all validators have zero stake."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            aggregate_scores_from_commitments
        )
        
        # Setup validators with zero stake
        round_number = 100
        
        # Create commitments
        commitments = {}
        for validator_uid in range(3):
            scores = {1: 0.8, 2: 0.6}
            payload = {"round_number": round_number, "r": round_number, "scores": scores}
            cid = await mock_ipfs_client.add_json_async(payload)
            
            commitments[f"hotkey{validator_uid}"] = {
                "r": round_number,
                "c": cid[0],
                "p": 0
            }
        
        # Mock read_all_plain_commitments to return our commitments
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments',
                   new=AsyncMock(return_value=commitments)):
            # Setup dummy validator for method call
            dummy_validator.block = 1000
            dummy_validator.config.netuid = 99
            dummy_validator.round_manager.calculate_round = Mock(return_value=round_number)
            dummy_validator.metagraph.stake = [0.0, 0.0, 0.0]
            dummy_validator.metagraph.hotkeys = [f"hotkey{i}" for i in range(3)]
            dummy_validator.metagraph.axons = [Mock(hotkey=f"hotkey{i}") for i in range(3)]
            
            # With zero stake, validators are filtered out by MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO
            result, _ = await aggregate_scores_from_commitments(
                dummy_validator,
                st=mock_async_subtensor
            )
        
        # Should return empty dict since all validators have zero stake (below minimum)
        assert result == {}, "Should return empty dict when all validators have zero stake"

    @pytest.mark.asyncio
    async def test_settlement_when_no_validators_committed(
        self, validator_with_agents
    ):
        """Test settlement when no validators committed scores."""
        from tests.conftest import _bind_settlement_mixin
        validator_with_agents = _bind_settlement_mixin(validator_with_agents)
        
        # Setup agents with scores
        validator_with_agents.agents_dict = {
            1: MagicMock(uid=1, score=0.8),
            2: MagicMock(uid=2, score=0.6)
        }
        
        # Mock consensus to return empty dict
        with patch(
            'autoppia_web_agents_subnet.validator.settlement.consensus.aggregate_scores_from_commitments',
            new=AsyncMock(return_value=({}, None))
        ):
            validator_with_agents.update_scores = Mock()
            validator_with_agents.set_weights = Mock()
            validator_with_agents.round_manager.enter_phase = MagicMock()
            
            # Should not crash - pass empty scores dict
            await validator_with_agents._calculate_final_weights(scores={})
            
            # Should still set weights (using burn logic since no scores)
            validator_with_agents.set_weights.assert_called()


@pytest.mark.unit
class TestEmptyDataEdgeCases:
    """Test edge cases with empty or missing data."""

    @pytest.mark.asyncio
    async def test_evaluation_with_no_agents(self, validator_with_agents):
        """Test evaluation phase with no agents."""
        from tests.conftest import _bind_evaluation_mixin
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        
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
        from tests.conftest import _bind_evaluation_mixin
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        
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
        
        mock_instance = Mock()
        mock_instance.base_url = "http://localhost:8001"
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=mock_instance)
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        # Should not crash
        await validator_with_agents._run_evaluation_phase()
        
        # Agent score should remain 0 (no tasks to evaluate)
        assert agent.score == 0.0

    @pytest.mark.asyncio
    async def test_settlement_with_no_scores(self, validator_with_agents):
        """Test settlement when no agents have scores."""
        from tests.conftest import _bind_settlement_mixin
        validator_with_agents = _bind_settlement_mixin(validator_with_agents)
        
        # Setup agents with zero scores
        validator_with_agents.agents_dict = {
            1: MagicMock(uid=1, score=0.0),
            2: MagicMock(uid=2, score=0.0)
        }
        
        validator_with_agents.update_scores = Mock()
        validator_with_agents.set_weights = Mock()
        validator_with_agents.round_manager.enter_phase = MagicMock()
        
        # Should trigger burn logic - pass empty scores dict
        await validator_with_agents._calculate_final_weights(scores={})
        
        # Should still call set_weights (with burn)
        validator_with_agents.set_weights.assert_called()

    @pytest.mark.asyncio
    async def test_consensus_with_no_commitments(
        self, mock_ipfs_client, mock_async_subtensor, dummy_validator
    ):
        """Test consensus when no validators have commitments."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            aggregate_scores_from_commitments
        )
        
        # Mock read_all_plain_commitments to return empty dict
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments',
                   new=AsyncMock(return_value={})):
            # Setup dummy validator for method call
            dummy_validator.block = 1000
            dummy_validator.config.netuid = 99
            dummy_validator.round_manager.calculate_round = Mock(return_value=100)
            
            # Should return empty dict
            result, _ = await aggregate_scores_from_commitments(
                dummy_validator,
                st=mock_async_subtensor
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
        season_size = mock_validator_config["season_size_epochs"]
        epoch_length = season_manager.BLOCKS_PER_EPOCH
        minimum_start_block = mock_validator_config["minimum_start_block"]
        
        season_boundary = minimum_start_block + int(season_size * epoch_length)
        
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
        season_size = mock_validator_config["season_size_epochs"]
        epoch_length = season_manager.BLOCKS_PER_EPOCH
        minimum_start_block = mock_validator_config["minimum_start_block"]
        
        season_numbers = []
        
        # Simulate 3 seasons
        for i in range(3):
            block = minimum_start_block + int(i * season_size * epoch_length)
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
        from tests.conftest import _bind_round_start_mixin
        validator_with_agents = _bind_round_start_mixin(validator_with_agents)
        
        # Clear pre-populated agents
        validator_with_agents.agents_dict = {}
        
        # Setup metagraph with only validator
        mock_metagraph = MagicMock()
        mock_metagraph.n = 1
        mock_metagraph.S = [1000.0]  # Only validator
        mock_metagraph.stake = [1000.0]  # Add stake attribute
        mock_metagraph.axons = [MagicMock()]  # Add axons
        
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
        from tests.conftest import _bind_evaluation_mixin
        from autoppia_web_agents_subnet.validator.models import AgentInfo
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        
        # Clear pre-populated agents
        validator_with_agents.agents_dict = {}
        validator_with_agents.agents_queue.queue.clear()
        
        # Setup initial agents using AgentInfo
        for i in range(3):
            agent = AgentInfo(
                uid=i,
                agent_name=f"Agent{i}",
                github_url=f"https://github.com/test/agent{i}/tree/main",
                score=0.0
            )
            
            validator_with_agents.agents_dict[i] = agent
            validator_with_agents.agents_queue.put(agent)
        
        # Mock season_manager to return tasks
        mock_task = Mock()
        mock_task.id = "test-task"
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=[mock_task])
        
        # Mock deploy_agent to return proper instance
        mock_instance = Mock()
        mock_instance.base_url = "http://localhost:8001"
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=mock_instance)
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        # Mock evaluation
        async def mock_evaluate(*args, **kwargs):
            return (0.8, None, None)  # Return tuple as expected
        
        with patch(
            'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
            new=mock_evaluate
        ):
            with patch(
                "autoppia_web_agents_subnet.validator.evaluation.mixin.resolve_remote_ref_commit",
                return_value="deadbeef",
            ):
                # Should handle gracefully
                await validator_with_agents._run_evaluation_phase()
        
        # Should have evaluated agents
        evaluated = sum(1 for a in validator_with_agents.agents_dict.values() if a.score > 0)
        assert evaluated > 0
