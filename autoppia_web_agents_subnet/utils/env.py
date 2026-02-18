import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def _env_str(name: str, default: str = "") -> str:
    """
    Retrieve a string environment variable, falling back to default for empty values.
    """
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False, *, test_default: Optional[bool] = None) -> bool:
    """
    Retrieve a boolean environment variable, falling back to default for invalid values.
    Supports TEST_* overrides when TESTING=true.
    """

    def _parse_bool(value: str) -> bool:
        return value.strip().lower() in {"y", "yes", "t", "true", "on", "1"}

    TESTING = _parse_bool(_env_str("TESTING", "false"))
    if TESTING:
        test_key = f"TEST_{name}"
        test_val = os.getenv(test_key)
        if test_val is not None and test_val.strip() != "":
            return _parse_bool(test_val)

        if test_default is not None:
            return _parse_bool(str(test_default))
        return _parse_bool(_env_str(name, str(default)))
    return _parse_bool(_env_str(name, str(default)))


def _env_int(name: str, default: int = 0, *, test_default: Optional[int] = None) -> int:
    """
    Retrieve an integer environment variable, falling back to default for invalid values.
    """
    TESTING = _env_bool("TESTING", False)
    if TESTING:
        test_key = f"TEST_{name}"
        test_val = os.getenv(test_key)
        if test_val is not None and test_val.strip() != "":
            return int(test_val.strip())

        # In testing mode, prefer TEST_* overrides. If none provided, fall back:
        # - if a test_default is specified: use it
        # - otherwise: allow the non-test env var to be used (more ergonomic for .env files)
        if test_default is not None:
            return int(str(test_default))
        return int(_env_str(name, str(default)))
    return int(_env_str(name, str(default)))


def _env_float(name: str, default: float = 0.0, *, test_default: Optional[float] = None) -> float:
    """
    Retrieve a float environment variable, falling back to default for invalid values and testing default if provided.
    """
    TESTING = _env_bool("TESTING", False)
    if TESTING:
        test_key = f"TEST_{name}"
        test_val = os.getenv(test_key)
        if test_val is not None and test_val.strip() != "":
            return float(test_val.strip())

        if test_default is not None:
            return float(str(test_default))
        return float(_env_str(name, str(default)))
    return float(_env_str(name, str(default)))
