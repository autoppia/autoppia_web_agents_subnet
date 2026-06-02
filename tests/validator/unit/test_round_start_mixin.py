"""
Unit tests for ValidatorRoundStartMixin.

Covers round-start behavior plus miner discovery through on-chain commitments.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from autoppia_web_agents_subnet.validator.round_manager import RoundPhase


@pytest.mark.unit
@pytest.mark.asyncio
class TestRoundStart:
    async def test_start_round_early_in_round_continues_forward(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator.block = 1100

        result = await dummy_validator._start_round()

        assert result.continue_forward is True
        assert dummy_validator.round_manager.round_number == 1

    async def test_start_round_late_in_round_waits_for_boundary(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator.block = 1650
        dummy_validator._wait_until_specific_block = AsyncMock()

        with patch("autoppia_web_agents_subnet.validator.round_start.mixin.SKIP_ROUND_IF_STARTED_AFTER_FRACTION", 0.2):
            result = await dummy_validator._start_round()

        assert result.continue_forward is False
        dummy_validator._wait_until_specific_block.assert_called_once()

    async def test_season_transition_triggers_task_regeneration(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator.block = 4600
        dummy_validator.season_manager.task_generated_season = 1
        dummy_validator.season_manager.should_start_new_season = Mock(return_value=True)
        dummy_validator.season_manager.generate_season_tasks.reset_mock()

        from autoppia_web_agents_subnet.validator.models import AgentInfo

        agent = AgentInfo(uid=1, agent_name="test", github_url="https://test.com")
        dummy_validator.agents_dict[1] = agent
        dummy_validator.agents_queue.put(agent)

        await dummy_validator._start_round()

        dummy_validator.season_manager.generate_season_tasks.assert_called_once()
        assert len(dummy_validator.agents_dict) == 0

    async def test_round_manager_start_new_round_is_called(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator.block = 1100

        await dummy_validator._start_round()

        assert dummy_validator.round_manager.current_phase == RoundPhase.PREPARING
        assert len(dummy_validator.round_manager.phase_history) > 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestCommitmentDiscovery:
    async def test_discovery_populates_agents_from_commitments(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator.uid = 0
        dummy_validator.metagraph.n = 3
        dummy_validator.metagraph.stake = [0.0, 15000.0, 5000.0]
        dummy_validator.metagraph.S = [0.0, 15000.0, 5000.0]
        dummy_validator.metagraph.hotkeys = ["validator", "miner-1", "miner-2"]
        dummy_validator.metagraph.coldkeys = ["validator-cold", "miner-cold-1", "miner-cold-2"]

        commitments = {
            "miner-1": {
                "t": "m",
                "n": "agent1",
                "g": "https://github.com/test/agent1/tree/main",
            }
        }

        with (
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new=AsyncMock(return_value=commitments)),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.resolve_remote_ref_commit", return_value="deadbeef"),
        ):
            await dummy_validator._perform_handshake()

        assert 1 in dummy_validator.agents_dict
        assert dummy_validator.agents_dict[1].github_url == "https://github.com/test/agent1/commit/deadbeef"
        assert dummy_validator.eligibility_status_by_uid[1] == "handshake_valid"
        assert dummy_validator.active_miner_uids == [1]

    async def test_discovery_reuses_same_commit_when_stats_match(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator.uid = 0
        dummy_validator.metagraph.n = 2
        dummy_validator.metagraph.stake = [0.0, 15000.0]
        dummy_validator.metagraph.S = [0.0, 15000.0]
        dummy_validator.metagraph.hotkeys = ["validator", "miner-1"]
        dummy_validator.metagraph.coldkeys = ["validator-cold", "miner-cold-1"]

        from autoppia_web_agents_subnet.validator.models import AgentInfo

        existing = AgentInfo(
            uid=1,
            agent_name="agent1",
            github_url="https://github.com/test/agent1/tree/main",
            normalized_repo="https://github.com/test/agent1",
            git_commit="deadbeef",
            evaluated=True,
            score=0.42,
        )
        dummy_validator.agents_dict = {1: existing}
        dummy_validator._find_reusable_commit_stats = Mock(
            return_value={"agent_run_id": "run-1", "evaluation_context": {"evaluation_context_hash": "sha256:test"}}
        )

        commitments = {
            "miner-1": {
                "t": "m",
                "n": "agent1",
                "g": "https://github.com/test/agent1/tree/main",
            }
        }

        with (
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new=AsyncMock(return_value=commitments)),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.resolve_remote_ref_commit", return_value="deadbeef"),
        ):
            dummy_validator.agents_queue.put.reset_mock()
            await dummy_validator._perform_handshake()

        dummy_validator.agents_queue.put.assert_not_called()
        assert dummy_validator.eligibility_status_by_uid[1] == "reused"
        assert 1 in dummy_validator.miners_reused_this_round

    async def test_discovery_cooldown_stores_pending_submission(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator.uid = 0
        dummy_validator.metagraph.n = 2
        dummy_validator.metagraph.stake = [0.0, 15000.0]
        dummy_validator.metagraph.S = [0.0, 15000.0]
        dummy_validator.metagraph.hotkeys = ["validator", "miner-1"]
        dummy_validator.metagraph.coldkeys = ["validator-cold", "miner-cold-1"]
        dummy_validator.round_manager.round_number = 5

        from autoppia_web_agents_subnet.validator.models import AgentInfo

        existing = AgentInfo(
            uid=1,
            agent_name="agent1",
            github_url="https://github.com/test/agent1/tree/main",
            normalized_repo="https://github.com/test/agent1",
            git_commit="old",
            evaluated=True,
            score=0.42,
            last_evaluated_round=4,
        )
        dummy_validator.agents_dict = {1: existing}

        commitments = {
            "miner-1": {
                "t": "m",
                "n": "agent1",
                "g": "https://github.com/test/agent1/tree/main",
            }
        }

        with (
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new=AsyncMock(return_value=commitments)),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.resolve_remote_ref_commit", return_value="newcommit"),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.ENABLE_EVALUATION_COOLDOWN", True),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.EVALUATION_COOLDOWN_MIN_ROUNDS", 1),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.EVALUATION_COOLDOWN_MAX_ROUNDS", 2),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.EVALUATION_COOLDOWN_NO_RESPONSE_BADNESS", 0.0),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.EVALUATION_COOLDOWN_ZERO_SCORE_BADNESS", 0.0),
        ):
            dummy_validator.agents_queue.put.reset_mock()
            await dummy_validator._perform_handshake()

        dummy_validator.agents_queue.put.assert_not_called()
        assert dummy_validator.agents_dict[1].pending_github_url == "https://github.com/test/agent1/commit/newcommit"

    async def test_discovery_with_no_metagraph_is_a_noop(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator.metagraph = None

        await dummy_validator._perform_handshake()

        assert dummy_validator.agents_dict == {}


@pytest.mark.unit
@pytest.mark.asyncio
class TestMinimumBlock:
    async def test_wait_for_minimum_start_block_waits_when_early(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator.block = 500

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await dummy_validator._wait_for_minimum_start_block()

        assert result is True
        mock_sleep.assert_called_once()

    async def test_wait_for_minimum_start_block_continues_when_ready(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator.block = 1500

        result = await dummy_validator._wait_for_minimum_start_block()

        assert result is False

    async def test_wait_calculates_correct_eta(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator.block = 500

        blocks_remaining = dummy_validator.round_manager.blocks_until_allowed(500)
        assert blocks_remaining == 500
        assert abs((500 * 12 / 60) - 100.0) < 0.1
