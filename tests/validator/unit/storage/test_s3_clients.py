"""Tests for AWS S3 and Hippius S3 clients."""

import json
import io
import pytest
from unittest.mock import patch, Mock, MagicMock

from autoppia_web_agents_subnet.utils.storage.aws_s3 import AWSS3Client, AWSS3Error
from autoppia_web_agents_subnet.utils.storage.hippius_s3 import HippiusS3Client, HippiusS3Error


@pytest.mark.unit
class TestAWSS3Client:
    """Test AWS S3 client."""

    def test_init_raises_without_boto3(self):
        """Test that init raises if boto3 is not installed."""
        with patch("autoppia_web_agents_subnet.utils.storage.aws_s3._HAVE_BOTO3", False):
            with pytest.raises(AWSS3Error, match="boto3 is required"):
                AWSS3Client()

    def test_upload_bytes(self):
        """Test uploading bytes to S3."""
        mock_boto = MagicMock()
        with patch("autoppia_web_agents_subnet.utils.storage.aws_s3._HAVE_BOTO3", True):
            with patch("autoppia_web_agents_subnet.utils.storage.aws_s3.boto3") as mock_boto3:
                mock_client = MagicMock()
                mock_boto3.client.return_value = mock_client

                client = AWSS3Client(
                    aws_access_key_id="test",
                    aws_secret_access_key="test",
                )

                result = client.upload_bytes(
                    b"test data",
                    bucket="test-bucket",
                    key="test/file.bin",
                )

                assert result == "s3://test-bucket/test/file.bin"
                mock_client.put_object.assert_called_once()

    def test_upload_json(self):
        """Test uploading JSON to S3."""
        with patch("autoppia_web_agents_subnet.utils.storage.aws_s3._HAVE_BOTO3", True):
            with patch("autoppia_web_agents_subnet.utils.storage.aws_s3.boto3") as mock_boto3:
                mock_client = MagicMock()
                mock_boto3.client.return_value = mock_client

                client = AWSS3Client()
                result = client.upload_json(
                    {"key": "value"},
                    bucket="test-bucket",
                    key="test/data.json",
                )

                assert "test-bucket" in result
                mock_client.put_object.assert_called_once()
                call_kwargs = mock_client.put_object.call_args[1]
                assert call_kwargs["ContentType"] == "application/json"

    def test_download_bytes(self):
        """Test downloading bytes from S3."""
        with patch("autoppia_web_agents_subnet.utils.storage.aws_s3._HAVE_BOTO3", True):
            with patch("autoppia_web_agents_subnet.utils.storage.aws_s3.boto3") as mock_boto3:
                mock_client = MagicMock()
                mock_boto3.client.return_value = mock_client

                mock_body = MagicMock()
                mock_body.read.return_value = b"downloaded data"
                mock_client.get_object.return_value = {"Body": mock_body}

                client = AWSS3Client()
                data = client.download_bytes(bucket="test-bucket", key="test/file.bin")

                assert data == b"downloaded data"

    def test_download_json(self):
        """Test downloading JSON from S3."""
        with patch("autoppia_web_agents_subnet.utils.storage.aws_s3._HAVE_BOTO3", True):
            with patch("autoppia_web_agents_subnet.utils.storage.aws_s3.boto3") as mock_boto3:
                mock_client = MagicMock()
                mock_boto3.client.return_value = mock_client

                obj = {"key": "value"}
                mock_body = MagicMock()
                mock_body.read.return_value = json.dumps(obj).encode("utf-8")
                mock_client.get_object.return_value = {"Body": mock_body}

                client = AWSS3Client()
                result = client.download_json(bucket="test-bucket", key="test.json")

                assert result == obj

    def test_list_objects(self):
        """Test listing objects in S3."""
        with patch("autoppia_web_agents_subnet.utils.storage.aws_s3._HAVE_BOTO3", True):
            with patch("autoppia_web_agents_subnet.utils.storage.aws_s3.boto3") as mock_boto3:
                mock_client = MagicMock()
                mock_boto3.client.return_value = mock_client

                mock_client.list_objects_v2.return_value = {
                    "Contents": [
                        {"Key": "file1.json", "Size": 100},
                        {"Key": "file2.json", "Size": 200},
                    ]
                }

                client = AWSS3Client()
                objects = client.list_objects(bucket="test-bucket", prefix="prefix/")

                assert len(objects) == 2
                assert objects[0]["key"] == "file1.json"
                assert objects[1]["size"] == 200

    def test_ensure_bucket_creates_if_not_exists(self):
        """Test that ensure_bucket creates the bucket if it doesn't exist."""
        with patch("autoppia_web_agents_subnet.utils.storage.aws_s3._HAVE_BOTO3", True):
            with patch("autoppia_web_agents_subnet.utils.storage.aws_s3.boto3") as mock_boto3:
                mock_client = MagicMock()
                mock_boto3.client.return_value = mock_client

                # Use the ClientError class from aws_s3 module (which falls back
                # to Exception when botocore is not installed)
                from autoppia_web_agents_subnet.utils.storage.aws_s3 import ClientError as CE
                mock_client.head_bucket.side_effect = CE(
                    {"Error": {"Code": "404"}}, "HeadBucket"
                ) if CE is not Exception else Exception("Not found")

                client = AWSS3Client()
                client.ensure_bucket("new-bucket")

                mock_client.create_bucket.assert_called_once()


@pytest.mark.unit
class TestHippiusS3Client:
    """Test Hippius S3 client."""

    def test_init_raises_without_minio(self):
        """Test that init raises if minio is not installed."""
        with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3._HAVE_MINIO", False):
            with pytest.raises(HippiusS3Error, match="minio is required"):
                HippiusS3Client(access_key="test", secret_key="test")

    def test_default_endpoint(self):
        """Test that default endpoint is s3.hippius.com."""
        with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3._HAVE_MINIO", True):
            with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3.Minio") as mock_minio:
                client = HippiusS3Client(access_key="test", secret_key="test")
                mock_minio.assert_called_once_with(
                    "s3.hippius.com",
                    access_key="test",
                    secret_key="test",
                    secure=True,
                    region="decentralized",
                )

    def test_upload_bytes(self):
        """Test uploading bytes via Hippius S3."""
        with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3._HAVE_MINIO", True):
            with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3.Minio") as mock_minio:
                mock_client = MagicMock()
                mock_minio.return_value = mock_client

                client = HippiusS3Client(access_key="test", secret_key="test")
                result = client.upload_bytes(
                    b"test data",
                    bucket="test-bucket",
                    key="test/file.bin",
                )

                assert "s3.hippius.com" in result
                assert "test-bucket" in result
                mock_client.put_object.assert_called_once()

    def test_upload_json(self):
        """Test uploading JSON via Hippius S3."""
        with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3._HAVE_MINIO", True):
            with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3.Minio") as mock_minio:
                mock_client = MagicMock()
                mock_minio.return_value = mock_client

                client = HippiusS3Client(access_key="test", secret_key="test")
                result = client.upload_json(
                    {"key": "value"},
                    bucket="test-bucket",
                    key="test/data.json",
                )

                assert "test-bucket" in result
                mock_client.put_object.assert_called_once()

    def test_download_bytes(self):
        """Test downloading bytes via Hippius S3."""
        with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3._HAVE_MINIO", True):
            with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3.Minio") as mock_minio:
                mock_client = MagicMock()
                mock_minio.return_value = mock_client

                mock_response = MagicMock()
                mock_response.read.return_value = b"downloaded data"
                mock_client.get_object.return_value = mock_response

                client = HippiusS3Client(access_key="test", secret_key="test")
                data = client.download_bytes(bucket="test-bucket", key="test/file.bin")

                assert data == b"downloaded data"
                mock_response.close.assert_called_once()
                mock_response.release_conn.assert_called_once()

    def test_list_objects(self):
        """Test listing objects via Hippius S3."""
        with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3._HAVE_MINIO", True):
            with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3.Minio") as mock_minio:
                mock_client = MagicMock()
                mock_minio.return_value = mock_client

                mock_obj1 = MagicMock()
                mock_obj1.object_name = "file1.json"
                mock_obj1.size = 100
                mock_obj2 = MagicMock()
                mock_obj2.object_name = "file2.json"
                mock_obj2.size = 200

                mock_client.list_objects.return_value = [mock_obj1, mock_obj2]

                client = HippiusS3Client(access_key="test", secret_key="test")
                objects = client.list_objects(bucket="test-bucket")

                assert len(objects) == 2
                assert objects[0]["key"] == "file1.json"

    def test_ensure_bucket_creates_if_not_exists(self):
        """Test that ensure_bucket creates if not exists."""
        with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3._HAVE_MINIO", True):
            with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3.Minio") as mock_minio:
                mock_client = MagicMock()
                mock_minio.return_value = mock_client
                mock_client.bucket_exists.return_value = False

                client = HippiusS3Client(access_key="test", secret_key="test")
                client.ensure_bucket("new-bucket")

                mock_client.make_bucket.assert_called_once_with("new-bucket")
