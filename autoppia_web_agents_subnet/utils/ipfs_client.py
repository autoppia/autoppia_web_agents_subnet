"""
IPFS client facade.

Delegates to the configured IPFS backend (standard or Hippius) via the storage
abstraction layer.  All public function signatures are preserved for backward
compatibility so existing callers (consensus, tests, scripts) continue to work
without changes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Optional, Sequence, Tuple


class IPFSError(Exception):
    pass


# ── helpers (unchanged, still used by get_json for normalisation) ──────────

def minidumps(obj: Any, *, sort_keys: bool = True) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, sort_keys=sort_keys)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── internal: get the configured backend ───────────────────────────────────

def _get_client():
    """Return the configured IPFS client from the storage layer."""
    from autoppia_web_agents_subnet.utils.storage import get_ipfs_client
    return get_ipfs_client()


# ── public synchronous API (unchanged signatures) ─────────────────────────

def ipfs_add_bytes(
    data: bytes,
    *,
    filename: str = "commit.json",
    api_url: Optional[str] = None,
    pin: bool = True,
) -> str:
    """Upload bytes and return CID.

    ``api_url`` is accepted for backward compatibility but ignored when using
    Hippius backend (the backend's own endpoint is used instead).
    """
    return _get_client().add_bytes(data, filename=filename, pin=pin)


def ipfs_add_json(
    obj: Any,
    *,
    filename: str = "commit.json",
    api_url: Optional[str] = None,
    pin: bool = True,
    sort_keys: bool = True,
) -> Tuple[str, str, int]:
    """Upload a JSON object and return (CID, sha256_hex, byte_len)."""
    return _get_client().add_json(obj, filename=filename, pin=pin, sort_keys=sort_keys)


def ipfs_cat(
    cid: str,
    *,
    api_url: Optional[str] = None,
    gateways: Optional[Sequence[str]] = None,
    timeout: float = 20.0,
) -> bytes:
    """Download raw bytes by CID."""
    return _get_client().cat(cid, timeout=timeout)


def ipfs_get_json(
    cid: str,
    *,
    api_url: Optional[str] = None,
    gateways: Optional[Sequence[str]] = None,
    expected_sha256_hex: Optional[str] = None,
) -> Tuple[Any, bytes, str]:
    """Download and parse JSON.  Returns (obj, normalised_bytes, sha256_hex)."""
    return _get_client().get_json(cid, expected_sha256_hex=expected_sha256_hex)


# ── async wrappers (unchanged signatures) ──────────────────────────────────

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
        None,
        lambda: ipfs_add_json(obj, filename=filename, api_url=api_url, pin=pin, sort_keys=sort_keys),
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
        None,
        lambda: ipfs_get_json(cid, api_url=api_url, gateways=gateways, expected_sha256_hex=expected_sha256_hex),
    )
