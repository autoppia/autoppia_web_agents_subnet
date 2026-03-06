"""Unit tests for Hippius storage backend integration.

Tests:
  - IPFS routing (legacy vs hippius) in add_json_async / get_json_async
  - hippius_ipfs.py internals (add, get, hash validation, error handling)
  - s3_client.py (is_configured, key sanitization, upload helpers, client creation)
  - Integration tests with FakeHippiusClient (full round-trip, no SDK mocks)
"""

import hashlib
import json
import os
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("VALIDATOR_NAME", "test-hippius")
os.environ.setdefault("VALIDATOR_IMAGE", "https://example.com/test.png")


# ---------------------------------------------------------------------------
# IPFS routing tests — add_json_async / get_json_async
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestIPFSRouting:

    async def test_add_json_async_uses_legacy_when_disabled(self):
        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", False):
            with patch("autoppia_web_agents_subnet.utils.ipfs_client.ipfs_add_json") as mock_legacy:
                mock_legacy.return_value = ("QmLegacy", "abc123", 42)

                from autoppia_web_agents_subnet.utils.ipfs_client import add_json_async

                result = await add_json_async({"test": 1})

                mock_legacy.assert_called_once()
                assert result == ("QmLegacy", "abc123", 42)

    async def test_add_json_async_uses_hippius_when_enabled(self):
        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", True):
            with patch("autoppia_web_agents_subnet.utils.hippius_ipfs.hippius_add_json_async", new_callable=AsyncMock) as mock_hippius:
                mock_hippius.return_value = ("QmHippius", "def456", 100)

                from autoppia_web_agents_subnet.utils.ipfs_client import add_json_async

                result = await add_json_async({"test": 1}, filename="test.json")

                mock_hippius.assert_called_once()
                assert result[0] == "QmHippius"

    async def test_get_json_async_uses_legacy_when_disabled(self):
        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", False):
            with patch("autoppia_web_agents_subnet.utils.ipfs_client.ipfs_get_json") as mock_legacy:
                mock_legacy.return_value = ({"scores": {}}, b"{}", "abc")

                from autoppia_web_agents_subnet.utils.ipfs_client import get_json_async

                obj, _, _ = await get_json_async("QmTest")

                assert obj == {"scores": {}}

    async def test_get_json_async_uses_hippius_when_enabled(self):
        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", True):
            with patch("autoppia_web_agents_subnet.utils.hippius_ipfs.hippius_get_json_async", new_callable=AsyncMock) as mock_hippius:
                mock_hippius.return_value = ({"data": 1}, b'{"data":1}', "hash")

                from autoppia_web_agents_subnet.utils.ipfs_client import get_json_async

                obj, _, _ = await get_json_async("QmTest", expected_sha256_hex="hash")

                mock_hippius.assert_called_once_with("QmTest", expected_sha256_hex="hash")


# ---------------------------------------------------------------------------
# hippius_ipfs.py internals
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestHippiusAddJson:

    async def test_returns_correct_tuple_format(self):
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
            assert isinstance(h, str) and len(h) == 64
            assert isinstance(size, int) and size > 0

    async def test_reuses_cached_client(self):
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

            assert mock_hippius_module.HippiusClient.call_count == 1

    async def test_raises_ipfs_error_when_sdk_not_installed(self):
        with patch.dict("sys.modules", {"hippius": None}):
            import importlib
            import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod
            hip_mod.reset_client()
            importlib.reload(hip_mod)
            from autoppia_web_agents_subnet.utils.ipfs_client import IPFSError

            with pytest.raises(IPFSError, match="hippius package not installed"):
                await hip_mod.hippius_add_json_async({"test": 1})

    async def test_upload_failure_raises_ipfs_error(self):
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

    async def test_hash_validation_passes(self):
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
            obj, _, h = await hip_mod.hippius_get_json_async("QmTest", expected_sha256_hex=expected_hash)

            assert obj == payload
            assert h == expected_hash

    async def test_hash_validation_fails(self):
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
        with patch.dict("sys.modules", {"hippius": None}):
            import importlib
            import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod
            hip_mod.reset_client()
            importlib.reload(hip_mod)
            from autoppia_web_agents_subnet.utils.ipfs_client import IPFSError

            with pytest.raises(IPFSError, match="hippius package not installed"):
                await hip_mod.hippius_get_json_async("QmTest")


# ---------------------------------------------------------------------------
# S3 client tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsConfigured:

    def test_returns_false_when_disabled(self):
        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_ENABLED", False):
            from autoppia_web_agents_subnet.utils.s3_client import is_configured
            assert is_configured() is False

    def test_returns_false_when_credentials_missing(self):
        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_ENABLED", True):
            with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_ENDPOINT", "https://s3.hippius.com"):
                with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_ACCESS_KEY", ""):
                    with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_SECRET_KEY", "secret"):
                        from autoppia_web_agents_subnet.utils.s3_client import is_configured
                        assert is_configured() is False

    def test_returns_true_when_fully_configured(self):
        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_ENABLED", True):
            with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_ENDPOINT", "https://s3.hippius.com"):
                with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_ACCESS_KEY", "key"):
                    with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_SECRET_KEY", "secret"):
                        from autoppia_web_agents_subnet.utils.s3_client import is_configured
                        assert is_configured() is True


@pytest.mark.unit
class TestSanitizeKeySegment:

    def test_replaces_unsafe_chars(self):
        from autoppia_web_agents_subnet.utils.s3_client import _sanitize_key_segment
        assert _sanitize_key_segment("a/b c..d") == "a_b_c_d"

    def test_truncates_long_values(self):
        from autoppia_web_agents_subnet.utils.s3_client import _sanitize_key_segment
        result = _sanitize_key_segment("a" * 200, max_len=10)
        assert len(result) == 10


@pytest.mark.unit
class TestS3ClientCreation:

    def setup_method(self):
        from autoppia_web_agents_subnet.utils.s3_client import reset_client
        reset_client()

    def test_raises_when_boto3_not_installed(self):
        with patch.dict("sys.modules", {"boto3": None}):
            import importlib
            import autoppia_web_agents_subnet.utils.s3_client as s3_mod
            s3_mod.reset_client()
            importlib.reload(s3_mod)
            from autoppia_web_agents_subnet.utils.s3_client import S3Error

            with pytest.raises(S3Error, match="boto3 package not installed"):
                s3_mod._get_s3_client()

    def test_raises_when_credentials_missing(self):
        mock_boto3 = MagicMock()
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_ACCESS_KEY", ""):
                with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_SECRET_KEY", ""):
                    from autoppia_web_agents_subnet.utils.s3_client import S3Error, _get_s3_client, reset_client
                    reset_client()
                    with pytest.raises(S3Error, match="HIPPIUS_S3_ACCESS_KEY"):
                        _get_s3_client()

    def test_caches_client_across_calls(self):
        mock_boto3 = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_ENDPOINT", "https://s3.test"):
                with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_ACCESS_KEY", "key"):
                    with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_SECRET_KEY", "secret"):
                        from autoppia_web_agents_subnet.utils.s3_client import _get_s3_client, reset_client
                        reset_client()
                        c1 = _get_s3_client()
                        c2 = _get_s3_client()
                        assert c1 is c2
                        assert mock_boto3.client.call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestS3UploadJson:

    async def test_serialization_and_key(self):
        mock_s3 = MagicMock()

        with patch("autoppia_web_agents_subnet.utils.s3_client._get_s3_client", return_value=mock_s3):
            from autoppia_web_agents_subnet.utils.s3_client import s3_upload_json_async

            key = await s3_upload_json_async({"score": 0.95}, key="test/data.json", bucket="test-bucket")

            assert key == "test/data.json"
            mock_s3.put_object.assert_called_once()
            call_kwargs = mock_s3.put_object.call_args[1]
            assert call_kwargs["Bucket"] == "test-bucket"
            assert call_kwargs["Key"] == "test/data.json"
            assert call_kwargs["ContentType"] == "application/json"
            body = call_kwargs["Body"]
            assert json.loads(body) == {"score": 0.95}

    async def test_uses_default_bucket(self):
        mock_s3 = MagicMock()

        with patch("autoppia_web_agents_subnet.utils.s3_client._get_s3_client", return_value=mock_s3):
            with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_BUCKET", "default-bucket"):
                from autoppia_web_agents_subnet.utils.s3_client import s3_upload_json_async
                await s3_upload_json_async({"data": 1}, key="k")
                call_kwargs = mock_s3.put_object.call_args[1]
                assert call_kwargs["Bucket"] == "default-bucket"


@pytest.mark.unit
@pytest.mark.asyncio
class TestS3UploadBytes:

    async def test_uploads_with_content_type(self):
        mock_s3 = MagicMock()

        with patch("autoppia_web_agents_subnet.utils.s3_client._get_s3_client", return_value=mock_s3):
            from autoppia_web_agents_subnet.utils.s3_client import s3_upload_bytes_async

            key = await s3_upload_bytes_async(b"GIF89a...", key="test/rec.gif", content_type="image/gif", bucket="b")

            assert key == "test/rec.gif"
            call_kwargs = mock_s3.put_object.call_args[1]
            assert call_kwargs["ContentType"] == "image/gif"
            assert call_kwargs["Body"] == b"GIF89a..."


@pytest.mark.unit
@pytest.mark.asyncio
class TestUploadEvaluationMetadata:

    async def test_uploads_metadata_with_sanitized_key(self):
        mock_s3 = MagicMock()

        with patch("autoppia_web_agents_subnet.utils.s3_client._get_s3_client", return_value=mock_s3):
            with patch("autoppia_web_agents_subnet.utils.s3_client.is_configured", return_value=True):
                from autoppia_web_agents_subnet.utils.s3_client import upload_evaluation_metadata_async

                key = await upload_evaluation_metadata_async(
                    round_id="round-1",
                    validator_uid=5,
                    miner_uid=42,
                    metadata={"score": 0.8},
                    task_id="task/abc def",
                )

                assert key is not None
                assert "task_abc_def" in key
                assert "/" not in key.split("metadata_")[1].replace(".json", "")

    async def test_noop_when_not_configured(self):
        with patch("autoppia_web_agents_subnet.utils.s3_client.is_configured", return_value=False):
            from autoppia_web_agents_subnet.utils.s3_client import upload_evaluation_metadata_async
            result = await upload_evaluation_metadata_async(round_id="r", validator_uid=1, miner_uid=2, metadata={})
            assert result is None

    async def test_returns_none_on_error(self):
        with patch("autoppia_web_agents_subnet.utils.s3_client.is_configured", return_value=True):
            with patch("autoppia_web_agents_subnet.utils.s3_client.s3_upload_json_async", side_effect=RuntimeError("boom")):
                from autoppia_web_agents_subnet.utils.s3_client import upload_evaluation_metadata_async
                result = await upload_evaluation_metadata_async(round_id="r", validator_uid=1, miner_uid=2, metadata={})
                assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestUploadEvaluationGif:

    async def test_uploads_gif(self):
        mock_s3 = MagicMock()

        with patch("autoppia_web_agents_subnet.utils.s3_client._get_s3_client", return_value=mock_s3):
            with patch("autoppia_web_agents_subnet.utils.s3_client.is_configured", return_value=True):
                from autoppia_web_agents_subnet.utils.s3_client import upload_evaluation_gif_async

                key = await upload_evaluation_gif_async(
                    round_id="round-1",
                    validator_uid=5,
                    miner_uid=42,
                    gif_data=b"GIF89a...",
                    task_id="task-abc",
                )

                assert key is not None
                assert "recording_task-abc.gif" in key
                call_kwargs = mock_s3.put_object.call_args[1]
                assert call_kwargs["ContentType"] == "image/gif"

    async def test_noop_when_not_configured(self):
        with patch("autoppia_web_agents_subnet.utils.s3_client.is_configured", return_value=False):
            from autoppia_web_agents_subnet.utils.s3_client import upload_evaluation_gif_async
            result = await upload_evaluation_gif_async(round_id="r", validator_uid=1, miner_uid=2, gif_data=b"GIF89a")
            assert result is None


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
        await asyncio.sleep(0)
        cid = "bafk" + hashlib.sha256(data).hexdigest()[:48]
        self._store[cid] = data
        return cid

    async def ipfs_download_bytes(self, cid: str) -> bytes:
        await asyncio.sleep(0)
        if cid not in self._store:
            raise RuntimeError(f"CID not found: {cid}")
        return self._store[cid]


@pytest.mark.unit
@pytest.mark.asyncio
class TestHippiusRoundTrip:
    """Integration tests that run the full add->get pipeline through real
    serialization, hashing, and validation code -- only the network transport
    is replaced with an in-memory store."""

    async def test_full_round_trip_through_public_api(self):
        """add_json_async -> get_json_async exercises the exact consensus.py production path."""
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod
        from autoppia_web_agents_subnet.utils.ipfs_client import add_json_async, get_json_async, minidumps, sha256_hex

        fake = _FakeHippiusClient()
        hip_mod._state["client"] = fake

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

            canonical = minidumps(payload, sort_keys=True).encode("utf-8")
            assert sha_hex == sha256_hex(canonical)
            assert byte_len == len(canonical)

            obj, _, h = await get_json_async(cid, expected_sha256_hex=sha_hex)
            assert obj == payload
            assert h == sha_hex

    async def test_hash_mismatch_detected_on_download(self):
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod
        from autoppia_web_agents_subnet.utils.ipfs_client import IPFSError, add_json_async, get_json_async

        fake = _FakeHippiusClient()
        hip_mod._state["client"] = fake

        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", True):
            cid, _, _ = await add_json_async({"data": "real"})

            with pytest.raises(IPFSError, match="Hash mismatch"):
                await get_json_async(cid, expected_sha256_hex="0" * 64)

    async def test_large_payload_round_trip(self):
        """Realistic 256-miner evaluation payload survives serialization round-trip."""
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod
        from autoppia_web_agents_subnet.utils.ipfs_client import add_json_async, get_json_async

        fake = _FakeHippiusClient()
        hip_mod._state["client"] = fake

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

            obj, _, _ = await get_json_async(cid, expected_sha256_hex=sha_hex)
            assert obj["scores"]["255"] == pytest.approx(2.55)
            assert len(obj["scores"]) == 256

    async def test_content_addressing_same_content_same_cid(self):
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod
        from autoppia_web_agents_subnet.utils.ipfs_client import add_json_async

        fake = _FakeHippiusClient()
        hip_mod._state["client"] = fake

        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", True):
            cid1, _, _ = await add_json_async({"x": 1})
            cid2, _, _ = await add_json_async({"x": 1})
            assert cid1 == cid2

    async def test_different_content_different_cid(self):
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod
        from autoppia_web_agents_subnet.utils.ipfs_client import add_json_async

        fake = _FakeHippiusClient()
        hip_mod._state["client"] = fake

        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", True):
            cid1, _, _ = await add_json_async({"x": 1})
            cid2, _, _ = await add_json_async({"x": 2})
            assert cid1 != cid2

    async def test_nonexistent_cid_raises(self):
        import autoppia_web_agents_subnet.utils.hippius_ipfs as hip_mod
        from autoppia_web_agents_subnet.utils.ipfs_client import IPFSError, get_json_async

        fake = _FakeHippiusClient()
        hip_mod._state["client"] = fake

        with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_IPFS_ENABLED", True):
            with pytest.raises(IPFSError, match="download failed"):
                await get_json_async("QmNonexistent")
