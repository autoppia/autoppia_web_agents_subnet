from __future__ import annotations

import inspect
import logging
from typing import Dict

import bittensor as bt


_LOG_PREFIX = "autoppia_web_agents_subnet."
_BLOATED_BT_LEVELS = {
    "trace": 5,
    "debug": 10,
    "info": 20,
    "success": 25,
    "warning": 30,
    "error": 40,
    "critical": 50,
}

_MODULE_ALIASES = {
    "iwa": "platform",
    "iwap": "platform",
    "iwap_client": "platform",
    "platform": "platform",
    "validator": "validator",
    "round": "validator.round_start",
    "round_start": "validator.round_start",
    "evaluation": "validator.evaluation",
    "consensus": "validator.settlement",
    "settlement": "validator.settlement",
    "opensource": "opensource",
}

_FILTER_CACHE: Dict[str, tuple[int | None, bool]] = {}


def _coerce_level(raw_level: str | None) -> int | None:
    if not raw_level:
        return None
    text = str(raw_level).strip().upper()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return logging._nameToLevel.get(text)


def _canonical_module_name(module_name: str) -> str:
    if not module_name:
        return ""
    normalized = str(module_name).strip().lower().replace("-", "_")
    if normalized.startswith(_LOG_PREFIX):
        normalized = normalized[len(_LOG_PREFIX) :]
    normalized = normalized.strip(".")
    if not normalized:
        return ""
    return _MODULE_ALIASES.get(normalized, normalized)


def _parse_module_levels() -> Dict[str, int]:
    config_raw = (_canonical_module_name(v) for v in __import__("os").environ.get("LOG_MODULE_LEVELS", "").split(","))
    settings: Dict[str, int] = {}
    for item in config_raw:
        token = item.strip()
        if not token:
            continue
        if "=" in token:
            module, level_text = token.split("=", 1)
        elif ":" in token:
            module, level_text = token.split(":", 1)
        else:
            continue
        normalized_module = _canonical_module_name(module)
        level = _coerce_level(level_text)
        if not normalized_module or level is None:
            continue
        settings[normalized_module] = level
    return settings


def _parse_disabled_modules() -> set[str]:
    raw_disabled = __import__("os").environ.get("LOG_DISABLED_MODULES", "")
    disabled: set[str] = set()
    for token in raw_disabled.split(","):
        normalized = _canonical_module_name(token)
        if normalized:
            disabled.add(normalized)
    return disabled


def _resolve_caller_module() -> str:
    frame = inspect.currentframe()
    if frame is None:
        return ""
    try:
        frame = frame.f_back
        while frame is not None:
            module = inspect.getmodule(frame)
            module_name = getattr(module, "__name__", "") or ""
            if module_name and module_name.startswith(_LOG_PREFIX):
                if module_name == __name__:
                    frame = frame.f_back
                    continue
                return _canonical_module_name(module_name)
            frame = frame.f_back
    finally:
        del frame
    return ""


def _module_matches(module: str, configured: set[str] | Dict[str, int]) -> str | None:
    for candidate in sorted(configured, key=len, reverse=True):
        if module == candidate or module.startswith(f"{candidate}."):
            return candidate
    return None


def _should_emit(
    target_module: str,
    level: int,
    levels: Dict[str, int],
    disabled: set[str],
    global_level: int | None,
) -> bool:
    key = (target_module, level, bool(levels), bool(disabled), global_level or 0)
    cache_value = _FILTER_CACHE.get(key)
    if cache_value is not None:
        min_level, enabled = cache_value
        if min_level is None:
            return level >= (global_level or level) if global_level is not None else True
        return enabled if level >= min_level else False

    blocked = False
    target_level = global_level

    matched_disabled = _module_matches(target_module, disabled)
    if matched_disabled is not None:
        blocked = True

    matched_module = _module_matches(target_module, levels)
    if matched_module is not None:
        target_level = levels[matched_module]

    emit = not blocked and (global_level is None or level >= global_level)
    if target_level is not None:
        emit = emit and level >= target_level

    _FILTER_CACHE[key] = (target_level, emit)
    return emit


class _SubNetStdlibFilter(logging.Filter):
    def __init__(
        self,
        module_levels: Dict[str, int],
        disabled_modules: set[str],
        global_level: int | None,
    ) -> None:
        super().__init__()
        self.module_levels = module_levels
        self.disabled_modules = disabled_modules
        self.global_level = global_level

    def filter(self, record: logging.LogRecord) -> bool:
        return _should_emit(
            _canonical_module_name(record.name),
            record.levelno,
            self.module_levels,
            self.disabled_modules,
            self.global_level,
        )


def apply_subnet_module_logging_filters(logging_config=None) -> None:
    module_levels = _parse_module_levels()
    disabled_modules = _parse_disabled_modules()

    global_level = _coerce_level(__import__("os").environ.get("LOG_LEVEL"))
    if global_level is None and logging_config is not None and getattr(logging_config, "level", None):
        global_level = _coerce_level(str(logging_config.level))
    if global_level is not None:
        logging.getLogger().setLevel(global_level)

    if not hasattr(logging, "_autoppia_stdlib_module_filter"):
        filter_instance = _SubNetStdlibFilter(module_levels, disabled_modules, global_level)
        root_logger = logging.getLogger()
        root_logger.addFilter(filter_instance)
        logging._autoppia_stdlib_module_filter = filter_instance

    if not getattr(bt.logging, "_autoppia_bt_module_filter", False):
        for method, level in _BLOATED_BT_LEVELS.items():
            original = getattr(bt.logging, method, None)
            if not callable(original):
                continue

            def _wrap(original_fn=original, method_level=level):
                def _wrapped(*args, **kwargs):
                    module = _resolve_caller_module()
                    if _should_emit(
                        module,
                        method_level,
                        module_levels,
                        disabled_modules,
                        global_level,
                    ):
                        return original_fn(*args, **kwargs)

                _wrapped.__name__ = f"autoppia_filtered_{method}"
                _wrapped.__doc__ = original_fn.__doc__
                return _wrapped

            setattr(bt.logging, method, _wrap())
        bt.logging._autoppia_bt_module_filter = True
