from __future__ import annotations

from typing import Any, Optional


class RoundCheckpoint:
    """Placeholder for compatibility (no persisted state)."""


class RoundStateManager:
    """
    No-op state manager. All persistence is disabled; methods are stubs so code paths
    that call them continue to work without touching disk.
    """

    def __init__(self, validator: Any) -> None:
        self._validator = validator

    def save_checkpoint(self, *, tasks: Optional[list[Any]] = None) -> None:  # noqa: ANN401
        return None

    def load_checkpoint(self) -> Optional[RoundCheckpoint]:
        return None

    def cleanup(self) -> None:
        return None
