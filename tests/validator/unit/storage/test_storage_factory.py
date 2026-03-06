"""Tests for the storage factory (backend switching via config)."""

import os
import pytest
from unittest.mock import patch, MagicMock

# Ensure validator config env vars are set before importing config
os.environ.setdefault("VALIDATOR_NAME", "test-factory-validator")
os.environ.setdefault("VALIDATOR_IMAGE", "https://example.com/test.png")

import autoppia_web_agents_subnet.validator.config as cfg
from autoppia_web_agents_subnet.utils.storage import (
    get_ipfs_client,
    get_s3_client,
    reset_clients,
)
from autoppia_web_agents_subnet.utils.storage.base import BaseIPFSClient, BaseS3Client


@pytest.fixture(autouse=True)
def clean_singletons():
    """Reset storage singletons before each test."""
    reset_clients()
    yield
    reset_clients()


@pytest.mark.unit
class TestIPFSFactory:
    """Test IPFS backend factory."""

    def test_default_backend_is_standard(self):
        """Test that the default IPFS backend is 'standard'."""
        orig = cfg.STORAGE_IPFS_BACKEND
        try:
            cfg.STORAGE_IPFS_BACKEND = "standard"
            client = get_ipfs_client()
            assert isinstance(client, BaseIPFSClient)
            from autoppia_web_agents_subnet.utils.storage.standard_ipfs import StandardIPFSClient
            assert isinstance(client, StandardIPFSClient)
        finally:
            cfg.STORAGE_IPFS_BACKEND = orig

    def test_hippius_backend(self):
        """Test that setting 'hippius' returns HippiusIPFSClient."""
        orig_backend = cfg.STORAGE_IPFS_BACKEND
        orig_url = cfg.HIPPIUS_IPFS_API_URL
        orig_key = cfg.HIPPIUS_KEY
        try:
            cfg.STORAGE_IPFS_BACKEND = "hippius"
            cfg.HIPPIUS_IPFS_API_URL = "http://localhost:5001"
            cfg.HIPPIUS_KEY = "test-key"

            with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs._HAVE_HIPPIUS", True):
                with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs.HippiusClient"):
                    client = get_ipfs_client()
                    assert isinstance(client, BaseIPFSClient)
                    from autoppia_web_agents_subnet.utils.storage.hippius_ipfs import HippiusIPFSClient
                    assert isinstance(client, HippiusIPFSClient)
        finally:
            cfg.STORAGE_IPFS_BACKEND = orig_backend
            cfg.HIPPIUS_IPFS_API_URL = orig_url
            cfg.HIPPIUS_KEY = orig_key

    def test_singleton_returns_same_instance(self):
        """Test that get_ipfs_client returns the same singleton."""
        orig = cfg.STORAGE_IPFS_BACKEND
        try:
            cfg.STORAGE_IPFS_BACKEND = "standard"
            client1 = get_ipfs_client()
            client2 = get_ipfs_client()
            assert client1 is client2
        finally:
            cfg.STORAGE_IPFS_BACKEND = orig


@pytest.mark.unit
class TestS3Factory:
    """Test S3 backend factory."""

    def test_default_backend_is_aws(self):
        """Test that the default S3 backend is 'aws'."""
        orig = cfg.STORAGE_S3_BACKEND
        try:
            cfg.STORAGE_S3_BACKEND = "aws"
            with patch("autoppia_web_agents_subnet.utils.storage.aws_s3._HAVE_BOTO3", True):
                with patch("autoppia_web_agents_subnet.utils.storage.aws_s3.boto3") as mock_boto3:
                    mock_boto3.client.return_value = MagicMock()
                    client = get_s3_client()
                    assert isinstance(client, BaseS3Client)
                    from autoppia_web_agents_subnet.utils.storage.aws_s3 import AWSS3Client
                    assert isinstance(client, AWSS3Client)
        finally:
            cfg.STORAGE_S3_BACKEND = orig

    def test_hippius_s3_backend(self):
        """Test that setting 'hippius' returns HippiusS3Client."""
        orig_backend = cfg.STORAGE_S3_BACKEND
        orig_ak = cfg.HIPPIUS_S3_ACCESS_KEY
        orig_sk = cfg.HIPPIUS_S3_SECRET_KEY
        try:
            cfg.STORAGE_S3_BACKEND = "hippius"
            cfg.HIPPIUS_S3_ACCESS_KEY = "hip_test"
            cfg.HIPPIUS_S3_SECRET_KEY = "secret"

            with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3._HAVE_MINIO", True):
                with patch("autoppia_web_agents_subnet.utils.storage.hippius_s3.Minio"):
                    client = get_s3_client()
                    assert isinstance(client, BaseS3Client)
                    from autoppia_web_agents_subnet.utils.storage.hippius_s3 import HippiusS3Client
                    assert isinstance(client, HippiusS3Client)
        finally:
            cfg.STORAGE_S3_BACKEND = orig_backend
            cfg.HIPPIUS_S3_ACCESS_KEY = orig_ak
            cfg.HIPPIUS_S3_SECRET_KEY = orig_sk
