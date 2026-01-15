"""
Unit tests for ValidatorEvaluationMixin.

Tests evaluation phase, agent deployment, and score calculation.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.models import AgentInfo


@pytest.mark.unit
@pytest.mark.asyncio
class TestEvaluationPhase:
    """Test evaluation phase logic."""

    async def test_run_evaluation_phase_processes_all_agents_in_queue(self, validator_with_agents, season_tasks):
        """Test that evaluation phase processes all agents in the queue."""
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator_with_agents.sandbox_manager = Mock()
        
        # Mock agent deployment
        mock_instance = Mock()
        mock_instance.base_url = "http://localhost:8001"
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=mock_instance)
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua') as mock_eval:
            with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
                mock_normalize.return_value = "https://github.com/test/agent"
                mock_eval.return_value = (0.8, None, None)
                
                agents_evaluated = await validator_with_agents._run_evaluation_phase()
                
                # Should have evaluated 3 agents
                assert agents_evaluated == 3

    async def test_evaluation_respects_maximum_evaluation_time(self, validator_with_agents, season_tasks):
        """Test that evaluation stops when approaching settlement time."""
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator_with_agents.sandbox_manager = Mock()
        
        # Mock wait_info to show insufficient time
        validator_with_agents.round_manager.get_wait_info = Mock(return_value={
            "minutes_to_settlement": 5.0,  # Less than MAXIMUM_EVALUATION_TIME
            "blocks_to_settlement": 25,
        })
        
        with patch('autoppia_web_agents_subnet.validator.config.MAXIMUM_EVALUATION_TIME', 10.0):
            agents_evaluated = await validator_with_agents._run_evaluation_phase()
            
            # Should stop early due to time constraint
            assert agents_evaluated == 0

    async def test_evaluation_updates_current_block_during_loop(self, validator_with_agents, season_tasks):
        """Test that evaluation uses current block for timing checks."""
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator_with_agents.sandbox_manager = Mock()
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=None)
        
        # Track block access
        block_accesses = []
        original_block = validator_with_agents.block
        
        def track_block():
            block_accesses.append(original_block)
            return original_block
        
        type(validator_with_agents).block = property(lambda self: track_block())
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
            mock_normalize.return_value = "https://github.com/test/agent"
            
            await validator_with_agents._run_evaluation_phase()
            
            # Should have accessed block multiple times
            assert len(block_accesses) > 0

    async def test_evaluation_enters_evaluation_phase(self, validator_with_agents, season_tasks):
        """Test that evaluation enters EVALUATION phase."""
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator_with_agents.sandbox_manager = Mock()
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=None)
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
            mock_normalize.return_value = None  # Skip all agents
            
            await validator_with_agents._run_evaluation_phase()
            
            assert validator_with_agents.round_manager.current_phase == RoundPhase.EVALUATION


@pytest.mark.unit
@pytest.mark.asyncio
class TestAgentDeployment:
    """Test agent deployment during evaluation."""

    async def test_evaluation_deploys_agents_via_sandbox_manager(self, validator_with_agents, season_tasks):
        """Test that evaluation deploys agents using sandbox_manager."""
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator_with_agents.sandbox_manager = Mock()
        
        mock_instance = Mock()
        mock_instance.base_url = "http://localhost:8001"
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=mock_instance)
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua') as mock_eval:
            with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
                mock_normalize.return_value = "https://github.com/test/agent"
                mock_eval.return_value = (0.8, None, None)
                
                await validator_with_agents._run_evaluation_phase()
                
                # Should have called deploy_agent
                assert validator_with_agents.sandbox_manager.deploy_agent.call_count == 3

    async def test_evaluation_skips_agents_with_invalid_github_url(self, validator_with_agents, season_tasks):
        """Test that evaluation skips agents with invalid GitHub URLs."""
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator_with_agents.sandbox_manager = Mock()
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
            mock_normalize.return_value = None  # Invalid URL
            
            agents_evaluated = await validator_with_agents._run_evaluation_phase()
            
            # Should skip all agents
            assert agents_evaluated == 0

    async def test_evaluation_handles_sandbox_deployment_failure(self, validator_with_agents, season_tasks):
        """Test that evaluation handles sandbox deployment failures gracefully."""
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator_with_agents.sandbox_manager = Mock()
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=None)  # Deployment fails
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
            mock_normalize.return_value = "https://github.com/test/agent"
            
            agents_evaluated = await validator_with_agents._run_evaluation_phase()
            
            # Should handle failure and continue
            assert agents_evaluated == 0

    async def test_evaluation_cleans_up_containers_after_evaluation(self, validator_with_agents, season_tasks):
        """Test that evaluation cleans up agent containers after evaluation."""
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator_with_agents.sandbox_manager = Mock()
        
        mock_instance = Mock()
        mock_instance.base_url = "http://localhost:8001"
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=mock_instance)
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua') as mock_eval:
            with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
                mock_normalize.return_value = "https://github.com/test/agent"
                mock_eval.return_value = (0.8, None, None)
                
                await validator_with_agents._run_evaluation_phase()
                
                # Should have called cleanup_agent for each deployed agent
                assert validator_with_agents.sandbox_manager.cleanup_agent.call_count == 3


@pytest.mark.unit
@pytest.mark.asyncio
class TestScoreCalculation:
    """Test score calculation during evaluation."""

    async def test_evaluation_calculates_average_score_across_tasks(self, validator_with_agents, season_tasks):
        """Test that evaluation calculates average score across all tasks."""
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator_with_agents.sandbox_manager = Mock()
        
        mock_instance = Mock()
        mock_instance.base_url = "http://localhost:8001"
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=mock_instance)
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua') as mock_eval:
            with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
                mock_normalize.return_value = "https://github.com/test/agent"
                # Return different scores for each task
                mock_eval.side_effect = [(0.8, None, None), (0.6, None, None), (1.0, None, None), (0.4, None, None), (0.7, None, None)]
                
                await validator_with_agents._run_evaluation_phase()
                
                # Check that agent scores were calculated (average of task scores)
                # First agent should have average score
                agent = validator_with_agents.agents_dict[1]
                expected_avg = (0.8 + 0.6 + 1.0 + 0.4 + 0.7) / 5
                assert abs(agent.score - expected_avg) < 0.01

    async def test_evaluation_updates_agent_score_in_agents_dict(self, validator_with_agents, season_tasks):
        """Test that evaluation updates agent.score in agents_dict."""
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator_with_agents.sandbox_manager = Mock()
        
        mock_instance = Mock()
        mock_instance.base_url = "http://localhost:8001"
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=mock_instance)
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua') as mock_eval:
            with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
                mock_normalize.return_value = "https://github.com/test/agent"
                mock_eval.return_value = (0.75, None, None)
                
                # Initial scores should be 0.0
                assert validator_with_agents.agents_dict[1].score == 0.0
                
                await validator_with_agents._run_evaluation_phase()
                
                # Scores should be updated
                assert validator_with_agents.agents_dict[1].score > 0.0

    async def test_evaluation_handles_empty_scores_list(self, validator_with_agents):
        """Test that evaluation handles case with no tasks gracefully."""
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=[])  # No tasks
        validator_with_agents.sandbox_manager = Mock()
        
        mock_instance = Mock()
        mock_instance.base_url = "http://localhost:8001"
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=mock_instance)
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
            mock_normalize.return_value = "https://github.com/test/agent"
            
            # Should handle empty task list without crashing
            try:
                await validator_with_agents._run_evaluation_phase()
            except ZeroDivisionError:
                pytest.fail("Should handle empty scores list without ZeroDivisionError")

    async def test_evaluation_handles_exceptions_in_evaluate_with_stateful_cua(self, validator_with_agents, season_tasks):
        """Test that evaluation handles exceptions during task evaluation."""
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        validator_with_agents.sandbox_manager = Mock()
        
        mock_instance = Mock()
        mock_instance.base_url = "http://localhost:8001"
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=mock_instance)
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua') as mock_eval:
            with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url') as mock_normalize:
                mock_normalize.return_value = "https://github.com/test/agent"
                mock_eval.side_effect = Exception("Evaluation failed")
                
                # Should handle exception and continue
                try:
                    await validator_with_agents._run_evaluation_phase()
                except Exception:
                    pytest.fail("Should handle evaluation exceptions gracefully")
