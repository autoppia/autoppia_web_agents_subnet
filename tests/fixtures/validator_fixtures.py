"""
Validator fixtures for testing the new validator workflow.

Provides fixtures for:
- Validator configuration
- Validator instances with all mixins
- RoundManager instances
- SeasonManager instances
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock
from typing import Dict, Any

from autoppia_web_agents_subnet.validator.round_manager import RoundManager, RoundPhase
from autoppia_web_agents_subnet.validator.season_manager import SeasonManager


@pytest.fixture
def mock_validator_config() -> Dict[str, Any]:
    """
    Minimal validator configuration for testing.
    """
    return {
        "round_size_epochs": 2.0,
        "minimum_start_block": 1000,
        "settlement_fraction": 0.8,
        "season_size_epochs": 10.0,
        "netuid": 99,
        "subtensor": {
            "network": "test",
            "chain_endpoint": "ws://127.0.0.1:9944",
        },
        "wallet": {
            "name": "test_validator",
            "hotkey": "test_hotkey",
        },
    }


@pytest.fixture
def round_manager(mock_validator_config: Dict[str, Any]) -> RoundManager:
    """
    Create a RoundManager instance with test configuration.
    """
    return RoundManager(
        round_size_epochs=mock_validator_config["round_size_epochs"],
        minimum_start_block=mock_validator_config["minimum_start_block"],
        settlement_fraction=mock_validator_config["settlement_fraction"],
    )


@pytest.fixture
def season_manager(mock_validator_config: Dict[str, Any]) -> SeasonManager:
    """
    Create a SeasonManager instance with test configuration.
    """
    return SeasonManager()


@pytest.fixture
def dummy_validator(mock_validator_config: Dict[str, Any]) -> Mock:
    """
    Create a mock validator with all necessary attributes and mixins.
    
    This fixture provides a lightweight validator mock without requiring
    actual Bittensor network connections or Docker containers.
    """
    validator = Mock()
    
    # Basic attributes
    validator.config = mock_validator_config
    validator.block = 1000
    validator.uid = 0
    validator.version = "1.0.0"
    
    # Managers
    validator.round_manager = RoundManager(
        round_size_epochs=mock_validator_config["round_size_epochs"],
        minimum_start_block=mock_validator_config["minimum_start_block"],
        settlement_fraction=mock_validator_config["settlement_fraction"],
    )
    validator.season_manager = SeasonManager()
    
    # Agent tracking
    validator.agents_dict = {}
    validator.agents_queue = Mock()
    validator.agents_queue.empty = Mock(return_value=True)
    validator.agents_queue.get = Mock(side_effect=Exception("Queue empty"))
    
    # Sandbox manager (mocked)
    validator.sandbox_manager = None
    
    # Metagraph mock
    validator.metagraph = Mock()
    validator.metagraph.n = 10
    validator.metagraph.uids = list(range(10))
    validator.metagraph.S = [100.0] * 10  # Stake values
    validator.metagraph.axons = [Mock(ip="127.0.0.1", port=8000 + i) for i in range(10)]
    
    # Async methods
    validator.sync = AsyncMock()
    
    # Sync methods that were incorrectly marked as async
    validator.set_weights = Mock()
    validator.update_scores = Mock()
    
    # Mixin methods (will be tested separately)
    validator._start_round = AsyncMock()
    validator._perform_handshake = AsyncMock()
    validator._wait_for_minimum_start_block = AsyncMock(return_value=False)
    validator._wait_until_specific_block = AsyncMock()
    validator._run_evaluation_phase = AsyncMock(return_value=0)
    validator._run_settlement_phase = AsyncMock()
    
    # Round ID for logging
    validator.current_round_id = "test-round-1"
    
    return validator


@pytest.fixture
def validator_with_agents(dummy_validator: Mock) -> Mock:
    """
    Create a validator with pre-populated agent information.
    
    Useful for testing evaluation and settlement phases.
    """
    from autoppia_web_agents_subnet.validator.models import AgentInfo
    
    # Add 3 test agents
    for uid in [1, 2, 3]:
        agent = AgentInfo(
            uid=uid,
            agent_name=f"test_agent_{uid}",
            github_url=f"https://github.com/test/agent{uid}",
            score=0.0,
        )
        dummy_validator.agents_dict[uid] = agent
        dummy_validator.agents_queue.put(agent)
    
    # Update queue mock to return agents
    dummy_validator.agents_queue.empty = Mock(return_value=False)
    agents_list = list(dummy_validator.agents_dict.values())
    dummy_validator.agents_queue.get = Mock(side_effect=agents_list + [Exception("Queue empty")])
    
    return dummy_validator
