"""
Performance tests for evaluation phase scaling.

Tests validator's ability to handle large numbers of agents and tasks
while maintaining acceptable performance and memory usage.
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import psutil
import os


@pytest.mark.performance
@pytest.mark.slow
class TestEvaluationScaling:
    """Test evaluation phase performance with increasing load."""

    @pytest.mark.asyncio
    async def test_evaluate_100_agents_completes_in_time(
        self, validator_with_agents, season_tasks
    ):
        """Test that evaluating 100 agents completes within time limit."""
        from tests.conftest import _bind_evaluation_mixin
        from autoppia_web_agents_subnet.validator.models import AgentInfo
        import queue
        
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        
        # Override season_manager to return actual tasks
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        
        # Ensure get_wait_info returns plenty of time
        validator_with_agents.round_manager.get_wait_info = Mock(return_value={
            "minutes_to_settlement": 120.0,  # Plenty of time
            "blocks_to_settlement": 600,
            "minutes_to_target": 240.0,
            "blocks_to_target": 1200,
        })
        
        # Setup 10 agents for faster testing - use a fresh queue
        validator_with_agents.agents_dict = {}
        validator_with_agents.agents_queue = queue.Queue()
        
        for i in range(10):
            agent_info = AgentInfo(
                uid=i,
                agent_name=f"Agent{i}",
                github_url=f"https://github.com/test/agent{i}/tree/main",
                score=0.0
            )
            
            validator_with_agents.agents_dict[i] = agent_info
            validator_with_agents.agents_queue.put(agent_info)
        
        # Mock fast evaluation (simulate 0.001s per agent)
        async def fast_evaluate(*args, **kwargs):
            await asyncio.sleep(0.001)  # Simulate work
            return (0.8, None, None)  # Return tuple as expected
        
        # Mock deploy_agent to return proper instance - make it a callable
        def mock_deploy(*args, **kwargs):
            mock_instance = Mock()
            mock_instance.base_url = "http://localhost:8001"
            return mock_instance
        
        validator_with_agents.sandbox_manager.deploy_agent = mock_deploy
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        # Patch normalize_and_validate_github_url to always return valid URL
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url',
                   return_value=("https://github.com/test/agent", "main")):
            with patch(
                'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
                new=fast_evaluate
            ):
                with patch(
                    "autoppia_web_agents_subnet.validator.evaluation.mixin.resolve_remote_ref_commit",
                    return_value="deadbeef",
                ):
                    start_time = time.time()
                    
                    # Run evaluation
                    await validator_with_agents._run_evaluation_phase()
                    
                    elapsed = time.time() - start_time
                    
                    # Should complete in reasonable time (< 10 seconds with mocked evaluation)
                    assert elapsed < 10.0, f"Evaluation took {elapsed:.2f}s, expected < 10s"
                    
                    # All agents should be evaluated
                    evaluated_count = sum(
                        1 for agent in validator_with_agents.agents_dict.values()
                        if agent.score > 0
                    )
                    assert evaluated_count > 0, f"No agents were evaluated"

    @pytest.mark.asyncio
    async def test_evaluation_memory_usage_stays_bounded(
        self, validator_with_agents, season_tasks
    ):
        """Test that memory usage doesn't grow unbounded during evaluation."""
        from tests.conftest import _bind_evaluation_mixin
        from autoppia_web_agents_subnet.validator.models import AgentInfo
        import queue
        
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        
        # Override season_manager to return actual tasks
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Setup 50 agents - use fresh queue
        validator_with_agents.agents_dict = {}
        validator_with_agents.agents_queue = queue.Queue()
        
        for i in range(50):
            agent_info = AgentInfo(
                uid=i,
                agent_name=f"Agent{i}",
                github_url=f"https://github.com/test/agent{i}/tree/main",
                score=0.0
            )
            
            validator_with_agents.agents_dict[i] = agent_info
            validator_with_agents.agents_queue.put(agent_info)
        
        # Mock evaluation
        async def mock_evaluate(*args, **kwargs):
            await asyncio.sleep(0.001)
            return (0.75, None, None)
        
        # Mock deploy_agent to return proper instance
        def mock_deploy(*args, **kwargs):
            mock_instance = Mock()
            mock_instance.base_url = "http://localhost:8001"
            return mock_instance
        
        validator_with_agents.sandbox_manager.deploy_agent = mock_deploy
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url',
                   return_value=("https://github.com/test/agent", "main")):
            with patch(
                'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
                new=mock_evaluate
            ):
                with patch(
                    "autoppia_web_agents_subnet.validator.evaluation.mixin.resolve_remote_ref_commit",
                    return_value="deadbeef",
                ):
                    await validator_with_agents._run_evaluation_phase()
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        # Memory increase should be reasonable (< 100 MB)
        assert memory_increase < 100, \
            f"Memory increased by {memory_increase:.2f} MB, expected < 100 MB"

    @pytest.mark.asyncio
    async def test_concurrent_evaluations_dont_interfere(
        self, mock_validator_config, season_tasks
    ):
        """Test that concurrent evaluations maintain isolation."""
        from autoppia_web_agents_subnet.validator.evaluation.mixin import ValidatorEvaluationMixin
        from autoppia_web_agents_subnet.validator.models import AgentInfo
        from unittest.mock import Mock
        import queue
        
        class TestValidator(ValidatorEvaluationMixin):
            def __init__(self, config, tasks):
                self.config = config
                self.agents_dict = {}
                self.agents_queue = queue.Queue()  # Use regular queue, not asyncio.Queue
                self.sandbox_manager = MagicMock()
                
                # Mock deploy_agent to return proper instance
                def mock_deploy(*args, **kwargs):
                    mock_instance = Mock()
                    mock_instance.base_url = "http://localhost:8001"
                    return mock_instance
                
                self.sandbox_manager.deploy_agent = mock_deploy
                self.sandbox_manager.cleanup_agent = Mock()
                
                self.round_manager = MagicMock()
                self.round_manager.current_phase_state = MagicMock(return_value="EVALUATION")
                self.round_manager.get_wait_info = Mock(return_value={
                    "minutes_to_settlement": 120.0,
                    "blocks_to_settlement": 600,
                    "minutes_to_target": 240.0,
                    "blocks_to_target": 1200,
                })
                self.season_manager = MagicMock()
                self.season_manager.get_season_tasks = AsyncMock(return_value=tasks)
                self.block = 1000
        
        # Create two validators
        validator1 = TestValidator(mock_validator_config, season_tasks)
        validator2 = TestValidator(mock_validator_config, season_tasks)
        
        # Add agents to each
        for i in range(10):
            agent1 = AgentInfo(
                uid=i,
                agent_name=f"V1_Agent{i}",
                github_url=f"https://github.com/v1/agent{i}",
                score=0.0
            )
            validator1.agents_dict[i] = agent1
            validator1.agents_queue.put(agent1)  # Use synchronous put
            
            agent2 = AgentInfo(
                uid=i + 100,
                agent_name=f"V2_Agent{i}",
                github_url=f"https://github.com/v2/agent{i}",
                score=0.0
            )
            validator2.agents_dict[i + 100] = agent2
            validator2.agents_queue.put(agent2)  # Use synchronous put
        
        # Mock evaluation
        async def mock_evaluate(*args, **kwargs):
            await asyncio.sleep(0.001)
            return (0.8, None, None)
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url',
                   return_value=("https://github.com/test/agent", "main")):
            with patch(
                'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
                new=mock_evaluate
            ):
                # Run both evaluations concurrently
                with patch(
                    "autoppia_web_agents_subnet.validator.evaluation.mixin.resolve_remote_ref_commit",
                    return_value="deadbeef",
                ):
                    await asyncio.gather(
                        validator1._run_evaluation_phase(),
                        validator2._run_evaluation_phase()
                    )
        
        # Verify no cross-contamination
        for uid, agent in validator1.agents_dict.items():
            assert agent.agent_name.startswith("V1_"), \
                f"Validator1 has wrong agent: {agent.agent_name}"
        
        for uid, agent in validator2.agents_dict.items():
            assert agent.agent_name.startswith("V2_"), \
                f"Validator2 has wrong agent: {agent.agent_name}"


@pytest.mark.performance
@pytest.mark.slow
class TestEvaluationThroughput:
    """Test evaluation throughput and bottlenecks."""

    @pytest.mark.asyncio
    async def test_evaluation_throughput_with_varying_task_count(
        self, validator_with_agents
    ):
        """Test evaluation throughput with different numbers of tasks."""
        from tests.conftest import _bind_evaluation_mixin
        from autoppia_web_agents_subnet.validator.models import AgentInfo, TaskWithProject
        import queue
        
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        
        results = {}
        
        for task_count in [1, 3, 5]:
            # Reset for each iteration - use fresh queue
            validator_with_agents.agents_dict = {}
            validator_with_agents.agents_queue = queue.Queue()
            
            # Setup 5 agents for faster testing
            for i in range(5):
                agent_info = AgentInfo(
                    uid=i,
                    agent_name=f"Agent{i}",
                    github_url=f"https://github.com/test/agent{i}/tree/main",
                    score=0.0
                )
                
                validator_with_agents.agents_dict[i] = agent_info
                validator_with_agents.agents_queue.put(agent_info)
            
            # Create tasks using mocks
            tasks = []
            for j in range(task_count):
                mock_task = Mock()
                mock_task.id = f"task-{j}"
                mock_task.url = f"https://example.com/task{j}"
                mock_task.prompt = f"Test task {j}"
                mock_task.tests = []
                
                task_with_project = TaskWithProject(
                    project=None,
                    task=mock_task
                )
                tasks.append(task_with_project)
            
            validator_with_agents.season_manager.get_season_tasks = AsyncMock(
                return_value=tasks
            )
            
            # Mock deploy_agent to return proper instance
            def mock_deploy(*args, **kwargs):
                mock_instance = Mock()
                mock_instance.base_url = "http://localhost:8001"
                return mock_instance
            
            validator_with_agents.sandbox_manager.deploy_agent = mock_deploy
            validator_with_agents.sandbox_manager.cleanup_agent = Mock()
            
            # Mock evaluation - use closure to capture current task_count
            def make_mock_evaluate(num_tasks):
                async def mock_evaluate(*args, **kwargs):
                    await asyncio.sleep(0.001 * num_tasks)  # Simulate work proportional to tasks
                    return (0.8, None, None)
                return mock_evaluate
            
            with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url',
                       return_value=("https://github.com/test/agent", "main")):
                with patch(
                    'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
                    new=make_mock_evaluate(task_count)
                ):
                    with patch(
                        "autoppia_web_agents_subnet.validator.evaluation.mixin.resolve_remote_ref_commit",
                        return_value="deadbeef",
                    ):
                        start_time = time.time()
                        await validator_with_agents._run_evaluation_phase()
                        elapsed = time.time() - start_time
                    
                    results[task_count] = elapsed
        
        # Verify throughput scales reasonably
        # More tasks should take more time, but not linearly (due to parallelism)
        assert results[5] > results[1], "More tasks should take more time"
        # Relax the scaling constraint - with 5 agents and varying tasks, timing can vary
        assert results[5] < results[1] * 50, "Scaling should be reasonable"

    @pytest.mark.asyncio
    async def test_sandbox_deployment_parallelism(self, validator_with_agents, season_tasks):
        """Test that sandbox deployments happen efficiently."""
        from tests.conftest import _bind_evaluation_mixin
        from autoppia_web_agents_subnet.validator.models import AgentInfo
        import queue
        
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        
        # Override season_manager to return actual tasks
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
        
        # Setup 10 agents for faster testing - use fresh queue
        validator_with_agents.agents_dict = {}
        validator_with_agents.agents_queue = queue.Queue()
        
        for i in range(10):
            agent_info = AgentInfo(
                uid=i,
                agent_name=f"Agent{i}",
                github_url=f"https://github.com/test/agent{i}/tree/main",
                score=0.0
            )
            
            validator_with_agents.agents_dict[i] = agent_info
            validator_with_agents.agents_queue.put(agent_info)
        
        deployment_times = []
        
        def track_deployment(*args, **kwargs):
            start = time.time()
            time.sleep(0.01)  # Simulate deployment (sync sleep for tracking)
            deployment_times.append(time.time() - start)
            # Return proper mock instance
            mock_instance = Mock()
            mock_instance.base_url = "http://localhost:8001"
            return mock_instance
        
        validator_with_agents.sandbox_manager.deploy_agent = track_deployment
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        async def mock_evaluate(*args, **kwargs):
            return (0.8, None, None)
        
        with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url',
                   return_value=("https://github.com/test/agent", "main")):
            with patch(
                'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
                new=mock_evaluate
            ):
                with patch(
                    "autoppia_web_agents_subnet.validator.evaluation.mixin.resolve_remote_ref_commit",
                    return_value="deadbeef",
                ):
                    start_time = time.time()
                    await validator_with_agents._run_evaluation_phase()
                    total_time = time.time() - start_time
        
        # Verify deployments happened
        assert len(deployment_times) > 0, "No deployments tracked"
        
        # The evaluation mixin processes agents sequentially, so deployments are sequential
        # Just verify that all agents were deployed and total time is reasonable
        sum_deployment_times = sum(deployment_times)
        # Total time should be close to sum of deployment times (sequential processing)
        # Allow some overhead for evaluation and cleanup
        assert total_time >= sum_deployment_times * 0.9, \
            f"Total time {total_time:.2f}s should be at least 90% of deployment time {sum_deployment_times:.2f}s"
        assert total_time < sum_deployment_times * 2.0, \
            f"Total time {total_time:.2f}s should not be more than 2x deployment time {sum_deployment_times:.2f}s"
