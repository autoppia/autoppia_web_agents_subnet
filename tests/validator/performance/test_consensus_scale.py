"""
Performance tests for consensus phase scaling.

Tests consensus aggregation performance with large numbers of validators
and score commitments.
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import psutil
import os


@pytest.mark.performance
@pytest.mark.slow
class TestConsensusScaling:
    """Test consensus aggregation performance with increasing load."""

    @pytest.mark.asyncio
    async def test_aggregate_scores_from_50_validators(
        self, mock_ipfs_client, mock_async_subtensor, dummy_validator
    ):
        """Test aggregating scores from 50 validators completes in time."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            aggregate_scores_from_commitments
        )
        
        # Setup 50 validators with commitments
        round_number = 100
        num_validators = 50
        num_miners = 100
        
        # Create commitments for each validator
        commitments = {}
        for validator_uid in range(num_validators):
            # Each validator scores all miners
            scores = {
                miner_uid: 0.5 + (miner_uid % 10) * 0.05
                for miner_uid in range(num_miners)
            }
            
            payload = {
                "round_number": round_number,
                "r": round_number,
                "scores": scores,
                "timestamp": time.time()
            }
            
            # Upload to IPFS
            cid = await mock_ipfs_client.add_json_async(payload)
            
            # Commit to blockchain
            commitments[f"hotkey{validator_uid}"] = {
                "r": round_number,
                "c": cid[0],
                "p": 0
            }
        
        # Mock read_all_plain_commitments and get_json_async
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments',
                   new=AsyncMock(return_value=commitments)):
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async',
                       new=mock_ipfs_client.get_json_async):
                # Setup dummy validator
                dummy_validator.block = 1000
                dummy_validator.config.netuid = 99
                dummy_validator.round_manager.calculate_round = AsyncMock(return_value=round_number)
                dummy_validator.metagraph.stake = [15000.0] * num_validators
                dummy_validator.metagraph.hotkeys = [f"hotkey{i}" for i in range(num_validators)]
                dummy_validator.metagraph.axons = [Mock(hotkey=f"hotkey{i}") for i in range(num_validators)]
                
                start_time = time.time()
                
                # Aggregate scores
                aggregated, _ = await aggregate_scores_from_commitments(
                    dummy_validator,
                    st=mock_async_subtensor
                )
                
                elapsed = time.time() - start_time
        
        # Should complete in reasonable time (< 5 seconds)
        assert elapsed < 5.0, f"Aggregation took {elapsed:.2f}s, expected < 5s"
        
        # Should have aggregated scores for all miners
        assert len(aggregated) == num_miners, \
            f"Expected {num_miners} aggregated scores, got {len(aggregated)}"
        
        # Scores should be averaged
        for miner_uid, score in aggregated.items():
            assert 0.0 <= score <= 1.0, f"Score {score} out of range"

    @pytest.mark.asyncio
    async def test_consensus_memory_usage_stays_bounded(
        self, mock_ipfs_client, mock_async_subtensor, dummy_validator
    ):
        """Test that memory usage doesn't grow unbounded during consensus."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            aggregate_scores_from_commitments
        )
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Setup 30 validators with large score dictionaries
        round_number = 100
        num_validators = 30
        num_miners = 200
        
        commitments = {}
        for validator_uid in range(num_validators):
            scores = {
                miner_uid: 0.5 + (miner_uid % 20) * 0.025
                for miner_uid in range(num_miners)
            }
            
            payload = {
                "round_number": round_number,
                "r": round_number,
                "scores": scores,
                "timestamp": time.time(),
                "metadata": {"validator": validator_uid}  # Extra data
            }
            
            cid = await mock_ipfs_client.add_json_async(payload)
            
            commitments[f"hotkey{validator_uid}"] = {
                "r": round_number,
                "c": cid[0],
                "p": 0
            }
        
        # Mock read_all_plain_commitments
        with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments',
                   new=AsyncMock(return_value=commitments)):
            # Setup dummy validator
            dummy_validator.block = 1000
            dummy_validator.config.netuid = 99
            dummy_validator.round_manager.calculate_round = AsyncMock(return_value=round_number)
            dummy_validator.metagraph.stake = [15000.0] * num_validators
            dummy_validator.metagraph.hotkeys = [f"hotkey{i}" for i in range(num_validators)]
            dummy_validator.metagraph.axons = [Mock(hotkey=f"hotkey{i}") for i in range(num_validators)]
            
            # Aggregate scores
            await aggregate_scores_from_commitments(
                dummy_validator,
                st=mock_async_subtensor
            )
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        # Memory increase should be reasonable (< 50 MB)
        assert memory_increase < 50, \
            f"Memory increased by {memory_increase:.2f} MB, expected < 50 MB"

    @pytest.mark.asyncio
    async def test_consensus_with_varying_validator_count(
        self, mock_ipfs_client, mock_async_subtensor, dummy_validator
    ):
        """Test consensus performance with different numbers of validators."""
        from autoppia_web_agents_subnet.validator.settlement.consensus import (
            aggregate_scores_from_commitments
        )
        
        round_number = 100
        num_miners = 50
        results = {}
        
        for num_validators in [5, 10, 20, 40]:
            # Setup validators
            commitments = {}
            
            for validator_uid in range(num_validators):
                scores = {
                    miner_uid: 0.5 + (miner_uid % 10) * 0.05
                    for miner_uid in range(num_miners)
                }
                
                payload = {
                    "round_number": round_number,
                    "r": round_number,
                    "scores": scores,
                    "timestamp": time.time()
                }
                
                cid = await mock_ipfs_client.add_json_async(payload)
                
                commitments[f"hotkey{validator_uid}"] = {
                    "r": round_number,
                    "c": cid[0],
                    "p": 0
                }
            
            # Mock read_all_plain_commitments and get_json_async
            with patch('autoppia_web_agents_subnet.validator.settlement.consensus.read_all_plain_commitments',
                       new=AsyncMock(return_value=commitments)):
                with patch('autoppia_web_agents_subnet.validator.settlement.consensus.get_json_async',
                           new=mock_ipfs_client.get_json_async):
                    # Setup dummy validator
                    dummy_validator.block = 1000
                    dummy_validator.config.netuid = 99
                    dummy_validator.round_manager.calculate_round = AsyncMock(return_value=round_number)
                    dummy_validator.metagraph.stake = [15000.0] * num_validators
                    dummy_validator.metagraph.hotkeys = [f"hotkey{i}" for i in range(num_validators)]
                    dummy_validator.metagraph.axons = [Mock(hotkey=f"hotkey{i}") for i in range(num_validators)]
                    
                    start_time = time.time()
                    
                    aggregated, _ = await aggregate_scores_from_commitments(
                        dummy_validator,
                        st=mock_async_subtensor
                    )
                    
                    elapsed = time.time() - start_time
                    results[num_validators] = elapsed
                    
                    # Verify correctness
                    assert len(aggregated) == num_miners
        
        # Verify scaling is reasonable
        # 40 validators should take more time than 5, but not excessively more
        assert results[40] > results[5], "More validators should take more time"
        assert results[40] < results[5] * 15, "Scaling should be reasonable"


@pytest.mark.performance
@pytest.mark.slow
class TestIPFSPerformance:
    """Test IPFS operations performance."""

    @pytest.mark.asyncio
    async def test_ipfs_upload_throughput(self, mock_ipfs_client):
        """Test IPFS upload throughput with multiple payloads."""
        num_uploads = 100
        payload_size_kb = 10
        
        # Create test payload
        payload = {
            "round_number": 100,
            "scores": {i: 0.5 for i in range(100)},
            "data": "x" * (payload_size_kb * 1024)  # Padding
        }
        
        start_time = time.time()
        
        # Upload multiple payloads
        cids = []
        for i in range(num_uploads):
            cid = await mock_ipfs_client.add_json_async(payload)
            cids.append(cid[0])
        
        elapsed = time.time() - start_time
        throughput = num_uploads / elapsed
        
        # Should achieve reasonable throughput (> 50 uploads/sec with mock)
        assert throughput > 50, \
            f"Upload throughput {throughput:.2f} uploads/s, expected > 50"
        
        # All uploads should succeed
        assert len(cids) == num_uploads
        assert len(set(cids)) == num_uploads, "CIDs should be unique"

    @pytest.mark.asyncio
    async def test_ipfs_download_throughput(self, mock_ipfs_client):
        """Test IPFS download throughput with multiple payloads."""
        num_payloads = 100
        
        # Upload payloads first
        cids = []
        for i in range(num_payloads):
            payload = {
                "round_number": 100,
                "scores": {j: 0.5 + i * 0.001 for j in range(50)},
                "index": i
            }
            cid = await mock_ipfs_client.add_json_async(payload)
            cids.append(cid[0])
        
        start_time = time.time()
        
        # Download all payloads
        downloaded = []
        for cid in cids:
            data = await mock_ipfs_client.get_json_async(cid)
            downloaded.append(data[0])
        
        elapsed = time.time() - start_time
        throughput = num_payloads / elapsed
        
        # Should achieve reasonable throughput (> 100 downloads/sec with mock)
        assert throughput > 100, \
            f"Download throughput {throughput:.2f} downloads/s, expected > 100"
        
        # All downloads should succeed
        assert len(downloaded) == num_payloads
        
        # Verify data integrity
        for i, data in enumerate(downloaded):
            assert data["index"] == i, f"Data mismatch at index {i}"


@pytest.mark.performance
@pytest.mark.slow
class TestStressTests:
    """Stress tests for validator workflow."""

    @pytest.mark.asyncio
    async def test_continuous_rounds_no_memory_leak(
        self, mock_validator_config, season_tasks
    ):
        """Test that continuous rounds don't leak memory."""
        from autoppia_web_agents_subnet.validator.evaluation.mixin import ValidatorEvaluationMixin
        from autoppia_web_agents_subnet.validator.models import AgentInfo
        import queue
        
        class TestValidator(ValidatorEvaluationMixin):
            def __init__(self, config, tasks):
                self.config = config
                self.agents_dict = {}
                self.agents_queue = queue.Queue()
                self.sandbox_manager = MagicMock()
                
                # Mock deploy_agent to return proper instance
                def mock_deploy(*args, **kwargs):
                    mock_instance = Mock()
                    mock_instance.base_url = "http://localhost:8001"
                    return mock_instance
                
                self.sandbox_manager.deploy_agent = mock_deploy
                self.sandbox_manager.cleanup_agent = Mock()
                
                self.round_manager = MagicMock()
                self.round_manager.get_wait_info = Mock(return_value={
                    "minutes_to_settlement": 120.0,
                    "blocks_to_settlement": 600,
                    "minutes_to_target": 240.0,
                    "blocks_to_target": 1200,
                })
                self.season_manager = MagicMock()
                self.season_manager.get_season_tasks = AsyncMock(return_value=tasks)
                self.block = 1000
        
        validator = TestValidator(mock_validator_config, season_tasks)
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Simulate 10 rounds
        for round_num in range(10):
            # Add some agents using real queue
            validator.agents_dict = {}
            validator.agents_queue = queue.Queue()
            
            for i in range(5):
                agent = AgentInfo(
                    uid=i,
                    agent_name=f"Agent{i}",
                    github_url=f"https://github.com/test/agent{i}",
                    score=0.0
                )
                validator.agents_dict[i] = agent
                validator.agents_queue.put(agent)
            
            # Mock evaluation
            with patch('autoppia_web_agents_subnet.validator.evaluation.mixin.normalize_and_validate_github_url',
                       return_value="https://github.com/test/agent"):
                with patch(
                    'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
                    new=AsyncMock(return_value=(0.8, None, None))
                ):
                    await validator._run_evaluation_phase()
            
            # Clear for next round
            validator.agents_dict.clear()
            await asyncio.sleep(0.01)  # Small delay
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        # Memory increase should be minimal (< 30 MB for 10 rounds)
        assert memory_increase < 30, \
            f"Memory increased by {memory_increase:.2f} MB after 10 rounds, possible leak"

    @pytest.mark.asyncio
    async def test_validator_handles_10_tasks_per_agent(
        self, validator_with_agents
    ):
        """Test validator can handle 10 tasks per agent."""
        from tests.conftest import _bind_evaluation_mixin
        from autoppia_web_agents_subnet.validator.models import AgentInfo, TaskWithProject
        
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        
        # Create 10 tasks using mocks
        tasks = []
        for i in range(10):
            mock_task = Mock()
            mock_task.id = f"task-{i}"
            mock_task.url = f"https://example.com/task{i}"
            mock_task.prompt = f"Test task {i}"
            mock_task.tests = []
            
            task_with_project = TaskWithProject(
                project=None,
                task=mock_task
            )
            tasks.append(task_with_project)
        
        validator_with_agents.season_manager.get_season_tasks = AsyncMock(
            return_value=tasks
        )
        
        # Setup 5 agents
        validator_with_agents.agents_dict = {}
        validator_with_agents.agents_queue.queue.clear()
        
        for i in range(5):
            agent_info = AgentInfo(
                uid=i,
                agent_name=f"Agent{i}",
                github_url=f"https://github.com/test/agent{i}",
                score=0.0
            )
            
            validator_with_agents.agents_dict[i] = agent_info
            validator_with_agents.agents_queue.put(agent_info)
        
        # Mock deploy_agent to return proper instance
        mock_instance = Mock()
        mock_instance.base_url = "http://localhost:8001"
        validator_with_agents.sandbox_manager.deploy_agent = Mock(return_value=mock_instance)
        validator_with_agents.sandbox_manager.cleanup_agent = Mock()
        
        # Mock evaluation
        async def mock_evaluate(*args, **kwargs):
            await asyncio.sleep(0.001)
            return (0.8, None, None)
        
        with patch(
            'autoppia_web_agents_subnet.validator.evaluation.mixin.evaluate_with_stateful_cua',
            new=mock_evaluate
        ):
            start_time = time.time()
            await validator_with_agents._run_evaluation_phase()
            elapsed = time.time() - start_time
        
        # Should complete in reasonable time
        assert elapsed < 5.0, f"Evaluation took {elapsed:.2f}s, expected < 5s"
        
        # All agents should be evaluated
        evaluated_count = sum(
            1 for agent in validator_with_agents.agents_dict.values()
            if agent.score > 0
        )
        assert evaluated_count > 0, "No agents were evaluated"
