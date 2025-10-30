#!/usr/bin/env python3
"""Backward-compatible wrapper for the legacy summary email monitor."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from reporting.legacy.summary_email_monitor import main  # type: ignore
else:  # pragma: no cover
    from .legacy.summary_email_monitor import main


if __name__ == "__main__":
    main()
