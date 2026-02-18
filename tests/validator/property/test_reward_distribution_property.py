"""
Property-based tests for reward distribution.

Uses Hypothesis to test WTA (Winner Takes All) reward properties.
"""

import pytest
import numpy as np
from hypothesis import given, strategies as st, assume
from unittest.mock import patch


@pytest.mark.property
class TestRewardDistributionProperties:
    """Property-based tests for reward distribution."""

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=20
        )
    )
    def test_wta_produces_single_winner(self, scores):
        """
        Property 4: WTA Reward Distribution
        
        For any set of scores, WTA should produce exactly one winner
        (one UID with weight 1.0, all others with weight 0.0).
        
        **Validates: Requirements 5.4**
        """
        assume(len(scores) > 0)
        assume(max(scores) > 1e-6)  # At least one meaningful non-zero score
        
        from autoppia_web_agents_subnet.validator.settlement.rewards import wta_rewards
        
        scores_array = np.array(scores, dtype=np.float32)
        rewards = wta_rewards(scores_array)
        
        # Count winners (weight = 1.0)
        winners = np.sum(rewards == 1.0)
        
        # Should have exactly one winner
        assert winners == 1

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=20
        )
    )
    def test_winner_has_weight_one(self, scores):
        """
        Property 5: Winner Weight Value
        
        For any set of scores, the winner should have weight exactly 1.0.
        
        **Validates: Requirements 5.4**
        """
        assume(len(scores) > 0)
        assume(max(scores) > 1e-6)  # At least one meaningful non-zero score
        
        from autoppia_web_agents_subnet.validator.settlement.rewards import wta_rewards
        
        scores_array = np.array(scores, dtype=np.float32)
        rewards = wta_rewards(scores_array)
        
        # Winner should have weight 1.0
        max_reward = np.max(rewards)
        assert abs(max_reward - 1.0) < 1e-6

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=20
        )
    )
    def test_all_others_have_weight_zero(self, scores):
        """
        Property 6: Non-Winner Weights
        
        For any set of scores, all non-winners should have weight 0.0.
        
        **Validates: Requirements 5.4**
        """
        assume(len(scores) > 0)
        assume(max(scores) > 1e-6)  # At least one meaningful non-zero score
        
        from autoppia_web_agents_subnet.validator.settlement.rewards import wta_rewards
        
        scores_array = np.array(scores, dtype=np.float32)
        rewards = wta_rewards(scores_array)
        
        # All non-winners should have weight 0.0
        non_winners = rewards[rewards < 1.0]
        assert np.all(non_winners == 0.0)

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=20
        )
    )
    def test_highest_score_wins(self, scores):
        """
        Property 7: Highest Score Selection
        
        For any set of scores, the UID with the highest score should be
        the winner.
        
        **Validates: Requirements 5.4**
        """
        assume(len(scores) > 0)
        assume(max(scores) > 1e-6)  # At least one meaningful non-zero score
        
        from autoppia_web_agents_subnet.validator.settlement.rewards import wta_rewards
        
        scores_array = np.array(scores, dtype=np.float32)
        rewards = wta_rewards(scores_array)
        
        # Find winner index
        winner_idx = np.argmax(rewards)
        
        # Winner should have highest score
        assert scores_array[winner_idx] == np.max(scores_array)

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=20
        )
    )
    def test_total_weight_equals_one_or_zero(self, scores):
        """
        Property 8: Total Weight Conservation
        
        For any set of scores, the total weight should be either 1.0
        (if there's a winner) or 0.0 (if all scores are zero).
        
        **Validates: Requirements 5.4**
        """
        assume(len(scores) > 0)
        
        from autoppia_web_agents_subnet.validator.settlement.rewards import wta_rewards
        
        scores_array = np.array(scores, dtype=np.float32)
        rewards = wta_rewards(scores_array)
        
        total_weight = np.sum(rewards)
        
        # Should be either 0.0 or 1.0
        assert abs(total_weight - 0.0) < 1e-6 or abs(total_weight - 1.0) < 1e-6

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=20
        )
    )
    def test_wta_is_deterministic(self, scores):
        """
        Property 9: WTA Determinism
        
        For any set of scores, calling WTA multiple times should produce
        the same result.
        
        **Validates: Requirements 5.4**
        """
        assume(len(scores) > 0)
        assume(max(scores) > 1e-6)  # At least one meaningful non-zero score
        
        from autoppia_web_agents_subnet.validator.settlement.rewards import wta_rewards
        
        scores_array = np.array(scores, dtype=np.float32)
        
        rewards1 = wta_rewards(scores_array.copy())
        rewards2 = wta_rewards(scores_array.copy())
        
        # Should be identical
        assert np.array_equal(rewards1, rewards2)

    @given(
        score=st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
        n=st.integers(min_value=1, max_value=20)
    )
    def test_single_non_zero_score_wins(self, score, n):
        """
        Property 10: Single Non-Zero Winner
        
        For any array with only one non-zero score, that UID should win.
        
        **Validates: Requirements 5.4**
        """
        from autoppia_web_agents_subnet.validator.settlement.rewards import wta_rewards
        
        # Create array with one non-zero score
        scores_array = np.zeros(n, dtype=np.float32)
        winner_idx = n // 2  # Put winner in middle
        scores_array[winner_idx] = score
        
        rewards = wta_rewards(scores_array)
        
        # Only the non-zero score should win
        assert rewards[winner_idx] == 1.0
        assert np.sum(rewards) == 1.0

    @given(
        n=st.integers(min_value=1, max_value=20)
    )
    def test_all_zero_scores_no_winner(self, n):
        """
        Property 11: No Winner for All Zeros
        
        For any array with all zero scores, there should be no winner
        (all weights should be 0.0).
        
        **Validates: Requirements 5.4**
        """
        from autoppia_web_agents_subnet.validator.settlement.rewards import wta_rewards
        
        scores_array = np.zeros(n, dtype=np.float32)
        rewards = wta_rewards(scores_array)
        
        # No winner
        assert np.sum(rewards) == 0.0
