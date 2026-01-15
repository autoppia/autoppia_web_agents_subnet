"""
Error injection tests for validator workflow.

Tests graceful failure handling when external dependencies fail.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.unit
class TestMinerResponseErrors:
    """Test handling of invalid miner responses."""

    @pytest.mark.asyncio
    async def test_handshake_handles_missing_agent_name(
        self, validator_with_agents, mock_metagraph
    ):
        """Test handshake handles miners with missing agent_name."""
        validator_with_agents.metagraph = mock_metagraph
        validator_with_agents.uid = 0
        
        # Mock dendrite to return response with missing agent_name
        async def mock_query(*args, **kwargs):
            response = MagicMock()
            response.agent_name = None  # Missing
            response.github_url = "https://github.com/test/agent"
            response.axon = MagicMock()
            response.axon.hotkey = "hotkey1"
            return [response]
        
        validator_with_agents.dendrite.query = mock_query
        
        # Should not crash
        await validator_with_agents._perform_handshake()
        
        # Agent should not be added
        assert len(validator_with_agents.agents_dict) == 0

    @pytest.mark.asyncio
    async def test_handshake_handles_missing_github_url(
        self, validator_with_agents, mock_metagraph
    ):
        """Test handshake handles miners with missing github_url."""
        validator_with_agents.metagraph = mock_metagraph
        validator_with_agents.uid = 0
        
        # Mock dendrite to return response with missing github_url
        async def mock_query(*args, **kwargs):
            response = MagicMock()
            response.agent_name = "TestAgent"
            response.github_url = None  # Missing
            response.axon = MagicMock()
            response.axon.hotkey = "hotkey1"
            return [response]
        
        validator_with_agents.dendrite.query = mock_query
        
        # Should not crash
        await validator_with_agents._perform_handshake()
        
        # Agent should not be added
        assert len(validator_with_agents.agents_dict) == 0

    @pytest.mark.asyncio
    async def test_handshake_handles_invalid_github_url(
        self, validator_with_agents, mock_metagraph
    ):
        """Test handshake handles miners with invalid github_url."""
        validator_with_agents.metagraph = mock_metagraph
        validator_with_agents.uid = 0
        
        # Mock dendrite to return response with invalid github_url
        async def mock_query(*args, **kwargs):
            response = MagicMock()
            response.agent_name = "TestAgent"
            response.github_url = "not-a-url"  # Invalid
            response.axon = MagicMock()
            response.axon.hotkey = "hotkey1"
            return [response]
        
        validator_with_agents.dendrite.query = mock_query
        
        # Should not crash
        await validator_with_agents._perform_handshake()
        
        # Agent might be added but evaluation should handle it
        # This is acceptable behavior

    @pytest.mark.asyncio
    async def test_handshake_handles_dendrite_timeout(
        self, validator_with_agents, mock_metagraph
    ):
        """Test handshake handles dendrite timeout."""
        validator_with_agents.metagraph = mock_metagraph
        validator_with_agents.uid = 0
        
        # Mock dendrite to timeout
        async def mock_query(*args, **kwargs):
            raise TimeoutError("Dendrite timeout")
        
        validator_with_agents.dendrite.query = mock_query
        
        # Should not crash
        await validator_with_agents._perform_handshake()
        
        # No agents should be added
        assert len(validator_with_agents.agents_dict) == 0


@pytest.mark.unit
class TestIPFSErrors:
    """Test handling of IPFS failures."""

    @pytest.mark.asyncio
    async def test_consensus_handles_ipfs_upload_failure(
        self, mock_async_subtensor
    ):
        """Test consensus handles IPFS upload failure gracefully."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            publish_round_snapshot
        )
        
        # Mock IPFS client that fails
        mock_ipfs = MagicMock()
        mock_ipfs.add_json_async = AsyncMock(
            side_effect=Exception("IPFS unavailable")
        )
        
        # Should return None on failure
        result = await publish_round_snapshot(
            async_subtensor=mock_async_subtensor,
            ipfs_client=mock_ipfs,
            round_number=100,
            scores={"1": 0.8, "2": 0.6},
            validator_uid=0
        )
        
        assert result is None, "Should return None on IPFS failure"

    @pytest.mark.asyncio
    async def test_consensus_handles_ipfs_download_failure(
        self, mock_ipfs_client, mock_async_subtensor
    ):
        """Test consensus handles IPFS download failure gracefully."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            aggregate_scores_from_commitments
        )
        
        # Setup commitment with valid CID
        mock_async_subtensor.commitments[1] = {
            "round_number": 100,
            "cid": "invalid_cid",
            "block": 1000
        }
        mock_async_subtensor.stakes = {1: 1000.0}
        
        # Mock IPFS to fail on download
        mock_ipfs_client.get_json_async = AsyncMock(
            side_effect=Exception("IPFS download failed")
        )
        
        # Should return empty dict (no valid scores)
        result = await aggregate_scores_from_commitments(
            async_subtensor=mock_async_subtensor,
            ipfs_client=mock_ipfs_client,
            round_number=100,
            min_stake=100.0
        )
        
        assert result == {}, "Should return empty dict on download failure"

    @pytest.mark.asyncio
    async def test_consensus_handles_corrupted_ipfs_data(
        self, mock_ipfs_client, mock_async_subtensor
    ):
        """Test consensus handles corrupted IPFS data gracefully."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            aggregate_scores_from_commitments
        )
        
        # Upload corrupted data
        cid = await mock_ipfs_client.add_json_async({"invalid": "data"})
        
        mock_async_subtensor.commitments[1] = {
            "round_number": 100,
            "cid": cid[0],
            "block": 1000
        }
        mock_async_subtensor.stakes = {1: 1000.0}
        
        # Should handle missing 'scores' key
        result = await aggregate_scores_from_commitments(
            async_subtensor=mock_async_subtensor,
            ipfs_client=mock_ipfs_client,
            round_number=100,
            min_stake=100.0
        )
        
        assert result == {}, "Should return empty dict for corrupted data"


@pytest.mark.unit
class TestAsyncSubtensorErrors:
    """Test handling of AsyncSubtensor failures."""

    @pytest.mark.asyncio
    async def test_consensus_handles_commit_failure(
        self, mock_ipfs_client, mock_async_subtensor
    ):
        """Test consensus handles blockchain commit failure."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            publish_round_snapshot
        )
        
        # Mock commit to fail
        mock_async_subtensor.commit_round_snapshot = AsyncMock(
            side_effect=Exception("Blockchain unavailable")
        )
        
        # Should still return CID even if commit fails
        result = await publish_round_snapshot(
            async_subtensor=mock_async_subtensor,
            ipfs_client=mock_ipfs_client,
            round_number=100,
            scores={"1": 0.8, "2": 0.6},
            validator_uid=0
        )
        
        # CID should be returned (IPFS upload succeeded)
        assert result is not None, "Should return CID even if commit fails"

    @pytest.mark.asyncio
    async def test_settlement_handles_set_weights_failure(
        self, validator_with_agents
    ):
        """Test settlement handles set_weights failure gracefully."""
        # Setup agents with scores
        validator_with_agents.agents_dict = {
            1: MagicMock(uid=1, score=0.8),
            2: MagicMock(uid=2, score=0.6)
        }
        
        # Mock set_weights to fail
        validator_with_agents.set_weights = AsyncMock(
            side_effect=Exception("Failed to set weights")
        )
        
        # Mock other dependencies
        validator_with_agents.update_scores = MagicMock()
        validator_with_agents.round_manager.enter_phase = MagicMock()
        
        # Should not crash
        await validator_with_agents._calculate_final_weights()
        
        # Should still enter COMPLETE phase
        validator_with_agents.round_manager.enter_phase.assert_called()


@pytest.mark.unit
class TestSandboxErrors:
    """Test handling of sandbox deployment failures."""

    @pytest.mark.asyncio
    async def test_evaluation_handles_deployment_failure(
        self, validator_with_agents, season_tasks
    ):
        """Test evaluation handles sandbox deployment failure."""
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
        # Setup agent
        agent = MagicMock()
        agent.uid = 1
        agent.agent_name = "TestAgent"
        agent.github_url = "https://github.com/test/agent"
        agent.score = 0.0
        
        validator_with_agents.agents_dict = {1: agent}
        validator_with_agents.agents_queue.queue.clear()
        validator_with_agents.agents_queue.put(agent)
        
        validator_with_agents.sandbox_manager.deploy_agent = AsyncMock(return_value=True)
        validator_with_agents.sandbox_manager.cleanup_agent = AsyncMock()
        
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
        validator_with_agents.metagraph = mock_metagraph
        validator_with_agents.uid = 0
        
        # Mock dendrite to raise network error
        async def mock_query(*args, **kwargs):
            raise ConnectionError("Network unreachable")
        
        validator_with_agents.dendrite.query = mock_query
        
        # Should not crash
        await validator_with_agents._perform_handshake()
        
        # No agents should be added
        assert len(validator_with_agents.agents_dict) == 0

    @pytest.mark.asyncio
    async def test_evaluation_handles_agent_timeout(
        self, validator_with_agents, season_tasks
    ):
        """Test evaluation handles agent timeout."""
        # Setup agent
        agent = MagicMock()
        agent.uid = 1
        agent.agent_name = "TestAgent"
        agent.github_url = "https://github.com/test/agent"
        agent.score = 0.0
        
        validator_with_agents.agents_dict = {1: agent}
        validator_with_agents.agents_queue.queue.clear()
        validator_with_agents.agents_queue.put(agent)
        
        validator_with_agents.sandbox_manager.deploy_agent = AsyncMock(return_value=True)
        validator_with_agents.sandbox_manager.cleanup_agent = AsyncMock()
        
        # Mock evaluation to timeout
        with patch(
            'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
            new=AsyncMock(side_effect=TimeoutError("Agent timeout"))
        ):
            # Should not crash
            await validator_with_agents._run_evaluation_phase()
        
        # Agent score should remain 0
        assert agent.score == 0.0
