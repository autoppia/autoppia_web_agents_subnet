"""AWS S3 storage backend using boto3."""

from __future__ import annotations

import io
import json
from typing import Any, Optional

from autoppia_web_agents_subnet.utils.storage.base import BaseS3Client

try:
    import boto3  # type: ignore
    from botocore.exceptions import ClientError  # type: ignore
    _HAVE_BOTO3 = True
except Exception:  # pragma: no cover
    boto3 = None  # type: ignore
    ClientError = Exception  # type: ignore
    _HAVE_BOTO3 = False


class AWSS3Error(Exception):
    pass


class AWSS3Client(BaseS3Client):
    """S3 client that uses AWS S3 via boto3."""

    def __init__(
        self,
        *,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        region_name: str = "us-east-1",
        endpoint_url: Optional[str] = None,
    ) -> None:
        if not _HAVE_BOTO3:
            raise AWSS3Error(
                "boto3 is required for AWS S3 backend. "
                "Install it with: pip install boto3"
            )
        kwargs: dict = {"region_name": region_name}
        if aws_access_key_id:
            kwargs["aws_access_key_id"] = aws_access_key_id
        if aws_secret_access_key:
            kwargs["aws_secret_access_key"] = aws_secret_access_key
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        self._client = boto3.client("s3", **kwargs)
        self._region = region_name

    def upload_bytes(
        self,
        data: bytes,
        *,
        bucket: str,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        self._client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return f"s3://{bucket}/{key}"

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
        resp = self._client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()

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
        resp = self._client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        results = []
        for obj in resp.get("Contents", []):
            results.append({"key": obj["Key"], "size": obj["Size"]})
        return results

    def ensure_bucket(self, bucket: str) -> None:
        try:
            self._client.head_bucket(Bucket=bucket)
        except ClientError:
            create_kwargs: dict = {"Bucket": bucket}
            if self._region and self._region != "us-east-1":
                create_kwargs["CreateBucketConfiguration"] = {
                    "LocationConstraint": self._region
                }
            self._client.create_bucket(**create_kwargs)
