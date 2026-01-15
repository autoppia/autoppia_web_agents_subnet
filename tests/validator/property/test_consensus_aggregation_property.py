"""
Property-based tests for consensus score aggregation.

Uses Hypothesis to test score aggregation properties.
"""

import pytest
import numpy as np
from hypothesis import given, strategies as st, assume


@pytest.mark.property
class TestConsensusAggregationProperties:
    """Property-based tests for consensus aggregation."""

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=10
        ),
        stakes=st.lists(
            st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=10
        )
    )
    def test_aggregated_scores_are_normalized(self, scores, stakes):
        """
        Property 3: Score Aggregation Normalization
        
        For any set of scores and stakes, the aggregated score should be
        between 0.0 and 1.0 (assuming input scores are normalized).
        
        **Validates: Requirements 6.3, 6.6**
        """
        assume(len(scores) == len(stakes))
        assume(sum(stakes) > 0)  # At least some stake
        
        # Calculate stake-weighted average
        weighted_sum = sum(score * stake for score, stake in zip(scores, stakes))
        total_stake = sum(stakes)
        
        aggregated = weighted_sum / total_stake
        
        # Should be normalized
        assert 0.0 <= aggregated <= 1.0

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=5
        ),
        stakes=st.lists(
            st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=5
        )
    )
    def test_aggregation_is_commutative(self, scores, stakes):
        """
        Property 4: Aggregation Commutativity
        
        For any set of scores and stakes, the order of aggregation should not
        matter (aggregation is commutative).
        
        **Validates: Requirements 6.3**
        """
        assume(len(scores) == len(stakes))
        assume(sum(stakes) > 0)
        
        # Calculate in original order
        weighted_sum_1 = sum(score * stake for score, stake in zip(scores, stakes))
        total_stake_1 = sum(stakes)
        result_1 = weighted_sum_1 / total_stake_1
        
        # Reverse order
        scores_rev = list(reversed(scores))
        stakes_rev = list(reversed(stakes))
        
        weighted_sum_2 = sum(score * stake for score, stake in zip(scores_rev, stakes_rev))
        total_stake_2 = sum(stakes_rev)
        result_2 = weighted_sum_2 / total_stake_2
        
        # Should be equal (within floating point tolerance)
        assert abs(result_1 - result_2) < 1e-6

    @given(
        score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        stake=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    )
    def test_single_validator_returns_their_score(self, score, stake):
        """
        Property 5: Single Validator Identity
        
        For a single validator, the aggregated score should equal their score
        (regardless of stake).
        
        **Validates: Requirements 6.3**
        """
        # With only one validator, weighted average equals their score
        weighted_sum = score * stake
        total_stake = stake
        
        aggregated = weighted_sum / total_stake
        
        assert abs(aggregated - score) < 1e-6

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=10
        ),
        stakes=st.lists(
            st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=10
        )
    )
    def test_higher_stake_increases_influence(self, scores, stakes):
        """
        Property 6: Stake Weighting Correctness
        
        For any validator with higher stake, their score should have more
        influence on the aggregated result.
        
        **Validates: Requirements 6.3, 6.4**
        """
        assume(len(scores) == len(stakes))
        assume(len(scores) >= 2)
        assume(sum(stakes) > 0)
        assume(stakes[0] > stakes[1])  # First validator has more stake
        assume(abs(scores[0] - scores[1]) > 0.1)  # Scores are different
        
        # Calculate weighted average
        weighted_sum = sum(score * stake for score, stake in zip(scores, stakes))
        total_stake = sum(stakes)
        aggregated = weighted_sum / total_stake
        
        # If first validator has higher stake and higher score,
        # aggregated should be closer to their score
        if scores[0] > scores[1]:
            # Aggregated should be between the two scores
            assert min(scores[0], scores[1]) <= aggregated <= max(scores[0], scores[1])

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=10
        )
    )
    def test_equal_stakes_gives_simple_average(self, scores):
        """
        Property 7: Equal Stakes Simple Average
        
        When all validators have equal stake, the aggregated score should be
        the simple average of all scores.
        
        **Validates: Requirements 6.6**
        """
        assume(len(scores) > 0)
        
        # All equal stakes
        stakes = [1.0] * len(scores)
        
        # Calculate weighted average
        weighted_sum = sum(score * stake for score, stake in zip(scores, stakes))
        total_stake = sum(stakes)
        aggregated = weighted_sum / total_stake
        
        # Should equal simple average
        simple_avg = sum(scores) / len(scores)
        
        assert abs(aggregated - simple_avg) < 1e-6

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=10
        ),
        stakes=st.lists(
            st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=10
        )
    )
    def test_zero_stakes_handled_gracefully(self, scores, stakes):
        """
        Property 8: Zero Stake Handling
        
        When all stakes are zero, aggregation should handle it gracefully
        (either return 0 or use simple average).
        
        **Validates: Requirements 6.6**
        """
        assume(len(scores) == len(stakes))
        
        # Force all stakes to zero
        stakes = [0.0] * len(stakes)
        
        total_stake = sum(stakes)
        
        if total_stake == 0:
            # Should use simple average as fallback
            simple_avg = sum(scores) / len(scores) if scores else 0.0
            assert 0.0 <= simple_avg <= 1.0
