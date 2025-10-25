"""Reinforcement learning environment helpers for Infinite Web Arena (IWA)."""

from typing import Any

from .validator.iwa_evaluator_client import IWAValidator, ValidatorFeedback

_ENV_IMPORT_ERROR: Exception | None = None

try:  # pragma: no cover - optional dependency path
    from .envs.iwa_gym_env import IWAWebEnv, MacroAction
except ModuleNotFoundError as exc:  # pragma: no cover - handled lazily
    IWAWebEnv = None  # type: ignore[assignment]
    MacroAction = None  # type: ignore[assignment]
    _ENV_IMPORT_ERROR = exc


def __getattr__(name: str) -> Any:  # pragma: no cover - simple delegation
    if name in {"IWAWebEnv", "MacroAction"} and _ENV_IMPORT_ERROR is not None:
        raise ModuleNotFoundError(
            "gymnasium is required to instantiate IWAWebEnv; install optional dependency",
        ) from _ENV_IMPORT_ERROR
    raise AttributeError(f"module 'rl' has no attribute '{name}'")


__all__ = ["IWAWebEnv", "MacroAction", "IWAValidator", "ValidatorFeedback"]
