from __future__ import annotations

"""Adapters that connect the RL browser facade with the IWA executor stack."""

import inspect
import logging
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence

from ..envs.types import (
    BrowserInputsState,
    BrowserSnapshot,
    ElementMetadata,
)
from .browser import BrowserAdapter

logger = logging.getLogger(__name__)


class ConcurrentExecutorAdapter(BrowserAdapter):
    """Wrap the concurrent Playwright executor shipped with IWA.

    The adapter resolves the executor lazily via :class:`autoppia_iwa.src.bootstrap.AppBootstrap`
    so that the environment can run inside miners, validators or standalone
    scripts without manually wiring dependencies.  Because the upstream API is
    subject to change, the adapter performs defensive attribute lookups and
    accepts pre-instantiated executors via ``executor=``.
    """

    def __init__(
        self,
        *,
        executor: Optional[Any] = None,
        bootstrap_kwargs: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._bootstrap_kwargs = dict(bootstrap_kwargs or {})
        self._executor = executor or self._resolve_executor()
        if self._executor is None:
            raise RuntimeError(
                "ConcurrentExecutorAdapter could not locate a Playwright executor. "
                "Ensure autoppia_iwa is installed and AppBootstrap provides one."
            )
        self._snapshot: Optional[BrowserSnapshot] = None

    # ------------------------------------------------------------------
    # BrowserAdapter protocol
    # ------------------------------------------------------------------
    def reset(self, demo_web_id: str) -> BrowserSnapshot:
        self._call_executor(["reset_to_demo", "reset"], demo_web_id)
        return self.snapshot()

    def snapshot(self) -> BrowserSnapshot:
        state = self._call_executor(
            ["snapshot", "get_snapshot", "current_state", "state", "get_state"]
        )
        self._snapshot = self._coerce_snapshot(state)
        return self._snapshot

    def click(self, element_id: str) -> BrowserSnapshot:
        self._call_executor(["click", "click_element", "perform_click"], element_id)
        return self.snapshot()

    def focus(self, element_id: str) -> BrowserSnapshot:
        self._call_executor(["focus", "focus_element", "perform_focus"], element_id)
        return self.snapshot()

    def type_and_confirm(self, text: str) -> BrowserSnapshot:
        self._call_executor(
            ["type_and_confirm", "type_and_submit", "type", "enter_text"], text
        )
        return self.snapshot()

    def submit(self) -> BrowserSnapshot:
        self._call_executor(["submit", "press_submit", "trigger_submit"])
        return self.snapshot()

    def scroll(self, direction: str) -> BrowserSnapshot:
        self._call_executor(["scroll", "perform_scroll", "scroll_page"], direction)
        return self.snapshot()

    def back(self) -> BrowserSnapshot:
        self._call_executor(["back", "go_back", "navigate_back"])
        return self.snapshot()

    # ------------------------------------------------------------------
    # Executor helpers
    # ------------------------------------------------------------------
    def _resolve_executor(self) -> Optional[Any]:
        try:
            from autoppia_iwa.src.bootstrap import AppBootstrap  # type: ignore
        except Exception as exc:  # pragma: no cover - requires optional dependency
            logger.warning("Failed to import AppBootstrap: %s", exc)
            return None

        bootstrap = AppBootstrap(**self._bootstrap_kwargs)
        candidates: Sequence[str] = (
            "concurrent_executor",
            "executor",
            "web_executor",
            "browser_executor",
        )

        for attr in candidates:
            executor = getattr(bootstrap, attr, None)
            if executor is not None:
                return executor

        container = getattr(bootstrap, "di_container", None)
        if container is not None:
            for key in (
                "concurrent_executor",
                "browser_executor",
                "web_executor",
            ):
                try:
                    executor = container.resolve(key)  # type: ignore[attr-defined]
                    if executor is not None:
                        return executor
                except Exception:  # pragma: no cover - optional dependency
                    continue
        return None

    def _call_executor(self, method_candidates: Iterable[str], *args: Any) -> Any:
        for name in method_candidates:
            method = getattr(self._executor, name, None)
            if callable(method):
                return method(*args)
        raise AttributeError(
            f"Executor {type(self._executor)!r} does not expose any of {list(method_candidates)}"
        )

    # ------------------------------------------------------------------
    # Coercion helpers
    # ------------------------------------------------------------------
    def _coerce_snapshot(self, state: Any) -> BrowserSnapshot:
        if isinstance(state, BrowserSnapshot):
            return state

        if state is None and self._snapshot is not None:
            return self._snapshot

        if state is None:
            raise RuntimeError("Executor returned None snapshot; cannot proceed")

        url = self._first_attr(state, ["url", "current_url", "page_url"], default="")
        dom_text = self._first_attr(
            state,
            [
                "dom_text",
                "text",
                "visible_text",
                "page_text",
            ],
            default="",
        )
        elements = self._coerce_elements(
            self._first_attr(state, ["elements", "visible_elements", "nodes"], default=[])
        )
        inputs_raw = self._first_attr(
            state,
            ["inputs_state", "inputs", "form_values", "input_values"],
            default={},
        )
        cart_items = self._first_attr(state, ["cart_items", "cart_count"], default=0)
        metadata = self._coerce_mapping(
            self._first_attr(state, ["metadata", "meta", "extra"], default={})
        )

        inputs_state = (
            inputs_raw
            if isinstance(inputs_raw, BrowserInputsState)
            else BrowserInputsState(values=self._coerce_mapping(inputs_raw))
        )

        snapshot = BrowserSnapshot(
            url=str(url or ""),
            dom_text=str(dom_text or ""),
            elements=elements,
            inputs_state=inputs_state,
            cart_items=int(cart_items or 0),
            metadata=metadata,
        )
        self._snapshot = snapshot
        return snapshot

    def _coerce_elements(self, raw_elements: Any) -> list[ElementMetadata]:
        elements: list[ElementMetadata] = []
        if raw_elements is None:
            return elements

        if isinstance(raw_elements, Mapping):
            raw_iterable = raw_elements.values()
        elif isinstance(raw_elements, Sequence) and not isinstance(raw_elements, (str, bytes)):
            raw_iterable = raw_elements
        else:
            raw_iterable = [raw_elements]

        for raw in raw_iterable:
            if isinstance(raw, ElementMetadata):
                elements.append(raw)
                continue
            if raw is None:
                continue
            element_id = self._first_attr(
                raw,
                ["element_id", "id", "node_id", "handle"],
                default="",
            )
            role = self._first_attr(raw, ["role", "aria_role", "node_role"], default=None)
            tag = self._first_attr(raw, ["tag", "tag_name", "node_name"], default=None)
            text = self._first_attr(
                raw,
                [
                    "text",
                    "inner_text",
                    "innerText",
                    "label",
                    "value",
                ],
                default="",
            )
            aria_label = self._first_attr(
                raw,
                ["aria_label", "ariaLabel", "label"],
                default=None,
            )
            placeholder = self._first_attr(raw, ["placeholder"], default=None)
            input_type = self._first_attr(
                raw,
                ["input_type", "type"],
                default=None,
            )
            bounding_box = self._first_attr(
                raw,
                ["bounding_box", "bbox", "boundingBox"],
                default=None,
            )

            extra = self._coerce_mapping(self._first_attr(raw, ["extra", "metadata"], default={}))

            def truthy(keys: Sequence[str], default: bool = False) -> bool:
                for key in keys:
                    value = getattr(raw, key, None)
                    if value is None and isinstance(raw, Mapping):
                        value = raw.get(key)
                    if value is not None:
                        return bool(value)
                return default

            elements.append(
                ElementMetadata(
                    element_id=str(element_id or ""),
                    role=str(role) if role is not None else None,
                    tag=str(tag) if tag is not None else None,
                    text=str(text or ""),
                    aria_label=str(aria_label) if aria_label else None,
                    placeholder=str(placeholder) if placeholder else None,
                    input_type=str(input_type) if input_type else None,
                    clickable=truthy(["clickable", "is_clickable", "can_click"], False),
                    focusable=truthy(["focusable", "is_focusable", "can_focus"], False),
                    editable=truthy(["editable", "is_editable", "can_type"], False),
                    is_visible=truthy(["is_visible", "visible"], True),
                    is_enabled=truthy(["is_enabled", "enabled", "can_interact"], True),
                    is_in_viewport=truthy(["is_in_viewport", "in_viewport", "within_viewport"], True),
                    bounding_box=bounding_box,
                    extra=extra,
                )
            )
        return elements

    @staticmethod
    def _coerce_mapping(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, MutableMapping):
            return dict(raw)
        if hasattr(raw, "items"):
            return dict(raw.items())
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            result: Dict[str, Any] = {}
            for item in raw:
                if isinstance(item, Mapping):
                    result.update(item)
            return result
        return {}

    @staticmethod
    def _first_attr(obj: Any, names: Sequence[str], default: Any) -> Any:
        for name in names:
            if hasattr(obj, name):
                value = getattr(obj, name)
                if inspect.ismethod(value):
                    try:
                        return value()
                    except Exception:  # pragma: no cover - best effort
                        continue
                return value
            if isinstance(obj, Mapping) and name in obj:
                return obj[name]
        return default


__all__ = ["ConcurrentExecutorAdapter"]

