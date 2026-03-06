"""Abstract base classes for storage backends (IPFS and S3)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional, Sequence, Tuple


class BaseIPFSClient(ABC):
    """Abstract interface for IPFS storage backends."""

    @abstractmethod
    def add_bytes(
        self,
        data: bytes,
        *,
        filename: str = "commit.json",
        pin: bool = True,
    ) -> str:
        """Upload raw bytes. Returns the CID."""

    @abstractmethod
    def add_json(
        self,
        obj: Any,
        *,
        filename: str = "commit.json",
        pin: bool = True,
        sort_keys: bool = True,
    ) -> Tuple[str, str, int]:
        """Upload a JSON-serialisable object. Returns (CID, sha256_hex, byte_len)."""

    @abstractmethod
    def cat(
        self,
        cid: str,
        *,
        timeout: float = 20.0,
    ) -> bytes:
        """Download raw bytes by CID."""

    @abstractmethod
    def get_json(
        self,
        cid: str,
        *,
        expected_sha256_hex: Optional[str] = None,
    ) -> Tuple[Any, bytes, str]:
        """Download and parse JSON. Returns (obj, normalised_bytes, sha256_hex)."""


class BaseS3Client(ABC):
    """Abstract interface for S3-compatible storage backends."""

    @abstractmethod
    def upload_bytes(
        self,
        data: bytes,
        *,
        bucket: str,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload raw bytes to a bucket/key. Returns the object URL or key."""

    @abstractmethod
    def upload_json(
        self,
        obj: Any,
        *,
        bucket: str,
        key: str,
    ) -> str:
        """Upload a JSON object. Returns the object URL or key."""

    @abstractmethod
    def download_bytes(
        self,
        *,
        bucket: str,
        key: str,
    ) -> bytes:
        """Download raw bytes from a bucket/key."""

    @abstractmethod
    def download_json(
        self,
        *,
        bucket: str,
        key: str,
    ) -> Any:
        """Download and parse JSON from a bucket/key."""

    @abstractmethod
    def list_objects(
        self,
        *,
        bucket: str,
        prefix: str = "",
    ) -> list[dict]:
        """List objects in a bucket with an optional prefix. Returns list of dicts with 'key' and 'size'."""

    @abstractmethod
    def ensure_bucket(self, bucket: str) -> None:
        """Create the bucket if it does not exist."""
