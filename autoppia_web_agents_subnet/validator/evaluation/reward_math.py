"""
Pure reward formula for task scoring.

No config or bittensor dependency so it can be unit-tested in isolation.
"""

from __future__ import annotations


def calculate_reward_impl(
    *,
    eval_score: float,
    execution_time: float,
    token_cost: float,
    timeout_s: float,
    cost_norm: float,
    eval_weight: float,
    time_weight: float,
    cost_weight: float,
) -> float:
    """
    Pure reward formula: binary success, time/cost penalties, weighted sum.
    - eval_score >= 1.0 -> solved; apply time/cost shaping.
    - eval_score < 1.0 -> unsolved; reward = 0.0.
    """
    solved = float(eval_score) >= 1.0
    timeout_s = max(float(timeout_s), 1e-9)
    cost_norm = max(float(cost_norm), 1e-9)
    time_penalty = min(execution_time / timeout_s, 1.0)
    cost_penalty = min(token_cost / cost_norm, 1.0)
    if not solved:
        return 0.0
    time_component = 1.0 - time_penalty
    cost_component = 1.0 - cost_penalty
    reward = eval_weight * 1.0 + time_weight * time_component + cost_weight * cost_component
    return max(reward, 0.0)
