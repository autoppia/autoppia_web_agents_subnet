"""Validator reporting toolkit grouped by concerns (analysis, batch, monitor, legacy, tools)."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

__all__ = [
    "analysis",
    "batch",
    "common",
    "legacy",
    "monitor",
    "tools",
]


def __getattr__(name: str) -> ModuleType:
    if name in __all__:
        module = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__ + list(globals().keys()))
