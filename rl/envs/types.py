from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class ElementMetadata:
    """Normalized subset of DOM metadata used by the RL environment.

    The browser driver is responsible for extracting these fields from the
    underlying Playwright page or any other executor implementation.  We keep
    the structure lightweight on purpose so it can be serialized, logged or
    used inside vectorized environments without Playwright handles leaking.
    """

    element_id: str
    role: Optional[str]
    tag: Optional[str]
    text: str
    aria_label: Optional[str] = None
    placeholder: Optional[str] = None
    input_type: Optional[str] = None
    clickable: bool = False
    focusable: bool = False
    editable: bool = False
    is_visible: bool = True
    is_enabled: bool = True
    is_in_viewport: bool = True
    bounding_box: Optional[Tuple[float, float, float, float]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def label_candidates(self) -> Iterable[str]:
        """Return text features that can be matched against the goal."""

        if self.text:
            yield self.text
        if self.aria_label:
            yield self.aria_label
        if self.placeholder:
            yield self.placeholder
        for key in ("title", "name", "value"):
            value = self.extra.get(key)
            if isinstance(value, str) and value:
                yield value


@dataclass
class RankedElement:
    element: ElementMetadata
    score: float
    meta_features: Tuple[float, ...]


@dataclass
class RankResult:
    elements: List[RankedElement]
    click_mask: List[bool]
    focus_mask: List[bool]

    def padded_elements(self, k: int) -> List[RankedElement]:
        """Return the ranked elements padded to length *k* with dummy entries."""

        padding_needed = max(0, k - len(self.elements))
        if padding_needed == 0:
            return self.elements

        meta_len = len(self.elements[0].meta_features) if self.elements else 0
        dummy = RankedElement(
            element=ElementMetadata(
                element_id="__pad__",
                role=None,
                tag=None,
                text="",
                clickable=False,
                focusable=False,
                editable=False,
                is_visible=False,
                is_enabled=False,
                is_in_viewport=False,
            ),
            score=0.0,
            meta_features=tuple(0.0 for _ in range(meta_len)),
        )
        return self.elements + [dummy] * padding_needed


@dataclass
class TaskSpec:
    task_id: str
    demo_web_id: str
    goal: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BrowserInputsState:
    values: Dict[str, str] = field(default_factory=dict)

    def diff(self, other: "BrowserInputsState") -> Dict[str, Tuple[str, str]]:
        """Return the set of keys that changed between two snapshots."""

        delta: Dict[str, Tuple[str, str]] = {}
        keys = set(self.values.keys()) | set(other.values.keys())
        for key in keys:
            current_val = self.values.get(key)
            previous_val = other.values.get(key)
            if current_val != previous_val:
                delta[key] = (previous_val or "", current_val or "")
        return delta


@dataclass
class BrowserSnapshot:
    url: str
    dom_text: str
    elements: List[ElementMetadata]
    inputs_state: BrowserInputsState = field(default_factory=BrowserInputsState)
    cart_items: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def element_by_id(self, element_id: str) -> Optional[ElementMetadata]:
        for element in self.elements:
            if element.element_id == element_id:
                return element
        return None


@dataclass
class RewardSignal:
    reward: float
    success: bool
    invalid_episode: bool
    milestones: List[str] = field(default_factory=list)
    invalid_action: bool = False


@dataclass
class ActionResult:
    invalid: bool
    description: str = ""
    signature: str = ""


__all__ = [
    "ActionResult",
    "BrowserInputsState",
    "BrowserSnapshot",
    "ElementMetadata",
    "RankResult",
    "RankedElement",
    "RewardSignal",
    "TaskSpec",
]
