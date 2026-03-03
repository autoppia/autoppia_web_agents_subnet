"""Tests for the StandardIPFSClient backend."""

import json
import pytest
from unittest.mock import patch, Mock, MagicMock

from autoppia_web_agents_subnet.utils.storage.standard_ipfs import (
    StandardIPFSClient,
    IPFSError,
    _minidumps,
    _sha256_hex,
)


@pytest.mark.unit
class TestStandardIPFSClient:
    """Test standard IPFS HTTP API client."""

    def test_add_bytes_posts_to_ipfs_api(self):
        """Test that add_bytes sends data to the IPFS /add endpoint."""
        client = StandardIPFSClient(api_url="http://localhost:5001/api/v0")

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.text = '{"Hash": "QmTestCID123"}\n'
        mock_resp.raise_for_status = Mock()

        with patch("autoppia_web_agents_subnet.utils.storage.standard_ipfs.requests") as mock_requests:
            mock_requests.post.return_value = mock_resp
            cid = client.add_bytes(b"test data", filename="test.json")

            assert cid == "QmTestCID123"
            mock_requests.post.assert_called_once()
            call_args = mock_requests.post.call_args
            assert "/add" in call_args[0][0]

    def test_add_bytes_raises_on_no_api_url(self):
        """Test that add_bytes raises if no API URL is configured."""
        client = StandardIPFSClient(api_url="")
        with pytest.raises(IPFSError, match="No IPFS API URL"):
            client.add_bytes(b"data")

    def test_add_json_returns_cid_hash_and_length(self):
        """Test that add_json returns (CID, sha256, length) tuple."""
        client = StandardIPFSClient(api_url="http://localhost:5001/api/v0")

        mock_resp = Mock()
        mock_resp.text = '{"Hash": "QmJsonCID"}\n'
        mock_resp.raise_for_status = Mock()

        with patch("autoppia_web_agents_subnet.utils.storage.standard_ipfs.requests") as mock_requests:
            mock_requests.post.return_value = mock_resp

            obj = {"key": "value"}
            cid, sha_hex, byte_len = client.add_json(obj)

            assert cid == "QmJsonCID"
            assert isinstance(sha_hex, str)
            assert len(sha_hex) == 64  # SHA-256 hex
            assert byte_len > 0

    def test_cat_fetches_from_api(self):
        """Test that cat fetches from the IPFS API."""
        client = StandardIPFSClient(api_url="http://localhost:5001/api/v0")

        mock_resp = Mock()
        mock_resp.content = b'{"hello": "world"}'
        mock_resp.raise_for_status = Mock()

        with patch("autoppia_web_agents_subnet.utils.storage.standard_ipfs.requests") as mock_requests:
            mock_requests.post.return_value = mock_resp
            data = client.cat("QmTestCID")

            assert data == b'{"hello": "world"}'

    def test_cat_falls_back_to_gateways(self):
        """Test that cat falls back to gateways when API fails."""
        client = StandardIPFSClient(
            api_url="http://localhost:5001/api/v0",
            gateways=["https://ipfs.io/ipfs"],
        )

        with patch("autoppia_web_agents_subnet.utils.storage.standard_ipfs.requests") as mock_requests:
            mock_requests.post.side_effect = Exception("API down")

            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
                mock_response.read.return_value = b"gateway data"
                mock_urlopen.return_value = mock_response

                data = client.cat("QmTestCID")
                assert data == b"gateway data"

    def test_cat_raises_when_all_fail(self):
        """Test that cat raises IPFSError when all sources fail."""
        client = StandardIPFSClient(api_url="http://localhost:5001/api/v0", gateways=[])

        with patch("autoppia_web_agents_subnet.utils.storage.standard_ipfs.requests") as mock_requests:
            mock_requests.post.side_effect = Exception("API down")

            with pytest.raises(IPFSError, match="Failed to fetch CID"):
                client.cat("QmTestCID")

    def test_get_json_parses_and_verifies_hash(self):
        """Test that get_json parses JSON and verifies SHA-256."""
        client = StandardIPFSClient(api_url="http://localhost:5001/api/v0")

        obj = {"test": "data"}
        raw_bytes = json.dumps(obj).encode("utf-8")
        norm = _minidumps(obj).encode("utf-8")
        expected_hash = _sha256_hex(norm)

        mock_resp = Mock()
        mock_resp.content = raw_bytes
        mock_resp.raise_for_status = Mock()

        with patch("autoppia_web_agents_subnet.utils.storage.standard_ipfs.requests") as mock_requests:
            mock_requests.post.return_value = mock_resp

            result_obj, result_norm, result_hash = client.get_json(
                "QmTestCID", expected_sha256_hex=expected_hash
            )

            assert result_obj == obj
            assert result_hash == expected_hash

    def test_get_json_raises_on_hash_mismatch(self):
        """Test that get_json raises on SHA-256 mismatch."""
        client = StandardIPFSClient(api_url="http://localhost:5001/api/v0")

        raw_bytes = json.dumps({"test": "data"}).encode("utf-8")

        mock_resp = Mock()
        mock_resp.content = raw_bytes
        mock_resp.raise_for_status = Mock()

        with patch("autoppia_web_agents_subnet.utils.storage.standard_ipfs.requests") as mock_requests:
            mock_requests.post.return_value = mock_resp

            with pytest.raises(IPFSError, match="Hash mismatch"):
                client.get_json("QmTestCID", expected_sha256_hex="0000wrong")
