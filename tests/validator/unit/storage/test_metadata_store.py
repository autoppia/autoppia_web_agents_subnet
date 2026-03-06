"""Tests for the MetadataStore service."""

import json
import pytest
from unittest.mock import patch, Mock, MagicMock, call

from autoppia_web_agents_subnet.utils.storage.metadata_store import MetadataStore


@pytest.fixture
def mock_s3():
    """Create a mock S3 client."""
    s3 = MagicMock()
    s3.upload_json.return_value = "s3://bucket/key"
    s3.upload_bytes.return_value = "s3://bucket/key"
    s3.ensure_bucket.return_value = None
    return s3


@pytest.fixture
def store(mock_s3):
    """Create a MetadataStore with a mock S3 client."""
    return MetadataStore(s3_client=mock_s3, bucket="test-bucket")


@pytest.mark.unit
class TestMetadataStore:
    """Test MetadataStore service."""

    def test_upload_round_metadata(self, store, mock_s3):
        """Test uploading round metadata."""
        result = store.upload_round_metadata(
            season=1,
            round_num=5,
            validator_uid=0,
            validator_hotkey="hk_test",
            start_block=1000,
            end_block=2000,
            tasks_count=10,
            miners_evaluated=3,
        )

        assert result is not None
        mock_s3.upload_json.assert_called_once()
        call_kwargs = mock_s3.upload_json.call_args[1]
        assert call_kwargs["bucket"] == "test-bucket"
        assert "season_1/round_5/round_metadata.json" == call_kwargs["key"]

        payload = mock_s3.upload_json.call_args[0][0]
        assert payload["season"] == 1
        assert payload["round"] == 5
        assert payload["validator_uid"] == 0
        assert payload["tasks_count"] == 10

    def test_upload_evaluation_summary(self, store, mock_s3):
        """Test uploading evaluation summary for a miner."""
        result = store.upload_evaluation_summary(
            season=1,
            round_num=5,
            miner_uid=3,
            miner_hotkey="miner_hk",
            score=0.85,
            tasks_completed=8,
            total_time_seconds=120.5,
            total_cost_usd=0.03,
        )

        assert result is not None
        call_kwargs = mock_s3.upload_json.call_args[1]
        assert "uid_3/evaluation_summary.json" in call_kwargs["key"]

        payload = mock_s3.upload_json.call_args[0][0]
        assert payload["miner_uid"] == 3
        assert payload["score"] == 0.85

    def test_upload_task_result(self, store, mock_s3):
        """Test uploading task result."""
        result = store.upload_task_result(
            season=1,
            round_num=5,
            miner_uid=3,
            task_id="task-42",
            result={"eval_score": 1.0, "time": 15.3},
        )

        assert result is not None
        call_kwargs = mock_s3.upload_json.call_args[1]
        assert "task_task-42/result.json" in call_kwargs["key"]

    def test_upload_step_data(self, store, mock_s3):
        """Test uploading step data."""
        result = store.upload_step_data(
            season=1,
            round_num=5,
            miner_uid=3,
            task_id="task-42",
            step_number=1,
            step_data={"action": "click", "target": "#button"},
        )

        assert result is not None
        call_kwargs = mock_s3.upload_json.call_args[1]
        assert "step_001.json" in call_kwargs["key"]

    def test_upload_screenshot(self, store, mock_s3):
        """Test uploading a screenshot."""
        result = store.upload_screenshot(
            season=1,
            round_num=5,
            miner_uid=3,
            task_id="task-42",
            step_number=1,
            screenshot_bytes=b"\x89PNG\r\n\x1a\n",
        )

        assert result is not None
        mock_s3.upload_bytes.assert_called_once()
        call_kwargs = mock_s3.upload_bytes.call_args[1]
        assert "step_001_screenshot.png" in call_kwargs["key"]
        assert call_kwargs["content_type"] == "image/png"

    def test_upload_evaluation_gif(self, store, mock_s3):
        """Test uploading an evaluation GIF."""
        result = store.upload_evaluation_gif(
            season=1,
            round_num=5,
            miner_uid=3,
            task_id="task-42",
            gif_bytes=b"GIF89a",
        )

        assert result is not None
        call_kwargs = mock_s3.upload_bytes.call_args[1]
        assert "recording.gif" in call_kwargs["key"]
        assert call_kwargs["content_type"] == "image/gif"

    def test_upload_llm_request(self, store, mock_s3):
        """Test uploading LLM request data."""
        result = store.upload_llm_request(
            season=1,
            round_num=5,
            request_data={
                "model": "gpt-4o-mini",
                "prompt_tokens": 100,
                "completion_tokens": 50,
            },
        )

        assert result is not None
        call_kwargs = mock_s3.upload_json.call_args[1]
        assert "llm_requests/" in call_kwargs["key"]

    def test_upload_consensus_scores(self, store, mock_s3):
        """Test uploading consensus scores."""
        result = store.upload_consensus_scores(
            season=1,
            round_num=5,
            scores={1: 0.8, 2: 0.6, 3: 0.9},
            validator_uid=0,
        )

        assert result is not None
        call_kwargs = mock_s3.upload_json.call_args[1]
        assert "consensus/scores.json" in call_kwargs["key"]

        payload = mock_s3.upload_json.call_args[0][0]
        assert payload["scores"]["1"] == 0.8
        assert payload["scores"]["3"] == 0.9

    def test_bucket_layout_structure(self, store, mock_s3):
        """Test that the S3 key layout follows the documented structure."""
        store.upload_round_metadata(
            season=2, round_num=10, validator_uid=0,
            validator_hotkey="hk", start_block=0, end_block=100,
            tasks_count=5, miners_evaluated=2,
        )
        key = mock_s3.upload_json.call_args[1]["key"]
        assert key == "season_2/round_10/round_metadata.json"

        mock_s3.reset_mock()
        store.upload_evaluation_summary(
            season=2, round_num=10, miner_uid=7, miner_hotkey="mhk",
            score=0.5, tasks_completed=3, total_time_seconds=60.0, total_cost_usd=0.01,
        )
        key = mock_s3.upload_json.call_args[1]["key"]
        assert key == "season_2/round_10/evaluations/uid_7/evaluation_summary.json"

    def test_handles_s3_upload_failure_gracefully(self, store, mock_s3):
        """Test that upload failures return None instead of raising."""
        mock_s3.upload_json.side_effect = Exception("S3 upload failed")

        result = store.upload_round_metadata(
            season=1, round_num=1, validator_uid=0,
            validator_hotkey="hk", start_block=0, end_block=100,
            tasks_count=1, miners_evaluated=1,
        )

        assert result is None

    def test_ensure_bucket_called_once(self, store, mock_s3):
        """Test that ensure_bucket is called only once (on first upload)."""
        store.upload_round_metadata(
            season=1, round_num=1, validator_uid=0,
            validator_hotkey="hk", start_block=0, end_block=100,
            tasks_count=1, miners_evaluated=1,
        )
        store.upload_round_metadata(
            season=1, round_num=2, validator_uid=0,
            validator_hotkey="hk", start_block=100, end_block=200,
            tasks_count=1, miners_evaluated=1,
        )

        # ensure_bucket should only be called once (idempotent)
        mock_s3.ensure_bucket.assert_called_once_with("test-bucket")


@pytest.mark.unit
class TestGetMetadataStore:
    """Test the get_metadata_store factory function."""

    def test_returns_none_when_disabled(self):
        """Test that get_metadata_store returns None when uploads are disabled."""
        import autoppia_web_agents_subnet.validator.config as cfg
        import autoppia_web_agents_subnet.utils.storage.metadata_store as ms

        orig = cfg.S3_METADATA_UPLOAD_ENABLED
        ms._metadata_store = None
        try:
            cfg.S3_METADATA_UPLOAD_ENABLED = False
            result = ms.get_metadata_store()
            assert result is None
        finally:
            cfg.S3_METADATA_UPLOAD_ENABLED = orig
            ms._metadata_store = None

    def test_returns_store_when_enabled(self):
        """Test that get_metadata_store returns a MetadataStore when enabled."""
        import autoppia_web_agents_subnet.validator.config as cfg
        import autoppia_web_agents_subnet.utils.storage.metadata_store as ms
        import autoppia_web_agents_subnet.utils.storage as storage_mod

        orig_enabled = cfg.S3_METADATA_UPLOAD_ENABLED
        orig_bucket = cfg.S3_METADATA_BUCKET
        orig_backend = cfg.STORAGE_S3_BACKEND
        ms._metadata_store = None
        storage_mod._s3_client = None
        try:
            cfg.S3_METADATA_UPLOAD_ENABLED = True
            cfg.S3_METADATA_BUCKET = "test-bucket"
            cfg.STORAGE_S3_BACKEND = "aws"

            with patch("autoppia_web_agents_subnet.utils.storage.aws_s3._HAVE_BOTO3", True):
                with patch("autoppia_web_agents_subnet.utils.storage.aws_s3.boto3") as mock_boto3:
                    mock_boto3.client.return_value = MagicMock()
                    result = ms.get_metadata_store()
                    assert result is not None
                    assert isinstance(result, MetadataStore)
        finally:
            cfg.S3_METADATA_UPLOAD_ENABLED = orig_enabled
            cfg.S3_METADATA_BUCKET = orig_bucket
            cfg.STORAGE_S3_BACKEND = orig_backend
            ms._metadata_store = None
            storage_mod._s3_client = None
