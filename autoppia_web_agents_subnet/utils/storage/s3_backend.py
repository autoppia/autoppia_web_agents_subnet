"""StorageBackend that delegates S3/log operations to the existing IWAP client.

IPFS operations are forwarded to the legacy ``ipfs_client`` module so that
the S3 backend can coexist with any IPFS backend transparently.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from autoppia_web_agents_subnet.utils.storage.base import StorageBackend
from autoppia_web_agents_subnet.utils.storage.ipfs_backend import IPFSBackend


class S3IWAPBackend(StorageBackend):
    """Wraps the existing IWAP HTTP API for S3 log uploads.

    IPFS methods are delegated to :class:`IPFSBackend` so that this class
    can be used as a drop-in replacement where both IPFS and S3 are needed.

    Parameters
    ----------
    iwap_client:
        An instance of ``IWAPClient`` (from ``platform.client``) already
        configured with auth headers and base URL.
    ipfs_api_url:
        Forwarded to the embedded :class:`IPFSBackend`.
    ipfs_gateways:
        Forwarded to the embedded :class:`IPFSBackend`.
    """

    def __init__(
        self,
        *,
        iwap_client: Any = None,
        ipfs_api_url: Optional[str] = None,
        ipfs_gateways: Optional[list] = None,
    ) -> None:
        self._iwap_client = iwap_client
        self._ipfs = IPFSBackend(api_url=ipfs_api_url, gateways=ipfs_gateways)

    # ── IPFS (delegated) ────────────────────────────────────────────────

    def upload_json(self, obj: Any, **kw) -> Tuple[str, str, int]:
        return self._ipfs.upload_json(obj, **kw)

    def download_json(self, cid: str, **kw) -> Tuple[Any, bytes, str]:
        return self._ipfs.download_json(cid, **kw)

    def upload_bytes(self, data: bytes, **kw) -> str:
        return self._ipfs.upload_bytes(data, **kw)

    def download_bytes(self, cid: str) -> bytes:
        return self._ipfs.download_bytes(cid)

    # ── S3 via IWAP ─────────────────────────────────────────────────────

    async def upload_log(
        self,
        *,
        key: str,
        content: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """Upload log content via IWAP client's round-log endpoint."""
        if self._iwap_client is None:
            return None
        try:
            url = await self._iwap_client.upload_round_log(
                validator_round_id=metadata.get("validator_round_id", key) if metadata else key,
                content=content,
                season_number=int(metadata["season_number"]) if metadata and "season_number" in metadata else None,
                round_number_in_season=int(metadata["round_number_in_season"]) if metadata and "round_number_in_season" in metadata else None,
                validator_uid=int(metadata["validator_uid"]) if metadata and "validator_uid" in metadata else None,
                validator_hotkey=metadata.get("validator_hotkey") if metadata else None,
            )
            return url
        except Exception:
            return None
