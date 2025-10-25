from __future__ import annotations

import math
import re
from typing import Iterable, List, Sequence

from .types import ElementMetadata, RankResult, RankedElement, TaskSpec

_ROLE_PRIORITY = {
    "button": 1.0,
    "link": 0.9,
    "submit": 0.95,
    "textbox": 0.8,
    "combobox": 0.75,
    "listbox": 0.7,
    "menuitem": 0.65,
}

_ROLE_TO_ID = {role: idx + 1 for idx, role in enumerate(sorted(_ROLE_PRIORITY))}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _tokenize(text: str) -> List[str]:
    normalized = _normalize(text)
    return [token for token in re.split(r"[^\w]+", normalized) if token]


def _similarity(candidate_tokens: Sequence[str], goal_tokens: Sequence[str]) -> float:
    if not candidate_tokens or not goal_tokens:
        return 0.0
    goal_set = set(goal_tokens)
    overlap = sum(1 for token in candidate_tokens if token in goal_set)
    return overlap / math.sqrt(len(goal_tokens) * len(candidate_tokens))


def _element_score(element: ElementMetadata, goal_tokens: Sequence[str]) -> float:
    score = 0.0
    if not element.is_visible or not element.is_enabled:
        return score

    if element.clickable:
        score += 1.0
    if element.focusable:
        score += 0.3
    if element.editable:
        score += 0.2

    role_bonus = _ROLE_PRIORITY.get((element.role or "").lower())
    if role_bonus:
        score += role_bonus

    label_tokens: List[str] = []
    for label in element.label_candidates():
        label_tokens.extend(_tokenize(label))
    score += 1.25 * _similarity(label_tokens, goal_tokens)

    if element.is_in_viewport:
        score += 0.1
    if element.tag in {"input", "textarea"}:
        score += 0.2

    return score


def rank_clickables(
    elements: Iterable[ElementMetadata],
    task: TaskSpec,
    top_k: int,
) -> RankResult:
    """Rank actionable elements and return Top-K along with masks.

    Parameters
    ----------
    elements:
        Iterable of :class:`ElementMetadata` describing the DOM snapshot.
    task:
        The current :class:`TaskSpec`.  Only the goal text is used for now but the
        signature allows richer heuristics later on.
    top_k:
        Number of elements to keep.
    """

    goal_tokens = _tokenize(task.goal)
    ranked: List[RankedElement] = []

    for element in elements:
        score = _element_score(element, goal_tokens)
        if score <= 0:
            continue
        meta_features = (
            float(_ROLE_TO_ID.get((element.role or "").lower(), 0)) / max(len(_ROLE_TO_ID), 1),
            1.0 if element.clickable else 0.0,
            1.0 if element.focusable else 0.0,
            1.0 if element.editable else 0.0,
            1.0 if element.is_in_viewport else 0.0,
            min(len(_tokenize(element.text)), 64) / 64.0,
        )
        ranked.append(
            RankedElement(
                element=element,
                score=score,
                meta_features=meta_features,
            )
        )

    ranked.sort(key=lambda item: item.score, reverse=True)
    ranked = ranked[:top_k]
    click_mask: List[bool] = [
        bool(item.element.clickable and item.element.is_visible and item.element.is_enabled)
        for item in ranked
    ]
    focus_mask: List[bool] = [
        bool(item.element.focusable and item.element.is_visible and item.element.is_enabled)
        for item in ranked
    ]

    return RankResult(elements=ranked, click_mask=click_mask, focus_mask=focus_mask)


__all__ = ["rank_clickables"]
