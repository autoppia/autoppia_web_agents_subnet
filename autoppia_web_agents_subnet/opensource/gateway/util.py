import logging
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

HF_API_BASE = "https://huggingface.co/api/models"


def is_valid_chutes_base_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and (parsed.hostname or "").lower().endswith(".chutes.ai")
    except Exception:
        return False


async def fetch_chutes_models(http_client: httpx.AsyncClient, base_url: str, api_key: str | None) -> list[dict[str, Any]]:
    models_url = f"{base_url.rstrip('/')}/v1/models"
    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = await http_client.get(models_url, headers=headers, timeout=10)
    except Exception as exc:
        logger.warning(f"Custom chute unreachable at {models_url}: {exc}")
        raise HTTPException(status_code=400, detail=f"Custom chute endpoint unreachable: {base_url}") from exc

    if resp.status_code in (401, 403):
        raise HTTPException(status_code=400, detail="Custom chute endpoint is private or unauthorized")
    if resp.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"Custom chute /v1/models failed with status {resp.status_code}")

    try:
        data = resp.json()
        entries = data.get("data") or (data if isinstance(data, list) else [])
        return [m for m in entries if isinstance(m, dict) and m.get("id")]
    except Exception:
        return []


def get_model_root(model_entry: dict[str, Any]) -> str:
    return str(model_entry.get("root") or model_entry.get("id") or "")


def _parse_usd(obj: dict, key: str) -> float | None:
    value = obj.get(key) or {}
    return float(value["usd"]) if isinstance(value, dict) and "usd" in value else None


def extract_model_pricing(model_entry: dict[str, Any]) -> dict[str, float]:
    entry: dict[str, float] = {}
    price = model_entry.get("price")
    if isinstance(price, dict):
        try:
            for source, dest in [("input", "input"), ("output", "output"), ("input_cache_read", "input_cache_read")]:
                usd = _parse_usd(price, source)
                if usd is not None:
                    entry[dest] = usd
        except Exception:
            entry = {}

    if not entry:
        pricing = model_entry.get("pricing")
        if isinstance(pricing, dict):
            try:
                for source, dest in [
                    ("input", "input"),
                    ("prompt", "input"),
                    ("output", "output"),
                    ("completion", "output"),
                    ("input_cache_read", "input_cache_read"),
                ]:
                    if pricing.get(source) is not None:
                        entry[dest] = float(pricing[source])
            except Exception:
                entry = {}

    return entry


async def check_hf_model_public(http_client: httpx.AsyncClient, model_id: str) -> bool:
    if "/" not in model_id:
        return False
    try:
        resp = await http_client.get(f"{HF_API_BASE}/{model_id}", timeout=10)
        return resp.status_code == 200 and resp.json().get("private") is not True
    except Exception:
        return False
