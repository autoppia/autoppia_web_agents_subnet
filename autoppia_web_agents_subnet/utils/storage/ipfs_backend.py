"""StorageBackend that wraps the existing ``ipfs_client`` module."""
from __future__ import annotations

from typing import Any, Optional, Sequence, Tuple

from autoppia_web_agents_subnet.utils.ipfs_client import (
    ipfs_add_bytes,
    ipfs_add_json,
    ipfs_cat,
    ipfs_get_json,
)
from autoppia_web_agents_subnet.utils.storage.base import StorageBackend


class IPFSBackend(StorageBackend):
    """Thin wrapper around the legacy IPFS HTTP-API helpers."""

    def __init__(
        self,
        *,
        api_url: Optional[str] = None,
        gateways: Optional[Sequence[str]] = None,
    ) -> None:
        self._api_url = api_url
        self._gateways = list(gateways) if gateways else None

    # ── IPFS operations ─────────────────────────────────────────────────

    def upload_json(
        self,
        obj: Any,
        *,
        filename: str = "commit.json",
        pin: bool = True,
        sort_keys: bool = True,
    ) -> Tuple[str, str, int]:
        return ipfs_add_json(
            obj,
            filename=filename,
            api_url=self._api_url,
            pin=pin,
            sort_keys=sort_keys,
        )

    def download_json(
        self,
        cid: str,
        *,
        expected_sha256_hex: Optional[str] = None,
    ) -> Tuple[Any, bytes, str]:
        return ipfs_get_json(
            cid,
            api_url=self._api_url,
            gateways=self._gateways,
            expected_sha256_hex=expected_sha256_hex,
        )

    def upload_bytes(
        self,
        data: bytes,
        *,
        filename: str = "data.bin",
        pin: bool = True,
    ) -> str:
        return ipfs_add_bytes(
            data,
            filename=filename,
            api_url=self._api_url,
            pin=pin,
        )

    def download_bytes(self, cid: str) -> bytes:
        return ipfs_cat(
            cid,
            api_url=self._api_url,
            gateways=self._gateways,
        )
