"""Tests for the HippiusIPFSClient backend."""

import json
import pytest
from unittest.mock import patch, Mock, AsyncMock, MagicMock

from autoppia_web_agents_subnet.utils.storage.hippius_ipfs import (
    HippiusIPFSClient,
    HippiusIPFSError,
    _minidumps,
    _sha256_hex,
)


@pytest.mark.unit
class TestHippiusIPFSClient:
    """Test Hippius IPFS client."""

    def test_init_raises_without_hippius_sdk(self):
        """Test that init raises if hippius_sdk is not installed."""
        with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs._HAVE_HIPPIUS", False):
            with pytest.raises(HippiusIPFSError, match="hippius_sdk is required"):
                HippiusIPFSClient()

    def test_add_bytes_uploads_via_hippius(self):
        """Test that add_bytes uses HippiusClient.upload_file."""
        mock_hippius_client = MagicMock()
        mock_upload = AsyncMock(return_value={"cid": "QmHippiusCID123"})
        mock_hippius_client.upload_file = mock_upload

        with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs._HAVE_HIPPIUS", True):
            with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs.HippiusClient", return_value=mock_hippius_client):
                client = HippiusIPFSClient(ipfs_api_url="http://localhost:5001")

                with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs._run_async") as mock_run:
                    mock_run.return_value = {"cid": "QmHippiusCID123"}
                    cid = client.add_bytes(b"test data", filename="test.json")

                    assert cid == "QmHippiusCID123"
                    mock_run.assert_called_once()

    def test_add_json_returns_cid_hash_length(self):
        """Test that add_json returns proper tuple."""
        mock_hippius_client = MagicMock()

        with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs._HAVE_HIPPIUS", True):
            with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs.HippiusClient", return_value=mock_hippius_client):
                client = HippiusIPFSClient()

                with patch.object(client, "add_bytes", return_value="QmJsonCID"):
                    obj = {"key": "value"}
                    cid, sha_hex, byte_len = client.add_json(obj)

                    assert cid == "QmJsonCID"
                    assert isinstance(sha_hex, str)
                    assert len(sha_hex) == 64
                    assert byte_len > 0

    def test_cat_fetches_via_hippius(self):
        """Test that cat uses HippiusClient.cat."""
        mock_hippius_client = MagicMock()

        with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs._HAVE_HIPPIUS", True):
            with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs.HippiusClient", return_value=mock_hippius_client):
                client = HippiusIPFSClient()

                with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs._run_async") as mock_run:
                    mock_run.return_value = b'{"hello": "world"}'
                    data = client.cat("QmTestCID")
                    assert data == b'{"hello": "world"}'

    def test_cat_handles_string_response(self):
        """Test that cat handles string response from Hippius."""
        mock_hippius_client = MagicMock()

        with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs._HAVE_HIPPIUS", True):
            with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs.HippiusClient", return_value=mock_hippius_client):
                client = HippiusIPFSClient()

                with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs._run_async") as mock_run:
                    mock_run.return_value = '{"hello": "world"}'
                    data = client.cat("QmTestCID")
                    assert data == b'{"hello": "world"}'

    def test_cat_raises_on_failure(self):
        """Test that cat raises HippiusIPFSError on failure."""
        mock_hippius_client = MagicMock()

        with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs._HAVE_HIPPIUS", True):
            with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs.HippiusClient", return_value=mock_hippius_client):
                client = HippiusIPFSClient()

                with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs._run_async") as mock_run:
                    mock_run.side_effect = Exception("Network error")
                    with pytest.raises(HippiusIPFSError, match="Hippius failed to fetch"):
                        client.cat("QmBadCID")

    def test_get_json_parses_and_verifies(self):
        """Test that get_json parses JSON and verifies hash."""
        mock_hippius_client = MagicMock()

        with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs._HAVE_HIPPIUS", True):
            with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs.HippiusClient", return_value=mock_hippius_client):
                client = HippiusIPFSClient()

                obj = {"test": "data"}
                raw = json.dumps(obj).encode("utf-8")
                norm = _minidumps(obj).encode("utf-8")
                expected_hash = _sha256_hex(norm)

                with patch.object(client, "cat", return_value=raw):
                    result_obj, _, result_hash = client.get_json(
                        "QmTestCID", expected_sha256_hex=expected_hash
                    )
                    assert result_obj == obj
                    assert result_hash == expected_hash

    def test_get_json_raises_on_hash_mismatch(self):
        """Test that get_json raises on hash mismatch."""
        mock_hippius_client = MagicMock()

        with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs._HAVE_HIPPIUS", True):
            with patch("autoppia_web_agents_subnet.utils.storage.hippius_ipfs.HippiusClient", return_value=mock_hippius_client):
                client = HippiusIPFSClient()

                raw = json.dumps({"test": "data"}).encode("utf-8")
                with patch.object(client, "cat", return_value=raw):
                    with pytest.raises(HippiusIPFSError, match="Hash mismatch"):
                        client.get_json("QmTestCID", expected_sha256_hex="wrong")
