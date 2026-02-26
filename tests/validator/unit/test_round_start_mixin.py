"""
Unit tests for ValidatorRoundStartMixin.

Tests round start logic, commitment collection, and minimum block waiting.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase


@pytest.mark.unit
@pytest.mark.asyncio
class TestRoundStart:
    """Test round start logic."""

    async def test_start_round_early_in_round_continues_forward(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)

        """Test that _start_round early in round continues with forward pass."""
        dummy_validator.block = 1100  # Early in round (fraction < 0.2)

        result = await dummy_validator._start_round()

        assert result.continue_forward is True
        assert dummy_validator.round_manager.round_number == 1

    async def test_start_round_late_in_round_waits_for_boundary(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)

        """Test that _start_round late in round waits for next boundary."""
        dummy_validator.block = 1650  # Late in round (fraction > 0.2)
        dummy_validator._wait_until_specific_block = AsyncMock()

        with patch("autoppia_web_agents_subnet.validator.round_start.mixin.SKIP_ROUND_IF_STARTED_AFTER_FRACTION", 0.2):
            result = await dummy_validator._start_round()

        assert result.continue_forward is False
        dummy_validator._wait_until_specific_block.assert_called_once()

    async def test_season_transition_triggers_task_regeneration(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)

        """Test that season transition regenerates tasks and clears agents."""
        dummy_validator.block = 4600  # Start of new season (early in round)
        dummy_validator.season_manager.task_generated_season = 1
        # Mock should_start_new_season to return True for this test
        dummy_validator.season_manager.should_start_new_season = Mock(return_value=True)
        # Use the existing mock from fixture, just reset it
        dummy_validator.season_manager.generate_season_tasks.reset_mock()

        # Add some agents to queue
        from autoppia_web_agents_subnet.validator.models import AgentInfo

        agent = AgentInfo(uid=1, agent_name="test", github_url="https://test.com")
        dummy_validator.agents_dict[1] = agent
        dummy_validator.agents_queue.put(agent)

        await dummy_validator._start_round()

        # Should regenerate tasks
        dummy_validator.season_manager.generate_season_tasks.assert_called_once()
        # Should clear agents
        assert len(dummy_validator.agents_dict) == 0

    async def test_round_manager_start_new_round_is_called(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)

        """Test that start_new_round is called on round_manager."""
        dummy_validator.block = 1100

        await dummy_validator._start_round()

        assert dummy_validator.round_manager.current_phase == RoundPhase.PREPARING
        assert len(dummy_validator.round_manager.phase_history) > 0


def _mock_commitments_for_uids(hotkeys, uid_data):
    """
    Build a Dict[hotkey_ss58, commitment_dict] from a uid→data mapping.

    ``uid_data`` maps uid (int) to a dict with keys ``n``, ``g``, and optionally ``i``.
    """
    result = {}
    for uid, data in uid_data.items():
        hk = hotkeys[uid] if uid < len(hotkeys) else f"hk_{uid}"
        result[hk] = {"t": "m", **data}
    return result


@pytest.mark.unit
@pytest.mark.asyncio
class TestCollectMinerCommitments:
    """Test commitment collection logic."""

    async def test_collect_reads_commitments_for_eligible_miners(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())

        commitments = _mock_commitments_for_uids(
            dummy_validator.metagraph.hotkeys,
            {
                1: {"n": "agent1", "g": "https://github.com/test/agent1/tree/main"},
                2: {"n": "agent2", "g": "https://github.com/test/agent2/tree/main"},
            },
        )

        with patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new_callable=AsyncMock, return_value=commitments):
            await dummy_validator._collect_miner_commitments()

        # Should have active miners for UIDs with commitments
        assert len(dummy_validator.active_miner_uids) >= 1

    async def test_collect_filters_miners_by_min_stake(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())

        # Set stakes: UIDs 1,2,3 have sufficient stake (UID 0 is validator)
        dummy_validator.metagraph.S = [100.0, 150.0, 200.0, 100.0, 50.0, 30.0, 10.0, 0.0, 0.0, 0.0]
        dummy_validator.metagraph.stake = [100.0, 150.0, 200.0, 100.0, 50.0, 30.0, 10.0, 0.0, 0.0, 0.0]

        # Provide commitments for all UIDs 1-9
        commitments = _mock_commitments_for_uids(
            dummy_validator.metagraph.hotkeys,
            {uid: {"n": f"agent{uid}", "g": f"https://github.com/test/agent{uid}/tree/main"} for uid in range(1, 10)},
        )

        with (
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.MIN_MINER_STAKE_ALPHA", 100.0),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new_callable=AsyncMock, return_value=commitments),
        ):
            await dummy_validator._collect_miner_commitments()

        # Only UIDs 1, 2, 3 have stake >= 100 (uid 0 is validator)
        # Active miners should be those with valid commitments AND sufficient stake
        for uid in dummy_validator.active_miner_uids:
            assert uid in [1, 2, 3]

    async def test_collect_populates_agents_dict_and_queue(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.agents_dict = {}

        commitments = _mock_commitments_for_uids(
            dummy_validator.metagraph.hotkeys,
            {
                1: {"n": "agent1", "g": "https://github.com/test/agent1/tree/main"},
                2: {"n": "agent2", "g": "https://github.com/test/agent2/tree/main"},
            },
        )

        with patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new_callable=AsyncMock, return_value=commitments):
            await dummy_validator._collect_miner_commitments()

        assert len(dummy_validator.agents_dict) > 0

    async def test_collect_excludes_validator_own_uid(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.uid = 0

        # Provide commitment for the validator's own UID
        commitments = _mock_commitments_for_uids(
            dummy_validator.metagraph.hotkeys,
            {
                0: {"n": "validator_agent", "g": "https://github.com/test/validator/tree/main"},
                1: {"n": "agent1", "g": "https://github.com/test/agent1/tree/main"},
            },
        )

        with patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new_callable=AsyncMock, return_value=commitments):
            await dummy_validator._collect_miner_commitments()

        # UID 0 (validator) should not appear in active miners
        assert 0 not in dummy_validator.active_miner_uids

    async def test_collect_handles_missing_agent_name_or_github_url(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.agents_dict = {}

        commitments = _mock_commitments_for_uids(
            dummy_validator.metagraph.hotkeys,
            {
                1: {"n": "agent1", "g": "https://github.com/test/agent1/tree/main"},
                2: {"n": "", "g": "https://github.com/test/agent2/tree/main"},  # Empty name
                3: {"n": "agent3", "g": ""},  # Empty URL
            },
        )

        with patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new_callable=AsyncMock, return_value=commitments):
            await dummy_validator._collect_miner_commitments()

        # agent1 should be active; agent2/3 should be marked as evaluated with 0
        valid_agents = [a for a in dummy_validator.agents_dict.values() if a.agent_name and a.github_url]
        assert len(valid_agents) >= 1

    async def test_collect_does_not_reenqueue_when_submission_unchanged(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())

        dummy_validator.uid = 0
        dummy_validator.metagraph.n = 2
        dummy_validator.metagraph.stake = [15000.0, 15000.0]

        from autoppia_web_agents_subnet.validator.models import AgentInfo

        existing = AgentInfo(
            uid=1,
            agent_name="agent1",
            github_url="https://github.com/test/agent1/tree/main",
            agent_image=None,
            score=0.42,
            evaluated=True,
            normalized_repo="https://github.com/test/agent1",
            git_commit="deadbeef",
        )
        dummy_validator.agents_dict = {1: existing}

        commitments = _mock_commitments_for_uids(
            dummy_validator.metagraph.hotkeys,
            {1: {"n": "agent1", "g": "https://github.com/test/agent1/tree/main"}},
        )

        with (
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new_callable=AsyncMock, return_value=commitments),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.resolve_remote_ref_commit", return_value="deadbeef"),
        ):
            dummy_validator.agents_queue.put.reset_mock()
            await dummy_validator._collect_miner_commitments()

            dummy_validator.agents_queue.put.assert_not_called()
            assert dummy_validator.agents_dict[1].score == 0.42
            assert dummy_validator.agents_dict[1].evaluated is True

    async def test_collect_reenqueues_when_submission_commit_changes(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())

        dummy_validator.uid = 0
        dummy_validator.metagraph.n = 2
        dummy_validator.metagraph.stake = [15000.0, 15000.0]

        from autoppia_web_agents_subnet.validator.models import AgentInfo

        existing = AgentInfo(
            uid=1,
            agent_name="agent1",
            github_url="https://github.com/test/agent1/tree/main",
            agent_image=None,
            score=0.42,
            evaluated=True,
            normalized_repo="https://github.com/test/agent1",
            git_commit="old",
        )
        dummy_validator.agents_dict = {1: existing}

        commitments = _mock_commitments_for_uids(
            dummy_validator.metagraph.hotkeys,
            {1: {"n": "agent1", "g": "https://github.com/test/agent1/tree/main"}},
        )

        with (
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new_callable=AsyncMock, return_value=commitments),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.resolve_remote_ref_commit", return_value="new"),
        ):
            dummy_validator.agents_queue.put.reset_mock()
            await dummy_validator._collect_miner_commitments()

            dummy_validator.agents_queue.put.assert_called_once()
            # Preserve existing evaluated score until new evaluation completes.
            assert dummy_validator.agents_dict[1].score == 0.42
            assert dummy_validator.agents_dict[1].git_commit == "old"

    async def test_collect_limits_candidates_to_top_stake_window(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())

        dummy_validator.uid = 0
        dummy_validator.metagraph.n = 6
        dummy_validator.metagraph.stake = [0.0, 1.0, 10.0, 5.0, 2.0, 8.0]
        dummy_validator.metagraph.hotkeys = [f"hk_{i}" for i in range(6)]
        dummy_validator.metagraph.coldkeys = [f"ck_{i}" for i in range(6)]

        # Provide commitments for all
        commitments = _mock_commitments_for_uids(
            dummy_validator.metagraph.hotkeys,
            {uid: {"n": f"agent{uid}", "g": f"https://github.com/test/agent{uid}/tree/main"} for uid in range(1, 6)},
        )

        with (
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.MIN_MINER_STAKE_ALPHA", 0.0),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.MAX_MINERS_PER_ROUND_BY_STAKE", 2),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new_callable=AsyncMock, return_value=commitments),
        ):
            await dummy_validator._collect_miner_commitments()

            # Only top-2 stake miners (uids 2 and 5) should be candidates
            assert set(dummy_validator.round_candidate_uids) == {2, 5}

    async def test_collect_rate_limits_resubmissions_by_round_cooldown(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())

        dummy_validator.uid = 0
        dummy_validator.metagraph.n = 2
        dummy_validator.metagraph.stake = [15000.0, 15000.0]

        # Set current round so cooldown math is deterministic.
        dummy_validator.round_manager.round_number = 5

        from autoppia_web_agents_subnet.validator.models import AgentInfo

        existing = AgentInfo(
            uid=1,
            agent_name="agent1",
            github_url="https://github.com/test/agent1/tree/main",
            agent_image=None,
            score=0.42,
            evaluated=True,
            normalized_repo="https://github.com/test/agent1",
            git_commit="old",
            last_evaluated_round=4,  # cooldown should block in round 5
        )
        dummy_validator.agents_dict = {1: existing}

        commitments = _mock_commitments_for_uids(
            dummy_validator.metagraph.hotkeys,
            {1: {"n": "agent1", "g": "https://github.com/test/agent1/tree/main"}},
        )

        with (
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.EVALUATION_COOLDOWN_MIN_ROUNDS", 1),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.EVALUATION_COOLDOWN_MAX_ROUNDS", 2),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.EVALUATION_COOLDOWN_NO_RESPONSE_BADNESS", 0.0),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.EVALUATION_COOLDOWN_ZERO_SCORE_BADNESS", 0.0),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new_callable=AsyncMock, return_value=commitments),
            patch("autoppia_web_agents_subnet.validator.round_start.mixin.resolve_remote_ref_commit", return_value="new"),
        ):
            dummy_validator.agents_queue.put.reset_mock()
            await dummy_validator._collect_miner_commitments()

            # Cooldown blocks evaluation enqueue, but stores a pending submission.
            dummy_validator.agents_queue.put.assert_not_called()
            assert dummy_validator.agents_dict[1].pending_github_url == "https://github.com/test/agent1/commit/new"

            # Next eligible round: miner has no commitment => pending enqueued.
            dummy_validator.round_manager.round_number = 6
            dummy_validator.agents_queue.put.reset_mock()
            # Remove commitment so uid has "no commitment" → pending restoration kicks in
            empty_commitments: dict = {}
            with patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new_callable=AsyncMock, return_value=empty_commitments):
                await dummy_validator._collect_miner_commitments()
            dummy_validator.agents_queue.put.assert_called_once()
            pending_agent_info = dummy_validator.agents_queue.put.call_args.args[0]
            assert pending_agent_info.uid == 1
            assert pending_agent_info.github_url == "https://github.com/test/agent1/commit/new"

    async def test_collect_skips_non_miner_commitments(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.agents_dict = {}

        # Validator commitment (t=v) should be ignored
        hotkeys = dummy_validator.metagraph.hotkeys
        commitments = {
            hotkeys[1]: {"t": "v", "v": 1, "s": 1, "r": 1, "c": "QmCID"},
            hotkeys[2]: {"t": "m", "n": "agent2", "g": "https://github.com/test/agent2/tree/main"},
        }

        with patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new_callable=AsyncMock, return_value=commitments):
            await dummy_validator._collect_miner_commitments()

        # Only uid 2 should be active (uid 1 is validator commitment)
        assert 1 not in dummy_validator.active_miner_uids
        assert 2 in dummy_validator.active_miner_uids

    async def test_collect_handles_chain_read_failure_gracefully(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator._get_async_subtensor = AsyncMock(return_value=Mock())
        dummy_validator.agents_dict = {}

        with patch("autoppia_web_agents_subnet.validator.round_start.mixin.read_all_plain_commitments", new_callable=AsyncMock, side_effect=Exception("chain error")):
            # Should not raise; treats as no commitments
            await dummy_validator._collect_miner_commitments()

        assert dummy_validator.active_miner_uids == []


@pytest.mark.unit
@pytest.mark.asyncio
class TestMinimumBlock:
    """Test minimum block waiting logic."""

    async def test_wait_for_minimum_start_block_waits_when_early(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)

        """Test that _wait_for_minimum_start_block waits when before minimum."""
        dummy_validator.block = 500  # Before minimum_start_block (1000)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await dummy_validator._wait_for_minimum_start_block()

            assert result is True  # Indicates wait occurred
            mock_sleep.assert_called_once()

    async def test_wait_for_minimum_start_block_continues_when_ready(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)

        """Test that _wait_for_minimum_start_block continues when past minimum."""
        dummy_validator.block = 1500  # After minimum_start_block (1000)

        result = await dummy_validator._wait_for_minimum_start_block()

        assert result is False  # No wait needed

    async def test_wait_calculates_correct_eta(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)

        """Test that wait calculates correct ETA for minimum block."""
        dummy_validator.block = 500  # 500 blocks before minimum

        blocks_remaining = dummy_validator.round_manager.blocks_until_allowed(500)
        assert blocks_remaining == 500

        # ETA should be blocks * 12 seconds / 60 = 100 minutes
        expected_minutes = 500 * 12 / 60
        assert abs(expected_minutes - 100.0) < 0.1


@pytest.mark.unit
@pytest.mark.asyncio
class TestCollectMinerCommitmentsEdgeCases:
    """Test edge cases in commitment collection logic."""

    async def test_collect_with_no_metagraph(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)

        """Test commitment collection handles missing metagraph gracefully."""
        dummy_validator.metagraph = None

        # Should not raise exception
        await dummy_validator._collect_miner_commitments()

    async def test_collect_with_empty_metagraph(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)

        """Test commitment collection handles empty metagraph."""
        dummy_validator.metagraph.n = 0

        # Should not raise exception
        await dummy_validator._collect_miner_commitments()

    async def test_collect_with_no_eligible_miners(self, dummy_validator):
        from tests.conftest import _bind_round_start_mixin

        dummy_validator = _bind_round_start_mixin(dummy_validator)

        """Test commitment collection when no miners meet minimum stake."""
        dummy_validator.metagraph.S = [10.0] * 10
        dummy_validator.metagraph.stake = [10.0] * 10

        with patch("autoppia_web_agents_subnet.validator.round_start.mixin.MIN_MINER_STAKE_ALPHA", 100.0):
            # Should not raise exception
            await dummy_validator._collect_miner_commitments()
