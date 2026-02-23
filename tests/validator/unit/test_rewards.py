"""
Unit tests for validator reward calculation.

Tests the pure reward formula (reward_math.calculate_reward_impl) so they run
without loading config or bittensor. The public API calculate_reward_for_task
in rewards.py delegates to this implementation with config values.
"""

import pytest

from autoppia_web_agents_subnet.validator.evaluation.reward_math import calculate_reward_impl

# Test constants matching typical config (no config import needed)
TIMEOUT = 180.0
COST_NORM = 0.05
EVAL_W = 0.7
TIME_W = 0.1
COST_W = 0.2


def _r(eval_score, execution_time, token_cost):
    return calculate_reward_impl(
        eval_score=eval_score,
        execution_time=execution_time,
        token_cost=token_cost,
        timeout_s=TIMEOUT,
        cost_norm=COST_NORM,
        eval_weight=EVAL_W,
        time_weight=TIME_W,
        cost_weight=COST_W,
    )


@pytest.mark.unit
class TestCalculateRewardForTask:
    """Test reward calculation with binary task success."""

    def test_unsolved_task_returns_zero_reward(self):
        """eval_score < 1.0 must yield 0.0 reward regardless of time/cost."""
        assert _r(0.0, 0.0, 0.0) == 0.0
        assert _r(0.99, 0.0, 0.0) == 0.0
        assert _r(0.5, 10.0, 0.01) == 0.0

    def test_solved_task_zero_time_zero_cost_gives_max_reward(self):
        """eval_score >= 1.0 with zero time and cost gives max weighted sum."""
        assert _r(1.0, 0.0, 0.0) == pytest.approx(1.0)

    def test_solved_task_at_timeout_and_cost_cap_reduces_reward(self):
        """Full time and cost penalties reduce reward below 1.0."""
        assert _r(1.0, 180.0, 0.05) == pytest.approx(0.7)

    def test_time_penalty_capped_at_one(self):
        """Execution time beyond timeout does not increase penalty beyond 1."""
        r180 = _r(1.0, 180.0, 0.0)
        r360 = _r(1.0, 360.0, 0.0)
        assert r180 == pytest.approx(r360)
        assert r180 == pytest.approx(0.9)

    def test_cost_penalty_capped_at_one(self):
        """Token cost beyond normalizer does not increase penalty beyond 1."""
        r05 = _r(1.0, 0.0, 0.05)
        r10 = _r(1.0, 0.0, 0.10)
        assert r05 == pytest.approx(r10)
        assert r05 == pytest.approx(0.8)

    def test_eval_score_exactly_one_is_solved(self):
        """eval_score == 1.0 is treated as solved."""
        assert _r(1.0, 0.0, 0.0) > 0.0

    def test_reward_never_negative(self):
        """Return value is always >= 0."""
        assert _r(1.0, 180.0, 0.05) >= 0.0
        assert _r(0.0, 0.0, 0.0) >= 0.0
