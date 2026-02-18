from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Optional, Sequence, Tuple

try:
    import requests  # type: ignore
    _HAVE_REQUESTS = True
except Exception:  # pragma: no cover
    requests = None  # type: ignore
    _HAVE_REQUESTS = False

from autoppia_web_agents_subnet.validator.config import IPFS_API_URL, IPFS_GATEWAYS


class IPFSError(Exception):
    pass


def minidumps(obj: Any, *, sort_keys: bool = True) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, sort_keys=sort_keys)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _api_base() -> str:
    return (IPFS_API_URL or "").rstrip("/")


def ipfs_add_bytes(
    data: bytes,
    *,
    filename: str = "commit.json",
    api_url: Optional[str] = None,
    pin: bool = True,
) -> str:
    api = (api_url or _api_base())
    if not api:
        raise IPFSError("No IPFS API URL configured")
    if not _HAVE_REQUESTS:
        raise IPFSError("Python 'requests' is required for IPFS HTTP API")
    url = f"{api}/add"
    params = {
        "cid-version": "1",
        "hash": "sha2-256",
        "pin": "true" if pin else "false",
        "wrap-with-directory": "false",
        "quieter": "true",
    }
    files = {"file": (filename, data)}
    resp = requests.post(url, params=params, files=files, timeout=30)  # type: ignore
    resp.raise_for_status()
    lines = [ln for ln in resp.text.strip().splitlines() if ln.strip()]
    last = json.loads(lines[-1])
    cid = last.get("Hash") or last.get("Cid") or last.get("Key")
    if not cid:
        raise IPFSError(f"IPFS /add returned no CID: {last}")
    return str(cid)


def ipfs_add_json(
    obj: Any,
    *,
    filename: str = "commit.json",
    api_url: Optional[str] = None,
    pin: bool = True,
    sort_keys: bool = True,
) -> Tuple[str, str, int]:
    text = minidumps(obj, sort_keys=sort_keys)
    b = text.encode("utf-8")
    cid = ipfs_add_bytes(b, filename=filename, api_url=api_url, pin=pin)
    return cid, sha256_hex(b), len(b)


def ipfs_cat(
    cid: str,
    *,
    api_url: Optional[str] = None,
    gateways: Optional[Sequence[str]] = None,
    timeout: float = 20.0,
) -> bytes:
    last_err: Optional[Exception] = None
    api = (api_url or _api_base())

    # Try HTTP API first
    if api and _HAVE_REQUESTS:
        try:
            url = f"{api}/cat"
            resp = requests.post(url, params={"arg": cid}, timeout=timeout)  # type: ignore
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            last_err = e

    # Fallback to public gateways
    import urllib.request
    for gw in (gateways or IPFS_GATEWAYS or []):
        try:
            with urllib.request.urlopen(f"{gw.rstrip('/')}/{cid}", timeout=timeout) as r:
                return r.read()
        except Exception as e:  # pragma: no cover
            last_err = e
            continue

    raise IPFSError(f"Failed to fetch CID {cid}: {last_err}")


def ipfs_get_json(
    cid: str,
    *,
    api_url: Optional[str] = None,
    gateways: Optional[Sequence[str]] = None,
    expected_sha256_hex: Optional[str] = None,
) -> Tuple[Any, bytes, str]:
    raw = ipfs_cat(cid, api_url=api_url, gateways=gateways)
    obj = json.loads(raw.decode("utf-8"))
    norm = minidumps(obj).encode("utf-8")
    h = sha256_hex(norm)
    if expected_sha256_hex and h.lower() != expected_sha256_hex.lower():
        raise IPFSError(f"Hash mismatch for CID {cid}: expected {expected_sha256_hex}, got {h}")
    return obj, norm, h


async def add_json_async(
    obj: Any,
    *,
    filename: str = "commit.json",
    api_url: Optional[str] = None,
    pin: bool = True,
    sort_keys: bool = True,
) -> Tuple[str, str, int]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: ipfs_add_json(obj, filename=filename, api_url=api_url, pin=pin, sort_keys=sort_keys)
    )


async def get_json_async(
    cid: str,
    *,
    api_url: Optional[str] = None,
    gateways: Optional[Sequence[str]] = None,
    expected_sha256_hex: Optional[str] = None,
) -> Tuple[Any, bytes, str]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: ipfs_get_json(cid, api_url=api_url, gateways=gateways, expected_sha256_hex=expected_sha256_hex)
    )

