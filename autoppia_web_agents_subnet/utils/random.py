from typing import List, Any
import itertools
import random
import numpy as np


def interleave(*lists: List[Any]):
    """
    Interleaves multiple lists like [a1, a2], [b1, b2] → [a1, b1, a2, b2], skipping None.
    Accepts any number of lists.
    """
    return (
        item
        for group in itertools.zip_longest(*lists)
        for item in group
        if item is not None
    )


def split_tasks_evenly(total_tasks: int, num_projects: int) -> list[int]:
    """
    Evenly distributes `total_tasks` across `num_projects`,
    assigning the remainder one-by-one to the first few.
    """
    base = total_tasks // num_projects
    extra = total_tasks % num_projects
    distribution = [base] * num_projects
    for i in range(1, extra + 1):
        distribution[-i] += 1
    return distribution


def get_random_uids(validator, k: int, exclude: List[int] = None) -> np.ndarray:
    """Returns k random uids from the validator's metagraph.
    Args:
        validator: Object with .metagraph (must have .n for total number of uids).
        k (int): Number of uids to return.
        exclude (List[int]): List of uids to exclude from the random sampling.
    Returns:
        uids (np.ndarray): Randomly sampled uids.
    Notes:
        If `k` is larger than the number of available uids, it will be set to that number.
    """
    total_uids = list(range(validator.metagraph.n.item()))
    candidate_uids = [uid for uid in total_uids if exclude is None or uid not in exclude]

    k = min(k, len(candidate_uids))
    uids = np.array(random.sample(candidate_uids, k))
    return uids
