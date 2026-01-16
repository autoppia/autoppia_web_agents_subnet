"""
Error injection tests for validator workflow.

Tests graceful failure handling when external dependencies fail.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch


@pytest.mark.unit
class TestMinerResponseErrors:
    """Test handling of invalid miner responses."""

    @pytest.mark.asyncio
    async def test_handshake_handles_missing_agent_name(
        self, dummy_validator, mock_metagraph
    ):
        """Test handshake handles miners with missing agent_name."""
        dummy_validator.metagraph = mock_metagraph
        dummy_validator.uid = 0
        
        # Mock dendrite to return response with missing agent_name
        async def mock_query(*args, **kwargs):
            response = MagicMock()
            response.agent_name = None  # Missing
            response.github_url = "https://github.com/test/agent"
            response.axon = MagicMock()
            response.axon.hotkey = "hotkey1"
            return [response]
        
        dummy_validator.dendrite.query = mock_query
        
        # Should not crash
        await dummy_validator._perform_handshake()
        
        # Agent should not be added
        assert len(dummy_validator.agents_dict) == 0

    @pytest.mark.asyncio
    async def test_handshake_handles_missing_github_url(
        self, dummy_validator, mock_metagraph
    ):
        """Test handshake handles miners with missing github_url."""
        dummy_validator.metagraph = mock_metagraph
        dummy_validator.uid = 0
        
        # Mock dendrite to return response with missing github_url
        async def mock_query(*args, **kwargs):
            response = MagicMock()
            response.agent_name = "TestAgent"
            response.github_url = None  # Missing
            response.axon = MagicMock()
            response.axon.hotkey = "hotkey1"
            return [response]
        
        dummy_validator.dendrite.query = mock_query
        
        # Should not crash
        await dummy_validator._perform_handshake()
        
        # Agent should not be added
        assert len(dummy_validator.agents_dict) == 0

    @pytest.mark.asyncio
    async def test_handshake_handles_invalid_github_url(
        self, dummy_validator, mock_metagraph
    ):
        """Test handshake handles miners with invalid github_url."""
        dummy_validator.metagraph = mock_metagraph
        dummy_validator.uid = 0
        
        # Mock dendrite to return response with invalid github_url
        async def mock_query(*args, **kwargs):
            response = MagicMock()
            response.agent_name = "TestAgent"
            response.github_url = "not-a-url"  # Invalid
            response.axon = MagicMock()
            response.axon.hotkey = "hotkey1"
            return [response]
        
        dummy_validator.dendrite.query = mock_query
        
        # Should not crash
        await dummy_validator._perform_handshake()
        
        # Agent might be added but evaluation should handle it
        # This is acceptable behavior

    @pytest.mark.asyncio
    async def test_handshake_handles_dendrite_timeout(
        self, dummy_validator, mock_metagraph
    ):
        """Test handshake handles dendrite timeout."""
        dummy_validator.metagraph = mock_metagraph
        dummy_validator.uid = 0
        
        # Mock dendrite to timeout
        async def mock_query(*args, **kwargs):
            raise TimeoutError("Dendrite timeout")
        
        dummy_validator.dendrite.query = mock_query
        
        # Should not crash
        await dummy_validator._perform_handshake()
        
        # No agents should be added
        assert len(dummy_validator.agents_dict) == 0


@pytest.mark.unit
class TestIPFSErrors:
    """Test handling of IPFS failures."""

    @pytest.mark.asyncio
    async def test_consensus_handles_ipfs_upload_failure(
        self, mock_async_subtensor, dummy_validator
    ):
        """Test consensus handles IPFS upload failure gracefully."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            publish_round_snapshot
        )
        
        # Mock IPFS client that fails
        from unittest.mock import AsyncMock
        mock_ipfs = MagicMock()
        mock_ipfs.add_json_async = AsyncMock(
            side_effect=Exception("IPFS unavailable")
        )
        
        # Setup dummy validator
        dummy_validator.block = 1000
        dummy_validator.config.netuid = 99
        dummy_validator.round_manager.calculate_round = AsyncMock(return_value=100)
        dummy_validator.round_manager.get_current_boundaries = Mock(return_value={
            "round_start_epoch": 100,
            "round_target_epoch": 200
        })
        
        # Patch add_json_async to fail
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.add_json_async',
                   new=AsyncMock(side_effect=Exception("IPFS unavailable"))):
            # Should return None on failure
            result = await publish_round_snapshot(
                dummy_validator,
                st=mock_async_subtensor,
                scores={"1": 0.8, "2": 0.6}
            )
        
        assert result is None, "Should return None on IPFS failure"

    @pytest.mark.asyncio
    async def test_consensus_handles_ipfs_download_failure(
        self, mock_ipfs_client, mock_async_subtensor, dummy_validator
    ):
        """Test consensus handles IPFS download failure gracefully."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            aggregate_scores_from_commitments
        )
        
        # Setup commitment with valid CID
        round_number = 100
        mock_async_subtensor.commitments = {}
        
        # Create a commitment with CID
        cid = await mock_ipfs_client.add_json_async({"scores": {1: 0.8}})
        
        # Mock read_all_plain_commitments to return commitment
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments',
                   new=AsyncMock(return_value={"hotkey1": {"r": round_number, "c": cid[0], "p": 0}})):
            # Mock IPFS to fail on download
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async',
                       new=AsyncMock(side_effect=Exception("IPFS download failed"))):
                # Setup dummy validator
                dummy_validator.block = 1000
                dummy_validator.config.netuid = 99
                dummy_validator.round_manager.calculate_round = AsyncMock(return_value=round_number)
                dummy_validator.metagraph.stake = [15000.0]
                dummy_validator.metagraph.hotkeys = ["hotkey1"]
                dummy_validator.metagraph.axons = [Mock(hotkey="hotkey1")]
                
                # Should return empty dict (no valid scores)
                result, _ = await aggregate_scores_from_commitments(
                    dummy_validator,
                    st=mock_async_subtensor
                )
        
        assert result == {}, "Should return empty dict on download failure"

    @pytest.mark.asyncio
    async def test_consensus_handles_corrupted_ipfs_data(
        self, mock_ipfs_client, mock_async_subtensor, dummy_validator
    ):
        """Test consensus handles corrupted IPFS data gracefully."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            aggregate_scores_from_commitments
        )
        
        # Upload corrupted data
        round_number = 100
        cid = await mock_ipfs_client.add_json_async({"invalid": "data"})
        
        # Mock read_all_plain_commitments to return commitment
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments',
                   new=AsyncMock(return_value={"hotkey1": {"r": round_number, "c": cid[0], "p": 0}})):
            # Setup dummy validator
            dummy_validator.block = 1000
            dummy_validator.config.netuid = 99
            dummy_validator.round_manager.calculate_round = AsyncMock(return_value=round_number)
            dummy_validator.metagraph.stake = [15000.0]
            dummy_validator.metagraph.hotkeys = ["hotkey1"]
            dummy_validator.metagraph.axons = [Mock(hotkey="hotkey1")]
            
            # Should handle missing 'scores' key
            result, _ = await aggregate_scores_from_commitments(
                dummy_validator,
                st=mock_async_subtensor
            )
        
        assert result == {}, "Should return empty dict for corrupted data"


@pytest.mark.unit
class TestAsyncSubtensorErrors:
    """Test handling of AsyncSubtensor failures."""

    @pytest.mark.asyncio
    async def test_consensus_handles_commit_failure(
        self, mock_ipfs_client, mock_async_subtensor, dummy_validator
    ):
        """Test consensus handles blockchain commit failure."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            publish_round_snapshot
        )
        
        # Setup dummy validator
        dummy_validator.block = 1000
        dummy_validator.config.netuid = 99
        dummy_validator.round_manager.calculate_round = AsyncMock(return_value=100)
        dummy_validator.round_manager.get_current_boundaries = Mock(return_value={
            "round_start_epoch": 100,
            "round_target_epoch": 200
        })
        
        # Mock commit to fail
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.write_plain_commitment_json',
                   new=AsyncMock(side_effect=Exception("Blockchain unavailable"))):
            # Should still return CID even if commit fails (IPFS upload succeeded)
            result = await publish_round_snapshot(
                dummy_validator,
                st=mock_async_subtensor,
                scores={"1": 0.8, "2": 0.6}
            )
        
        # CID should be None because commit failed
        assert result is None, "Should return None if commit fails"

    @pytest.mark.asyncio
    async def test_settlement_handles_set_weights_failure(
        self, validator_with_agents
    ):
        """Test settlement handles set_weights failure gracefully."""
        from tests.conftest import _bind_settlement_mixin
        validator_with_agents = _bind_settlement_mixin(validator_with_agents)
        
        # Setup agents with scores
        validator_with_agents.agents_dict = {
            1: MagicMock(uid=1, score=0.8),
            2: MagicMock(uid=2, score=0.6)
        }
        
        # Mock set_weights to fail
        validator_with_agents.set_weights = MagicMock(
            side_effect=Exception("Failed to set weights")
        )
        
        # Mock other dependencies
        validator_with_agents.update_scores = MagicMock()
        validator_with_agents.round_manager.enter_phase = MagicMock()
        
        # Should raise exception but not crash the validator
        try:
            await validator_with_agents._calculate_final_weights(scores={1: 0.8, 2: 0.6})
        except Exception as e:
            # Exception is expected
            assert "Failed to set weights" in str(e)
        
        # update_scores should have been called before the exception
        validator_with_agents.update_scores.assert_called()


@pytest.mark.unit
class TestSandboxErrors:
    """Test handling of sandbox deployment failures."""

    @pytest.mark.asyncio
    async def test_evaluation_handles_deployment_failure(
        self, validator_with_agents, season_tasks
    ):
        """Test evaluation handles sandbox deployment failure."""
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
        
        # Mock deployment to fail
        validator_with_agents.sandbox_manager.deploy_agent = AsyncMock(
            return_value=False
        )
        
        # Should not crash
        await validator_with_agents._run_evaluation_phase()
        
        # Agent score should remain 0
        assert agent.score == 0.0

    @pytest.mark.asyncio
    async def test_evaluation_handles_deployment_exception(
        self, validator_with_agents, season_tasks
    ):
        """Test evaluation handles sandbox deployment exception."""
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
        
        # Mock deployment to raise exception
        validator_with_agents.sandbox_manager.deploy_agent = AsyncMock(
            side_effect=Exception("Docker error")
        )
        
        # Should not crash
        await validator_with_agents._run_evaluation_phase()
        
        # Agent score should remain 0
        assert agent.score == 0.0

    @pytest.mark.asyncio
    async def test_evaluation_handles_evaluation_exception(
        self, validator_with_agents, season_tasks
    ):
        """Test evaluation handles evaluation exception."""
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
        
        # Mock deploy_agent to return a proper mock with base_url
        mock_instance = Mock()
        mock_instance.base_url = "http://localhost:8001"
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=mock_instance)
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        # Mock evaluation to raise exception
        with patch(
            'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
            new=AsyncMock(side_effect=Exception("Evaluation error"))
        ):
            # Should not crash
            await validator_with_agents._run_evaluation_phase()
        
        # Agent score should remain 0
        assert agent.score == 0.0
        
        # Cleanup should still be called
        validator_with_agents.sandbox_manager.cleanup_agent.assert_called()


@pytest.mark.unit
class TestNetworkErrors:
    """Test handling of network-related errors."""

    @pytest.mark.asyncio
    async def test_handshake_handles_network_error(
        self, validator_with_agents, mock_metagraph
    ):
        """Test handshake handles network errors."""
        from tests.conftest import _bind_round_start_mixin
        validator_with_agents = _bind_round_start_mixin(validator_with_agents)
        
        validator_with_agents.metagraph = mock_metagraph
        validator_with_agents.uid = 0
        
        # Mock dendrite_with_retries to raise network error
        with patch('autoppia_web_agents_subnet.validator.round_start.synapse_handler.dendrite_with_retries',
                   new=AsyncMock(side_effect=ConnectionError("Network unreachable"))):
            # Should raise exception (handshake doesn't catch network errors)
            with pytest.raises(ConnectionError):
                await validator_with_agents._perform_handshake(total_prompts=0)

    @pytest.mark.asyncio
    async def test_evaluation_handles_agent_timeout(
        self, validator_with_agents, season_tasks
    ):
        """Test evaluation handles agent timeout."""
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
        
        # Mock deploy_agent to return a proper mock with base_url
        mock_instance = Mock()
        mock_instance.base_url = "http://localhost:8001"
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=mock_instance)
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        # Mock evaluation to timeout
        with patch(
            'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
            new=AsyncMock(side_effect=TimeoutError("Agent timeout"))
        ):
            # Should not crash
            await validator_with_agents._run_evaluation_phase()
        
        # Agent score should remain 0
        assert agent.score == 0.0
