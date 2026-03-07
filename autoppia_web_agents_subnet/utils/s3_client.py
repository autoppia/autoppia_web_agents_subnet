"""Hippius S3-compatible storage client for evaluation datasets.

All uploads are fire-and-forget — callers wrap calls in try/except and
failures are logged, never propagated.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class S3Error(Exception):
    pass


# Singleton — lazily initialised on first use.
_state: dict[str, Any] = {"client": None}


def _get_s3_client():
    """Return a cached boto3 S3 client configured for Hippius endpoint."""
    if _state["client"] is not None:
        return _state["client"]

    try:
        import boto3  # type: ignore[import-untyped]
    except ImportError as exc:
        raise S3Error("boto3 package not installed — run: pip install boto3") from exc

    from autoppia_web_agents_subnet.validator.config import (
        HIPPIUS_S3_ENDPOINT,
        HIPPIUS_S3_ACCESS_KEY,
        HIPPIUS_S3_SECRET_KEY,
    )

    if not HIPPIUS_S3_ACCESS_KEY or not HIPPIUS_S3_SECRET_KEY:
        raise S3Error("HIPPIUS_S3_ACCESS_KEY and HIPPIUS_S3_SECRET_KEY must be set")

    _state["client"] = boto3.client(
        "s3",
        endpoint_url=HIPPIUS_S3_ENDPOINT,
        aws_access_key_id=HIPPIUS_S3_ACCESS_KEY,
        aws_secret_access_key=HIPPIUS_S3_SECRET_KEY,
    )
    logger.info("Hippius S3 client initialised: endpoint=%s", HIPPIUS_S3_ENDPOINT)
    return _state["client"]


def reset_client() -> None:
    """Clear the cached client (useful for tests)."""
    _state["client"] = None


def is_configured() -> bool:
    """Return True when S3 uploads are enabled and all required credentials are set."""
    from autoppia_web_agents_subnet.validator.config import (
        HIPPIUS_S3_ENABLED,
        HIPPIUS_S3_ENDPOINT,
        HIPPIUS_S3_ACCESS_KEY,
        HIPPIUS_S3_SECRET_KEY,
    )

    return bool(
        HIPPIUS_S3_ENABLED
        and HIPPIUS_S3_ENDPOINT
        and HIPPIUS_S3_ACCESS_KEY
        and HIPPIUS_S3_SECRET_KEY
    )


def _sanitize_key_segment(value: str, max_len: int = 80) -> str:
    """Sanitize a value for use in an S3 key (replace unsafe chars, truncate)."""
    return value.replace("/", "_").replace(" ", "_").replace("..", "_")[:max_len]


async def s3_upload_json_async(
    obj: Any,
    *,
    key: str,
    bucket: Optional[str] = None,
) -> str:
    """Serialize *obj* as JSON and upload to S3.  Returns the S3 key."""
    from autoppia_web_agents_subnet.validator.config import HIPPIUS_S3_BUCKET

    bucket = bucket or HIPPIUS_S3_BUCKET
    data = json.dumps(
        obj, separators=(",", ":"), ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: _get_s3_client().put_object(
            Bucket=bucket, Key=key, Body=data, ContentType="application/json"
        ),
    )
    logger.info("S3 upload: %s (%d bytes)", key, len(data))
    return key


async def s3_upload_bytes_async(
    data: bytes,
    *,
    key: str,
    content_type: str = "application/octet-stream",
    bucket: Optional[str] = None,
) -> str:
    """Upload raw bytes to S3.  Returns the S3 key."""
    from autoppia_web_agents_subnet.validator.config import HIPPIUS_S3_BUCKET

    bucket = bucket or HIPPIUS_S3_BUCKET
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: _get_s3_client().put_object(
            Bucket=bucket, Key=key, Body=data, ContentType=content_type
        ),
    )
    logger.info("S3 upload: %s (%d bytes)", key, len(data))
    return key


async def upload_evaluation_metadata_async(
    *,
    round_id: str,
    validator_uid: int,
    miner_uid: int,
    metadata: dict,
    task_id: Optional[str] = None,
) -> Optional[str]:
    """Upload evaluation metadata JSON to S3.

    No-op when S3 is not configured.  Errors are caught and logged.
    """
    if not is_configured():
        return None

    safe_task = _sanitize_key_segment(task_id) if task_id else "unknown"
    key = (
        f"evaluations/{_sanitize_key_segment(round_id)}"
        f"/v{validator_uid}/m{miner_uid}/metadata_{safe_task}.json"
    )

    try:
        return await s3_upload_json_async(metadata, key=key)
    except Exception as exc:
        logger.warning("S3 metadata upload failed (%s): %s", key, exc)
        return None


async def upload_evaluation_gif_async(
    *,
    round_id: str,
    validator_uid: int,
    miner_uid: int,
    gif_data: bytes,
    task_id: Optional[str] = None,
) -> Optional[str]:
    """Upload evaluation GIF to S3.

    No-op when S3 is not configured.  Errors are caught and logged.
    """
    if not is_configured():
        return None

    safe_task = _sanitize_key_segment(task_id) if task_id else "unknown"
    key = (
        f"evaluations/{_sanitize_key_segment(round_id)}"
        f"/v{validator_uid}/m{miner_uid}/recording_{safe_task}.gif"
    )

    try:
        return await s3_upload_bytes_async(gif_data, key=key, content_type="image/gif")
    except Exception as exc:
        logger.warning("S3 GIF upload failed (%s): %s", key, exc)
        return None
