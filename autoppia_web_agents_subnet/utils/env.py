import os
from typing import Optional

from dotenv import load_dotenv
load_dotenv()


def _env_str(name: str, default: str = "") -> str:
    """
    Retrieve a string environment variable, falling back to default for empty values.
    """
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    """
    Retrieve a boolean environment variable, falling back to default for invalid values.
    """
    return _env_str(name, str(default)).strip().lower() in {"y", "yes", "t", "true", "on", "1"}


def _env_int(name: str, default: int = 0, *, test_default: Optional[int] = None) -> int:
    """
    Retrieve an integer environment variable, falling back to default for invalid values.
    """
    TESTING = _env_bool("TESTING", False)
    if TESTING:
        if test_default is not None:
            return int(_env_str(f"TEST_{name}", str(test_default)))
        else:
            return int(_env_str(f"TEST_{name}", str(default)))
    return int(_env_str(name, str(default)))


def _env_float(name: str, default: float = 0.0, *, test_default: Optional[float] = None) -> float:
    """
    Retrieve a float environment variable, falling back to default for invalid values and testing default if provided.
    """
    TESTING = _env_bool("TESTING", False)
    if TESTING:
        if test_default is not None:
            return float(_env_str(f"TEST_{name}", str(test_default)))
        else:
            return float(_env_str(f"TEST_{name}", str(default)))
    return float(_env_str(name, str(default)))
