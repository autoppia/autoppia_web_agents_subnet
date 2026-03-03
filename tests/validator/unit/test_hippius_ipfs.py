"""Unit tests for Hippius IPFS integration.

Tests routing logic in ipfs_client.py and the hippius_ipfs.py wrapper.
"""

import hashlib
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.unit
@pytest.mark.asyncio
class TestIPFSRouting:
    """Test that HIPPIUS_IPFS_ENABLED routes to the correct backend."""

    async def test_add_json_async_uses_legacy_when_disabled(self):
        """When HIPPIUS_IPFS_ENABLED=False, add_json_async uses legacy run_in_executor path."""
        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", False):
            with patch("autoppia_web_agents_subnet.utils.ipfs_client.ipfs_add_json") as mock_legacy:
                mock_legacy.return_value = ("QmLegacy", "abc123", 42)

                from autoppia_web_agents_subnet.utils.ipfs_client import add_json_async

                cid, h, size = await add_json_async({"test": 1})

                assert cid == "QmLegacy"
                assert h == "abc123"
                assert size == 42

    async def test_add_json_async_uses_hippius_when_enabled(self):
        """When HIPPIUS_IPFS_ENABLED=True, add_json_async delegates to hippius_add_json_async."""
        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", True):
            with patch("autoppia_web_agents_subnet.utils.hippius_ipfs.hippius_add_json_async", new_callable=AsyncMock) as mock_hippius:
                mock_hippius.return_value = ("QmHippius", "def456", 100)

                from autoppia_web_agents_subnet.utils.ipfs_client import add_json_async

                cid, h, size = await add_json_async({"test": 1}, filename="test.json")

                mock_hippius.assert_called_once()
                assert cid == "QmHippius"

    async def test_get_json_async_uses_legacy_when_disabled(self):
        """When HIPPIUS_IPFS_ENABLED=False, get_json_async uses legacy run_in_executor path."""
        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", False):
            with patch("autoppia_web_agents_subnet.utils.ipfs_client.ipfs_get_json") as mock_legacy:
                mock_legacy.return_value = ({"scores": {}}, b"{}", "abc")

                from autoppia_web_agents_subnet.utils.ipfs_client import get_json_async

                obj, norm, h = await get_json_async("QmTest")

                assert obj == {"scores": {}}

    async def test_get_json_async_uses_hippius_when_enabled(self):
        """When HIPPIUS_IPFS_ENABLED=True, get_json_async delegates to hippius_get_json_async."""
        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", True):
            with patch("autoppia_web_agents_subnet.utils.hippius_ipfs.hippius_get_json_async", new_callable=AsyncMock) as mock_hippius:
                mock_hippius.return_value = ({"data": 1}, b'{"data":1}', "hash")

                from autoppia_web_agents_subnet.utils.ipfs_client import get_json_async

                obj, norm, h = await get_json_async("QmTest", expected_sha256_hex="hash")

                mock_hippius.assert_called_once_with("QmTest", expected_sha256_hex="hash")


@pytest.mark.unit
@pytest.mark.asyncio
class TestHippiusAddJson:
    """Test hippius_add_json_async internals."""

    def setup_method(self):
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod

        hip_mod.reset_client()

    def teardown_method(self):
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod

        hip_mod.reset_client()

    async def test_returns_correct_tuple_format(self):
        """hippius_add_json_async returns (cid, sha256_hex, byte_len)."""
        mock_client = MagicMock()
        mock_client.ipfs_upload_bytes = AsyncMock(return_value="QmNewCid123")

        mock_hippius_module = MagicMock()
        mock_hippius_module.HippiusClient = MagicMock(return_value=mock_client)

        with patch.dict("sys.modules", {"hippius": mock_hippius_module}):
            import importlib
            import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod

            hip_mod.reset_client()
            importlib.reload(hip_mod)
            cid, h, size = await hip_mod.hippius_add_json_async({"key": "value"})

            assert cid == "QmNewCid123"
            assert isinstance(h, str) and len(h) == 64  # sha256 hex
            assert isinstance(size, int) and size > 0

    async def test_reuses_cached_client(self):
        """hippius_add_json_async reuses the singleton client across calls."""
        mock_client = MagicMock()
        mock_client.ipfs_upload_bytes = AsyncMock(return_value="QmCid1")

        mock_hippius_module = MagicMock()
        mock_hippius_module.HippiusClient = MagicMock(return_value=mock_client)

        with patch.dict("sys.modules", {"hippius": mock_hippius_module}):
            import importlib
            import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod

            hip_mod.reset_client()
            importlib.reload(hip_mod)

            await hip_mod.hippius_add_json_async({"a": 1})
            await hip_mod.hippius_add_json_async({"b": 2})

            # HippiusClient constructor called only once (singleton)
            assert mock_hippius_module.HippiusClient.call_count == 1

    async def test_raises_ipfs_error_when_sdk_not_installed(self):
        """hippius_add_json_async raises IPFSError when hippius not installed."""
        with patch.dict("sys.modules", {"hippius": None}):
            import importlib
            import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod

            hip_mod.reset_client()
            importlib.reload(hip_mod)
            from autoppia_web_agents_subnet.utils.ipfs_client import IPFSError

            with pytest.raises(IPFSError, match="hippius package not installed"):
                await hip_mod.hippius_add_json_async({"test": 1})

    async def test_upload_failure_raises_ipfs_error(self):
        """hippius_add_json_async wraps SDK errors in IPFSError."""
        mock_client = MagicMock()
        mock_client.ipfs_upload_bytes = AsyncMock(side_effect=RuntimeError("network down"))

        mock_hippius_module = MagicMock()
        mock_hippius_module.HippiusClient = MagicMock(return_value=mock_client)

        with patch.dict("sys.modules", {"hippius": mock_hippius_module}):
            import importlib
            import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod

            hip_mod.reset_client()
            importlib.reload(hip_mod)
            from autoppia_web_agents_subnet.utils.ipfs_client import IPFSError

            with pytest.raises(IPFSError, match="Hippius IPFS upload failed"):
                await hip_mod.hippius_add_json_async({"test": 1})


@pytest.mark.unit
@pytest.mark.asyncio
class TestHippiusGetJson:
    """Test hippius_get_json_async internals."""

    def setup_method(self):
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod

        hip_mod.reset_client()

    def teardown_method(self):
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod

        hip_mod.reset_client()

    async def test_hash_validation_passes(self):
        """hippius_get_json_async returns data when hash matches."""
        payload = {"scores": {"1": 0.5}}
        norm_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode("utf-8")
        expected_hash = hashlib.sha256(norm_bytes).hexdigest()

        mock_client = MagicMock()
        mock_client.ipfs_download_bytes = AsyncMock(return_value=json.dumps(payload).encode("utf-8"))

        mock_hippius_module = MagicMock()
        mock_hippius_module.HippiusClient = MagicMock(return_value=mock_client)

        with patch.dict("sys.modules", {"hippius": mock_hippius_module}):
            import importlib
            import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod

            hip_mod.reset_client()
            importlib.reload(hip_mod)
            obj, norm, h = await hip_mod.hippius_get_json_async("QmTest", expected_sha256_hex=expected_hash)

            assert obj == payload
            assert h == expected_hash

    async def test_hash_validation_fails(self):
        """hippius_get_json_async raises IPFSError on hash mismatch."""
        mock_client = MagicMock()
        mock_client.ipfs_download_bytes = AsyncMock(return_value=b'{"data":1}')

        mock_hippius_module = MagicMock()
        mock_hippius_module.HippiusClient = MagicMock(return_value=mock_client)

        with patch.dict("sys.modules", {"hippius": mock_hippius_module}):
            import importlib
            import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod

            hip_mod.reset_client()
            importlib.reload(hip_mod)
            from autoppia_web_agents_subnet.utils.ipfs_client import IPFSError

            with pytest.raises(IPFSError, match="Hash mismatch"):
                await hip_mod.hippius_get_json_async("QmTest", expected_sha256_hex="0000000000000000")

    async def test_raises_ipfs_error_when_sdk_not_installed(self):
        """hippius_get_json_async raises IPFSError when hippius not installed."""
        with patch.dict("sys.modules", {"hippius": None}):
            import importlib
            import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod

            hip_mod.reset_client()
            importlib.reload(hip_mod)
            from autoppia_web_agents_subnet.utils.ipfs_client import IPFSError

            with pytest.raises(IPFSError, match="hippius package not installed"):
                await hip_mod.hippius_get_json_async("QmTest")
