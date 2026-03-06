"""Tests for the ipfs_client.py facade (backward-compatible API)."""

import pytest
from unittest.mock import patch, MagicMock

from autoppia_web_agents_subnet.utils.ipfs_client import (
    ipfs_add_bytes,
    ipfs_add_json,
    ipfs_cat,
    ipfs_get_json,
    add_json_async,
    get_json_async,
    IPFSError,
)


@pytest.fixture
def mock_backend():
    """Create a mock IPFS backend."""
    backend = MagicMock()
    backend.add_bytes.return_value = "QmTestCID"
    backend.add_json.return_value = ("QmTestCID", "sha256hex", 100)
    backend.cat.return_value = b'{"test": "data"}'
    backend.get_json.return_value = ({"test": "data"}, b'{"test":"data"}', "sha256hex")
    return backend


@pytest.mark.unit
class TestIPFSFacade:
    """Test that ipfs_client.py delegates to the configured backend."""

    def test_ipfs_add_bytes_delegates_to_backend(self, mock_backend):
        """Test that ipfs_add_bytes delegates to the backend."""
        with patch("autoppia_web_agents_subnet.utils.ipfs_client._get_client", return_value=mock_backend):
            cid = ipfs_add_bytes(b"test data", filename="test.json", pin=True)

            assert cid == "QmTestCID"
            mock_backend.add_bytes.assert_called_once_with(
                b"test data", filename="test.json", pin=True
            )

    def test_ipfs_add_json_delegates_to_backend(self, mock_backend):
        """Test that ipfs_add_json delegates to the backend."""
        with patch("autoppia_web_agents_subnet.utils.ipfs_client._get_client", return_value=mock_backend):
            cid, sha, length = ipfs_add_json({"key": "value"})

            assert cid == "QmTestCID"
            mock_backend.add_json.assert_called_once()

    def test_ipfs_cat_delegates_to_backend(self, mock_backend):
        """Test that ipfs_cat delegates to the backend."""
        with patch("autoppia_web_agents_subnet.utils.ipfs_client._get_client", return_value=mock_backend):
            data = ipfs_cat("QmTestCID")

            assert data == b'{"test": "data"}'
            mock_backend.cat.assert_called_once_with("QmTestCID", timeout=20.0)

    def test_ipfs_get_json_delegates_to_backend(self, mock_backend):
        """Test that ipfs_get_json delegates to the backend."""
        with patch("autoppia_web_agents_subnet.utils.ipfs_client._get_client", return_value=mock_backend):
            obj, norm, h = ipfs_get_json("QmTestCID")

            assert obj == {"test": "data"}
            mock_backend.get_json.assert_called_once()

    def test_api_url_accepted_but_ignored_by_backend(self, mock_backend):
        """Test that api_url param is accepted for backward compat."""
        with patch("autoppia_web_agents_subnet.utils.ipfs_client._get_client", return_value=mock_backend):
            # These should not raise even though api_url is passed
            ipfs_add_bytes(b"data", api_url="http://custom:5001/api/v0")
            ipfs_add_json({"k": "v"}, api_url="http://custom:5001/api/v0")
            ipfs_cat("QmCID", api_url="http://custom:5001/api/v0")
            ipfs_get_json("QmCID", api_url="http://custom:5001/api/v0")

    @pytest.mark.asyncio
    async def test_add_json_async_delegates(self, mock_backend):
        """Test that add_json_async runs in executor and delegates."""
        with patch("autoppia_web_agents_subnet.utils.ipfs_client._get_client", return_value=mock_backend):
            cid, sha, length = await add_json_async({"async": "data"})
            assert cid == "QmTestCID"

    @pytest.mark.asyncio
    async def test_get_json_async_delegates(self, mock_backend):
        """Test that get_json_async runs in executor and delegates."""
        with patch("autoppia_web_agents_subnet.utils.ipfs_client._get_client", return_value=mock_backend):
            obj, norm, h = await get_json_async("QmTestCID")
            assert obj == {"test": "data"}
