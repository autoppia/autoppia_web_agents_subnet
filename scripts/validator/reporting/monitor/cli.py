#!/usr/bin/env python3
from __future__ import annotations

"""Entry point that delegates to the pm2 monitor loop."""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from reporting.monitor.loop import cli_main  # type: ignore
else:  # pragma: no cover
    from .loop import cli_main


def main() -> None:  # pragma: no cover - convenience wrapper
    cli_main()


if __name__ == "__main__":
    main()
