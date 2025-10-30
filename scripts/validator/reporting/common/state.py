from __future__ import annotations

from pathlib import Path
from typing import Optional


def load_last_state(path: Path) -> Optional[str]:
    """Return the previously stored round identifier (if any)."""
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None
    except OSError:
        return None


def save_last_state(path: Path, round_id: str) -> None:
    """Persist the last processed round identifier."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(round_id, encoding="utf-8")
    except OSError:
        # Fail quietly; the monitor will retry next iteration.
        pass
