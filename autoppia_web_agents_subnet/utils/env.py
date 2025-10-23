from __future__ import annotations

import os
from typing import Optional


def _str_to_bool(value: str) -> bool:
    """
    Minimal replacement for distutils.util.strtobool that keeps behaviour consistent
    while remaining compatible with Python 3.12+ where distutils is deprecated.
    """
    normalized = value.strip().lower()
    if normalized in {"y", "yes", "t", "true", "on", "1"}:
        return True
    if normalized in {"n", "no", "f", "false", "off", "0"}:
        return False
    raise ValueError(f"Invalid truth value {value!r}")


def _normalized(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _env_int(name: str, default: int) -> int:
    """
    Retrieve an integer environment variable, falling back to default for invalid values.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw.strip())
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _env_float(
    name: str,
    default: float,
    *,
    alias: Optional[str] = None,
    test_default: Optional[float] = None,
) -> float:
    """
    Retrieve a float environment variable with optional:
    - alias: fallback env var name (for backward compatibility)
    - test_default: default used when TESTING env is true and TEST_* variable is not set

    Resolution order:
      1) If TESTING env and TEST_<name> is set → parse and return
      2) If <name> is set → parse and return
      3) If alias is set and alias is set → parse and return
      4) If TESTING env and test_default is provided → return test_default
      5) Otherwise → return default
    """
    # Determine TESTING from environment (avoid circular imports)
    testing_env = False
    try:
        testing_env = _str_to_bool(os.getenv("TESTING", "false"))
    except Exception:
        testing_env = False

    # 1) Explicit testing override
    if testing_env:
        tval = os.getenv(f"TEST_{name}")
        if tval is not None:
            try:
                return float(tval.strip())
            except (TypeError, ValueError):
                pass

    # 2) Primary name
    raw = os.getenv(name)
    if raw is not None:
        try:
            return float(raw.strip())
        except (TypeError, ValueError):
            pass

    # 3) Backward-compatible alias
    if alias is not None:
        ar = os.getenv(alias)
        if ar is not None:
            try:
                return float(ar.strip())
            except (TypeError, ValueError):
                pass

    # 4) Testing default
    if testing_env and test_default is not None:
        return float(test_default)

    # 5) Production/default
    return float(default)

