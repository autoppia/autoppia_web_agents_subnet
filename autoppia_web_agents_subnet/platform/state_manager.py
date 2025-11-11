from __future__ import annotations

"""
Legacy import bridge.

The validator checkpoint manager was moved to
``autoppia_web_agents_subnet.validator.round_state.state_manager``.
Re-export it here so older platform code keeps functioning without changes.
"""

from autoppia_web_agents_subnet.validator.round_state.state_manager import (  # noqa: F401
    RoundCheckpoint,
    RoundStateManager,
)
