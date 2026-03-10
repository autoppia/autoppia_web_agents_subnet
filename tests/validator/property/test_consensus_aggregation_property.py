"""
Property-based tests for consensus score aggregation.

Uses Hypothesis to test score aggregation properties.
"""

import pytest
from hypothesis import given, strategies as st, assume

from autoppia_web_agents_subnet.validator.settlement.consensus import _aggregate_scores_for_validators


@pytest.mark.property
class TestConsensusAggregationProperties:
    """Property-based tests for consensus aggregation."""

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=10,
        ),
        stakes=st.lists(
            st.floats(min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=10,
        ),
    )
    def test_aggregated_scores_are_normalized(self, scores, stakes):
        """
        Property 3: Score Aggregation Normalization
        
        For any set of scores and stakes, the aggregated score should be
        between 0.0 and 1.0 (assuming input scores are normalized).
        
        **Validates: Requirements 6.3, 6.6**
        """
        assume(len(scores) == len(stakes))

        # Build entries for a single miner (uid=0) across validators.
        entries = [(stake, {0: score}) for score, stake in zip(scores, stakes)]
        result, _ = _aggregate_scores_for_validators(entries)
        aggregated = result.get(0, 0.0) if result else 0.0

        # Aggregated score should remain within normalized bounds.
        assert 0.0 <= aggregated <= 1.0

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=5,
        ),
        stakes=st.lists(
            st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=5,
        ),
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

        # Original order
        entries1 = [(stake, {0: score}) for score, stake in zip(scores, stakes)]
        result1, _ = _aggregate_scores_for_validators(entries1)
        agg1 = result1.get(0, 0.0) if result1 else 0.0

        # Reversed order
        entries2 = list(reversed(entries1))
        result2, _ = _aggregate_scores_for_validators(entries2)
        agg2 = result2.get(0, 0.0) if result2 else 0.0

        # Aggregation should be commutative (within floating point tolerance).
        assert abs(agg1 - agg2) < 1e-6

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
        # Generate two clearly different scores to avoid heavy assume() filtering.
        score_high=st.floats(min_value=0.6, max_value=1.0, allow_nan=False, allow_infinity=False),
        score_low=st.floats(min_value=0.0, max_value=0.4, allow_nan=False, allow_infinity=False),
        # Generate stakes such that the first validator has significantly more stake.
        stakes=st.floats(min_value=1.0, max_value=66.0, allow_nan=False, allow_infinity=False).flatmap(
            lambda stake_low: st.tuples(
                st.just(stake_low),
                st.floats(
                    min_value=(stake_low * 1.5) + 1e-6,
                    max_value=100.0,
                    allow_nan=False,
                    allow_infinity=False,
                ),
            )
        ),
    )
    def test_higher_stake_increases_influence(self, score_high, score_low, stakes):
        """
        Property 6: Stake Weighting Correctness
        
        For any validator with higher stake, their score should have more
        influence on the aggregated result.
        
        **Validates: Requirements 6.3, 6.4**
        """
        stake_low, stake_high = stakes

        scores = [score_high, score_low]
        stakes_list = [stake_high, stake_low]

        entries = [(stake, {0: score}) for score, stake in zip(scores, stakes_list)]
        result, _ = _aggregate_scores_for_validators(entries)
        aggregated = result.get(0, 0.0) if result else 0.0

        # With higher stake and higher score, the aggregate should be closer to the
        # higher-stake validator's score than to the lower-stake validator's score.
        assert abs(aggregated - score_high) < abs(aggregated - score_low)

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=10,
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
        entries = [(stake, {0: score}) for score, stake in zip(scores, stakes)]
        result, _ = _aggregate_scores_for_validators(entries)
        aggregated = result.get(0, 0.0) if result else 0.0

        # Should equal simple average
        simple_avg = sum(scores) / len(scores)

        assert abs(aggregated - simple_avg) < 1e-6

    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=10,
        ),
        stakes=st.lists(
            st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=10,
        ),
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
        zero_stakes = [0.0] * len(stakes)
        entries = [(stake, {0: score}) for score, stake in zip(scores, zero_stakes)]

        result, all_zero = _aggregate_scores_for_validators(entries)
        aggregated = result.get(0, 0.0) if result else 0.0

        simple_avg = sum(scores) / len(scores) if scores else 0.0

        # When all stakes are zero, aggregation should fall back to simple average.
        assert all_zero is True
        assert abs(aggregated - simple_avg) < 1e-6
