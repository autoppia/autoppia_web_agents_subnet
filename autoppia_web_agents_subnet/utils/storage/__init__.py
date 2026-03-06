"""
Storage abstraction layer for IPFS and S3 backends.

Supports switching between standard and Hippius backends via configuration:
  - IPFS: standard IPFS HTTP API  <-->  Hippius IPFS (SN 75)
  - S3:   AWS S3                  <-->  Hippius S3
"""

from __future__ import annotations

import logging
from typing import Optional

from autoppia_web_agents_subnet.utils.storage.base import BaseIPFSClient, BaseS3Client

logger = logging.getLogger(__name__)

# Singleton instances (lazily initialised)
_ipfs_client: Optional[BaseIPFSClient] = None
_s3_client: Optional[BaseS3Client] = None


def get_ipfs_client() -> BaseIPFSClient:
    """Return the configured IPFS client singleton.

    Backend is selected by the STORAGE_IPFS_BACKEND env/config variable:
      - "standard" (default): uses the original IPFS HTTP API
      - "hippius": uses Hippius SDK (SN 75)
    """
    global _ipfs_client
    if _ipfs_client is not None:
        return _ipfs_client

    from autoppia_web_agents_subnet.validator.config import (
        STORAGE_IPFS_BACKEND,
        IPFS_API_URL,
        IPFS_GATEWAYS,
        HIPPIUS_IPFS_API_URL,
        HIPPIUS_KEY,
    )

    backend = (STORAGE_IPFS_BACKEND or "standard").strip().lower()

    if backend == "hippius":
        from autoppia_web_agents_subnet.utils.storage.hippius_ipfs import HippiusIPFSClient
        _ipfs_client = HippiusIPFSClient(
            ipfs_api_url=HIPPIUS_IPFS_API_URL or None,
            hippius_key=HIPPIUS_KEY or None,
        )
        logger.info("IPFS backend: Hippius (SN 75)")
    else:
        from autoppia_web_agents_subnet.utils.storage.standard_ipfs import StandardIPFSClient
        _ipfs_client = StandardIPFSClient(
            api_url=IPFS_API_URL,
            gateways=IPFS_GATEWAYS,
        )
        logger.info("IPFS backend: Standard IPFS HTTP API")

    return _ipfs_client


def get_s3_client() -> BaseS3Client:
    """Return the configured S3 client singleton.

    Backend is selected by the STORAGE_S3_BACKEND env/config variable:
      - "aws" (default): uses AWS S3 via boto3
      - "hippius": uses Hippius S3-compatible storage via MinIO client
    """
    global _s3_client
    if _s3_client is not None:
        return _s3_client

    from autoppia_web_agents_subnet.validator.config import (
        STORAGE_S3_BACKEND,
        AWS_ACCESS_KEY_ID,
        AWS_SECRET_ACCESS_KEY,
        AWS_S3_REGION,
        AWS_S3_ENDPOINT_URL,
        HIPPIUS_S3_ACCESS_KEY,
        HIPPIUS_S3_SECRET_KEY,
        HIPPIUS_S3_ENDPOINT,
        HIPPIUS_S3_REGION,
    )

    backend = (STORAGE_S3_BACKEND or "aws").strip().lower()

    if backend == "hippius":
        from autoppia_web_agents_subnet.utils.storage.hippius_s3 import HippiusS3Client
        _s3_client = HippiusS3Client(
            access_key=HIPPIUS_S3_ACCESS_KEY,
            secret_key=HIPPIUS_S3_SECRET_KEY,
            endpoint=HIPPIUS_S3_ENDPOINT or None,
            region=HIPPIUS_S3_REGION or None,
        )
        logger.info("S3 backend: Hippius S3")
    else:
        from autoppia_web_agents_subnet.utils.storage.aws_s3 import AWSS3Client
        _s3_client = AWSS3Client(
            aws_access_key_id=AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY or None,
            region_name=AWS_S3_REGION or "us-east-1",
            endpoint_url=AWS_S3_ENDPOINT_URL or None,
        )
        logger.info("S3 backend: AWS S3")

    return _s3_client


def reset_clients() -> None:
    """Reset singletons (useful for testing)."""
    global _ipfs_client, _s3_client
    _ipfs_client = None
    _s3_client = None
