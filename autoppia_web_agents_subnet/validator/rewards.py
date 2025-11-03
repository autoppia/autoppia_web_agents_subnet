from __future__ import annotations

"""Backward-compatible reward helpers."""

import numpy as np
from numpy.typing import NDArray

from autoppia_web_agents_subnet.validator.evaluation.rewards import (
    calculate_rewards_for_task,
    pad_or_trim,
    times_to_scores,
)
from autoppia_web_agents_subnet.validator.settlement.rewards import wta_rewards


def reduce_rewards_to_averages(rewards_sum: np.ndarray, counts: np.ndarray) -> NDArray[np.float32]:
    """Safe element-wise average helper maintained for older call-sites."""
    counts_safe = np.maximum(counts, 1).astype(np.float32)
    avg = (rewards_sum.astype(np.float32) / counts_safe).astype(np.float32)
    return avg


__all__ = [
    "pad_or_trim",
    "times_to_scores",
    "calculate_rewards_for_task",
    "reduce_rewards_to_averages",
    "wta_rewards",
]
