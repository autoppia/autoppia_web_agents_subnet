import requests
import asyncio
from typing import Dict, Any
from autoppia_web_agents_subnet.config.config import LEADERBOARD_VALIDATOR_RUNS_ENDPOINT


def _post_json(url: str, payload: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {}


# --------- VALIDATOR INFO ---------
def upsert_validator_info(doc: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
    """
    Envía o actualiza la información estática del validador (foto al arrancar).
    """
    url = f"{LEADERBOARD_VALIDATOR_RUNS_ENDPOINT}/info"
    return _post_json(url, doc, timeout=timeout)


async def upsert_validator_info_async(doc: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, upsert_validator_info, doc, timeout)


# --------- VALIDATOR EVENTS ---------
def send_validator_event(event: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
    """
    Envía un evento de forward (append-only).
    """
    url = f"{LEADERBOARD_VALIDATOR_RUNS_ENDPOINT}/events"
    return _post_json(url, event, timeout=timeout)


async def send_validator_event_async(event: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, send_validator_event, event, timeout)
