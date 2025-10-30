"""
Compatibility shim for legacy `ValidatorPlatformMixin` import paths.

Importing from `autoppia_web_agents_subnet.platform.mixin` is preferred,
but this module keeps older references working during the transition.
"""

from __future__ import annotations

from autoppia_web_agents_subnet.platform.mixin import ValidatorPlatformMixin

__all__ = ["ValidatorPlatformMixin"]
