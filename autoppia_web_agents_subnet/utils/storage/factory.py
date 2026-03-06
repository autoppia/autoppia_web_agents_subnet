"""Factory for creating the configured storage backend at runtime."""
from __future__ import annotations

import os
from typing import Any, Optional

from autoppia_web_agents_subnet.utils.storage.base import StorageBackend


def get_storage_backend(
    *,
    override: Optional[str] = None,
    ipfs_api_url: Optional[str] = None,
    ipfs_gateways: Optional[list] = None,
    hippius_ipfs_api_url: Optional[str] = None,
    hippius_api_key: Optional[str] = None,
    hippius_s3_bucket: Optional[str] = None,
) -> StorageBackend:
    """Return the storage backend selected by configuration.

    Priority:
    1. *override* parameter (for tests / programmatic use)
    2. ``STORAGE_BACKEND`` environment variable
    3. Falls back to ``"ipfs"``

    Supported values: ``"ipfs"`` | ``"hippius"``
    """
    backend_name = (override or os.getenv("STORAGE_BACKEND", "ipfs")).strip().lower()

    if backend_name == "hippius":
        from autoppia_web_agents_subnet.utils.storage.hippius_backend import HippiusBackend

        _hippius_url = hippius_ipfs_api_url or os.getenv("HIPPIUS_IPFS_API_URL", "")
        _hippius_key = hippius_api_key or os.getenv("HIPPIUS_API_KEY", "")
        _hippius_bucket = hippius_s3_bucket or os.getenv("HIPPIUS_S3_BUCKET", "autoppia-logs")

        return HippiusBackend(
            ipfs_api_url=_hippius_url or None,
            api_key=_hippius_key or None,
            s3_bucket=_hippius_bucket,
        )

    # Default: legacy IPFS backend
    from autoppia_web_agents_subnet.utils.storage.ipfs_backend import IPFSBackend

    _api_url = ipfs_api_url
    _gateways = ipfs_gateways
    if _api_url is None:
        try:
            from autoppia_web_agents_subnet.validator.config import IPFS_API_URL

            _api_url = IPFS_API_URL
        except Exception:
            pass
    if _gateways is None:
        try:
            from autoppia_web_agents_subnet.validator.config import IPFS_GATEWAYS

            _gateways = IPFS_GATEWAYS
        except Exception:
            pass

    return IPFSBackend(api_url=_api_url, gateways=_gateways)


def get_s3_backend(
    *,
    override: Optional[str] = None,
    iwap_client: Any = None,
    hippius_api_key: Optional[str] = None,
    hippius_s3_bucket: Optional[str] = None,
) -> StorageBackend:
    """Return the S3/log-upload backend selected by configuration.

    Priority:
    1. *override* parameter
    2. ``S3_BACKEND`` environment variable
    3. Falls back to ``"iwap"``

    Supported values: ``"iwap"`` | ``"hippius"``
    """
    backend_name = (override or os.getenv("S3_BACKEND", "iwap")).strip().lower()

    if backend_name == "hippius":
        from autoppia_web_agents_subnet.utils.storage.hippius_backend import HippiusBackend

        _hippius_key = hippius_api_key or os.getenv("HIPPIUS_API_KEY", "")
        _hippius_bucket = hippius_s3_bucket or os.getenv("HIPPIUS_S3_BUCKET", "autoppia-logs")
        _hippius_url = os.getenv("HIPPIUS_IPFS_API_URL", "")

        return HippiusBackend(
            ipfs_api_url=_hippius_url or None,
            api_key=_hippius_key or None,
            s3_bucket=_hippius_bucket,
        )

    # Default: IWAP S3 backend
    from autoppia_web_agents_subnet.utils.storage.s3_backend import S3IWAPBackend

    return S3IWAPBackend(iwap_client=iwap_client)
