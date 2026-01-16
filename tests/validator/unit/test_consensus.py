"""
Unit tests for Consensus module.

Tests IPFS publishing and score aggregation.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase


@pytest.mark.unit
@pytest.mark.asyncio
class TestIPFSPublishing:
    """Test IPFS publishing logic."""

    async def test_publish_round_snapshot_creates_correct_payload(self, dummy_validator):
        """Test that publish_round_snapshot creates payload with correct structure."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.wallet = Mock()
        dummy_validator.wallet.hotkey.ss58_address = "test_hotkey"
        dummy_validator.current_round_id = "round-1"
        dummy_validator.version = "1.0.0"
        
        scores = {1: 0.8, 2: 0.6}
        
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.add_json_async') as mock_add:
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.write_plain_commitment_json') as mock_write:
                with patch('autoppia_web_agents_subnet.validator.settlement.consensus.ENABLE_DISTRIBUTED_CONSENSUS', True):
                    mock_add.return_value = ("QmTest123", "sha256hex", 1024)
                    mock_write.return_value = True
                    
                    from autoppia_web_agents_subnet.validator.settlement.consensus import publish_round_snapshot
                    cid = await publish_round_snapshot(dummy_validator, st=Mock(), scores=scores)
                    
                    # Should have called add_json_async with payload
                    mock_add.assert_called_once()
                    payload = mock_add.call_args[0][0]
                    
                    assert payload['v'] == 2
                    assert 'r' in payload
                    assert payload['scores'] == scores
                    assert payload['hk'] == "test_hotkey"

    async def test_publishing_returns_cid_on_success(self, dummy_validator):
        """Test that publishing returns CID when successful."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.wallet = Mock()
        dummy_validator.wallet.hotkey.ss58_address = "test_hotkey"
        
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.add_json_async') as mock_add:
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.write_plain_commitment_json') as mock_write:
                with patch('autoppia_web_agents_subnet.validator.settlement.consensus.ENABLE_DISTRIBUTED_CONSENSUS', True):
                    mock_add.return_value = ("QmTest123", "sha256hex", 1024)
                    mock_write.return_value = True
                    
                    from autoppia_web_agents_subnet.validator.settlement.consensus import publish_round_snapshot
                    cid = await publish_round_snapshot(dummy_validator, st=Mock(), scores={})
                    
                    assert cid == "QmTest123"

    async def test_publishing_returns_none_on_ipfs_failure(self, dummy_validator):
        """Test that publishing returns None when IPFS upload fails."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.wallet = Mock()
        dummy_validator.wallet.hotkey.ss58_address = "test_hotkey"
        
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.add_json_async') as mock_add:
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.ENABLE_DISTRIBUTED_CONSENSUS', True):
                mock_add.side_effect = Exception("IPFS connection failed")
                
                from autoppia_web_agents_subnet.validator.settlement.consensus import publish_round_snapshot
                cid = await publish_round_snapshot(dummy_validator, st=Mock(), scores={})
                
                assert cid is None

    async def test_publishing_commits_to_blockchain(self, dummy_validator):
        """Test that publishing commits CID to blockchain."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.wallet = Mock()
        dummy_validator.wallet.hotkey.ss58_address = "test_hotkey"
        
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.add_json_async') as mock_add:
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.write_plain_commitment_json') as mock_write:
                with patch('autoppia_web_agents_subnet.validator.settlement.consensus.ENABLE_DISTRIBUTED_CONSENSUS', True):
                    mock_add.return_value = ("QmTest123", "sha256hex", 1024)
                    mock_write.return_value = True
                    
                    from autoppia_web_agents_subnet.validator.settlement.consensus import publish_round_snapshot
                    await publish_round_snapshot(dummy_validator, st=Mock(), scores={})
                    
                    # Should have called write_plain_commitment_json
                    mock_write.assert_called_once()

    async def test_publishing_handles_commit_failure(self, dummy_validator):
        """Test that publishing handles blockchain commit failure gracefully."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.wallet = Mock()
        dummy_validator.wallet.hotkey.ss58_address = "test_hotkey"
        
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.add_json_async') as mock_add:
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.write_plain_commitment_json') as mock_write:
                with patch('autoppia_web_agents_subnet.validator.settlement.consensus.ENABLE_DISTRIBUTED_CONSENSUS', True):
                    mock_add.return_value = ("QmTest123", "sha256hex", 1024)
                    mock_write.return_value = False  # Commit fails
                    
                    from autoppia_web_agents_subnet.validator.settlement.consensus import publish_round_snapshot
                    cid = await publish_round_snapshot(dummy_validator, st=Mock(), scores={})
                    
                    # Should return None when commit fails
                    assert cid is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestScoreAggregation:
    """Test score aggregation from commitments."""

    async def test_aggregate_scores_filters_by_round(self, dummy_validator):
        """Test that aggregation only includes commitments for current round."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.round_manager.calculate_round = AsyncMock(return_value=5)
        
        # Mock commitments with different rounds
        mock_commits = {
            "hotkey1": {"r": 5, "c": "QmCID1"},  # Current round
            "hotkey2": {"r": 4, "c": "QmCID2"},  # Old round
            "hotkey3": {"r": 5, "c": "QmCID3"},  # Current round
        }
        
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments') as mock_read:
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async') as mock_get:
                mock_read.return_value = mock_commits
                mock_get.return_value = ({"scores": {1: 0.8}}, None, None)
                
                from autoppia_web_agents_subnet.validator.settlement.consensus import aggregate_scores_from_commitments
                scores, details = await aggregate_scores_from_commitments(dummy_validator, st=Mock())
                
                # Should only fetch CIDs for round 5
                assert mock_get.call_count == 2  # Only hotkey1 and hotkey3

    async def test_aggregation_filters_by_stake_threshold(self, dummy_validator):
        """Test that aggregation filters out validators below stake threshold."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.round_manager.calculate_round = AsyncMock(return_value=5)
        
        # Set up metagraph with stakes
        dummy_validator.metagraph.stake = [100.0, 50.0, 200.0]  # Only UIDs 0 and 2 meet threshold
        dummy_validator.metagraph.hotkeys = ["hotkey1", "hotkey2", "hotkey3"]
        
        mock_commits = {
            "hotkey1": {"r": 5, "c": "QmCID1"},  # 100 TAO - meets threshold
            "hotkey2": {"r": 5, "c": "QmCID2"},  # 50 TAO - below threshold
            "hotkey3": {"r": 5, "c": "QmCID3"},  # 200 TAO - meets threshold
        }
        
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments') as mock_read:
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async') as mock_get:
                with patch('autoppia_web_agents_subnet.validator.settlement.consensus.MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO', 75.0):
                    mock_read.return_value = mock_commits
                    mock_get.return_value = ({"scores": {1: 0.8}}, None, None)
                    
                    from autoppia_web_agents_subnet.validator.settlement.consensus import aggregate_scores_from_commitments
                    scores, details = await aggregate_scores_from_commitments(dummy_validator, st=Mock())
                    
                    # Should only fetch CIDs for hotkey1 and hotkey3 (above threshold)
                    assert mock_get.call_count == 2

    async def test_aggregation_handles_ipfs_download_failure(self, dummy_validator):
        """Test that aggregation handles IPFS download failures gracefully."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.round_manager.calculate_round = AsyncMock(return_value=5)
        
        mock_commits = {
            "hotkey1": {"r": 5, "c": "QmCID1"},
            "hotkey2": {"r": 5, "c": "QmCID2"},
        }
        
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments') as mock_read:
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async') as mock_get:
                mock_read.return_value = mock_commits
                # First call succeeds, second fails
                mock_get.side_effect = [
                    ({"scores": {1: 0.8}}, None, None),
                    Exception("IPFS download failed")
                ]
                
                from autoppia_web_agents_subnet.validator.settlement.consensus import aggregate_scores_from_commitments
                scores, details = await aggregate_scores_from_commitments(dummy_validator, st=Mock())
                
                # Should continue despite failure
                assert isinstance(scores, dict)

    async def test_aggregation_uses_stake_weighted_average(self, dummy_validator):
        """Test that aggregation uses stake-weighted average for scores."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.round_manager.calculate_round = AsyncMock(return_value=5)
        
        # Set up metagraph with different stakes (above MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO)
        dummy_validator.metagraph.stake = [10000.0, 20000.0]
        dummy_validator.metagraph.hotkeys = ["hotkey1", "hotkey2"]
        
        mock_commits = {
            "hotkey1": {"r": 5, "c": "QmCID1"},  # 10000 TAO stake
            "hotkey2": {"r": 5, "c": "QmCID2"},  # 20000 TAO stake
        }
        
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments') as mock_read:
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async') as mock_get:
                mock_read.return_value = mock_commits
                # hotkey1 gives UID 1 score 0.6, hotkey2 gives UID 1 score 0.9
                mock_get.side_effect = [
                    ({"scores": {"1": 0.6}}, None, None),
                    ({"scores": {"1": 0.9}}, None, None),
                ]
                
                from autoppia_web_agents_subnet.validator.settlement.consensus import aggregate_scores_from_commitments
                scores, details = await aggregate_scores_from_commitments(dummy_validator, st=Mock())
                
                # Weighted average: (10000*0.6 + 20000*0.9) / (10000+20000) = 24000/30000 = 0.8
                assert 1 in scores
                assert abs(scores[1] - 0.8) < 0.01

    async def test_aggregation_uses_simple_average_when_all_stakes_zero(self, dummy_validator):
        """Test that aggregation uses simple average when all stakes are zero."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.round_manager.calculate_round = AsyncMock(return_value=5)
        
        # All stakes are zero
        dummy_validator.metagraph.stake = [0.0, 0.0]
        dummy_validator.metagraph.hotkeys = ["hotkey1", "hotkey2"]
        
        mock_commits = {
            "hotkey1": {"r": 5, "c": "QmCID1"},
            "hotkey2": {"r": 5, "c": "QmCID2"},
        }
        
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments') as mock_read:
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async') as mock_get:
                with patch('autoppia_web_agents_subnet.validator.settlement.consensus.MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO', 0.0):
                    mock_read.return_value = mock_commits
                    mock_get.side_effect = [
                        ({"scores": {"1": 0.6}}, None, None),
                        ({"scores": {"1": 0.8}}, None, None),
                    ]
                    
                    from autoppia_web_agents_subnet.validator.settlement.consensus import aggregate_scores_from_commitments
                    scores, details = await aggregate_scores_from_commitments(dummy_validator, st=Mock())
                    
                    # Simple average: (0.6 + 0.8) / 2 = 0.7
                    assert 1 in scores
                    assert abs(scores[1] - 0.7) < 0.01

    async def test_aggregation_returns_empty_dict_when_no_validators(self, dummy_validator):
        """Test that aggregation returns empty dict when no validators included."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.round_manager.calculate_round = AsyncMock(return_value=5)
        
        # No commitments
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments') as mock_read:
            mock_read.return_value = {}
            
            from autoppia_web_agents_subnet.validator.settlement.consensus import aggregate_scores_from_commitments
            scores, details = await aggregate_scores_from_commitments(dummy_validator, st=Mock())
            
            assert scores == {}


@pytest.mark.unit
@pytest.mark.asyncio
class TestCommitmentFiltering:
    """Test commitment filtering logic."""

    async def test_filtering_excludes_wrong_round_numbers(self, dummy_validator):
        """Test that filtering excludes commitments with wrong round number."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.round_manager.calculate_round = AsyncMock(return_value=5)
        
        mock_commits = {
            "hotkey1": {"r": 5, "c": "QmCID1"},  # Correct round
            "hotkey2": {"r": 3, "c": "QmCID2"},  # Wrong round
            "hotkey3": {"r": 6, "c": "QmCID3"},  # Wrong round
        }
        
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments') as mock_read:
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async') as mock_get:
                mock_read.return_value = mock_commits
                mock_get.return_value = ({"scores": {}}, None, None)
                
                from autoppia_web_agents_subnet.validator.settlement.consensus import aggregate_scores_from_commitments
                await aggregate_scores_from_commitments(dummy_validator, st=Mock())
                
                # Should only fetch CID for hotkey1
                assert mock_get.call_count == 1

    async def test_filtering_excludes_missing_cids(self, dummy_validator):
        """Test that filtering excludes commitments without CID."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.round_manager.calculate_round = AsyncMock(return_value=5)
        
        mock_commits = {
            "hotkey1": {"r": 5, "c": "QmCID1"},  # Has CID
            "hotkey2": {"r": 5},  # Missing CID
            "hotkey3": {"r": 5, "c": ""},  # Empty CID
        }
        
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments') as mock_read:
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async') as mock_get:
                mock_read.return_value = mock_commits
                mock_get.return_value = ({"scores": {}}, None, None)
                
                from autoppia_web_agents_subnet.validator.settlement.consensus import aggregate_scores_from_commitments
                await aggregate_scores_from_commitments(dummy_validator, st=Mock())
                
                # Should only fetch CID for hotkey1
                assert mock_get.call_count == 1

    async def test_filtering_handles_invalid_payload_structures(self, dummy_validator):
        """Test that filtering handles invalid payload structures gracefully."""
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.round_manager.calculate_round = AsyncMock(return_value=5)
        
        mock_commits = {
            "hotkey1": {"r": 5, "c": "QmCID1"},
            "hotkey2": "invalid_structure",  # Not a dict
            "hotkey3": {"r": 5, "c": "QmCID3"},
        }
        
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments') as mock_read:
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async') as mock_get:
                mock_read.return_value = mock_commits
                mock_get.return_value = ({"scores": {}}, None, None)
                
                from autoppia_web_agents_subnet.validator.settlement.consensus import aggregate_scores_from_commitments
                scores, details = await aggregate_scores_from_commitments(dummy_validator, st=Mock())
                
                # Should skip invalid structure and continue
                assert isinstance(scores, dict)
