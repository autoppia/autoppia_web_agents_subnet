"""
Unit tests for RoundManager.

Tests round boundary calculations, phase transitions, and timing logic.
"""

import pytest
from autoppia_web_agents_subnet.validator.round_manager import (
    RoundManager,
    RoundPhase,
    PhaseTransition,
)


@pytest.mark.unit
class TestRoundBoundaries:
    """Test round boundary calculations."""

    def test_sync_boundaries_calculates_correct_blocks(self, round_manager):
        """Test that sync_boundaries calculates start, settlement, and target blocks correctly."""
        current_block = 1360  # 1 epoch into first round (360 blocks)
        round_manager.sync_boundaries(current_block)

        # With minimum_start_block=1000, round_size_epochs=2.0 (720 blocks)
        # First round: 1000-1719
        assert round_manager.start_block == 1000
        assert round_manager.target_block == 1720  # 1000 + 720
        assert round_manager.settlement_block == 1576  # 1000 + 720 * 0.8
        assert round_manager.round_number == 1

    def test_sync_boundaries_second_round(self, round_manager):
        """Test boundary calculation for second round."""
        current_block = 2000  # Into second round
        round_manager.sync_boundaries(current_block)

        # Second round: 1720-2439
        assert round_manager.start_block == 1720
        assert round_manager.target_block == 2440  # 1720 + 720
        assert round_manager.round_number == 2

    def test_sync_boundaries_before_minimum_start(self, round_manager):
        """Test that boundaries use minimum_start_block when current block is before it."""
        current_block = 500  # Before minimum_start_block (1000)
        round_manager.sync_boundaries(current_block)

        # Should still start from minimum_start_block
        assert round_manager.start_block == 1000
        assert round_manager.round_number == 1

    def test_get_round_boundaries_returns_correct_values(self, round_manager):
        """Test that get_round_boundaries returns all boundary information."""
        current_block = 1500
        boundaries = round_manager.get_round_boundaries(current_block)

        assert "round_start_block" in boundaries
        assert "round_target_block" in boundaries
        assert "round_start_epoch" in boundaries
        assert "round_target_epoch" in boundaries
        assert boundaries["round_start_block"] == 1000
        assert boundaries["round_target_block"] == 1720

    def test_final_start_fraction_calculates_settlement_correctly(self, round_manager):
        """Test that settlement_fraction correctly calculates settlement_block."""
        current_block = 1000
        round_manager.sync_boundaries(current_block)

        # settlement_fraction = 0.8, round_block_length = 720
        # settlement_block should be 80% through the round
        expected_settlement = 1000 + int(720 * 0.8)
        assert round_manager.settlement_block == expected_settlement


@pytest.mark.unit
class TestPhaseTransitions:
    """Test phase transition tracking."""

    def test_enter_phase_records_history(self, round_manager):
        """Test that entering a phase adds it to history."""
        assert len(round_manager.phase_history) == 0

        round_manager.enter_phase(RoundPhase.START, block=1000)
        assert len(round_manager.phase_history) == 1
        assert round_manager.current_phase == RoundPhase.START

    def test_enter_phase_with_note(self, round_manager):
        """Test that phase transitions can include notes."""
        round_manager.enter_phase(RoundPhase.HANDSHAKE, block=1010, note="Starting handshake")

        transition = round_manager.phase_history[-1]
        assert transition.note == "Starting handshake"
        assert transition.phase == RoundPhase.HANDSHAKE

    def test_current_phase_state_returns_latest(self, round_manager):
        """Test that current_phase_state returns the most recent transition."""
        round_manager.enter_phase(RoundPhase.START, block=1000)
        round_manager.enter_phase(RoundPhase.EVALUATION, block=1100)

        current = round_manager.current_phase_state()
        assert current.phase == RoundPhase.EVALUATION
        assert current.started_at_block == 1100

    def test_phase_transitions_maintain_chronological_order(self, round_manager):
        """Test that phase history maintains order of transitions."""
        phases = [RoundPhase.START, RoundPhase.HANDSHAKE, RoundPhase.EVALUATION, RoundPhase.COMPLETE]

        for i, phase in enumerate(phases):
            round_manager.enter_phase(phase, block=1000 + i * 100)

        assert len(round_manager.phase_history) == len(phases)
        for i, transition in enumerate(round_manager.phase_history):
            assert transition.phase == phases[i]

    def test_enter_phase_idempotent_without_force(self, round_manager):
        """Test that entering the same phase twice doesn't duplicate without force."""
        round_manager.enter_phase(RoundPhase.EVALUATION, block=1000)
        round_manager.enter_phase(RoundPhase.EVALUATION, block=1100)

        # Should still be only one entry
        assert len(round_manager.phase_history) == 1
        assert round_manager.phase_history[0].started_at_block == 1000

    def test_enter_phase_with_force_creates_new_entry(self, round_manager):
        """Test that force=True creates a new phase entry even for same phase."""
        round_manager.enter_phase(RoundPhase.EVALUATION, block=1000)
        round_manager.enter_phase(RoundPhase.EVALUATION, block=1100, force=True)

        assert len(round_manager.phase_history) == 2


@pytest.mark.unit
class TestRoundTiming:
    """Test round timing calculations."""

    def test_fraction_elapsed_returns_correct_value(self, round_manager):
        """Test that fraction_elapsed calculates progress through round."""
        round_manager.sync_boundaries(1000)

        # At start of round
        assert round_manager.fraction_elapsed(1000) == 0.0

        # Halfway through round (360 blocks = 1 epoch)
        assert round_manager.fraction_elapsed(1360) == 0.5

        # At end of round
        assert abs(round_manager.fraction_elapsed(1720) - 1.0) < 0.01

    def test_get_wait_info_calculates_time_correctly(self, round_manager):
        """Test that get_wait_info returns correct block and time estimates."""
        round_manager.sync_boundaries(1000)
        wait_info = round_manager.get_wait_info(1000)

        # At start, should have full time to settlement and target
        assert wait_info["blocks_to_settlement"] == 576  # 720 * 0.8
        assert wait_info["blocks_to_target"] == 720
        # Minutes = blocks * 12 seconds / 60
        assert abs(wait_info["minutes_to_settlement"] - 115.2) < 0.1
        assert abs(wait_info["minutes_to_target"] - 144.0) < 0.1

    def test_get_wait_info_past_target(self, round_manager):
        """Test wait info when past target block."""
        round_manager.sync_boundaries(1000)
        wait_info = round_manager.get_wait_info(2000)  # Past target

        # Should return 0 for blocks/time remaining
        assert wait_info["blocks_to_target"] == 0
        assert wait_info["minutes_to_target"] == 0.0

    def test_blocks_until_allowed_before_minimum(self, round_manager):
        """Test blocks_until_allowed when before minimum_start_block."""
        current_block = 500
        blocks_remaining = round_manager.blocks_until_allowed(current_block)

        assert blocks_remaining == 500  # 1000 - 500

    def test_blocks_until_allowed_after_minimum(self, round_manager):
        """Test blocks_until_allowed when past minimum_start_block."""
        current_block = 1500
        blocks_remaining = round_manager.blocks_until_allowed(current_block)

        assert blocks_remaining == 0


@pytest.mark.unit
class TestMinimumStartBlock:
    """Test minimum start block enforcement."""

    def test_can_start_round_enforces_minimum_block(self, round_manager):
        """Test that can_start_round returns False before minimum block."""
        assert not round_manager.can_start_round(500)
        assert not round_manager.can_start_round(999)

    def test_can_start_round_allows_after_minimum(self, round_manager):
        """Test that can_start_round returns True at or after minimum block."""
        assert round_manager.can_start_round(1000)
        assert round_manager.can_start_round(1500)

    def test_start_new_round_initializes_state(self, round_manager):
        """Test that start_new_round properly initializes round state."""
        round_manager.start_new_round(1000)

        assert round_manager.round_number == 1
        assert round_manager.current_phase == RoundPhase.PREPARING
        assert len(round_manager.phase_history) == 1


@pytest.mark.unit
class TestRoundReset:
    """Test round reset functionality."""

    def test_reset_round_clears_phase_tracking(self, round_manager):
        """Test that reset_round clears phase history."""
        round_manager.enter_phase(RoundPhase.EVALUATION, block=1000)
        round_manager.enter_phase(RoundPhase.COMPLETE, block=1500)

        round_manager.reset_round()

        assert round_manager.current_phase == RoundPhase.IDLE
        assert len(round_manager.phase_history) == 0


@pytest.mark.unit
class TestBlockEpochConversion:
    """Test block/epoch conversion utilities."""

    def test_block_to_epoch_conversion(self):
        """Test converting blocks to epochs."""
        assert RoundManager.block_to_epoch(0) == 0.0
        assert RoundManager.block_to_epoch(360) == 1.0
        assert RoundManager.block_to_epoch(720) == 2.0
        assert RoundManager.block_to_epoch(180) == 0.5

    def test_epoch_to_block_conversion(self):
        """Test converting epochs to blocks."""
        assert RoundManager.epoch_to_block(0.0) == 0
        assert RoundManager.epoch_to_block(1.0) == 360
        assert RoundManager.epoch_to_block(2.0) == 720
        assert RoundManager.epoch_to_block(0.5) == 180


@pytest.mark.unit
class TestRoundStatus:
    """Test round status reporting."""

    def test_get_status_returns_complete_info(self, round_manager):
        """Test that get_status returns all relevant status information."""
        round_manager.sync_boundaries(1200)
        round_manager.enter_phase(RoundPhase.EVALUATION, block=1200, note="Evaluating agents")

        status = round_manager.get_status(current_block=1200)

        assert status.phase == RoundPhase.EVALUATION
        assert status.round_start_block == 1000
        assert status.target_block == 1720
        assert status.current_block == 1200
        assert status.blocks_remaining == 520
        assert status.note == "Evaluating agents"
        assert status.minutes_remaining is not None
