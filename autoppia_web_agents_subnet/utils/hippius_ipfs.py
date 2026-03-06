"""Hippius (SN75) IPFS wrapper — drop-in async replacement for legacy metahash73 calls.

Uses the high-level ``hippius.HippiusClient`` which is async-native,
so we skip ``run_in_executor`` entirely for the Hippius path.

These async functions match the return signatures of the sync helpers in
``ipfs_client.py`` so that ``add_json_async`` / ``get_json_async`` can
delegate transparently.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional, Tuple

from autoppia_web_agents_subnet.utils.ipfs_client import IPFSError, minidumps, sha256_hex

logger = logging.getLogger(__name__)

# Singleton — lazily initialised on first use, reused across calls.
_state: dict[str, Any] = {"client": None}


def _get_client() -> Any:
    """Return a cached HippiusClient instance (created on first call)."""
    if _state["client"] is None:
        try:
            from hippius import HippiusClient  # type: ignore[import-untyped]
        except ImportError as exc:
            raise IPFSError(
                "hippius package not installed — run: pip install hippius>=0.2.60"
            ) from exc
        _state["client"] = HippiusClient()
        logger.info("Hippius IPFS client initialised")
    return _state["client"]


def reset_client() -> None:
    """Clear the cached client (useful for tests)."""
    _state["client"] = None


async def hippius_add_json_async(
    obj: Any,
    *,
    filename: str = "commit.json",
    pin: bool = True,
    sort_keys: bool = True,
) -> Tuple[str, str, int]:
    """Upload JSON to IPFS via Hippius SDK.

    Returns ``(cid, sha256_hex, byte_len)`` — same shape as
    ``ipfs_client.ipfs_add_json``.
    """
    text = minidumps(obj, sort_keys=sort_keys)
    data = text.encode("utf-8")
    h = sha256_hex(data)

    try:
        client = _get_client()
        cid = await client.ipfs_upload_bytes(data, filename=filename, pin=pin)
    except IPFSError:
        raise
    except Exception as exc:
        raise IPFSError(f"Hippius IPFS upload failed: {exc}") from exc

    if not cid:
        raise IPFSError("Hippius IPFS upload returned no CID")
    return str(cid), h, len(data)


async def hippius_get_json_async(
    cid: str,
    *,
    expected_sha256_hex: Optional[str] = None,
) -> Tuple[Any, bytes, str]:
    """Download JSON from IPFS via Hippius SDK.

    Returns ``(obj, normalised_bytes, sha256_hex)`` — same shape as
    ``ipfs_client.ipfs_get_json``.
    """
    try:
        client = _get_client()
        raw = await client.ipfs_download_bytes(cid)
    except IPFSError:
        raise
    except Exception as exc:
        raise IPFSError(f"Hippius IPFS download failed for CID {cid}: {exc}") from exc

    obj = json.loads(raw.decode("utf-8"))
    norm = minidumps(obj).encode("utf-8")
    h = sha256_hex(norm)

    if expected_sha256_hex and h.lower() != expected_sha256_hex.lower():
        raise IPFSError(
            f"Hash mismatch for CID {cid}: expected {expected_sha256_hex}, got {h}"
        )

    return obj, norm, h
