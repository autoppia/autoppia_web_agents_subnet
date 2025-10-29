#!/usr/bin/env python3
from __future__ import annotations

"""
Entry-point script that delegates to the shared reporting.monitor module.

This thin wrapper keeps the existing CLI behaviour intact while the heavy
lifting lives in scripts/validator/reporting/monitor.py so it can be reused.
"""

from reporting.monitor import cli_main


def main() -> None:  # pragma: no cover - convenience wrapper
    cli_main()


if __name__ == "__main__":
    main()
