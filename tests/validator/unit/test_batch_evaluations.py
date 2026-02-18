"""
Test for batch evaluation submission to IWAP.

This test verifies the complete flow:
1. Agent run is created and stored in ctx.current_agent_runs
2. Evaluations are prepared correctly
3. Batch submission to IWAP works
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from autoppia_web_agents_subnet.platform import models as iwa_models
from autoppia_web_agents_subnet.platform.utils.task_flow import prepare_evaluation_payload


class MockContext:
    """Mock validator context for testing."""
    
    def __init__(self):
        self.current_round_id = "validator_round_2_3_test123"
        self.current_agent_runs = {}
        self.current_round_tasks = {}
        self.uid = 60
        self.wallet = SimpleNamespace(
            hotkey=SimpleNamespace(ss58_address="5HYo41dSa8XNfFMJf8HF8HgGi1RHsr3Wxfcsd4NLFNVuJXkC")
        )
        self.metagraph = SimpleNamespace(
            hotkeys=["5F3sa...", "5F4sa...", "5F5sa..."]
        )
        self.iwap_client = AsyncMock()


@pytest.fixture
def mock_ctx():
    """Create a mock context with agent_run registered."""
    ctx = MockContext()
    
    # Simulate agent_run creation (what happens in register_participating_miners_in_iwap)
    agent_run = iwa_models.AgentRunIWAP(
        agent_run_id="agent_run_153_abc123def456",
        validator_round_id=ctx.current_round_id,
        validator_uid=int(ctx.uid),
        validator_hotkey=ctx.wallet.hotkey.ss58_address,
        miner_uid=153,
        miner_hotkey="5F3sa...",
        is_sota=False,
        version=None,
        started_at=1234567890.0,
        metadata={},
    )
    
    # CRITICAL: Store agent_run in ctx (this is what the validator does)
    ctx.current_agent_runs[153] = agent_run
    
    # Create task payloads
    task_id_1 = f"{ctx.current_round_id}_task-001"
    task_id_2 = f"{ctx.current_round_id}_task-002"
    
    ctx.current_round_tasks[task_id_1] = iwa_models.TaskIWAP(
        task_id=task_id_1,
        validator_round_id=ctx.current_round_id,
        is_web_real=True,
        web_project_id="project-1",
        web_version="1.0",
        url="http://test1.com",
        prompt="Test task 1",
        specifications={},
        tests=[],
        use_case={},
    )
    
    ctx.current_round_tasks[task_id_2] = iwa_models.TaskIWAP(
        task_id=task_id_2,
        validator_round_id=ctx.current_round_id,
        is_web_real=True,
        web_project_id="project-2",
        web_version="1.0",
        url="http://test2.com",
        prompt="Test task 2",
        specifications={},
        tests=[],
        use_case={},
    )
    
    return ctx


@pytest.mark.asyncio
async def test_agent_run_is_stored_in_context(mock_ctx):
    """Test that agent_run is stored correctly in ctx.current_agent_runs."""
    # Verify agent_run exists
    assert 153 in mock_ctx.current_agent_runs
    agent_run = mock_ctx.current_agent_runs[153]
    
    # Verify agent_run has correct data
    assert agent_run.agent_run_id == "agent_run_153_abc123def456"
    assert agent_run.validator_round_id == mock_ctx.current_round_id
    assert agent_run.miner_uid == 153
    assert agent_run.validator_uid == 60


@pytest.mark.asyncio
async def test_prepare_evaluation_payload_basic(mock_ctx):
    """Test that prepare_evaluation_payload creates correct structure."""
    from autoppia_iwa.src.data_generation.tasks.classes import Task
    from autoppia_iwa.src.demo_webs.classes import WebProject
    from autoppia_iwa.src.web_agents.classes import TaskSolution
    from autoppia_web_agents_subnet.validator.models import TaskWithProject
    
    # Get task payload
    task_id_full = f"{mock_ctx.current_round_id}_task-001"
    task_payload = mock_ctx.current_round_tasks[task_id_full]
    
    # Get agent_run
    agent_run = mock_ctx.current_agent_runs[153]
    
    # Create solution
    solution = TaskSolution(
        task_id="task-001",
        actions=[
            {"type": "navigate", "url": "http://test1.com"},
            {"type": "click", "selector": "#button1"},
        ],
        web_agent_id="153"
    )
    
    # Prepare evaluation payload
    evaluation_payload = prepare_evaluation_payload(
        ctx=mock_ctx,
        task_payload=task_payload,
        agent_run=agent_run,
        miner_uid=153,
        solution=solution,
        eval_score=0.85,
        evaluation_meta={"test_results": [{"passed": True}], "feedback": "Good job"},
        test_results_data=[{"passed": True}],
        exec_time=5.5,
        reward=0.80,
    )
    
    # Verify structure
    assert "task" in evaluation_payload
    assert "task_solution" in evaluation_payload
    assert "evaluation" in evaluation_payload
    assert "evaluation_result" in evaluation_payload
    
    # Verify task_solution
    task_solution = evaluation_payload["task_solution"]
    assert task_solution["task_id"] == task_id_full
    assert task_solution["agent_run_id"] == "agent_run_153_abc123def456"
    assert task_solution["validator_round_id"] == mock_ctx.current_round_id
    assert task_solution["miner_uid"] == 153
    assert len(task_solution["actions"]) == 2
    
    # Verify evaluation
    evaluation = evaluation_payload["evaluation"]
    assert evaluation["task_id"] == task_id_full
    assert evaluation["agent_run_id"] == "agent_run_153_abc123def456"
    assert evaluation["eval_score"] == 0.85
    assert evaluation["reward"] == 0.80


@pytest.mark.asyncio
async def test_batch_submission_flow(mock_ctx):
    """Test the complete batch submission flow."""
    from autoppia_iwa.src.data_generation.tasks.classes import Task
    from autoppia_iwa.src.demo_webs.classes import WebProject
    from autoppia_iwa.src.web_agents.classes import TaskSolution
    from autoppia_web_agents_subnet.validator.models import TaskWithProject
    
    # Create 2 task items (simulating a batch of 2)
    tasks_data = [
        ("task-001", "http://test1.com", "Test task 1", 0.85, 5.5, 0.80),
        ("task-002", "http://test2.com", "Test task 2", 0.90, 4.2, 0.85),
    ]
    
    evaluations_batch = []
    
    for task_id, url, prompt, score, exec_time, reward in tasks_data:
        task_id_full = f"{mock_ctx.current_round_id}_{task_id}"
        task_payload = mock_ctx.current_round_tasks[task_id_full]
        
        agent_run = mock_ctx.current_agent_runs[153]
        
        solution = TaskSolution(
            task_id=task_id,
            actions=[{"type": "navigate", "url": url}],
            web_agent_id="153"
        )
        
        evaluation_payload = prepare_evaluation_payload(
            ctx=mock_ctx,
            task_payload=task_payload,
            agent_run=agent_run,
            miner_uid=153,
            solution=solution,
            eval_score=score,
            evaluation_meta={},
            test_results_data=[],
            exec_time=exec_time,
            reward=reward,
        )
        
        evaluations_batch.append(evaluation_payload)
    
    # Verify batch has correct size
    assert len(evaluations_batch) == 2
    
    # Verify all evaluations have same agent_run_id
    agent_run_ids = [eval["evaluation"]["agent_run_id"] for eval in evaluations_batch]
    assert all(aid == "agent_run_153_abc123def456" for aid in agent_run_ids)
    
    # Mock the batch submission
    mock_ctx.iwap_client.add_evaluations_batch.return_value = {
        "message": "Batch evaluations processed: 2 created",
        "evaluations_created": 2,
        "total_requested": 2,
    }
    
    # Get agent_run for batch submission
    agent_run = mock_ctx.current_agent_runs[153]
    
    # Call batch submission
    result = await mock_ctx.iwap_client.add_evaluations_batch(
        validator_round_id=mock_ctx.current_round_id,
        agent_run_id=agent_run.agent_run_id,
        evaluations=evaluations_batch,
    )
    
    # Verify call was made
    mock_ctx.iwap_client.add_evaluations_batch.assert_called_once_with(
        validator_round_id=mock_ctx.current_round_id,
        agent_run_id="agent_run_153_abc123def456",
        evaluations=evaluations_batch,
    )
    
    # Verify result
    assert result["evaluations_created"] == 2
    assert result["total_requested"] == 2


@pytest.mark.asyncio
async def test_agent_run_not_found_error(mock_ctx):
    """Test that error is raised if agent_run is not in context."""
    # Try to access non-existent agent_run
    with pytest.raises(KeyError):
        agent_run = mock_ctx.current_agent_runs[999]  # Doesn't exist


@pytest.mark.asyncio
async def test_multiple_agents_have_separate_runs(mock_ctx):
    """Test that multiple agents have separate agent_runs."""
    # Add a second agent_run
    agent_run_2 = iwa_models.AgentRunIWAP(
        agent_run_id="agent_run_154_xyz789abc123",
        validator_round_id=mock_ctx.current_round_id,
        validator_uid=int(mock_ctx.uid),
        validator_hotkey=mock_ctx.wallet.hotkey.ss58_address,
        miner_uid=154,
        miner_hotkey="5F4sa...",
        is_sota=False,
        version=None,
        started_at=1234567891.0,
        metadata={},
    )
    
    mock_ctx.current_agent_runs[154] = agent_run_2
    
    # Verify both exist
    assert 153 in mock_ctx.current_agent_runs
    assert 154 in mock_ctx.current_agent_runs
    
    # Verify they are different
    assert mock_ctx.current_agent_runs[153].agent_run_id != mock_ctx.current_agent_runs[154].agent_run_id
    assert mock_ctx.current_agent_runs[153].miner_uid == 153
    assert mock_ctx.current_agent_runs[154].miner_uid == 154


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
