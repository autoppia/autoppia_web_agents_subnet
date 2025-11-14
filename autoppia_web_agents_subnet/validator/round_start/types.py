from __future__ import annotations

from dataclasses import dataclass

from autoppia_web_agents_subnet.validator.round_manager import RoundPhase


@dataclass
class RoundStartResult:
    starting_phase: RoundPhase
