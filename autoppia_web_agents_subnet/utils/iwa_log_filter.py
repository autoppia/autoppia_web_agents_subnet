from __future__ import annotations

from autoppia_web_agents_subnet.utils.logging_filter import apply_subnet_module_logging_filters

_APPLIED = False


def enforce_iwa_log_filter() -> None:
    global _APPLIED
    if _APPLIED:
        return
    apply_subnet_module_logging_filters()
    _APPLIED = True
