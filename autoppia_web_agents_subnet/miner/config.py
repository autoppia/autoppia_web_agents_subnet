from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_ENV_VAR = "AUTOPPIA_MINER_CLI_CONFIG"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "autoppia" / "miner-cli.json"


def get_config_path() -> Path:
    raw = (os.getenv(CONFIG_ENV_VAR) or "").strip()
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_CONFIG_PATH


def load_config() -> dict[str, Any]:
    path = get_config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_config(data: dict[str, Any]) -> Path:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def update_config(updates: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    current = load_config()
    for key, value in updates.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    path = save_config(current)
    return path, current


def get_default(config: dict[str, Any], key: str, fallback: Any = None) -> Any:
    value = config.get(key, fallback)
    if isinstance(value, str):
        return value.strip()
    return value
