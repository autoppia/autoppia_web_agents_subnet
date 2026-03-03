"""Unit tests for Hippius S3 client.

Tests upload functions with mocked boto3 — no real network calls.
"""

import json
import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.unit
@pytest.mark.asyncio
class TestS3UploadJson:
    """Test s3_upload_json_async."""

    def setup_method(self):
        from autoppia_web_agents_subnet.utils.s3_client import reset_client

        reset_client()

    async def test_serialization_and_key(self):
        """s3_upload_json_async serializes to compact JSON and returns the key."""
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
        """s3_upload_json_async uses HIPPIUS_S3_BUCKET when bucket not specified."""
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
    """Test s3_upload_bytes_async."""

    async def test_uploads_with_content_type(self):
        """s3_upload_bytes_async forwards content_type correctly."""
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
    """Test upload_evaluation_metadata_async."""

    async def test_uploads_metadata_with_sanitized_key(self):
        """upload_evaluation_metadata_async uses sanitized task_id in key."""
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
        """upload_evaluation_metadata_async returns None when S3 not configured."""
        with patch("autoppia_web_agents_subnet.utils.s3_client.is_configured", return_value=False):
            from autoppia_web_agents_subnet.utils.s3_client import upload_evaluation_metadata_async

            result = await upload_evaluation_metadata_async(round_id="r", validator_uid=1, miner_uid=2, metadata={})
            assert result is None

    async def test_returns_none_on_error(self):
        """upload_evaluation_metadata_async returns None on upload failure."""
        with patch("autoppia_web_agents_subnet.utils.s3_client.is_configured", return_value=True):
            with patch("autoppia_web_agents_subnet.utils.s3_client.s3_upload_json_async", side_effect=RuntimeError("boom")):
                from autoppia_web_agents_subnet.utils.s3_client import upload_evaluation_metadata_async

                result = await upload_evaluation_metadata_async(round_id="r", validator_uid=1, miner_uid=2, metadata={})
                assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestUploadEvaluationGif:
    """Test upload_evaluation_gif_async."""

    async def test_uploads_gif(self):
        """upload_evaluation_gif_async uploads GIF with correct content type."""
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
        """upload_evaluation_gif_async returns None when S3 not configured."""
        with patch("autoppia_web_agents_subnet.utils.s3_client.is_configured", return_value=False):
            from autoppia_web_agents_subnet.utils.s3_client import upload_evaluation_gif_async

            result = await upload_evaluation_gif_async(round_id="r", validator_uid=1, miner_uid=2, gif_data=b"GIF89a")
            assert result is None


@pytest.mark.unit
class TestIsConfigured:
    """Test is_configured()."""

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
class TestS3ClientCreation:
    """Test _get_s3_client error handling."""

    def setup_method(self):
        from autoppia_web_agents_subnet.utils.s3_client import reset_client

        reset_client()

    def test_raises_when_boto3_not_installed(self):
        """_get_s3_client raises S3Error when boto3 is not available."""
        with patch.dict("sys.modules", {"boto3": None}):
            import importlib
            import autoppia_web_agents_subnet.utils.s3_client as s3_mod

            s3_mod.reset_client()
            importlib.reload(s3_mod)
            from autoppia_web_agents_subnet.utils.s3_client import S3Error

            with pytest.raises(S3Error, match="boto3 package not installed"):
                s3_mod._get_s3_client()

    def test_raises_when_credentials_missing(self):
        """_get_s3_client raises S3Error when access keys are empty."""
        mock_boto3 = MagicMock()
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_ACCESS_KEY", ""):
                with patch("autoppia_web_agents_subnet.validator.config.HIPPIUS_S3_SECRET_KEY", ""):
                    from autoppia_web_agents_subnet.utils.s3_client import S3Error, _get_s3_client, reset_client

                    reset_client()
                    with pytest.raises(S3Error, match="HIPPIUS_S3_ACCESS_KEY"):
                        _get_s3_client()

    def test_caches_client_across_calls(self):
        """_get_s3_client returns the same instance on subsequent calls."""
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
class TestSanitizeKeySegment:
    """Test _sanitize_key_segment."""

    def test_replaces_unsafe_chars(self):
        from autoppia_web_agents_subnet.utils.s3_client import _sanitize_key_segment

        assert _sanitize_key_segment("a/b c..d") == "a_b_c_d"

    def test_truncates_long_values(self):
        from autoppia_web_agents_subnet.utils.s3_client import _sanitize_key_segment

        result = _sanitize_key_segment("a" * 200, max_len=10)
        assert len(result) == 10
