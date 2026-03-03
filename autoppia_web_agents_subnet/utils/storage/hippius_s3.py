"""Hippius S3-compatible storage backend using the MinIO client."""

from __future__ import annotations

import io
import json
from typing import Any, Optional

from autoppia_web_agents_subnet.utils.storage.base import BaseS3Client

try:
    from minio import Minio  # type: ignore
    from minio.error import S3Error  # type: ignore
    _HAVE_MINIO = True
except Exception:  # pragma: no cover
    Minio = None  # type: ignore
    S3Error = Exception  # type: ignore
    _HAVE_MINIO = False


class HippiusS3Error(Exception):
    pass


class HippiusS3Client(BaseS3Client):
    """S3 client that uses Hippius S3-compatible storage via MinIO client."""

    # Default Hippius S3 endpoint
    DEFAULT_ENDPOINT = "s3.hippius.com"
    DEFAULT_REGION = "decentralized"

    def __init__(
        self,
        *,
        access_key: str,
        secret_key: str,
        endpoint: Optional[str] = None,
        region: Optional[str] = None,
        secure: bool = True,
    ) -> None:
        if not _HAVE_MINIO:
            raise HippiusS3Error(
                "minio is required for Hippius S3 backend. "
                "Install it with: pip install minio"
            )
        self._endpoint = endpoint or self.DEFAULT_ENDPOINT
        self._region = region or self.DEFAULT_REGION
        self._client = Minio(
            self._endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=self._region,
        )

    def upload_bytes(
        self,
        data: bytes,
        *,
        bucket: str,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        stream = io.BytesIO(data)
        self._client.put_object(
            bucket,
            key,
            stream,
            length=len(data),
            content_type=content_type,
        )
        return f"s3://{self._endpoint}/{bucket}/{key}"

    def upload_json(
        self,
        obj: Any,
        *,
        bucket: str,
        key: str,
    ) -> str:
        data = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        return self.upload_bytes(
            data, bucket=bucket, key=key, content_type="application/json"
        )

    def download_bytes(
        self,
        *,
        bucket: str,
        key: str,
    ) -> bytes:
        response = self._client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def download_json(
        self,
        *,
        bucket: str,
        key: str,
    ) -> Any:
        raw = self.download_bytes(bucket=bucket, key=key)
        return json.loads(raw.decode("utf-8"))

    def list_objects(
        self,
        *,
        bucket: str,
        prefix: str = "",
    ) -> list[dict]:
        results = []
        objects = self._client.list_objects(bucket, prefix=prefix, recursive=True)
        for obj in objects:
            results.append({"key": obj.object_name, "size": obj.size})
        return results

    def ensure_bucket(self, bucket: str) -> None:
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)
