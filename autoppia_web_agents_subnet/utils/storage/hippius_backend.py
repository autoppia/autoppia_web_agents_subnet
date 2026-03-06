"""StorageBackend that delegates to the Hippius Python SDK (SN75).

This backend uses ``hippius_sdk.IPFSClient`` for content-addressed
storage and ``hippius_sdk.HippiusClient`` for optional S3 object storage.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional, Tuple

from autoppia_web_agents_subnet.utils.storage.base import StorageBackend

# Compact JSON serialisation matching the existing ipfs_client convention.
_SEPARATORS = (",", ":")


def _minidumps(obj: Any, *, sort_keys: bool = True) -> str:
    return json.dumps(obj, separators=_SEPARATORS, ensure_ascii=False, sort_keys=sort_keys)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class HippiusBackend(StorageBackend):
    """Hippius SDK backend for IPFS and S3 operations.

    Parameters
    ----------
    ipfs_api_url:
        Hippius IPFS gateway / API URL.  Passed through to
        ``hippius_sdk.IPFSClient``.
    api_key:
        Optional Hippius platform API key.  When provided, a full
        ``HippiusClient`` is initialised for S3 operations.
    s3_bucket:
        S3 bucket name for log uploads (used only when *api_key* is set).
    """

    def __init__(
        self,
        *,
        ipfs_api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        s3_bucket: Optional[str] = None,
    ) -> None:
        try:
            from hippius_sdk import IPFSClient  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "hippius_sdk is required for the Hippius storage backend. "
                "Install it with: pip install hippius_sdk"
            ) from exc

        kwargs: Dict[str, Any] = {}
        if ipfs_api_url:
            kwargs["api_url"] = ipfs_api_url

        self._ipfs = IPFSClient(**kwargs)
        self._api_key = api_key
        self._s3_bucket = s3_bucket or "autoppia-logs"
        self._hippius_client: Any = None

        if api_key:
            try:
                from hippius_sdk import HippiusClient  # type: ignore[import-untyped]

                self._hippius_client = HippiusClient(api_key=api_key)
            except Exception:
                pass

    # ── IPFS operations ─────────────────────────────────────────────────

    def upload_json(
        self,
        obj: Any,
        *,
        filename: str = "commit.json",
        pin: bool = True,
        sort_keys: bool = True,
    ) -> Tuple[str, str, int]:
        text = _minidumps(obj, sort_keys=sort_keys)
        raw = text.encode("utf-8")
        cid = self._ipfs_upload(raw, filename=filename, pin=pin)
        return cid, _sha256_hex(raw), len(raw)

    def download_json(
        self,
        cid: str,
        *,
        expected_sha256_hex: Optional[str] = None,
    ) -> Tuple[Any, bytes, str]:
        raw = self.download_bytes(cid)
        obj = json.loads(raw.decode("utf-8"))
        norm = _minidumps(obj).encode("utf-8")
        h = _sha256_hex(norm)
        if expected_sha256_hex and h.lower() != expected_sha256_hex.lower():
            raise ValueError(
                f"Hash mismatch for CID {cid}: expected {expected_sha256_hex}, got {h}"
            )
        return obj, norm, h

    def upload_bytes(
        self,
        data: bytes,
        *,
        filename: str = "data.bin",
        pin: bool = True,
    ) -> str:
        return self._ipfs_upload(data, filename=filename, pin=pin)

    def download_bytes(self, cid: str) -> bytes:
        # hippius_sdk.IPFSClient exposes download / cat methods.
        # Try the most common API surface names.
        for method_name in ("cat", "download", "get"):
            fn = getattr(self._ipfs, method_name, None)
            if callable(fn):
                result = fn(cid)
                if isinstance(result, bytes):
                    return result
                if isinstance(result, str):
                    return result.encode("utf-8")
        raise RuntimeError(f"HippiusBackend: unable to download CID {cid}")

    # ── S3 log upload ───────────────────────────────────────────────────

    async def upload_log(
        self,
        *,
        key: str,
        content: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        if self._hippius_client is None:
            return None

        try:
            upload_fn = getattr(self._hippius_client, "s3_upload", None) or getattr(
                self._hippius_client, "upload", None
            )
            if upload_fn is None:
                return None
            result = upload_fn(
                bucket=self._s3_bucket,
                key=key,
                data=content.encode("utf-8"),
                metadata=metadata or {},
            )
            if isinstance(result, str):
                return result
            if isinstance(result, dict):
                return result.get("url") or result.get("key")
        except Exception:
            return None
        return None

    # ── Internal helpers ────────────────────────────────────────────────

    def _ipfs_upload(self, data: bytes, *, filename: str, pin: bool) -> str:
        """Upload bytes via hippius_sdk IPFSClient."""
        for method_name in ("upload", "add", "put"):
            fn = getattr(self._ipfs, method_name, None)
            if callable(fn):
                result = fn(data, filename=filename, pin=pin)
                if isinstance(result, str):
                    return result
                if isinstance(result, dict):
                    cid = result.get("Hash") or result.get("cid") or result.get("Cid")
                    if cid:
                        return str(cid)
        raise RuntimeError("HippiusBackend: unable to upload via IPFSClient")
