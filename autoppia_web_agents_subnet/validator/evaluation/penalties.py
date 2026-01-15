from __future__ import annotations

from typing import List, Any, Sequence, Dict
import math
from collections import Counter

import numpy as np
import bittensor as bt

from autoppia_web_agents_subnet.validator.config import (
    SAME_SOLUTION_PENALTY,
    SAME_SOLUTION_SIM_THRESHOLD,
)

def detect_same_solution_groups(solutions: List[Any]) -> List[List[int]]:
    """
    Return groups (list of index lists) where each group contains 2+
    indices of solutions that are identical or highly similar.
    """
    if len(solutions) < 2:
        return []
    try:
        # Normalize solutions and build simple bag-of-words representations
        safe_solutions = [
            s if s is not None else type("_Empty", (), {"actions": []})() for s in solutions
        ]
        bows: List[Counter[str]] = []
        norms: List[float] = []

        for sol in safe_solutions:
            tokens: List[str] = []
            for a in getattr(sol, "actions", []) or []:
                try:
                    a_type = str(getattr(a, "type", "") or "").lower()
                    url = str(getattr(a, "url", "") or "").lower()
                    text = str(
                        getattr(a, "text", None)
                        or getattr(a, "value", None)
                        or ""
                    ).lower()
                    # Keep only coarse information to avoid overfitting to noise
                    token = f"{a_type}|{url}|{text[:64]}"
                    tokens.append(token)
                except Exception:
                    continue
            bow = Counter(tokens)
            bows.append(bow)
            norm = math.sqrt(sum(float(v) * float(v) for v in bow.values())) or 1.0
            norms.append(norm)

        groups: List[List[int]] = []
        n = len(bows)
        thr = float(SAME_SOLUTION_SIM_THRESHOLD)
        # Build adjacency based on cosine similarity over the simple BOW vectors.
        adj: Dict[int, set[int]] = {i: set() for i in range(n)}
        for i in range(n):
            if not bows[i]:
                continue
            for j in range(i + 1, n):
                if not bows[j]:
                    continue
                # Cosine similarity
                common = bows[i].keys() & bows[j].keys()
                dot = sum(float(bows[i][k]) * float(bows[j][k]) for k in common)
                sim = dot / (norms[i] * norms[j]) if norms[i] and norms[j] else 0.0
                if sim >= thr:
                    adj[i].add(j)
                    adj[j].add(i)

        visited = set()
        for i in range(n):
            if i in visited or not adj[i]:
                continue
            stack = [i]
            comp = set()
            while stack:
                k = stack.pop()
                if k in visited:
                    continue
                visited.add(k)
                comp.add(k)
                for nb in adj[k]:
                    if nb not in visited:
                        stack.append(nb)
            if len(comp) >= 2:
                groups.append(sorted(comp))

        return groups
    except Exception as e:
        bt.logging.warning(f"[EVAL] Duplicate-solution detection failed: {e}")
        return []


def apply_same_solution_penalty_with_meta(
    solutions: List[Any],
    scores_arr: np.ndarray,
) -> tuple[np.ndarray, List[List[int]]]:
    """
    Like apply_same_solution_penalty but also returns the penalized groups
    (index lists) for visibility/logging.
    """
    scores_arr = np.asarray(scores_arr, dtype=float)
    if SAME_SOLUTION_PENALTY >= 1.0 or len(solutions) < 2:
        return scores_arr, []

    groups = detect_same_solution_groups(solutions)
    if groups:
        idxs = sorted({i for g in groups for i in g})
        scores_arr[idxs] *= float(SAME_SOLUTION_PENALTY)
        bt.logging.warning(
            f"[EVAL] SAME-SOLUTION penalty applied to {len(idxs)} miners. "
            f"Threshold={SAME_SOLUTION_SIM_THRESHOLD}, Penalty={SAME_SOLUTION_PENALTY}"
        )
    return scores_arr, groups


def apply_same_solution_penalty(
    solutions: List[Any],
    eval_scores: Sequence[float],
) -> np.ndarray:
    penalized, _groups = apply_same_solution_penalty_with_meta(solutions, np.asarray(eval_scores, dtype=float))
    return penalized
