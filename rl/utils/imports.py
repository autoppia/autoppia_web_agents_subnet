from __future__ import annotations

"""Utility helpers for dynamic imports used by the RL environment."""

import importlib
from typing import Any


def load_object(path: str) -> Any:
    """Load an object from a fully-qualified import path.

    Parameters
    ----------
    path:
        String in the form ``"package.module:object"`` or ``"package.module.object"``.

    Returns
    -------
    Any
        The imported attribute.

    Raises
    ------
    ImportError
        If the module cannot be imported.
    AttributeError
        If the attribute does not exist within the module.
    """

    if not isinstance(path, str) or not path:
        raise ValueError("Import path must be a non-empty string")

    module_path: str
    attr_name: str

    if ":" in path:
        module_path, attr_name = path.split(":", 1)
    else:
        parts = path.split(".")
        if len(parts) < 2:
            raise ValueError(
                "Import path must include both module and attribute, e.g. 'pkg.mod:Class'"
            )
        module_path = ".".join(parts[:-1])
        attr_name = parts[-1]

    module = importlib.import_module(module_path)
    try:
        return getattr(module, attr_name)
    except AttributeError as exc:  # pragma: no cover - precise error message
        raise AttributeError(f"Module '{module_path}' has no attribute '{attr_name}'") from exc


__all__ = ["load_object"]

