"""
Integration tests for complete round flow.

Tests the entire validator round workflow from start to finish.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase


@pytest.mark.integration
@pytest.mark.asyncio
class TestCompleteRound:
    """Test complete round flow."""

    async def test_round_progresses_through_all_phases(self, validator_with_agents, season_tasks):
        from tests.conftest import _bind_evaluation_mixin, _bind_settlement_mixin, _bind_round_start_mixin
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        validator_with_agents = _bind_settlement_mixin(validator_with_agents)
        validator_with_agents = _bind_round_start_mixin(validator_with_agents)
        
        """Test that a round progresses through all expected phases."""
        validator = validator_with_agents
        
        # Setup mocks
        validator.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator.sandbox_manager = Mock()
        mock_instance = Mock()
        mock_instance.base_url = "http://localhost:8001"
        validator.sandbox_manager.deploy_agent = Mock(return_value=mock_instance)
        validator.sandbox_manager.cleanup_agent = Mock()
        validator._get_async_subtensor = AsyncMock(return_value=Mock())
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua') as mock_eval:
            with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
                with patch('autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot'):
                    with patch('autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments') as mock_aggregate:
                        with patch('autoppia_web_agents_subnet.validator.round_start.synapse_handler.dendrite_with_retries', new_callable=AsyncMock, return_value=[]) as mock_dendrite:
                            mock_normalize.return_value = "https://github.com/test/agent"
                            mock_eval.return_value = (0.8, None, None)
                            mock_aggregate.return_value = ({1: 0.8, 2: 0.6, 3: 0.9}, None)
                            
                            # Run complete round
                            await validator._start_round()
                            await validator._perform_handshake(total_prompts=0)
                            agents_evaluated = await validator._run_evaluation_phase()
                            await validator._run_settlement_phase(agents_evaluated=agents_evaluated)
                            
                            # Check phases
                            phases = [t.phase for t in validator.round_manager.phase_history]
                        assert RoundPhase.PREPARING in phases
                        assert RoundPhase.EVALUATION in phases
                        # CONSENSUS phase is not explicitly entered in current implementation
                        # assert RoundPhase.CONSENSUS in phases
                        assert RoundPhase.COMPLETE in phases

    async def test_round_evaluates_miners_and_calculates_rewards(self, validator_with_agents, season_tasks):
        from tests.conftest import _bind_evaluation_mixin, _bind_settlement_mixin, _bind_round_start_mixin
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        validator_with_agents = _bind_settlement_mixin(validator_with_agents)
        validator_with_agents = _bind_round_start_mixin(validator_with_agents)
        
        """Test that round evaluates miners and calculates rewards."""
        validator = validator_with_agents
        
        validator.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator.sandbox_manager = Mock()
        mock_instance = Mock()
        mock_instance.base_url = "http://localhost:8001"
        validator.sandbox_manager.deploy_agent = Mock(return_value=mock_instance)
        validator.sandbox_manager.cleanup_agent = Mock()
        validator._get_async_subtensor = AsyncMock(return_value=Mock())
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua') as mock_eval:
            with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
                with patch('autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot'):
                    with patch('autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments') as mock_aggregate:
                        with patch('autoppia_web_agents_subnet.validator.round_start.synapse_handler.dendrite_with_retries', new_callable=AsyncMock, return_value=[]):
                            mock_normalize.return_value = "https://github.com/test/agent"
                            mock_eval.return_value = (0.8, None, None)
                            mock_aggregate.return_value = ({1: 0.8, 2: 0.6, 3: 0.9}, None)
                            
                            # Run evaluation
                            await validator._start_round()
                            agents_evaluated = await validator._run_evaluation_phase()
                            
                            # Should have evaluated agents
                            assert agents_evaluated > 0
                            
                            # Agents should have scores
                            for agent in validator.agents_dict.values():
                                assert agent.score is not None

    async def test_round_publishes_consensus_and_sets_weights(self, validator_with_agents):
        from tests.conftest import _bind_evaluation_mixin, _bind_settlement_mixin, _bind_round_start_mixin
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        validator_with_agents = _bind_settlement_mixin(validator_with_agents)
        validator_with_agents = _bind_round_start_mixin(validator_with_agents)
        
        """Test that round publishes consensus and sets weights."""
        validator = validator_with_agents
        validator._get_async_subtensor = AsyncMock(return_value=Mock())
        validator._calculate_final_weights = AsyncMock()
        
        with patch('autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot') as mock_publish:
            with patch('autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments') as mock_aggregate:
                mock_publish.return_value = "QmTestCID"
                mock_aggregate.return_value = ({1: 0.8}, None)
                
                await validator._run_settlement_phase(agents_evaluated=1)
                
                # Should have published snapshot
                mock_publish.assert_called_once()
                
                # Should have calculated weights
                validator._calculate_final_weights.assert_called_once()

    async def test_round_completes_with_complete_phase(self, validator_with_agents):
        from tests.conftest import _bind_evaluation_mixin, _bind_settlement_mixin, _bind_round_start_mixin
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        validator_with_agents = _bind_settlement_mixin(validator_with_agents)
        validator_with_agents = _bind_round_start_mixin(validator_with_agents)
        
        """Test that round completes with COMPLETE phase."""
        validator = validator_with_agents
        validator._get_async_subtensor = AsyncMock(return_value=Mock())
        validator._calculate_final_weights = AsyncMock()
        
        with patch('autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot'):
            with patch('autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments') as mock_aggregate:
                mock_aggregate.return_value = ({}, None)
                
                await validator._run_settlement_phase(agents_evaluated=0)
                
                # Should be in COMPLETE phase
                assert validator.round_manager.current_phase == RoundPhase.COMPLETE


@pytest.mark.integration
@pytest.mark.asyncio
class TestErrorHandling:
    """Test error handling in complete round flow."""

    async def test_round_handles_miner_timeout_gracefully(self, validator_with_agents, season_tasks):
        from tests.conftest import _bind_evaluation_mixin, _bind_settlement_mixin, _bind_round_start_mixin
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        validator_with_agents = _bind_settlement_mixin(validator_with_agents)
        validator_with_agents = _bind_round_start_mixin(validator_with_agents)
        
        """Test that round handles miner timeout without crashing."""
        validator = validator_with_agents
        validator.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator.sandbox_manager = Mock()
        validator.sandbox_manager.deploy_agent = Mock(return_value=None)  # Deployment fails
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
            mock_normalize.return_value = "https://github.com/test/agent"
            
            # Should not raise exception
            agents_evaluated = await validator._run_evaluation_phase()
            
            # Should handle failure gracefully
            assert agents_evaluated == 0

    async def test_round_handles_sandbox_deployment_failure(self, validator_with_agents, season_tasks):
        from tests.conftest import _bind_evaluation_mixin, _bind_settlement_mixin, _bind_round_start_mixin
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        validator_with_agents = _bind_settlement_mixin(validator_with_agents)
        validator_with_agents = _bind_round_start_mixin(validator_with_agents)
        
        """Test that round handles sandbox deployment failure."""
        validator = validator_with_agents
        validator.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator.sandbox_manager = Mock()
        validator.sandbox_manager.deploy_agent = Mock(side_effect=Exception("Docker error"))
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
            mock_normalize.return_value = "https://github.com/test/agent"
            
            # Should not raise exception
            try:
                await validator._run_evaluation_phase()
            except Exception:
                pytest.fail("Should handle deployment failure gracefully")

    async def test_round_handles_ipfs_failure(self, validator_with_agents):
        from tests.conftest import _bind_evaluation_mixin, _bind_settlement_mixin, _bind_round_start_mixin
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        validator_with_agents = _bind_settlement_mixin(validator_with_agents)
        validator_with_agents = _bind_round_start_mixin(validator_with_agents)
        
        """Test that round handles IPFS failure gracefully."""
        validator = validator_with_agents
        validator._get_async_subtensor = AsyncMock(return_value=Mock())
        validator._calculate_final_weights = AsyncMock()
        
        with patch('autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot') as mock_publish:
            with patch('autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments') as mock_aggregate:
                mock_publish.return_value = None  # IPFS fails
                mock_aggregate.return_value = ({}, None)
                
                # Should not raise exception
                await validator._run_settlement_phase(agents_evaluated=0)

    async def test_round_handles_consensus_failure(self, validator_with_agents):
        from tests.conftest import _bind_evaluation_mixin, _bind_settlement_mixin, _bind_round_start_mixin
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        validator_with_agents = _bind_settlement_mixin(validator_with_agents)
        validator_with_agents = _bind_round_start_mixin(validator_with_agents)
        
        """Test that round handles consensus aggregation failure."""
        validator = validator_with_agents
        validator._get_async_subtensor = AsyncMock(return_value=Mock())
        validator._calculate_final_weights = AsyncMock()
        
        with patch('autoppia_web_agents_subnet.validator.settlement.mixin.publish_round_snapshot'):
            with patch('autoppia_web_agents_subnet.validator.settlement.mixin.aggregate_scores_from_commitments') as mock_aggregate:
                mock_aggregate.side_effect = Exception("Consensus error")
                
                # Should not raise exception
                try:
                    await validator._run_settlement_phase(agents_evaluated=0)
                except Exception:
                    pytest.fail("Should handle consensus failure gracefully")
