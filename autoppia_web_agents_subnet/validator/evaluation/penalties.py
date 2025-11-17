from __future__ import annotations

from typing import List, Any, Sequence
import numpy as np
import bittensor as bt

from autoppia_web_agents_subnet.validator.config import (
    SAME_SOLUTION_PENALTY,
    SAME_SOLUTION_SIM_THRESHOLD,
)

try:
    from autoppia_web_agents_subnet.validator.topk import get_similarity_score
except Exception:
    get_similarity_score = None


def detect_same_solution_groups(solutions: List[Any]) -> List[List[int]]:
    """
    Return groups (list of index lists) where each group contains 2+
    indices of solutions that are identical or highly similar.
    """
    if len(solutions) < 2:
        return []
    try:
        safe_solutions = [s if s is not None else type("_Empty", (), {"actions": []})() for s in solutions]
        has_actions = [bool(getattr(s, "actions", []) or []) for s in safe_solutions]

        groups: List[List[int]] = []
        if get_similarity_score is not None:
            n = len(safe_solutions)
            adj = {i: set() for i in range(n)}
            thr = float(SAME_SOLUTION_SIM_THRESHOLD)
            for i in range(n):
                if not has_actions[i]:
                    continue
                for j in range(i + 1, n):
                    if not has_actions[j]:
                        continue
                    try:
                        sim = float(get_similarity_score(safe_solutions[i], safe_solutions[j]))
                    except Exception:
                        sim = 0.0
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
        else:
            # Fallback exact-hash grouping
            import hashlib
            buckets: dict[str, list[int]] = {}
            for idx, sol in enumerate(safe_solutions):
                if not has_actions[idx]:
                    continue
                try:
                    parts_list = []
                    for a in getattr(sol, "actions", []) or []:
                        parts = [str(getattr(a, "type", ""))]
                        url = getattr(a, "url", None)
                        if url:
                            parts.append(str(url))
                        text = getattr(a, "text", None)
                        if text:
                            parts.append(str(text))
                        sel = getattr(a, "selector", None)
                        if sel is not None:
                            sel_s = f"{getattr(sel, 'type', '')}:{getattr(sel, 'value', '')}:{getattr(sel, 'attribute', '')}"
                            parts.append(sel_s)
                        parts_list.append("|".join(parts))
                    key = hashlib.md5("||".join(parts_list).encode()).hexdigest()[:12]
                except Exception:
                    key = f"idx_{idx}"
                buckets.setdefault(key, []).append(idx)
            for _, idxs in buckets.items():
                if len(idxs) >= 2:
                    groups.append(sorted(idxs))
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
    penalized, _groups = apply_same_solution_penalty_with_meta(solutions, eval_scores)
    return penalized
