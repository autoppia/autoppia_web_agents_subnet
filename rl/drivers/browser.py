from __future__ import annotations

import logging
from typing import Mapping, Optional, Protocol

from ..envs.types import BrowserSnapshot, ElementMetadata
from ..utils import load_object

logger = logging.getLogger(__name__)


class BrowserAdapter(Protocol):
    """Protocol that concrete IWA executors must implement.

    The adapter isolates the RL environment from the concrete Playwright based
    executor shipped in the `autoppia_iwa` module.  The goal is to make it
    possible to mock the browser in unit tests while keeping the production
    adapter thin.
    """

    def reset(self, demo_web_id: str) -> BrowserSnapshot:
        ...

    def snapshot(self) -> BrowserSnapshot:
        ...

    def click(self, element_id: str) -> BrowserSnapshot:
        ...

    def focus(self, element_id: str) -> BrowserSnapshot:
        ...

    def type_and_confirm(self, text: str) -> BrowserSnapshot:
        ...

    def submit(self) -> BrowserSnapshot:
        ...

    def scroll(self, direction: str) -> BrowserSnapshot:
        ...

    def back(self) -> BrowserSnapshot:
        ...


class Browser:
    """Stateful façade over the low-level executor.

    The instance maintains the latest :class:`BrowserSnapshot` and exposes
    higher level helpers used by the environment to build observations, compute
    rewards and masks.
    """

    def __init__(
        self,
        config: Optional[Mapping[str, object]] = None,
        adapter: Optional[BrowserAdapter] = None,
    ) -> None:
        self._config = dict(config or {})
        if adapter is None:
            adapter_cfg = dict(self._config.get("adapter") or {})
            adapter = self._load_adapter_from_config(adapter_cfg)
        self._adapter = adapter
        self._snapshot = BrowserSnapshot(url="", dom_text="", elements=[])

    # ------------------------------------------------------------------
    # Snapshot helpers
    # ------------------------------------------------------------------
    @property
    def snapshot(self) -> BrowserSnapshot:
        return self._snapshot

    def refresh(self) -> BrowserSnapshot:
        if self._adapter is None:
            raise RuntimeError("Browser adapter not configured")
        self._snapshot = self._adapter.snapshot()
        return self._snapshot

    def reset_to_demo(self, demo_web_id: str) -> BrowserSnapshot:
        if self._adapter is None:
            raise RuntimeError("Browser adapter not configured")
        self._snapshot = self._adapter.reset(demo_web_id)
        return self._snapshot

    def _load_adapter_from_config(self, adapter_cfg: Mapping[str, object]) -> Optional[BrowserAdapter]:
        if not adapter_cfg:
            return None

        entrypoint = adapter_cfg.get("class") or adapter_cfg.get("entrypoint")
        if not entrypoint:
            raise ValueError("Browser adapter configuration must include 'class' or 'entrypoint'")

        try:
            adapter_cls = load_object(str(entrypoint))
        except (ImportError, AttributeError) as exc:
            logger.warning("Failed to import browser adapter '%s': %s", entrypoint, exc)
            return None
        kwargs = dict(adapter_cfg.get("kwargs") or {})
        return adapter_cls(**kwargs)

    # ------------------------------------------------------------------
    # DOM Queries
    # ------------------------------------------------------------------
    def get_visible_elements(self) -> list[ElementMetadata]:
        return list(self._snapshot.elements)

    def get_dom_text(self) -> str:
        return self._snapshot.dom_text

    def get_url(self) -> str:
        return self._snapshot.url

    def get_inputs_state(self) -> Mapping[str, str]:
        return dict(self._snapshot.inputs_state.values)

    # ------------------------------------------------------------------
    # Capability flags used for action masking
    # ------------------------------------------------------------------
    def can_submit(self) -> bool:
        return any(
            el.clickable
            and el.is_visible
            and el.is_enabled
            and (el.role in {"button", "link", "submit"} or el.tag in {"button", "a", "input"})
            for el in self._snapshot.elements
        )

    def has_focusable_inputs(self) -> bool:
        return any(el.focusable and el.is_enabled and el.is_visible for el in self._snapshot.elements)

    def can_scroll(self) -> bool:
        # Assume scrolling is always possible unless explicitly disabled via config
        return bool(self._config.get("allow_scroll", True))

    def can_go_back(self) -> bool:
        metadata_flag = self._snapshot.metadata.get("can_go_back")
        if isinstance(metadata_flag, bool):
            return metadata_flag
        return bool(self._config.get("allow_back", True))

    # ------------------------------------------------------------------
    # Action primitives (delegate to adapter)
    # ------------------------------------------------------------------
    def click(self, element: ElementMetadata) -> BrowserSnapshot:
        if self._adapter is None:
            raise RuntimeError("Browser adapter not configured")
        logger.debug("Browser.click -> %s", element.element_id)
        self._snapshot = self._adapter.click(element.element_id)
        return self._snapshot

    def focus(self, element: ElementMetadata) -> BrowserSnapshot:
        if self._adapter is None:
            raise RuntimeError("Browser adapter not configured")
        logger.debug("Browser.focus -> %s", element.element_id)
        self._snapshot = self._adapter.focus(element.element_id)
        return self._snapshot

    def type_confirm(self, text: str) -> BrowserSnapshot:
        if self._adapter is None:
            raise RuntimeError("Browser adapter not configured")
        logger.debug("Browser.type_confirm -> %s", text)
        self._snapshot = self._adapter.type_and_confirm(text)
        return self._snapshot

    def submit(self) -> BrowserSnapshot:
        if self._adapter is None:
            raise RuntimeError("Browser adapter not configured")
        logger.debug("Browser.submit")
        self._snapshot = self._adapter.submit()
        return self._snapshot

    def scroll(self, direction: str) -> BrowserSnapshot:
        if self._adapter is None:
            raise RuntimeError("Browser adapter not configured")
        if direction not in {"up", "down"}:
            raise ValueError(f"Unsupported scroll direction: {direction}")
        logger.debug("Browser.scroll -> %s", direction)
        self._snapshot = self._adapter.scroll(direction)
        return self._snapshot

    def back(self) -> BrowserSnapshot:
        if self._adapter is None:
            raise RuntimeError("Browser adapter not configured")
        logger.debug("Browser.back")
        self._snapshot = self._adapter.back()
        return self._snapshot


__all__ = ["Browser", "BrowserAdapter"]
