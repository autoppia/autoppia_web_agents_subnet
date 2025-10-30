"""
Compatibility shim for legacy imports.

The refactor moved the round state utilities into
`autoppia_web_agents_subnet.validator.round_state`. Keep the old import path
alive so existing scripts continue to operate until every call-site migrates.
"""

from __future__ import annotations

from autoppia_web_agents_subnet.validator.round_state.state_manager import (
    RoundCheckpoint,
    RoundStateManager,
)

__all__ = ["RoundStateManager", "RoundCheckpoint"]
