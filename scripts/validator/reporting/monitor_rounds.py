#!/usr/bin/env python3
"""Backward-compatible wrapper for the pm2 monitor CLI."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from reporting.monitor.cli import main  # type: ignore
else:  # pragma: no cover
    from .monitor.cli import main


if __name__ == "__main__":
    main()
