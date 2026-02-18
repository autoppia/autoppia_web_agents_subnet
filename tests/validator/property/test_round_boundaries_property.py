"""
Property-based tests for round boundary calculations.

Uses Hypothesis to test round boundary consistency across many inputs.
"""

import pytest
from hypothesis import given, strategies as st, assume
from autoppia_web_agents_subnet.validator.round_manager import RoundManager


@pytest.mark.property
class TestRoundBoundaryProperties:
    """Property-based tests for round boundaries."""

    @given(
        current_block=st.integers(min_value=1000, max_value=100000),
        round_size_epochs=st.floats(min_value=0.5, max_value=10.0),
        minimum_start_block=st.integers(min_value=500, max_value=2000),
    )
    def test_round_boundary_consistency(self, current_block, round_size_epochs, minimum_start_block):
        """
        Property 1: Round Boundary Consistency
        
        For any current block, calling sync_boundaries multiple times should
        produce the same boundaries.
        
        **Validates: Requirements 1.1**
        """
        manager = RoundManager(
            round_size_epochs=round_size_epochs,
            minimum_start_block=minimum_start_block,
            settlement_fraction=0.8,
        )
        
        # First call
        manager.sync_boundaries(current_block)
        start_block_1 = manager.start_block
        target_block_1 = manager.target_block
        settlement_block_1 = manager.settlement_block
        
        # Second call with same block
        manager.sync_boundaries(current_block)
        start_block_2 = manager.start_block
        target_block_2 = manager.target_block
        settlement_block_2 = manager.settlement_block
        
        # Should be consistent
        assert start_block_1 == start_block_2
        assert target_block_1 == target_block_2
        assert settlement_block_1 == settlement_block_2

    @given(
        current_block=st.integers(min_value=1000, max_value=100000),
        round_size_epochs=st.floats(min_value=0.5, max_value=10.0),
    )
    def test_fraction_elapsed_is_between_zero_and_one(self, current_block, round_size_epochs):
        """
        Property 2: Fraction Elapsed Bounds
        
        For any current block within a round, fraction_elapsed should be
        between 0.0 and 1.0 (inclusive).
        
        **Validates: Requirements 1.2**
        """
        manager = RoundManager(
            round_size_epochs=round_size_epochs,
            minimum_start_block=1000,
            settlement_fraction=0.8,
        )
        
        manager.sync_boundaries(current_block)
        
        # Test at start, middle, and end of round
        for test_block in [manager.start_block, 
                          manager.start_block + manager.round_block_length // 2,
                          manager.target_block]:
            fraction = manager.fraction_elapsed(test_block)
            assert 0.0 <= fraction <= 1.0

    @given(
        current_block=st.integers(min_value=1000, max_value=100000),
        round_size_epochs=st.floats(min_value=0.5, max_value=10.0),
        settlement_fraction=st.floats(min_value=0.1, max_value=0.9),
    )
    def test_settlement_block_is_between_start_and_target(
        self, current_block, round_size_epochs, settlement_fraction
    ):
        """
        Property 3: Settlement Block Position
        
        For any round, settlement_block should be between start_block and
        target_block.
        
        **Validates: Requirements 1.1, 1.4**
        """
        manager = RoundManager(
            round_size_epochs=round_size_epochs,
            minimum_start_block=1000,
            settlement_fraction=settlement_fraction,
        )
        
        manager.sync_boundaries(current_block)
        
        assert manager.start_block <= manager.settlement_block <= manager.target_block

    @given(
        block1=st.integers(min_value=1000, max_value=50000),
        block2=st.integers(min_value=1000, max_value=50000),
        round_size_epochs=st.floats(min_value=1.0, max_value=5.0),
    )
    def test_round_number_increases_monotonically(self, block1, block2, round_size_epochs):
        """
        Property 4: Round Number Monotonicity
        
        For any two blocks where block2 > block1, the round number at block2
        should be >= the round number at block1.
        
        **Validates: Requirements 1.1**
        """
        assume(block2 > block1)
        
        manager = RoundManager(
            round_size_epochs=round_size_epochs,
            minimum_start_block=1000,
            settlement_fraction=0.8,
        )
        
        manager.sync_boundaries(block1)
        round1 = manager.round_number
        
        manager.sync_boundaries(block2)
        round2 = manager.round_number
        
        assert round2 >= round1

    @given(
        current_block=st.integers(min_value=1000, max_value=100000),
        round_size_epochs=st.floats(min_value=0.5, max_value=10.0),
    )
    def test_round_block_length_is_positive(self, current_block, round_size_epochs):
        """
        Property 5: Positive Round Length
        
        For any valid round configuration, round_block_length should be positive.
        
        **Validates: Requirements 1.1**
        """
        manager = RoundManager(
            round_size_epochs=round_size_epochs,
            minimum_start_block=1000,
            settlement_fraction=0.8,
        )
        
        assert manager.round_block_length > 0

    @given(
        current_block=st.integers(min_value=1000, max_value=100000),
        round_size_epochs=st.floats(min_value=0.5, max_value=10.0),
    )
    def test_target_block_equals_start_plus_length(self, current_block, round_size_epochs):
        """
        Property 6: Target Block Calculation
        
        For any round, target_block should equal start_block + round_block_length.
        
        **Validates: Requirements 1.1**
        """
        manager = RoundManager(
            round_size_epochs=round_size_epochs,
            minimum_start_block=1000,
            settlement_fraction=0.8,
        )
        
        manager.sync_boundaries(current_block)
        
        expected_target = manager.start_block + manager.round_block_length
        assert manager.target_block == expected_target

    @given(
        block=st.integers(min_value=0, max_value=100000),
    )
    def test_block_epoch_conversion_is_reversible(self, block):
        """
        Property 7: Block/Epoch Conversion Round Trip
        
        For any block, converting to epoch and back should yield the same block
        (within rounding tolerance).
        
        **Validates: Requirements 1.1**
        """
        epoch = RoundManager.block_to_epoch(block)
        block_back = RoundManager.epoch_to_block(epoch)
        
        # Should be equal (epoch_to_block uses int conversion)
        assert abs(block - block_back) <= 1
