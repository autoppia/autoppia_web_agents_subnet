from __future__ import annotations

import math
from typing import List
import numpy as np
from numpy.typing import NDArray

# Default weights (override at call-site if desired)
EVAL_SCORE_WEIGHT: float = 0.8
TIME_WEIGHT: float = 0.2


def pad_or_trim(vec: NDArray[np.float32], n: int) -> NDArray[np.float32]:
    """Pad with zeros or trim to length n."""
    if vec.shape[0] == n:
        return vec
    out = np.zeros(n, dtype=np.float32)
    lim = min(n, vec.shape[0])
    out[:lim] = vec[:lim]
    return out


def times_to_scores(execution_times: List[float], n_miners: int) -> NDArray[np.float32]:
    """
    Convert execution times to [0,1] via per-task min-max:
        score_i = (t_max - t_i) / max(t_max - t_min, eps)
    Invalid/NaN/negative -> treated as worst time.
    If all missing/equal -> neutral 0.5 for everyone.
    """
    eps = 1e-8
    arr = np.zeros(n_miners, dtype=np.float32)

    if execution_times:
        times = np.asarray(execution_times, dtype=np.float32).ravel()
        lim = min(n_miners, times.shape[0])
        arr[:lim] = times[:lim]

    clean = arr.copy()
    invalid = ~np.isfinite(clean) | (clean < 0.0)
    clean[invalid] = np.nan

    if np.all(np.isnan(clean)):
        return np.full(n_miners, 0.5, dtype=np.float32)

    t_min = np.nanmin(clean)
    t_max = np.nanmax(clean)
    span = max(t_max - t_min, eps)

    clean[np.isnan(clean)] = t_max  # worst case
    scores = (t_max - clean) / span
    np.clip(scores, 0.0, 1.0, out=scores)

    if scores.shape[0] != n_miners:
        scores = pad_or_trim(scores.astype(np.float32), n_miners)
    else:
        scores = scores.astype(np.float32)
    return scores


def calculate_final_scores(
    *,
    eval_scores: NDArray[np.float32],
    execution_times: List[float],
    n_miners: int,
    eval_score_weight: float = EVAL_SCORE_WEIGHT,
    time_weight: float = TIME_WEIGHT,
) -> NDArray[np.float32]:
    """
    Calculate final scores by combining eval scores and execution time scores.

    Formula: final_score = eval_weight × eval_scores + time_weight × time_scores

    The time scores are calculated inversely: faster miners get higher scores.
    """
    # Caller may choose non-unit sum; we don't enforce exact 1.0.
    eval_scores = pad_or_trim(eval_scores, n_miners)
    time_scores = times_to_scores(execution_times, n_miners)
    final = (eval_score_weight * eval_scores) + (time_weight * time_scores)
    return final.astype(np.float32)


def reduce_rewards_to_averages(rewards_sum: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """
    Safe element-wise division: average = sum / max(count, 1).
    Returns float32 vector with same length as inputs.
    """
    counts_safe = np.maximum(counts, 1).astype(np.float32)
    avg = (rewards_sum.astype(np.float32) / counts_safe).astype(np.float32)
    return avg


def wta_rewards(avg_rewards: NDArray[np.float32]) -> NDArray[np.float32]:
    """
    Winner-takes-all transform:
      - Returns a 0/1 vector with a single 1 at the index of the maximum value.
      - Deterministic on ties: selects the *first* index with the max value.
      - If input is empty, returns it unchanged.
    NaNs are treated as -inf for the purpose of argmax.
    """
    if avg_rewards.size == 0:
        return avg_rewards

    arr = np.asarray(avg_rewards, dtype=np.float32)
    # Treat NaN as -inf so they never win.
    where_nan = ~np.isfinite(arr)
    if np.any(where_nan):
        tmp = arr.copy()
        tmp[where_nan] = -np.inf
        winner = int(np.argmax(tmp))
    else:
        winner = int(np.argmax(arr))

    out = np.zeros_like(arr, dtype=np.float32)
    out[winner] = 1.0
    return out
