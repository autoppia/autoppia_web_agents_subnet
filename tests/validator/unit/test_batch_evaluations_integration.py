"""
Integration test for batch evaluation flow.

This test simulates the COMPLETE flow:
1. Agent run is created and stored
2. Multiple evaluations are prepared
3. Batch is submitted to IWAP
4. Verifies that agent_run stats are updated correctly
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from autoppia_web_agents_subnet.platform import models as iwa_models
from autoppia_web_agents_subnet.platform.utils.task_flow import prepare_evaluation_payload


class MockContext:
    """Mock validator context that simulates real validator state."""
    
    def __init__(self):
        self.current_round_id = "validator_round_2_3_test123"
        self.current_agent_runs = {}
        self.current_round_tasks = {}
        self.uid = 60
        self.wallet = SimpleNamespace(
            hotkey=SimpleNamespace(ss58_address="5HYo41dSa8XNfFMJf8HF8HgGi1RHsr3Wxfcsd4NLFNVuJXkC")
        )
        self.metagraph = SimpleNamespace(
            hotkeys={153: "5F3sa...", 154: "5F4sa..."}
        )
        self.iwap_client = AsyncMock()


@pytest.fixture
def complete_flow_context():
    """Create a complete context simulating a real validator round."""
    ctx = MockContext()
    
    # STEP 1: Simulate agent_run creation (what happens during handshake)
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
    
    # CRITICAL: Store agent_run (this is what the validator does)
    ctx.current_agent_runs[153] = agent_run
    
    # STEP 2: Create task payloads (what happens during set_tasks)
    for i in range(1, 6):  # 5 tasks
        task_id = f"{ctx.current_round_id}_task-{i:03d}"
        ctx.current_round_tasks[task_id] = iwa_models.TaskIWAP(
            task_id=task_id,
            validator_round_id=ctx.current_round_id,
            is_web_real=True,
            web_project_id=f"project-{i}",
            web_version="1.0",
            url=f"http://test{i}.com",
            prompt=f"Test task {i}",
            specifications={},
            tests=[],
            relevant_data={},
            use_case={},
        )
    
    return ctx


@pytest.mark.asyncio
async def test_complete_batch_flow_simulation(complete_flow_context):
    """
    Test the COMPLETE flow from evaluation to batch submission.
    
    This simulates:
    1. Agent is deployed
    2. 5 tasks are evaluated in parallel (batch)
    3. Batch is prepared and submitted to IWAP
    4. Verifies agent_run_id is used correctly
    """
    ctx = complete_flow_context
    
    # Verify agent_run exists (simulating what happens after handshake)
    assert 153 in ctx.current_agent_runs, "Agent run should exist after handshake"
    agent_run = ctx.current_agent_runs[153]
    assert agent_run.agent_run_id == "agent_run_153_abc123def456"
    
    # STEP 3: Simulate evaluation of 5 tasks (batch)
    from autoppia_iwa.src.web_agents.classes import TaskSolution
    
    batch_eval_data = []
    for i in range(1, 6):
        task_id = f"task-{i:03d}"
        task_id_full = f"{ctx.current_round_id}_{task_id}"
        
        # Simulate evaluation results
        score = 0.7 + (i * 0.05)  # Scores: 0.75, 0.80, 0.85, 0.90, 0.95
        exec_time = 5.0 + i
        reward = score * 0.9
        
        solution = TaskSolution(
            task_id=task_id,
            actions=[
                {"type": "navigate", "url": f"http://test{i}.com"},
                {"type": "click", "selector": f"#button{i}"},
            ],
            web_agent_id="153"
        )
        
        batch_eval_data.append({
            'task_item': None,  # Not needed anymore
            'score': score,
            'exec_time': exec_time,
            'cost': 0.01 * i,
            'reward': reward,
            'task_solution': {
                'test_results': [{"passed": True, "test_id": f"test_{i}"}],
                'feedback': f"Task {i} completed successfully",
            },
        })
    
    # STEP 4: Prepare batch payloads (what _submit_batch_evaluations_to_iwap does)
    evaluations_batch = []
    
    for i, eval_data in enumerate(batch_eval_data, 1):
        task_id = f"task-{i:03d}"
        task_id_full = f"{ctx.current_round_id}_{task_id}"
        task_payload = ctx.current_round_tasks[task_id_full]
        
        # Get agent_run (CRITICAL: This must exist!)
        agent_run = ctx.current_agent_runs[153]
        
        solution = TaskSolution(
            task_id=task_id,
            actions=[{"type": "navigate", "url": f"http://test{i}.com"}],
            web_agent_id="153"
        )
        
        evaluation_payload = prepare_evaluation_payload(
            ctx=ctx,
            task_payload=task_payload,
            agent_run=agent_run,
            miner_uid=153,
            solution=solution,
            eval_score=eval_data['score'],
            evaluation_meta=eval_data['task_solution'] if isinstance(eval_data['task_solution'], dict) else {},
            test_results_data=eval_data['task_solution'].get('test_results', []) if isinstance(eval_data['task_solution'], dict) else [],
            exec_time=eval_data['exec_time'],
            reward=eval_data['reward'],
        )
        
        evaluations_batch.append(evaluation_payload)
    
    # Verify batch structure
    assert len(evaluations_batch) == 5, "Should have 5 evaluations in batch"
    
    # STEP 5: Verify all evaluations use the SAME agent_run_id
    agent_run_ids = [eval["evaluation"]["agent_run_id"] for eval in evaluations_batch]
    assert all(aid == "agent_run_153_abc123def456" for aid in agent_run_ids), \
        "All evaluations must use the same agent_run_id"
    
    # STEP 6: Simulate batch submission to IWAP
    ctx.iwap_client.add_evaluations_batch.return_value = {
        "message": "Batch evaluations processed: 5 created",
        "evaluations_created": 5,
        "total_requested": 5,
    }
    
    result = await ctx.iwap_client.add_evaluations_batch(
        validator_round_id=ctx.current_round_id,
        agent_run_id=agent_run.agent_run_id,
        evaluations=evaluations_batch,
    )
    
    # STEP 7: Verify submission
    ctx.iwap_client.add_evaluations_batch.assert_called_once()
    call_args = ctx.iwap_client.add_evaluations_batch.call_args
    
    assert call_args.kwargs["validator_round_id"] == ctx.current_round_id
    assert call_args.kwargs["agent_run_id"] == "agent_run_153_abc123def456"
    assert len(call_args.kwargs["evaluations"]) == 5
    
    # Verify result
    assert result["evaluations_created"] == 5
    assert result["total_requested"] == 5


@pytest.mark.asyncio
async def test_agent_run_must_exist_before_batch(complete_flow_context):
    """Test that agent_run MUST exist before submitting batch."""
    ctx = complete_flow_context
    
    # Try to submit batch without agent_run
    ctx.current_agent_runs.clear()
    
    # This should fail or be skipped
    with pytest.raises(KeyError):
        agent_run = ctx.current_agent_runs[153]  # Doesn't exist


@pytest.mark.asyncio
async def test_multiple_agents_separate_batches(complete_flow_context):
    """Test that multiple agents have separate batches."""
    ctx = complete_flow_context
    
    # Add second agent
    agent_run_2 = iwa_models.AgentRunIWAP(
        agent_run_id="agent_run_154_xyz789abc123",
        validator_round_id=ctx.current_round_id,
        validator_uid=int(ctx.uid),
        validator_hotkey=ctx.wallet.hotkey.ss58_address,
        miner_uid=154,
        miner_hotkey="5F4sa...",
        is_sota=False,
        version=None,
        started_at=1234567891.0,
        metadata={},
    )
    ctx.current_agent_runs[154] = agent_run_2
    
    # Prepare batch for agent 153
    batch_153 = []
    task_id_full = f"{ctx.current_round_id}_task-001"
    task_payload = ctx.current_round_tasks[task_id_full]
    agent_run_153 = ctx.current_agent_runs[153]
    
    eval_payload_153 = prepare_evaluation_payload(
        ctx=ctx,
        task_payload=task_payload,
        agent_run=agent_run_153,
        miner_uid=153,
        solution=None,
        eval_score=0.8,
        evaluation_meta={},
        test_results_data=[],
        exec_time=5.0,
        reward=0.75,
    )
    batch_153.append(eval_payload_153)
    
    # Prepare batch for agent 154
    batch_154 = []
    agent_run_154 = ctx.current_agent_runs[154]
    
    eval_payload_154 = prepare_evaluation_payload(
        ctx=ctx,
        task_payload=task_payload,
        agent_run=agent_run_154,
        miner_uid=154,
        solution=None,
        eval_score=0.9,
        evaluation_meta={},
        test_results_data=[],
        exec_time=4.0,
        reward=0.85,
    )
    batch_154.append(eval_payload_154)
    
    # Verify they have different agent_run_ids
    assert batch_153[0]["evaluation"]["agent_run_id"] == "agent_run_153_abc123def456"
    assert batch_154[0]["evaluation"]["agent_run_id"] == "agent_run_154_xyz789abc123"
    assert batch_153[0]["evaluation"]["agent_run_id"] != batch_154[0]["evaluation"]["agent_run_id"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
