from __future__ import annotations

from autoppia_web_agents_subnet.validator.config import (
    MAXIMUM_EXECUTION_TIME,
    REWARD_TASK_DOLLAR_COST_NORMALIZATOR,
    TIME_WEIGHT, 
    COST_WEIGHT
)


def calculate_reward_for_task(
    *,
    eval_score: float,
    execution_time: float,
    token_cost: float,
) -> float:
    """
    Calculate the reward for a task based on evaluation score, execution time, and token cost.
    The reward is a weighted combination of the normalized evaluation score, time penalty, and cost penalty.
    """
    # Normalize evaluation score to [0, 1]
    normalized_score = max(0.0, min(1.0, eval_score))

    # Time penalty: linearly scaled from 0 at 0 seconds to 1 at MAXIMUM_EXECUTION_TIME seconds
    time_penalty = min(execution_time / MAXIMUM_EXECUTION_TIME, 1.0)

    # Cost penalty: linearly scaled from 0 at 0 USD to 1 at REWARD_TASK_DOLLAR_COST_NORMALIZATOR USD
    cost_penalty = min(token_cost / REWARD_TASK_DOLLAR_COST_NORMALIZATOR, 1.0)

    # Calculate final reward as a weighted combination
    reward = (
        normalized_score
        - TIME_WEIGHT * time_penalty
        - COST_WEIGHT * cost_penalty
    )

    return max(reward, 0.0)  # Ensure reward is not negative
