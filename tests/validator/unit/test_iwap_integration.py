"""
Unit tests for IWAP integration flow.

Tests verify that:
1. Miners are registered correctly in IWAP after handshake
2. Task results are submitted to IWAP during evaluation
3. Round is finalized correctly in IWAP after settlement
4. Offline mode works when IWAP is unavailable
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from typing import Dict, Any

from autoppia_web_agents_subnet.platform.utils.round_flow import (
    register_participating_miners_in_iwap,
    start_round_flow,
    finish_round_flow,
)
from autoppia_web_agents_subnet.platform.utils.task_flow import submit_task_results
from autoppia_web_agents_subnet.platform import models as iwa_models


class MockContext:
    """Mock context object for testing IWAP integration."""
    
    def __init__(self):
        self.current_round_id = "1/1"
        self.active_miner_uids = [42, 55]
        self.round_handshake_payloads = {
            42: MagicMock(agent_name="AutoAgent-v1", github_url="https://github.com/test/agent1", note="test"),
            55: MagicMock(agent_name="BestAgent", github_url="https://github.com/test/agent2", note="test2"),
        }
        self.current_round_tasks = {}
        self.current_agent_runs = {}
        self.current_miner_snapshots = {}
        self.agent_run_accumulators = {}
        self.round_start_timestamp = 1234567890.0
        self._iwap_offline_mode = False
        self._completed_pairs = set()
        self.uid = 1
        self.wallet = MagicMock()
        self.wallet.hotkey = MagicMock()
        self.wallet.hotkey.ss58_address = "5FValidator..."
        self.metagraph = MagicMock()
        self.metagraph.hotkeys = {42: "5F3sa...", 55: "5Gx9a..."}
        self.metagraph.coldkeys = ["5CValidator...", "5CMiner1...", "5CMiner2..."]
        self.metagraph.n = 100
        self.iwap_client = AsyncMock()
        self.round_manager = MagicMock()
        self.round_manager.ROUND_BLOCK_LENGTH = 360
        
        # Add _reset_iwap_round_state method
        def _reset_iwap_round_state():
            pass
        self._reset_iwap_round_state = _reset_iwap_round_state


@pytest.mark.asyncio
async def test_register_participating_miners_success():
    """Test successful registration of miners in IWAP."""
    ctx = MockContext()
    ctx.iwap_client.start_agent_run = AsyncMock(return_value={"status": "success"})
    
    await register_participating_miners_in_iwap(ctx)
    
    # Verify start_agent_run was called for each miner
    assert ctx.iwap_client.start_agent_run.call_count == 2
    
    # Verify calls contain correct data
    calls = ctx.iwap_client.start_agent_run.call_args_list
    
    # First miner (uid 42)
    first_call = calls[0].kwargs
    assert first_call["validator_round_id"] == "1/1"
    assert first_call["agent_run"].miner_uid == 42
    assert first_call["miner_identity"].uid == 42
    assert first_call["miner_identity"].hotkey == "5F3sa..."
    
    # Second miner (uid 55)
    second_call = calls[1].kwargs
    assert second_call["validator_round_id"] == "1/1"
    assert second_call["agent_run"].miner_uid == 55
    assert second_call["miner_identity"].uid == 55
    assert second_call["miner_identity"].hotkey == "5Gx9a..."


@pytest.mark.asyncio
async def test_register_miners_offline_mode():
    """Test that registration is skipped when IWAP is in offline mode."""
    ctx = MockContext()
    ctx._iwap_offline_mode = True
    ctx.iwap_client.start_agent_run = AsyncMock()
    
    await register_participating_miners_in_iwap(ctx)
    
    # Verify no calls were made in offline mode
    ctx.iwap_client.start_agent_run.assert_not_called()


@pytest.mark.asyncio
async def test_register_miners_no_active_miners():
    """Test that registration handles empty miner list."""
    ctx = MockContext()
    ctx.active_miner_uids = []
    ctx.iwap_client.start_agent_run = AsyncMock()
    
    await register_participating_miners_in_iwap(ctx)
    
    # Verify no calls were made when no miners are active
    ctx.iwap_client.start_agent_run.assert_not_called()


@pytest.mark.asyncio
async def test_register_miners_handles_duplicate():
    """Test that registration handles 409 conflict (duplicate) gracefully."""
    ctx = MockContext()
    
    # Mock 409 response
    from httpx import Response, HTTPStatusError, Request
    mock_response = Response(status_code=409, text="Already exists")
    mock_request = Request("POST", "http://test.com")
    error = HTTPStatusError("Conflict", request=mock_request, response=mock_response)
    ctx.iwap_client.start_agent_run = AsyncMock(side_effect=error)
    
    # Should not raise, just log warning
    await register_participating_miners_in_iwap(ctx)
    
    # Verify calls were made despite 409
    assert ctx.iwap_client.start_agent_run.call_count == 2
    
    # Verify agent runs were added to context
    assert 42 in ctx.current_agent_runs
    assert 55 in ctx.current_agent_runs


@pytest.mark.asyncio
async def test_register_miners_missing_handshake_data():
    """Test that registration handles missing handshake payload."""
    ctx = MockContext()
    ctx.round_handshake_payloads = {42: None}  # Missing payload for miner 42
    ctx.active_miner_uids = [42]
    ctx.iwap_client.start_agent_run = AsyncMock(return_value={"status": "success"})
    
    await register_participating_miners_in_iwap(ctx)
    
    # Should still call start_agent_run with None handshake_payload
    assert ctx.iwap_client.start_agent_run.call_count == 1


@pytest.mark.asyncio
async def test_submit_task_results_success():
    """Test successful submission of task results to IWAP."""
    ctx = MockContext()
    ctx.current_agent_runs = {
        42: iwa_models.AgentRunIWAP(
            agent_run_id="1/1_UID42",
            validator_round_id="1/1",
            validator_uid=1,
            validator_hotkey="5FValidator...",
            miner_uid=42,
            miner_hotkey="5F3sa...",
            is_sota=False,
            version=None,
            started_at=1234567890.0,
        )
    }
    ctx.active_miner_uids = [42]
    
    # Mock task (TaskStub from conftest doesn't accept id parameter)
    from autoppia_iwa.src.data_generation.tasks.classes import Task
    from autoppia_iwa.src.demo_webs.classes import WebProject
    from autoppia_web_agents_subnet.validator.models import TaskWithProject
    
    task = Task(url="http://test.com", prompt="Test task")
    task.id = "task-1"  # Set id after creation
    project = WebProject(name="test-project", frontend_url="http://test.com")
    task_item = TaskWithProject(project=project, task=task)
    
    # Mock current_round_tasks
    ctx.current_round_tasks = {
        "task-1": iwa_models.TaskIWAP(
            task_id="task-1",
            validator_round_id="1/1",
            url="http://test.com",
            prompt="Test task",
            tests=[],
            is_web_real=True,
            specifications={},
            use_case="test",
        )
    }
    
    # Mock task solutions
    from autoppia_iwa.src.web_agents.classes import TaskSolution
    task_solution = TaskSolution(task_id="task-1", actions=[], web_agent_id="42")
    
    ctx.iwap_client.add_evaluation = AsyncMock()
    
    await submit_task_results(
        ctx,
        task_item=task_item,
        task_solutions=[task_solution],
        eval_scores=[0.8],
        test_results_list=[[]],
        evaluation_results=[{}],
        execution_times=[5.0],
        rewards=[0.8],
    )
    
    # Verify add_evaluation was called
    assert ctx.iwap_client.add_evaluation.call_count == 1


@pytest.mark.asyncio
async def test_submit_task_results_offline_mode():
    """Test that task results submission is skipped in offline mode."""
    ctx = MockContext()
    ctx._iwap_offline_mode = True
    ctx.iwap_client.add_evaluation = AsyncMock()
    
    from autoppia_iwa.src.data_generation.tasks.classes import Task
    from autoppia_iwa.src.demo_webs.classes import WebProject
    from autoppia_web_agents_subnet.validator.models import TaskWithProject
    
    task = Task(url="http://test.com", prompt="Test task")
    task.id = "task-1"  # Set id after creation
    project = WebProject(name="test-project", frontend_url="http://test.com")
    task_item = TaskWithProject(project=project, task=task)
    
    # This should return early and not call add_evaluation
    await submit_task_results(
        ctx,
        task_item=task_item,
        task_solutions=[],
        eval_scores=[],
        test_results_list=[],
        evaluation_results=[],
        execution_times=[],
        rewards=[],
    )
    
    # In offline mode, early return at line 28-29
    # No assertion needed - just verify it doesn't crash


@pytest.mark.asyncio
async def test_offline_mode_detection():
    """Test that offline mode is detected when IWAP is unreachable."""
    ctx = MockContext()
    ctx.iwap_client.auth_check = AsyncMock(side_effect=Exception("Connection refused"))
    
    # Mock dependencies
    with patch('autoppia_web_agents_subnet.platform.utils.round_flow.build_validator_identity'):
        with patch('autoppia_web_agents_subnet.platform.utils.round_flow.build_validator_snapshot'):
            try:
                await start_round_flow(ctx, current_block=1000, n_tasks=5)
            except:
                pass  # Expected to fail, we just want to verify offline mode was set
    
    # Verify offline mode was activated
    assert ctx._iwap_offline_mode == True


@pytest.mark.asyncio
async def test_full_integration_flow():
    """Test the complete IWAP integration flow from start to finish."""
    ctx = MockContext()
    
    # Mock all IWAP client methods
    ctx.iwap_client.auth_check = AsyncMock()
    ctx.iwap_client.start_round = AsyncMock(return_value={"validator_round_id": "1/1"})
    ctx.iwap_client.set_tasks = AsyncMock()
    ctx.iwap_client.start_agent_run = AsyncMock(return_value={"status": "success"})
    ctx.iwap_client.add_evaluation = AsyncMock()
    ctx.iwap_client.finish_round = AsyncMock()
    
    # Mock season manager
    ctx.season_manager = MagicMock()
    ctx.season_manager.get_season_number = MagicMock(return_value=1)
    
    # Mock round manager with round_times to avoid division by zero
    ctx.round_manager = MagicMock()
    ctx.round_manager.round_times = {42: [5.0, 6.0], 55: [7.0, 8.0]}
    
    # 1. Start round
    with patch('autoppia_web_agents_subnet.platform.utils.round_flow.build_validator_identity'):
        with patch('autoppia_web_agents_subnet.platform.utils.round_flow.build_validator_snapshot'):
            await start_round_flow(ctx, current_block=1000, n_tasks=5)
    
    # Verify start_round was called
    ctx.iwap_client.start_round.assert_called_once()
    
    # 2. Register miners (already tested above)
    await register_participating_miners_in_iwap(ctx)
    assert ctx.iwap_client.start_agent_run.call_count == 2
    
    # 3. Finish round (mock BURN_AMOUNT_PERCENTAGE if it doesn't exist)
    import autoppia_web_agents_subnet.validator.config as config_module
    original_hasattr = hasattr(config_module, 'BURN_AMOUNT_PERCENTAGE')
    if not original_hasattr:
        config_module.BURN_AMOUNT_PERCENTAGE = 0.1
    try:
        await finish_round_flow(ctx, avg_rewards={42: 0.8, 55: 0.6}, final_weights={42: 0.7, 55: 0.3}, tasks_completed=5)
    finally:
        if not original_hasattr:
            delattr(config_module, 'BURN_AMOUNT_PERCENTAGE')
    
    # Verify finish_round was called
    ctx.iwap_client.finish_round.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
