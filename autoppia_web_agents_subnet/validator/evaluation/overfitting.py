from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class OverfitCheck:
    base_task_id: str
    alt_task: Any
    alt_seed: int


def _extract_seed(url: str) -> str | None:
    try:
        query = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
    except Exception:
        return None
    seed = query.get("seed")
    if seed is None:
        return None
    seed_text = str(seed).strip()
    return seed_text or None


def _replace_seed(url: str, *, seed: int) -> str:
    split = urlsplit(url)
    query_items = dict(parse_qsl(split.query, keep_blank_values=True))
    query_items["seed"] = str(int(seed))
    return urlunsplit(split._replace(query=urlencode(query_items, doseq=True)))


def _clone_task_with_seed(task: Any, *, alt_seed: int) -> Any:
    try:
        task_copy = task.model_copy(deep=True)  # type: ignore[attr-defined]
    except Exception:
        task_copy = copy.deepcopy(task)

    base_task_id = str(getattr(task_copy, "id", "task"))
    original_url = str(getattr(task_copy, "url", "") or "")
    setattr(task_copy, "id", f"{base_task_id}__overfit_seed_{alt_seed}")
    setattr(task_copy, "url", _replace_seed(original_url, seed=alt_seed))
    return task_copy


def build_overfit_checks(
    season_tasks: list[Any],
    *,
    round_rng: random.Random,
) -> dict[str, OverfitCheck]:
    eligible_tasks: list[Any] = []
    for task_item in season_tasks:
        task = getattr(task_item, "task", None)
        if task is None:
            continue
        task_id = getattr(task, "id", None)
        task_url = getattr(task, "url", None)
        if not task_id or not isinstance(task_url, str) or not task_url:
            continue
        if _extract_seed(task_url) is None:
            continue
        eligible_tasks.append(task)

    if not eligible_tasks:
        return {}
    checks: dict[str, OverfitCheck] = {}
    for task in eligible_tasks:
        base_task_id = str(getattr(task, "id"))
        original_seed = _extract_seed(str(getattr(task, "url", "") or ""))
        alt_seed = round_rng.randint(1, 2_147_483_647)
        while original_seed is not None and str(alt_seed) == original_seed:
            alt_seed = round_rng.randint(1, 2_147_483_647)
        checks[base_task_id] = OverfitCheck(
            base_task_id=base_task_id,
            alt_task=_clone_task_with_seed(task, alt_seed=alt_seed),
            alt_seed=alt_seed,
        )
    return checks


def apply_overfit_penalty(
    *,
    base_reward: float,
    alt_reward: float,
    diff_threshold: float,
    penalty: float,
) -> tuple[float, float, bool]:
    reward_diff = max(float(base_reward) - float(alt_reward), 0.0)
    should_penalize = reward_diff > float(diff_threshold)
    if not should_penalize:
        return float(base_reward), reward_diff, False
    penalized_reward = max(float(base_reward) - float(penalty), 0.0)
    return penalized_reward, reward_diff, True
