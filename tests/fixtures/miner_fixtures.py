"""
Miner fixtures for testing validator interactions with miners.

Provides fixtures for:
- Mock miner instances
- Agent response payloads
- Task solution data
"""

import pytest
from unittest.mock import Mock
from typing import Dict, Any, List


@pytest.fixture
def mock_miner() -> Mock:
    """
    Create a mock miner with basic attributes.
    """
    miner = Mock()
    miner.uid = 1
    miner.hotkey = "test_miner_hotkey"
    miner.coldkey = "test_miner_coldkey"
    miner.ip = "127.0.0.1"
    miner.port = 8091
    miner.stake = 100.0
    
    return miner


@pytest.fixture
def agent_responses() -> List[Dict[str, Any]]:
    """
    Sample agent response payloads from miners during handshake.
    
    Returns a list of valid agent responses that would be received
    during the round start handshake phase.
    """
    return [
        {
            "uid": 1,
            "agent_name": "test_agent_1",
            "github_url": "https://github.com/test/agent1",
            "version": "1.0.0",
        },
        {
            "uid": 2,
            "agent_name": "test_agent_2",
            "github_url": "https://github.com/test/agent2",
            "version": "1.0.1",
        },
        {
            "uid": 3,
            "agent_name": "test_agent_3",
            "github_url": "https://github.com/test/agent3",
            "version": "1.1.0",
        },
    ]


@pytest.fixture
def invalid_agent_responses() -> List[Dict[str, Any]]:
    """
    Sample invalid agent responses for testing error handling.
    """
    return [
        {
            "uid": 4,
            # Missing agent_name
            "github_url": "https://github.com/test/agent4",
        },
        {
            "uid": 5,
            "agent_name": "test_agent_5",
            # Missing github_url
        },
        {
            "uid": 6,
            "agent_name": "",  # Empty agent_name
            "github_url": "https://github.com/test/agent6",
        },
    ]


@pytest.fixture
def task_solutions() -> List[Dict[str, Any]]:
    """
    Sample task solution data for testing evaluation.
    
    Returns task solutions with various scores to test
    score calculation and aggregation.
    """
    return [
        {
            "task_id": "task_1",
            "agent_id": "test_agent_1",
            "score": 0.9,
            "actions": [
                {"type": "click", "selector": "#button1"},
                {"type": "input", "selector": "#field1", "value": "test"},
            ],
            "success": True,
        },
        {
            "task_id": "task_2",
            "agent_id": "test_agent_1",
            "score": 0.7,
            "actions": [
                {"type": "click", "selector": "#button2"},
            ],
            "success": True,
        },
        {
            "task_id": "task_3",
            "agent_id": "test_agent_1",
            "score": 0.0,
            "actions": [],
            "success": False,
        },
    ]
