from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from autoppia_web_agents_subnet.validator.round_manager import RoundPhase


@dataclass
class RoundStartResult:
    next_phase: RoundPhase
