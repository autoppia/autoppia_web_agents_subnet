"""Tests for the pluggable storage backend abstraction layer."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from autoppia_web_agents_subnet.utils.storage.base import StorageBackend
from autoppia_web_agents_subnet.utils.storage.ipfs_backend import IPFSBackend
from autoppia_web_agents_subnet.utils.storage.s3_backend import S3IWAPBackend
from autoppia_web_agents_subnet.utils.storage.factory import get_storage_backend, get_s3_backend


# ═══════════════════════════════════════════════════════════════════════════
# StorageBackend ABC
# ═══════════════════════════════════════════════════════════════════════════


class TestStorageBackendABC:
    """Verify the abstract base class enforces the required interface."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            StorageBackend()

    def test_concrete_subclass_must_implement_methods(self):
        class Incomplete(StorageBackend):
            pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_concrete_subclass_works(self):
        class Dummy(StorageBackend):
            def upload_json(self, obj, **kw):
                return ("cid", "hash", 0)

            def download_json(self, cid, **kw):
                return ({}, b"", "hash")

            def upload_bytes(self, data, **kw):
                return "cid"

            def download_bytes(self, cid):
                return b""

        d = Dummy()
        assert d.upload_json({}) == ("cid", "hash", 0)

    @pytest.mark.asyncio
    async def test_upload_log_default_returns_none(self):
        class Dummy(StorageBackend):
            def upload_json(self, obj, **kw):
                return ("cid", "hash", 0)

            def download_json(self, cid, **kw):
                return ({}, b"", "hash")

            def upload_bytes(self, data, **kw):
                return "cid"

            def download_bytes(self, cid):
                return b""

        d = Dummy()
        result = await d.upload_log(key="k", content="c")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# IPFSBackend
# ═══════════════════════════════════════════════════════════════════════════


class TestIPFSBackend:
    """Verify IPFSBackend correctly delegates to ipfs_client functions."""

    @patch("autoppia_web_agents_subnet.utils.storage.ipfs_backend.ipfs_add_json")
    def test_upload_json_delegates(self, mock_add):
        mock_add.return_value = ("bafyabc", "deadbeef", 42)
        backend = IPFSBackend(api_url="http://test:5001/api/v0")
        cid, sha, size = backend.upload_json({"hello": "world"}, filename="test.json")
        assert cid == "bafyabc"
        assert sha == "deadbeef"
        assert size == 42
        mock_add.assert_called_once()
        call_kwargs = mock_add.call_args
        assert call_kwargs[1]["api_url"] == "http://test:5001/api/v0"

    @patch("autoppia_web_agents_subnet.utils.storage.ipfs_backend.ipfs_get_json")
    def test_download_json_delegates(self, mock_get):
        mock_get.return_value = ({"data": 1}, b'{"data":1}', "abc123")
        backend = IPFSBackend(api_url="http://test:5001/api/v0")
        obj, raw, h = backend.download_json("bafyxyz")
        assert obj == {"data": 1}
        mock_get.assert_called_once()

    @patch("autoppia_web_agents_subnet.utils.storage.ipfs_backend.ipfs_add_bytes")
    def test_upload_bytes_delegates(self, mock_add):
        mock_add.return_value = "bafybytes"
        backend = IPFSBackend()
        cid = backend.upload_bytes(b"raw data")
        assert cid == "bafybytes"
        mock_add.assert_called_once()

    @patch("autoppia_web_agents_subnet.utils.storage.ipfs_backend.ipfs_cat")
    def test_download_bytes_delegates(self, mock_cat):
        mock_cat.return_value = b"content"
        backend = IPFSBackend()
        data = backend.download_bytes("bafycid")
        assert data == b"content"
        mock_cat.assert_called_once()

    @pytest.mark.asyncio
    @patch("autoppia_web_agents_subnet.utils.storage.ipfs_backend.ipfs_add_json")
    async def test_upload_json_async(self, mock_add):
        mock_add.return_value = ("bafyasync", "hash", 10)
        backend = IPFSBackend()
        cid, sha, size = await backend.upload_json_async({"async": True})
        assert cid == "bafyasync"


# ═══════════════════════════════════════════════════════════════════════════
# HippiusBackend (mocked SDK)
# ═══════════════════════════════════════════════════════════════════════════


class TestHippiusBackend:
    """Test HippiusBackend with a fully mocked hippius_sdk."""

    def _make_backend(self, *, ipfs_client_mock=None, hippius_client_mock=None):
        """Create a HippiusBackend with mocked SDK classes."""
        mock_ipfs = ipfs_client_mock or MagicMock()
        mock_hippius = hippius_client_mock

        with patch.dict("sys.modules", {
            "hippius_sdk": MagicMock(
                IPFSClient=MagicMock(return_value=mock_ipfs),
                HippiusClient=MagicMock(return_value=mock_hippius) if mock_hippius else MagicMock(side_effect=Exception),
            ),
        }):
            from autoppia_web_agents_subnet.utils.storage.hippius_backend import HippiusBackend
            backend = HippiusBackend(ipfs_api_url="http://hippius:5001", api_key="test-key")

        backend._ipfs = mock_ipfs
        if mock_hippius:
            backend._hippius_client = mock_hippius
        return backend

    def test_upload_json(self):
        mock_ipfs = MagicMock()
        mock_ipfs.upload = MagicMock(return_value="bafyhippius123")
        backend = self._make_backend(ipfs_client_mock=mock_ipfs)
        cid, sha, size = backend.upload_json({"key": "value"})
        assert cid == "bafyhippius123"
        assert isinstance(sha, str) and len(sha) == 64
        assert size > 0
        mock_ipfs.upload.assert_called_once()

    def test_download_json(self):
        mock_ipfs = MagicMock()
        payload = json.dumps({"result": 42}, separators=(",", ":"), sort_keys=True)
        mock_ipfs.cat = MagicMock(return_value=payload.encode("utf-8"))
        backend = self._make_backend(ipfs_client_mock=mock_ipfs)
        obj, raw, h = backend.download_json("bafytest")
        assert obj == {"result": 42}
        mock_ipfs.cat.assert_called_once_with("bafytest")

    def test_upload_bytes(self):
        mock_ipfs = MagicMock()
        mock_ipfs.upload = MagicMock(return_value="bafybytescid")
        backend = self._make_backend(ipfs_client_mock=mock_ipfs)
        cid = backend.upload_bytes(b"hello hippius")
        assert cid == "bafybytescid"

    def test_download_bytes(self):
        mock_ipfs = MagicMock()
        mock_ipfs.cat = MagicMock(return_value=b"raw bytes")
        backend = self._make_backend(ipfs_client_mock=mock_ipfs)
        data = backend.download_bytes("bafyraw")
        assert data == b"raw bytes"

    @pytest.mark.asyncio
    async def test_upload_log_with_hippius_client(self):
        mock_ipfs = MagicMock()
        mock_ipfs.upload = MagicMock(return_value="cid")
        mock_hippius = MagicMock()
        mock_hippius.s3_upload = MagicMock(return_value="https://hippius.s3/logs/test")
        backend = self._make_backend(ipfs_client_mock=mock_ipfs, hippius_client_mock=mock_hippius)
        url = await backend.upload_log(key="round_123", content="log data here")
        assert url == "https://hippius.s3/logs/test"

    @pytest.mark.asyncio
    async def test_upload_log_without_hippius_client(self):
        mock_ipfs = MagicMock()
        mock_ipfs.upload = MagicMock(return_value="cid")
        backend = self._make_backend(ipfs_client_mock=mock_ipfs)
        backend._hippius_client = None
        url = await backend.upload_log(key="round_123", content="log data")
        assert url is None

    def test_hash_mismatch_raises(self):
        mock_ipfs = MagicMock()
        mock_ipfs.cat = MagicMock(return_value=b'{"x":1}')
        backend = self._make_backend(ipfs_client_mock=mock_ipfs)
        with pytest.raises(ValueError, match="Hash mismatch"):
            backend.download_json("bafytest", expected_sha256_hex="0000000000000000")


# ═══════════════════════════════════════════════════════════════════════════
# S3IWAPBackend
# ═══════════════════════════════════════════════════════════════════════════


class TestS3IWAPBackend:
    """Test S3IWAPBackend delegates to IWAP client and embedded IPFSBackend."""

    @patch("autoppia_web_agents_subnet.utils.storage.ipfs_backend.ipfs_add_json")
    def test_upload_json_delegates_to_ipfs(self, mock_add):
        mock_add.return_value = ("bafys3", "hash", 10)
        backend = S3IWAPBackend(ipfs_api_url="http://test:5001")
        cid, sha, size = backend.upload_json({"s3": True})
        assert cid == "bafys3"

    @pytest.mark.asyncio
    async def test_upload_log_delegates_to_iwap(self):
        mock_client = MagicMock()

        async def mock_upload_round_log(**kwargs):
            return "https://s3.example.com/log.txt"

        mock_client.upload_round_log = mock_upload_round_log
        backend = S3IWAPBackend(iwap_client=mock_client)
        url = await backend.upload_log(
            key="round_1",
            content="log content",
            metadata={
                "validator_round_id": "round_1",
                "season_number": "5",
                "round_number_in_season": "3",
                "validator_uid": "1",
                "validator_hotkey": "5Ftest",
            },
        )
        assert url == "https://s3.example.com/log.txt"

    @pytest.mark.asyncio
    async def test_upload_log_without_client_returns_none(self):
        backend = S3IWAPBackend()
        url = await backend.upload_log(key="k", content="c")
        assert url is None


# ═══════════════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════════════


class TestFactory:
    """Test the factory function for creating storage backends."""

    def test_default_returns_ipfs_backend(self):
        with patch.dict(os.environ, {"STORAGE_BACKEND": "ipfs"}, clear=False):
            backend = get_storage_backend(override="ipfs")
            assert isinstance(backend, IPFSBackend)

    def test_override_ipfs(self):
        backend = get_storage_backend(override="ipfs", ipfs_api_url="http://custom:5001")
        assert isinstance(backend, IPFSBackend)

    def test_override_hippius(self):
        with patch.dict("sys.modules", {
            "hippius_sdk": MagicMock(
                IPFSClient=MagicMock(return_value=MagicMock()),
                HippiusClient=MagicMock(return_value=MagicMock()),
            ),
        }):
            from autoppia_web_agents_subnet.utils.storage.hippius_backend import HippiusBackend
            backend = get_storage_backend(
                override="hippius",
                hippius_ipfs_api_url="http://hippius:5001",
                hippius_api_key="key123",
            )
            assert isinstance(backend, HippiusBackend)

    def test_env_var_selects_backend(self):
        with patch.dict(os.environ, {"STORAGE_BACKEND": "ipfs"}, clear=False):
            backend = get_storage_backend()
            assert isinstance(backend, IPFSBackend)

    def test_get_s3_backend_default_returns_iwap(self):
        backend = get_s3_backend(override="iwap")
        assert isinstance(backend, S3IWAPBackend)

    def test_get_s3_backend_hippius(self):
        with patch.dict("sys.modules", {
            "hippius_sdk": MagicMock(
                IPFSClient=MagicMock(return_value=MagicMock()),
                HippiusClient=MagicMock(return_value=MagicMock()),
            ),
        }):
            from autoppia_web_agents_subnet.utils.storage.hippius_backend import HippiusBackend
            backend = get_s3_backend(
                override="hippius",
                hippius_api_key="key",
            )
            assert isinstance(backend, HippiusBackend)


# ═══════════════════════════════════════════════════════════════════════════
# Config integration
# ═══════════════════════════════════════════════════════════════════════════


class TestConfigIntegration:
    """Verify config env vars are picked up correctly."""

    def test_storage_backend_config_exists(self):
        """The config module should export STORAGE_BACKEND and S3_BACKEND."""
        from autoppia_web_agents_subnet.validator.config import STORAGE_BACKEND, S3_BACKEND

        assert isinstance(STORAGE_BACKEND, str)
        assert isinstance(S3_BACKEND, str)

    def test_hippius_config_exists(self):
        """The config module should export Hippius-specific settings."""
        from autoppia_web_agents_subnet.validator.config import (
            HIPPIUS_IPFS_API_URL,
            HIPPIUS_API_KEY,
            HIPPIUS_S3_BUCKET,
        )

        assert isinstance(HIPPIUS_IPFS_API_URL, str)
        assert isinstance(HIPPIUS_API_KEY, str)
        assert isinstance(HIPPIUS_S3_BUCKET, str)
