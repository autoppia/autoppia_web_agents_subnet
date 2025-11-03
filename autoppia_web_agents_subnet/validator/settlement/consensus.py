from __future__ import annotations

"""
Backward-compatible facade for legacy imports.

The consensus implementation now lives in ``autoppia_web_agents_subnet.validator.consensus``.
Re-export the public helpers so existing call-sites under ``validator.settlement`` continue to work.
"""

from autoppia_web_agents_subnet.validator.consensus import (  # noqa: F401
    aggregate_scores_from_commitments,
    publish_round_snapshot,
    publish_scores_snapshot,
)
from autoppia_web_agents_subnet.utils.commitments import read_all_plain_commitments  # noqa: F401
