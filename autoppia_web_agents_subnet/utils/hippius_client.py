from __future__ import annotations

import hashlib
import json
from typing import Any, Optional, Tuple

try:
    from hippius_sdk.ipfs_core import AsyncIPFSClient
    _HAVE_HIPPIUS = True
except ImportError:
    AsyncIPFSClient = None  # type: ignore[assignment,misc]
    _HAVE_HIPPIUS = False

from autoppia_web_agents_subnet.validator.config import IPFS_API_URL


class IPFSError(Exception):
    pass

def minidumps(obj: Any, *, sort_keys: bool = True) -> str:
    """Compact JSON serialization for deterministic hashing."""
    return json.dumps(
        obj, separators=(",", ":"), ensure_ascii=False, sort_keys=sort_keys
    )

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _make_client(api_url: Optional[str] = None) -> AsyncIPFSClient:
    """Create a hippius AsyncIPFSClient, falling back to IPFS_API_URL from config."""
    api = (api_url or (IPFS_API_URL or "")).rstrip("/")
    if not api:
        raise IPFSError("No IPFS API URL configured")
    if not _HAVE_HIPPIUS:
        raise IPFSError("hippius-sdk is required: pip install hippius")
    return AsyncIPFSClient(api_url=api)

async def _hippius_add_bytes(
    data: bytes, *, filename: str = "commit.json", api_url: Optional[str] = None
) -> str:
    """Upload raw bytes to IPFS via hippius and return the CID."""
    client = _make_client(api_url)
    try:
        result = await client.add_bytes(data, filename=filename)
        # Response is a dict on success, raw bytes if JSON parsing failed
        if isinstance(result, dict):
            cid = result.get("Hash") or result.get("Cid") or result.get("Key")
        else:
            lines = [ln for ln in result.decode().strip().splitlines() if ln.strip()]
            parsed = json.loads(lines[-1])
            cid = parsed.get("Hash") or parsed.get("Cid") or parsed.get("Key")
        if not cid:
            raise IPFSError(f"IPFS /add returned no CID: {result}")
        return str(cid)
    except IPFSError:
        raise
    except Exception as e:
        raise IPFSError(f"IPFS add failed: {e}") from e
    finally:
        await client.client.aclose()

async def _hippius_cat(cid: str, *, api_url: Optional[str] = None) -> bytes:
    """Fetch raw bytes from IPFS by CID via hippius."""
    client = _make_client(api_url)
    try:
        return await client.cat(cid)
    except Exception as e:
        raise IPFSError(f"IPFS cat failed: {e}") from e
    finally:
        await client.client.aclose()

async def add_json_async(
    obj: Any,
    *,
    filename: str = "commit.json",
    api_url: Optional[str] = None,
    pin: bool = True,
    sort_keys: bool = True,
) -> Tuple[str, str, int]:
    """Upload a JSON object to IPFS. Returns (CID, sha256_hex, byte_length)."""
    text = minidumps(obj, sort_keys=sort_keys)
    b = text.encode("utf-8")
    cid = await _hippius_add_bytes(b, filename=filename, api_url=api_url)
    return cid, sha256_hex(b), len(b)

async def get_json_async(
    cid: str,
    *,
    api_url: Optional[str] = None,
    expected_sha256_hex: Optional[str] = None,
) -> Tuple[Any, bytes, str]:
    """Download JSON from IPFS by CID. Returns (parsed_obj, normalized_bytes, sha256_hex).
    Raises IPFSError if expected_sha256_hex is given and doesn't match."""
    raw = await _hippius_cat(cid, api_url=api_url)
    obj = json.loads(raw.decode("utf-8"))
    norm = minidumps(obj).encode("utf-8")
    h = sha256_hex(norm)
    if expected_sha256_hex and h.lower() != expected_sha256_hex.lower():
        raise IPFSError(f"Hash mismatch for CID {cid}: expected {expected_sha256_hex}, got {h}")
    return obj, norm, h
