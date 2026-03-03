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


# ---------------------------------------------------------------------------
# Fake in-memory Hippius client for integration tests
# ---------------------------------------------------------------------------


class _FakeHippiusClient:
    """In-memory IPFS client that content-addresses data like the real thing.

    Exercises the full code path through hippius_ipfs.py without network I/O.
    """

    def __init__(self):
        self._store: dict[str, bytes] = {}

    async def ipfs_upload_bytes(self, data: bytes, *, filename: str = "", pin: bool = True) -> str:
        cid = "bafk" + hashlib.sha256(data).hexdigest()[:48]
        self._store[cid] = data
        return cid

    async def ipfs_download_bytes(self, cid: str) -> bytes:
        if cid not in self._store:
            raise RuntimeError(f"CID not found: {cid}")
        return self._store[cid]


@pytest.mark.unit
@pytest.mark.asyncio
class TestHippiusRoundTrip:
    """Integration tests that run the full add→get pipeline through real
    serialization, hashing, and validation code — only the network transport
    is replaced with an in-memory store."""

    def setup_method(self):
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod

        hip_mod.reset_client()

    def teardown_method(self):
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod

        hip_mod.reset_client()

    async def test_full_round_trip_through_public_api(self):
        """add_json_async → get_json_async exercises the exact consensus.py production path."""
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod
        from autoppia_web_agents_subnet.utils.ipfs_client import add_json_async, get_json_async, minidumps, sha256_hex

        fake = _FakeHippiusClient()
        hip_mod._hippius_client = fake

        payload = {
            "v": 1,
            "r": 42,
            "season": 3,
            "validator_hotkey": "5FHneTest123",
            "scores": {"1": 0.95, "7": 0.30, "12": 0.0},
        }

        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", True):
            cid, sha_hex, byte_len = await add_json_async(payload, filename="commit_r42.json", pin=True, sort_keys=True)

            assert cid.startswith("bafk")
            assert byte_len > 0

            # Verify hash matches canonical serialization
            canonical = minidumps(payload, sort_keys=True).encode("utf-8")
            assert sha_hex == sha256_hex(canonical)
            assert byte_len == len(canonical)

            # Download and verify full round-trip
            obj, norm, h = await get_json_async(cid, expected_sha256_hex=sha_hex)
            assert obj == payload
            assert h == sha_hex

    async def test_hash_mismatch_detected_on_download(self):
        """get_json_async raises IPFSError when downloaded content doesn't match expected hash."""
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod
        from autoppia_web_agents_subnet.utils.ipfs_client import IPFSError, add_json_async, get_json_async

        fake = _FakeHippiusClient()
        hip_mod._hippius_client = fake

        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", True):
            cid, _, _ = await add_json_async({"data": "real"})

            with pytest.raises(IPFSError, match="Hash mismatch"):
                await get_json_async(cid, expected_sha256_hex="0" * 64)

    async def test_large_payload_round_trip(self):
        """Realistic 256-miner evaluation payload survives serialization round-trip."""
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod
        from autoppia_web_agents_subnet.utils.ipfs_client import add_json_async, get_json_async

        fake = _FakeHippiusClient()
        hip_mod._hippius_client = fake

        payload = {
            "v": 1,
            "r": 100,
            "season": 5,
            "validator_hotkey": "5FHne" + "a" * 43,
            "scores": {str(uid): round(uid * 0.01, 4) for uid in range(256)},
        }

        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", True):
            cid, sha_hex, byte_len = await add_json_async(payload)
            assert byte_len > 1000

            obj, _, h = await get_json_async(cid, expected_sha256_hex=sha_hex)
            assert obj["scores"]["255"] == 2.55
            assert len(obj["scores"]) == 256
