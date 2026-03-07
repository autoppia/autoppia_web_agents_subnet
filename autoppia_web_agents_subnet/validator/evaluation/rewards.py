from __future__ import annotations

from autoppia_web_agents_subnet.validator.config import (
    TASK_TIMEOUT_SECONDS,
    REWARD_TASK_DOLLAR_COST_NORMALIZATOR,
    EVAL_SCORE_WEIGHT,
    TIME_WEIGHT,
    COST_WEIGHT,
)
from autoppia_web_agents_subnet.validator.evaluation.reward_math import calculate_reward_impl


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
    return calculate_reward_impl(
        eval_score=eval_score,
        execution_time=execution_time,
        token_cost=token_cost,
        timeout_s=float(TASK_TIMEOUT_SECONDS),
        cost_norm=float(REWARD_TASK_DOLLAR_COST_NORMALIZATOR),
        eval_weight=float(EVAL_SCORE_WEIGHT),
        time_weight=float(TIME_WEIGHT),
        cost_weight=float(COST_WEIGHT),
    )
