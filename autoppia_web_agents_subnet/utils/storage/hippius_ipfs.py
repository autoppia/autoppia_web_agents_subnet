"""Hippius (SN 75) IPFS backend using the hippius-sdk."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import os
from typing import Any, Optional, Tuple

from autoppia_web_agents_subnet.utils.storage.base import BaseIPFSClient

try:
    from hippius_sdk import HippiusClient  # type: ignore
    _HAVE_HIPPIUS = True
except Exception:  # pragma: no cover
    HippiusClient = None  # type: ignore
    _HAVE_HIPPIUS = False


class HippiusIPFSError(Exception):
    pass


def _minidumps(obj: Any, *, sort_keys: bool = True) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, sort_keys=sort_keys)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_async(coro):
    """Run an async coroutine from sync context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=120)
    else:
        return asyncio.run(coro)


class HippiusIPFSClient(BaseIPFSClient):
    """IPFS client that uses Hippius (SN 75) decentralised storage."""

    def __init__(
        self,
        ipfs_api_url: Optional[str] = None,
        hippius_key: Optional[str] = None,
    ) -> None:
        if not _HAVE_HIPPIUS:
            raise HippiusIPFSError(
                "hippius_sdk is required for Hippius IPFS backend. "
                "Install it with: pip install hippius"
            )
        kwargs = {}
        if ipfs_api_url:
            kwargs["ipfs_api_url"] = ipfs_api_url
        self._client = HippiusClient(**kwargs)
        self._hippius_key = hippius_key

    def add_bytes(
        self,
        data: bytes,
        *,
        filename: str = "commit.json",
        pin: bool = True,
    ) -> str:
        with tempfile.NamedTemporaryFile(
            prefix="hippius_", suffix=f"_{filename}", delete=False
        ) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            result = _run_async(self._client.upload_file(tmp_path))
            cid = result.get("cid") if isinstance(result, dict) else str(result)
            if not cid:
                raise HippiusIPFSError(f"Hippius upload returned no CID: {result}")
            return str(cid)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def add_json(
        self,
        obj: Any,
        *,
        filename: str = "commit.json",
        pin: bool = True,
        sort_keys: bool = True,
    ) -> Tuple[str, str, int]:
        text = _minidumps(obj, sort_keys=sort_keys)
        b = text.encode("utf-8")
        cid = self.add_bytes(b, filename=filename, pin=pin)
        return cid, _sha256_hex(b), len(b)

    def cat(
        self,
        cid: str,
        *,
        timeout: float = 20.0,
    ) -> bytes:
        try:
            content = _run_async(self._client.cat(cid))
            if isinstance(content, str):
                return content.encode("utf-8")
            return bytes(content)
        except Exception as e:
            raise HippiusIPFSError(f"Hippius failed to fetch CID {cid}: {e}") from e

    def get_json(
        self,
        cid: str,
        *,
        expected_sha256_hex: Optional[str] = None,
    ) -> Tuple[Any, bytes, str]:
        raw = self.cat(cid)
        obj = json.loads(raw.decode("utf-8"))
        norm = _minidumps(obj).encode("utf-8")
        h = _sha256_hex(norm)
        if expected_sha256_hex and h.lower() != expected_sha256_hex.lower():
            raise HippiusIPFSError(
                f"Hash mismatch for CID {cid}: expected {expected_sha256_hex}, got {h}"
            )
        return obj, norm, h
