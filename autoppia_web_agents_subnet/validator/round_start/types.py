from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RoundStartResult:
    continue_forward: bool = True
