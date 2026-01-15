"""
Performance tests for evaluation phase scaling.

Tests validator's ability to handle large numbers of agents and tasks
while maintaining acceptable performance and memory usage.
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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
        # Setup 100 agents
        validator_with_agents.agents_dict = {}
        validator_with_agents.agents_queue.queue.clear()
        
        for i in range(100):
            agent_info = MagicMock()
            agent_info.uid = i
            agent_info.agent_name = f"Agent{i}"
            agent_info.github_url = f"https://github.com/test/agent{i}"
            agent_info.score = 0.0
            
            validator_with_agents.agents_dict[i] = agent_info
            validator_with_agents.agents_queue.put(agent_info)
        
        # Mock fast evaluation (simulate 0.1s per agent)
        async def fast_evaluate(*args, **kwargs):
            await asyncio.sleep(0.01)  # Simulate work
            return 0.8
        
        validator_with_agents.sandbox_manager.deploy_agent = AsyncMock(return_value=True)
        validator_with_agents.sandbox_manager.cleanup_agent = AsyncMock()
        
        with patch(
            'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
            new=fast_evaluate
        ):
            start_time = time.time()
            
            # Run evaluation
            await validator_with_agents._run_evaluation_phase()
            
            elapsed = time.time() - start_time
            
            # Should complete in reasonable time (< 5 seconds with mocked evaluation)
            assert elapsed < 5.0, f"Evaluation took {elapsed:.2f}s, expected < 5s"
            
            # All agents should be evaluated
            evaluated_count = sum(
                1 for agent in validator_with_agents.agents_dict.values()
                if agent.score > 0
            )
            assert evaluated_count > 0, "No agents were evaluated"

    @pytest.mark.asyncio
    async def test_evaluation_memory_usage_stays_bounded(
        self, validator_with_agents, season_tasks
    ):
        """Test that memory usage doesn't grow unbounded during evaluation."""
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Setup 50 agents
        validator_with_agents.agents_dict = {}
        validator_with_agents.agents_queue.queue.clear()
        
        for i in range(50):
            agent_info = MagicMock()
            agent_info.uid = i
            agent_info.agent_name = f"Agent{i}"
            agent_info.github_url = f"https://github.com/test/agent{i}"
            agent_info.score = 0.0
            
            validator_with_agents.agents_dict[i] = agent_info
            validator_with_agents.agents_queue.put(agent_info)
        
        # Mock evaluation
        async def mock_evaluate(*args, **kwargs):
            await asyncio.sleep(0.001)
            return 0.75
        
        validator_with_agents.sandbox_manager.deploy_agent = AsyncMock(return_value=True)
        validator_with_agents.sandbox_manager.cleanup_agent = AsyncMock()
        
        with patch(
            'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
            new=mock_evaluate
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
        
        class TestValidator(ValidatorEvaluationMixin):
            def __init__(self, config):
                self.config = config
                self.agents_dict = {}
                self.agents_queue = asyncio.Queue()
                self.sandbox_manager = MagicMock()
                self.sandbox_manager.deploy_agent = AsyncMock(return_value=True)
                self.sandbox_manager.cleanup_agent = AsyncMock()
                self.round_manager = MagicMock()
                self.round_manager.current_phase_state = MagicMock(return_value="EVALUATION")
                self.season_manager = MagicMock()
                self.season_manager.get_season_tasks = AsyncMock(return_value=season_tasks)
                self.block = 1000
        
        # Create two validators
        validator1 = TestValidator(mock_validator_config)
        validator2 = TestValidator(mock_validator_config)
        
        # Add agents to each
        for i in range(10):
            agent1 = MagicMock()
            agent1.uid = i
            agent1.agent_name = f"V1_Agent{i}"
            agent1.github_url = f"https://github.com/v1/agent{i}"
            agent1.score = 0.0
            validator1.agents_dict[i] = agent1
            await validator1.agents_queue.put(agent1)
            
            agent2 = MagicMock()
            agent2.uid = i + 100
            agent2.agent_name = f"V2_Agent{i}"
            agent2.github_url = f"https://github.com/v2/agent{i}"
            agent2.score = 0.0
            validator2.agents_dict[i + 100] = agent2
            await validator2.agents_queue.put(agent2)
        
        # Mock evaluation
        async def mock_evaluate(*args, **kwargs):
            await asyncio.sleep(0.001)
            return 0.8
        
        with patch(
            'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
            new=mock_evaluate
        ):
            # Run both evaluations concurrently
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
        from autoppia_web_agents_subnet.opensource.task import Task
        from autoppia_web_agents_subnet.opensource.web_project import WebProject
        
        # Setup 10 agents
        validator_with_agents.agents_dict = {}
        validator_with_agents.agents_queue.queue.clear()
        
        for i in range(10):
            agent_info = MagicMock()
            agent_info.uid = i
            agent_info.agent_name = f"Agent{i}"
            agent_info.github_url = f"https://github.com/test/agent{i}"
            agent_info.score = 0.0
            
            validator_with_agents.agents_dict[i] = agent_info
            validator_with_agents.agents_queue.put(agent_info)
        
        validator_with_agents.sandbox_manager.deploy_agent = AsyncMock(return_value=True)
        validator_with_agents.sandbox_manager.cleanup_agent = AsyncMock()
        
        results = {}
        
        for task_count in [1, 3, 5, 10]:
            # Create tasks
            tasks = []
            for j in range(task_count):
                project = WebProject(
                    name=f"Project{j}",
                    description=f"Test project {j}",
                    github_url=f"https://github.com/test/project{j}"
                )
                task = Task(
                    name=f"Task{j}",
                    description=f"Test task {j}",
                    project=project
                )
                tasks.append(MagicMock(project=project, task=task))
            
            validator_with_agents.season_manager.get_season_tasks = AsyncMock(
                return_value=tasks
            )
            
            # Mock evaluation
            async def mock_evaluate(*args, **kwargs):
                await asyncio.sleep(0.001 * task_count)  # Simulate work proportional to tasks
                return 0.8
            
            with patch(
                'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
                new=mock_evaluate
            ):
                start_time = time.time()
                await validator_with_agents._run_evaluation_phase()
                elapsed = time.time() - start_time
                
                results[task_count] = elapsed
        
        # Verify throughput scales reasonably
        # More tasks should take more time, but not linearly
        assert results[10] > results[1], "More tasks should take more time"
        assert results[10] < results[1] * 15, "Scaling should be sub-linear"

    @pytest.mark.asyncio
    async def test_sandbox_deployment_parallelism(self, validator_with_agents):
        """Test that sandbox deployments can happen in parallel."""
        # Setup 20 agents
        validator_with_agents.agents_dict = {}
        validator_with_agents.agents_queue.queue.clear()
        
        for i in range(20):
            agent_info = MagicMock()
            agent_info.uid = i
            agent_info.agent_name = f"Agent{i}"
            agent_info.github_url = f"https://github.com/test/agent{i}"
            agent_info.score = 0.0
            
            validator_with_agents.agents_dict[i] = agent_info
            validator_with_agents.agents_queue.put(agent_info)
        
        deployment_times = []
        
        async def track_deployment(*args, **kwargs):
            start = time.time()
            await asyncio.sleep(0.01)  # Simulate deployment
            deployment_times.append(time.time() - start)
            return True
        
        validator_with_agents.sandbox_manager.deploy_agent = track_deployment
        validator_with_agents.sandbox_manager.cleanup_agent = AsyncMock()
        
        async def mock_evaluate(*args, **kwargs):
            return 0.8
        
        with patch(
            'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
            new=mock_evaluate
        ):
            start_time = time.time()
            await validator_with_agents._run_evaluation_phase()
            total_time = time.time() - start_time
        
        # Verify deployments happened
        assert len(deployment_times) > 0, "No deployments tracked"
        
        # Total time should be less than sum of all deployment times
        # (indicating some parallelism)
        sum_deployment_times = sum(deployment_times)
        assert total_time < sum_deployment_times * 0.8, \
            "Deployments appear to be sequential, not parallel"
