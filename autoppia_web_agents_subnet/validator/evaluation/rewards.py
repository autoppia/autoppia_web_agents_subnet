from __future__ import annotations

from autoppia_web_agents_subnet.validator.config import (
    TASK_TIMEOUT_SECONDS,
    REWARD_TASK_DOLLAR_COST_NORMALIZATOR,
    EVAL_SCORE_WEIGHT,
    TIME_WEIGHT,
    COST_WEIGHT,
)


def calculate_reward_for_task(
    *,
    eval_score: float,
    execution_time: float,
    token_cost: float,
) -> float:
    """
    Calculate reward with binary task success:
    - eval_score >= 1.0 -> solved; apply time/cost shaping.
    - eval_score < 1.0 -> unsolved; reward = 0.0.
    """
    # Binary success semantics for current evaluator contract.
    solved = float(eval_score) >= 1.0

    # Time penalty: linearly scaled from 0 at 0 seconds to 1 at TASK_TIMEOUT_SECONDS.
    time_penalty = min(execution_time / TASK_TIMEOUT_SECONDS, 1.0)

    # Cost penalty: linearly scaled from 0 at 0 USD to 1 at REWARD_TASK_DOLLAR_COST_NORMALIZATOR USD
    cost_penalty = min(token_cost / REWARD_TASK_DOLLAR_COST_NORMALIZATOR, 1.0)

    # If unsolved, force zero reward.
    if not solved:
        return 0.0

    # Apply weighted shaping only for fully solved tasks.
    time_component = 1.0 - time_penalty
    cost_component = 1.0 - cost_penalty
    reward = EVAL_SCORE_WEIGHT * 1.0 + TIME_WEIGHT * time_component + COST_WEIGHT * cost_component

    return max(reward, 0.0)  # Ensure reward is not negative
