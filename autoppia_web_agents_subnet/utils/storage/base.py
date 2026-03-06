"""Abstract base class for storage backends (IPFS + S3)."""
from __future__ import annotations

import abc
from typing import Any, Dict, Optional, Tuple


class StorageBackend(abc.ABC):
    """
    Unified interface for content-addressed storage (IPFS) and object
    storage (S3) operations used across the subnet validator.

    Every concrete backend must implement the IPFS-style methods.
    S3-style methods have default no-op implementations so that
    pure-IPFS backends are not forced to provide them.
    """

    # ── IPFS-style operations ───────────────────────────────────────────

    @abc.abstractmethod
    def upload_json(
        self,
        obj: Any,
        *,
        filename: str = "commit.json",
        pin: bool = True,
        sort_keys: bool = True,
    ) -> Tuple[str, str, int]:
        """
        Serialise *obj* as compact JSON and store it.

        Returns ``(cid, sha256_hex, byte_length)``.
        """

    @abc.abstractmethod
    def download_json(
        self,
        cid: str,
        *,
        expected_sha256_hex: Optional[str] = None,
    ) -> Tuple[Any, bytes, str]:
        """
        Retrieve content by CID and deserialise as JSON.

        Returns ``(obj, normalised_bytes, sha256_hex)``.
        """

    @abc.abstractmethod
    def upload_bytes(
        self,
        data: bytes,
        *,
        filename: str = "data.bin",
        pin: bool = True,
    ) -> str:
        """Store raw bytes and return the CID."""

    @abc.abstractmethod
    def download_bytes(self, cid: str) -> bytes:
        """Retrieve raw bytes by CID."""

    # ── Async wrappers (default: run sync in executor) ──────────────────

    async def upload_json_async(
        self,
        obj: Any,
        *,
        filename: str = "commit.json",
        pin: bool = True,
        sort_keys: bool = True,
    ) -> Tuple[str, str, int]:
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.upload_json(obj, filename=filename, pin=pin, sort_keys=sort_keys),
        )

    async def download_json_async(
        self,
        cid: str,
        *,
        expected_sha256_hex: Optional[str] = None,
    ) -> Tuple[Any, bytes, str]:
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.download_json(cid, expected_sha256_hex=expected_sha256_hex),
        )

    # ── S3 / log operations (optional) ──────────────────────────────────

    async def upload_log(
        self,
        *,
        key: str,
        content: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """
        Upload a text log to object storage (S3).

        Returns the resulting URL/key, or *None* if not supported.
        """
        return None
