import pytest

from autoppia_web_agents_subnet.validator.round_manager import RoundManager, RoundPhase


@pytest.fixture
def round_manager():
    return RoundManager(
        round_size_epochs=0.2,
        avg_task_duration_seconds=30,
        safety_buffer_epochs=0.02,
        minimum_start_block=100,
    )


def test_start_new_round_sets_phase(round_manager):
    round_manager.start_new_round(200)
    expected_start = round_manager.get_round_boundaries(200, log_debug=False)["round_start_block"]
    assert round_manager.start_block == expected_start
    assert round_manager.current_phase == RoundPhase.PREPARING


def test_accumulate_and_average(round_manager):
    round_manager.start_new_round(200)
    round_manager.accumulate_rewards([0, 1], [1.0, 2.0], [0.5, 0.7], [10, 20])
    round_manager.accumulate_rewards([0, 1], [2.0, 4.0], [0.6, 0.8], [15, 25])

    averages = round_manager.get_average_rewards()
    assert averages[0] == pytest.approx(1.5)
    assert averages[1] == pytest.approx(3.0)

    assert round_manager.round_task_attempts[0] == 2
    assert round_manager.round_task_attempts[1] == 2


def test_duplicate_penalty_tracking(round_manager):
    round_manager.record_duplicate_penalties([10, 11, 12], [[0, 1]])
    round_manager.record_duplicate_penalties([10, 11, 12], [[1, 2]])
    assert round_manager.round_duplicate_counts[10] == 1
    assert round_manager.round_duplicate_counts[11] == 2
    assert round_manager.round_duplicate_counts[12] == 1


def test_fraction_elapsed(round_manager):
    round_manager.start_new_round(200)
    boundaries = round_manager.get_round_boundaries(200, log_debug=False)
    frac = round_manager.fraction_elapsed(200)
    expected = (200 - boundaries["round_start_block"]) / (boundaries["target_block"] - boundaries["round_start_block"])
    assert frac == pytest.approx(expected)
    frac_next = round_manager.fraction_elapsed(220)
    assert 0.0 <= frac_next <= 1.0


def test_phase_history_logging(round_manager):
    round_manager.start_new_round(200)
    round_manager.enter_phase(RoundPhase.PREPARING, block=200, note="prep")
    round_manager.enter_phase(RoundPhase.HANDSHAKE, block=205)
    round_manager.enter_phase(RoundPhase.TASK_EXECUTION, block=210, note="tasks")
    status = round_manager.get_status(current_block=215)
    assert status.phase == RoundPhase.TASK_EXECUTION
    assert status.blocks_remaining is not None
    assert len(round_manager.phase_history) == 3
