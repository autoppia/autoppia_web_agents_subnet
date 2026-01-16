from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def wta_rewards(avg_rewards: NDArray[np.float32]) -> NDArray[np.float32]:
    """Winner-takes-all transform used for final weight selection."""
    if avg_rewards.size == 0:
        return avg_rewards

    arr = np.asarray(avg_rewards, dtype=np.float32)
    
    # If all scores are zero or negative, no winner
    if np.all(arr <= 0):
        return np.zeros_like(arr, dtype=np.float32)
    
    mask_nan = ~np.isfinite(arr)
    if np.any(mask_nan):
        temp = arr.copy()
        temp[mask_nan] = -np.inf
        winner = int(np.argmax(temp))
    else:
        winner = int(np.argmax(arr))

    out = np.zeros_like(arr, dtype=np.float32)
    out[winner] = 1.0
    return out
