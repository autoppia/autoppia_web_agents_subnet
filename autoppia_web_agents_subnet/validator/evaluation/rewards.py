from __future__ import annotations

from typing import List

import numpy as np
from numpy.typing import NDArray


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


def calculate_rewards_for_task(
    *,
    eval_scores: NDArray[np.float32],
    execution_times: List[float],
    n_miners: int,
    eval_score_weight: float,
    time_weight: float,
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
